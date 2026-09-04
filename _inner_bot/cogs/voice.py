"""Voice transcription: joins a VC and turns spoken audio into text in a configured channel.

Audio is processed in memory in short chunks; no audio files are persisted by this cog.
Requires discord-ext-voice-recv and OPENAI_API_KEY for transcription.
"""

import asyncio
import io
import os
import threading
import wave
from collections import defaultdict

import discord
from discord import app_commands
from discord.ext import commands, voice_recv

try:
    from openai import OpenAI
except Exception:
    OpenAI = None


CHUNK_SECONDS = max(3, int(os.environ.get("VOICE_TRANSCRIBE_CHUNK_SECONDS", "5")))
TRANSCRIBE_MODEL = os.environ.get("VOICE_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")


class TranscriptionSink(voice_recv.AudioSink):
    """Collects PCM per speaker and hands complete chunks to the asyncio loop."""

    def __init__(self, loop, on_chunk):
        super().__init__()
        self.loop = loop
        self.on_chunk = on_chunk
        self.buffers = defaultdict(bytearray)
        self.started = {}
        self.lock = threading.Lock()
        self.bytes_per_second = 48000 * 2 * 2  # 48 kHz, stereo, 16-bit PCM
        self.target_bytes = self.bytes_per_second * CHUNK_SECONDS

    def write(self, user, data):
        if user is None or not getattr(user, "bot", False) is False:
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
        asyncio.run_coroutine_threadsafe(
            self.on_chunk(user, payload), self.loop
        )

    def cleanup(self):
        with self.lock:
            self.buffers.clear()


class VoiceCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.sessions = {}
        self._client = None

    voice = app_commands.Group(name="voice", description="Voice-Channel und Transkription")

    def _client_ready(self):
        if OpenAI is None:
            return None, "Das OpenAI-Paket ist nicht installiert."
        if not os.environ.get("OPENAI_API_KEY"):
            return None, "OPENAI_API_KEY fehlt. Für die Transkription wird ein Speech-to-Text-Dienst benötigt."
        return OpenAI(), None

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
    @app_commands.describe(enabled="True = starten, False = stoppen", channel="Textkanal für das Transkript")
    async def transcribe(self, interaction: discord.Interaction, enabled: bool, channel: discord.TextChannel | None = None):
        if not interaction.guild:
            await interaction.response.send_message("Nur auf einem Server möglich.", ephemeral=True)
            return
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("Du musst in einem Voice-Channel sein.", ephemeral=True)
            return

        if enabled:
            client, error = self._client_ready()
            if error:
                await interaction.response.send_message(f"❌ {error}", ephemeral=True)
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

            loop = asyncio.get_running_loop()
            session = {"enabled": True, "vc": vc, "channel": target, "client": client}

            async def on_chunk(user, pcm):
                if not session["enabled"]:
                    return
                try:
                    text = await asyncio.to_thread(self._transcribe_pcm, client, pcm)
                except Exception as exc:
                    print(f"[VOICE STT] {exc}")
                    return
                if not text:
                    return
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
                "Die Sprache wird nur in kurzen Audioabschnitten verarbeitet; diese Cog speichert keine Audiodateien dauerhaft."
            )
        else:
            session = self.sessions.pop(interaction.guild_id, None)
            if session:
                session["enabled"] = False
                try:
                    session["vc"].stop_listening()
                except Exception:
                    pass
            await interaction.response.send_message("🛑 Live-Transkription gestoppt.")

    @voice.command(name="status", description="Zeigt den Voice-Status")
    async def status(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client if interaction.guild else None
        session = self.sessions.get(interaction.guild_id)
        if not vc or not vc.is_connected():
            text = "🔴 Nicht im Voice-Channel"
        else:
            text = f"🟢 Verbunden mit **{vc.channel.name}**"
            if session and session.get("enabled"):
                text += f"\n📝 Transkription: **AN** → {session['channel'].mention}"
            else:
                text += "\n📝 Transkription: **AUS**"
        await interaction.response.send_message(text)

    @staticmethod
    def _transcribe_pcm(client, pcm):
        wav = io.BytesIO()
        with wave.open(wav, "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(48000)
            wf.writeframes(pcm)
        wav.seek(0)
        wav.name = "voice.wav"
        result = client.audio.transcriptions.create(
            model=TRANSCRIBE_MODEL,
            file=wav,
            response_format="text",
        )
        return getattr(result, "text", str(result)).strip()


async def setup(bot):
    await bot.add_cog(VoiceCog(bot))
