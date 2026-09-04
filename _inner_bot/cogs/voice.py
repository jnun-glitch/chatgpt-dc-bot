"""Voice receive + local speech-to-text transcription.

Transcripts are stored as UTF-8 text files below ``transcripts/``.  A transcript
file is named after the speakers who have talked in that session, for example:
``Alice_und_Bob_2026-09-04_0730.txt``.

Audio is processed in memory and is not written to disk by this cog.
Speech recognition uses faster-whisper locally; no OpenAI API key is required.
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
MAX_FILENAME_LENGTH = 100


class TranscriptionSink(voice_recv.AudioSink):
    """Collect PCM per speaker and hand complete chunks to the asyncio loop."""

    def __init__(self, loop, on_chunk):
        super().__init__()
        self.loop = loop
        self.on_chunk = on_chunk
        self.buffers = defaultdict(bytearray)
        self.lock = threading.Lock()
        self.bytes_per_second = 48000 * 2 * 2  # 48 kHz, stereo, 16-bit PCM
        self.target_bytes = self.bytes_per_second * CHUNK_SECONDS

    def write(self, user, data):
        if user is None or getattr(user, "bot", False):
            return
        pcm = getattr(data, "pcm", None)
        if not pcm:
            return
        user_id = int(user.id)
        with self.lock:
            buf = self.buffers[user_id]
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
    def __init__(self, bot):
        self.bot = bot
        self.sessions = {}
        self._model = None
        self._model_lock = threading.Lock()

    voice = app_commands.Group(name="voice", description="Voice-Channel und Transkription")

    def _get_model(self):
        if WhisperModel is None:
            raise RuntimeError("faster-whisper ist nicht installiert. Installiere die requirements.txt neu.")
        if self._model is None:
            with self._model_lock:
                if self._model is None:
                    print(f"[VOICE STT] Lade faster-whisper Modell: {WHISPER_MODEL} ({WHISPER_DEVICE}/{WHISPER_COMPUTE_TYPE})")
                    self._model = WhisperModel(
                        WHISPER_MODEL,
                        device=WHISPER_DEVICE,
                        compute_type=WHISPER_COMPUTE_TYPE,
                    )
                    print("[VOICE STT] Modell geladen.")
        return self._model

    @staticmethod
    def _safe_name(value: str) -> str:
        value = re.sub(r"[^A-Za-z0-9ÄÖÜäöüß _-]+", "", value).strip()
        value = re.sub(r"\s+", "_", value)
        return value[:MAX_FILENAME_LENGTH] or "Unbekannt"

    @staticmethod
    def _session_folder(guild_id: int, started_at: datetime) -> Path:
        return TRANSCRIPTS_DIR / str(guild_id) / started_at.strftime("%Y-%m-%d")

    def _transcript_path(self, session) -> Path:
        names = sorted(session["speakers"].values(), key=str.casefold)
        speaker_part = "_und_".join(self._safe_name(name) for name in names) or "Unbekannt"
        filename = f"{speaker_part}_{session['started_at'].strftime('%Y-%m-%d_%H-%M-%S')}.txt"
        return self._session_folder(session["guild_id"], session["started_at"]) / filename

    def _write_transcript(self, session, speaker: str, text: str):
        path = self._transcript_path(session)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            header = (
                f"Discord Voice-Transkript\n"
                f"Server-ID: {session['guild_id']}\n"
                f"Start: {session['started_at'].isoformat(timespec='seconds')}\n"
                f"Sprecher: {', '.join(sorted(session['speakers'].values(), key=str.casefold))}\n"
                f"{'=' * 60}\n\n"
            )
            path.write_text(header, encoding="utf-8")
        timestamp = datetime.now().strftime("%H:%M:%S")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] {speaker}: {text}\n")
        session["path"] = path

    @voice.command(name="join", description="Bot kommt in deinen Voice-Channel")
    async def join(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message("Nur auf einem Server möglich.", ephemeral=True)
            return
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("Du musst zuerst in einem Voice-Channel sein.", ephemeral=True)
            return
        channel = interaction.user.voice.channel
        await interaction.response.defer()
        vc = interaction.guild.voice_client
        try:
            if vc and vc.is_connected():
                if vc.channel.id != channel.id:
                    await vc.move_to(channel)
                await interaction.followup.send(f"🔊 Ich bin jetzt in **{channel.name}**.")
                return
            vc = await channel.connect(cls=voice_recv.VoiceRecvClient)
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
        await interaction.response.send_message("👋 Voice-Channel verlassen und Transkription beendet.")

    @voice.command(name="transcribe", description="Startet/stoppt die Live-Transkription")
    @app_commands.describe(enabled="True = starten, False = stoppen", channel="Textkanal für das Live-Transkript")
    async def transcribe(self, interaction: discord.Interaction, enabled: bool, channel: discord.TextChannel | None = None):
        if not interaction.guild:
            await interaction.response.send_message("Nur auf einem Server möglich.", ephemeral=True)
            return
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("Du musst in einem Voice-Channel sein.", ephemeral=True)
            return

        if enabled:
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
                await interaction.response.send_message(
                    "❌ Der Bot ist bereits mit einem normalen Voice-Client verbunden. Für Transkription muss die Voice-Session mit Voice Receive verbunden werden.",
                    ephemeral=True,
                )
                return

            old = self.sessions.get(interaction.guild_id)
            if old:
                old["enabled"] = False
                try:
                    vc.stop_listening()
                except Exception:
                    pass

            now = datetime.now()
            loop = asyncio.get_running_loop()
            session = {
                "enabled": True,
                "vc": vc,
                "channel": target,
                "guild_id": interaction.guild_id,
                "started_at": now,
                "speakers": {},
                "path": None,
            }

            async def on_chunk(user, pcm):
                if not session["enabled"]:
                    return
                session["speakers"][int(user.id)] = user.display_name
                try:
                    text = await asyncio.to_thread(self._transcribe_pcm, pcm)
                except Exception as exc:
                    print(f"[VOICE STT] {exc}")
                    return
                if not text:
                    return
                self._write_transcript(session, user.display_name, text)
                try:
                    await target.send(f"🎙️ **{discord.utils.escape_markdown(user.display_name)}:** {text[:1800]}")
                except discord.HTTPException:
                    pass

            sink = TranscriptionSink(loop, on_chunk)
            session["sink"] = sink
            self.sessions[interaction.guild_id] = session
            vc.listen(sink)
            await interaction.response.send_message(
                f"📝 **Live-Transkription gestartet.** Ausgabe: {target.mention}\n"
                f"💾 Speicherung: `{self._session_folder(interaction.guild_id, now)}`\n"
                "🤖 Die Spracherkennung läuft lokal mit faster-whisper – kein OpenAI nötig."
            )
        else:
            session = self.sessions.pop(interaction.guild_id, None)
            if session:
                session["enabled"] = False
                try:
                    session["vc"].stop_listening()
                except Exception:
                    pass
                path = session.get("path")
                extra = f" Datei: `{path}`" if path else " Es wurde noch kein Text erkannt."
            else:
                extra = ""
            await interaction.response.send_message("🛑 Live-Transkription gestoppt." + extra)

    @voice.command(name="status", description="Zeigt den Voice-Status")
    async def status(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client if interaction.guild else None
        session = self.sessions.get(interaction.guild_id)
        if not vc or not vc.is_connected():
            text = "🔴 Nicht im Voice-Channel"
        else:
            text = f"🟢 Verbunden mit **{vc.channel.name}**"
            text += f"\n📝 Transkription: **{'AN' if session and session.get('enabled') else 'AUS'}**"
            if session and session.get("enabled"):
                text += f" → {session['channel'].mention}"
                text += f"\n👥 Sprecher: {len(session['speakers'])}"
                if session.get("path"):
                    text += f"\n💾 Datei: `{session['path'].name}`"
        await interaction.response.send_message(text)

    @voice.command(name="history", description="Zeigt gespeicherte Transkripte auf diesem Server")
    async def history(self, interaction: discord.Interaction):
        folder = TRANSCRIPTS_DIR / str(interaction.guild_id)
        if not folder.exists():
            await interaction.response.send_message("📂 Noch keine Transkripte gespeichert.", ephemeral=True)
            return
        files = sorted(folder.rglob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            await interaction.response.send_message("📂 Noch keine Transkripte gespeichert.", ephemeral=True)
            return
        lines = [f"📚 **Letzte {min(len(files), 20)} Transkripte:**"]
        for path in files[:20]:
            lines.append(f"• `{path.relative_to(folder)}`")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @voice.command(name="clear", description="Löscht alle gespeicherten Transkripte dieses Servers")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def clear(self, interaction: discord.Interaction):
        folder = TRANSCRIPTS_DIR / str(interaction.guild_id)
        if not folder.exists():
            await interaction.response.send_message("📂 Es gibt nichts zu löschen.", ephemeral=True)
            return
        count = 0
        for path in folder.rglob("*.txt"):
            try:
                path.unlink()
                count += 1
            except OSError:
                pass
        await interaction.response.send_message(f"🗑️ **{count}** Transkript-Datei(en) gelöscht.", ephemeral=True)

    @staticmethod
    def _transcribe_pcm(pcm):
        # faster-whisper accepts file-like audio, so encode the received PCM as WAV in memory.
        wav = io.BytesIO()
        with wave.open(wav, "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(48000)
            wf.writeframes(pcm)
        wav.seek(0)
        # The model is attached by the caller through the instance method below.
        raise RuntimeError("Internal transcription routing error")

    def _transcribe_pcm(self, pcm):
        model = self._get_model()
        wav = io.BytesIO()
        with wave.open(wav, "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(48000)
            wf.writeframes(pcm)
        wav.seek(0)
        segments, _info = model.transcribe(wav, beam_size=5, vad_filter=True)
        return " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()


async def setup(bot):
    await bot.add_cog(VoiceCog(bot))
