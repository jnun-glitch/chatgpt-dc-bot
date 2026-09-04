"""Local Discord voice transcription with faster-whisper.

Audio is processed in memory only. Text transcripts are persisted below
``transcripts/<guild_id>/<date>/`` and the filename always contains the names
of every speaker who has spoken in that session.
"""

import asyncio
import io
import os
import re
import threading
import wave
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, voice_recv

try:
    from faster_whisper import WhisperModel
except Exception:
    WhisperModel = None

CHUNK_SECONDS = max(3, int(os.environ.get("VOICE_TRANSCRIBE_CHUNK_SECONDS", "5")))
WHISPER_MODEL = os.environ.get("VOICE_WHISPER_MODEL", "base")
WHISPER_DEVICE = os.environ.get("VOICE_WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.environ.get("VOICE_WHISPER_COMPUTE_TYPE", "int8")
TRANSCRIPTS_DIR = Path(os.environ.get("TRANSCRIPTS_DIR", "transcripts"))


class TranscriptionSink(voice_recv.AudioSink):
    def __init__(self, loop, on_chunk):
        super().__init__()
        self.loop = loop
        self.on_chunk = on_chunk
        self.buffers = defaultdict(bytearray)
        self.lock = threading.Lock()
        self.target_bytes = 48000 * 2 * 2 * CHUNK_SECONDS

    def write(self, user, data):
        if user is None or getattr(user, "bot", False):
            return
        pcm = getattr(data, "pcm", None)
        if not pcm:
            return
        with self.lock:
            buf = self.buffers[int(user.id)]
            buf.extend(pcm)
            if len(buf) < self.target_bytes:
                return
            payload = bytes(buf)
            del buf[:]
        asyncio.run_coroutine_threadsafe(self.on_chunk(user, payload), self.loop)

    def cleanup(self):
        with self.lock:
            self.buffers.clear()


class VoiceCog(commands.Cog):
    voice = app_commands.Group(name="voice", description="Voice-Channel und Transkription")

    def __init__(self, bot):
        self.bot = bot
        self.sessions = {}
        self._model = None
        self._model_lock = threading.Lock()

    def _get_model(self):
        if WhisperModel is None:
            raise RuntimeError("faster-whisper ist nicht installiert. requirements.txt neu installieren.")
        if self._model is None:
            with self._model_lock:
                if self._model is None:
                    print(f"[VOICE STT] Lade {WHISPER_MODEL} ({WHISPER_DEVICE}/{WHISPER_COMPUTE_TYPE}) ...")
                    self._model = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE_TYPE)
                    print("[VOICE STT] Modell geladen.")
        return self._model

    @staticmethod
    def _safe_name(name):
        name = re.sub(r"[^A-Za-z0-9ÄÖÜäöüß _-]+", "", name).strip()
        return re.sub(r"\s+", "_", name)[:60] or "Unbekannt"

    def _folder(self, session):
        return TRANSCRIPTS_DIR / str(session["guild_id"]) / session["started_at"].strftime("%Y-%m-%d")

    def _path(self, session):
        speakers = sorted(session["speakers"].values(), key=str.casefold)
        names = "_und_".join(self._safe_name(x) for x in speakers) or "Unbekannt"
        stamp = session["started_at"].strftime("%Y-%m-%d_%H-%M-%S")
        return self._folder(session) / f"{names}_{stamp}.txt"

    def _save_line(self, session, speaker, text):
        session["speakers"][int(session["current_user_id"])] = speaker
        new_path = self._path(session)
        old_path = session.get("path")
        new_path.parent.mkdir(parents=True, exist_ok=True)

        # If another person starts talking, rename the live transcript so the
        # filename always contains all speakers who have talked in the session.
        if old_path and old_path.exists() and old_path != new_path:
            try:
                old_path.rename(new_path)
            except OSError:
                if new_path.exists():
                    with old_path.open("r", encoding="utf-8") as src, new_path.open("a", encoding="utf-8") as dst:
                        dst.write(src.read())
                    old_path.unlink(missing_ok=True)

        if not new_path.exists():
            speakers = ", ".join(sorted(session["speakers"].values(), key=str.casefold))
            new_path.write_text(
                "Discord Voice-Transkript\n"
                f"Server-ID: {session['guild_id']}\n"
                f"Start: {session['started_at'].isoformat(timespec='seconds')}\n"
                f"Sprecher: {speakers}\n"
                f"{'=' * 60}\n\n",
                encoding="utf-8",
            )
        timestamp = datetime.now().strftime("%H:%M:%S")
        with new_path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] {speaker}: {text}\n")
        session["path"] = new_path

    @voice.command(name="join", description="Bot kommt in deinen Voice-Channel")
    async def join(self, interaction: discord.Interaction):
        if not interaction.guild or not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("Du musst auf einem Server in einem Voice-Channel sein.", ephemeral=True)
            return
        channel = interaction.user.voice.channel
        await interaction.response.defer()
        vc = interaction.guild.voice_client
        try:
            if vc and vc.is_connected():
                if vc.channel.id != channel.id:
                    await vc.move_to(channel)
            else:
                await channel.connect(cls=voice_recv.VoiceRecvClient)
            await interaction.followup.send(f"🔊 Ich bin jetzt in **{channel.name}**.")
        except Exception as exc:
            await interaction.followup.send(f"❌ Voice-Verbindung fehlgeschlagen: `{str(exc)[:300]}`")

    @voice.command(name="leave", description="Bot verlässt den Voice-Channel")
    async def leave(self, interaction: discord.Interaction):
        session = self.sessions.pop(interaction.guild_id, None)
        if session:
            session["enabled"] = False
            try:
                session["vc"].stop_listening()
            except Exception:
                pass
        vc = interaction.guild.voice_client if interaction.guild else None
        if vc:
            try:
                await vc.disconnect()
            except Exception:
                pass
        await interaction.response.send_message("👋 Voice verlassen und Transkription beendet.")

    @voice.command(name="transcribe", description="Startet oder stoppt die Live-Transkription")
    @app_commands.describe(enabled="True = starten, False = stoppen", channel="Textkanal für das Live-Transkript")
    async def transcribe(self, interaction: discord.Interaction, enabled: bool, channel: discord.TextChannel | None = None):
        if not interaction.guild:
            await interaction.response.send_message("Nur auf einem Server möglich.", ephemeral=True)
            return
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("Du musst in einem Voice-Channel sein.", ephemeral=True)
            return

        if not enabled:
            session = self.sessions.pop(interaction.guild_id, None)
            if session:
                session["enabled"] = False
                try:
                    session["vc"].stop_listening()
                except Exception:
                    pass
                path = session.get("path")
                await interaction.response.send_message(
                    "🛑 Transkription gestoppt." + (f" Gespeichert: `{path}`" if path else " Noch kein Text erkannt.")
                )
            else:
                await interaction.response.send_message("🛑 Es läuft keine Transkription.")
            return

        try:
            self._get_model()
        except Exception as exc:
            await interaction.response.send_message(f"❌ Lokale Transkription nicht verfügbar: `{str(exc)[:300]}`", ephemeral=True)
            return

        target = channel or interaction.channel
        if not isinstance(target, discord.TextChannel):
            await interaction.response.send_message("Bitte einen normalen Textkanal angeben.", ephemeral=True)
            return

        vc = interaction.guild.voice_client
        if not vc or not vc.is_connected():
            try:
                vc = await interaction.user.voice.channel.connect(cls=voice_recv.VoiceRecvClient)
            except Exception as exc:
                await interaction.response.send_message(f"❌ Konnte Voice nicht beitreten: `{str(exc)[:300]}`", ephemeral=True)
                return
        if not isinstance(vc, voice_recv.VoiceRecvClient):
            await interaction.response.send_message("❌ Der vorhandene Voice-Client unterstützt kein Voice Receive.", ephemeral=True)
            return

        old = self.sessions.get(interaction.guild_id)
        if old:
            old["enabled"] = False
            try:
                vc.stop_listening()
            except Exception:
                pass

        now = datetime.now()
        session = {
            "enabled": True,
            "vc": vc,
            "channel": target,
            "guild_id": interaction.guild_id,
            "started_at": now,
            "speakers": {},
            "path": None,
            "current_user_id": None,
        }
        loop = asyncio.get_running_loop()

        async def on_chunk(user, pcm):
            if not session["enabled"]:
                return
            session["current_user_id"] = int(user.id)
            try:
                text = await asyncio.to_thread(self._transcribe_pcm, pcm)
            except Exception as exc:
                print(f"[VOICE STT] {exc}")
                return
            if not text:
                return
            self._save_line(session, user.display_name, text)
            try:
                await target.send(f"🎙️ **{discord.utils.escape_markdown(user.display_name)}:** {text[:1800]}")
            except discord.HTTPException:
                pass

        sink = TranscriptionSink(loop, on_chunk)
        session["sink"] = sink
        self.sessions[interaction.guild_id] = session
        vc.listen(sink)
        await interaction.response.send_message(
            f"📝 **Live-Transkription gestartet!** Ausgabe: {target.mention}\n"
            f"💾 Dateien: `{self._folder(session)}`\n"
            "🤖 Speech-to-Text läuft lokal mit faster-whisper – kein OpenAI nötig."
        )

    @voice.command(name="status", description="Zeigt den Voice-Status")
    async def status(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client if interaction.guild else None
        session = self.sessions.get(interaction.guild_id)
        if not vc or not vc.is_connected():
            await interaction.response.send_message("🔴 Nicht im Voice-Channel")
            return
        text = f"🟢 **{vc.channel.name}**\n📝 Transkription: **{'AN' if session and session.get('enabled') else 'AUS'}**"
        if session:
            text += f"\n👥 Sprecher: {len(session['speakers'])}"
            if session.get("path"):
                text += f"\n💾 `{session['path'].name}`"
        await interaction.response.send_message(text)

    @voice.command(name="history", description="Zeigt die gespeicherten Transkripte dieses Servers")
    async def history(self, interaction: discord.Interaction):
        folder = TRANSCRIPTS_DIR / str(interaction.guild_id)
        files = sorted(folder.rglob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True) if folder.exists() else []
        if not files:
            await interaction.response.send_message("📂 Noch keine Transkripte gespeichert.", ephemeral=True)
            return
        lines = [f"📚 **Letzte {min(20, len(files))} Transkripte:**"]
        lines.extend(f"• `{p.relative_to(folder)}`" for p in files[:20])
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @voice.command(name="clear", description="Löscht alle Transkripte dieses Servers")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def clear(self, interaction: discord.Interaction):
        folder = TRANSCRIPTS_DIR / str(interaction.guild_id)
        count = 0
        if folder.exists():
            for path in folder.rglob("*.txt"):
                try:
                    path.unlink()
                    count += 1
                except OSError:
                    pass
        await interaction.response.send_message(f"🗑️ **{count}** Transkript-Datei(en) gelöscht.", ephemeral=True)

    def _transcribe_pcm(self, pcm):
        model = self._get_model()
        wav = io.BytesIO()
        with wave.open(wav, "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(48000)
            wf.writeframes(pcm)
        wav.seek(0)
        segments, _ = model.transcribe(wav, beam_size=5, vad_filter=True)
        return " ".join(s.text.strip() for s in segments if s.text.strip()).strip()


async def setup(bot):
    await bot.add_cog(VoiceCog(bot))
