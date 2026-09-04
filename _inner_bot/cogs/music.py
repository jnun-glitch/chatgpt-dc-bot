"""Music player using yt-dlp + FFmpeg.

The player intentionally keeps the dependency surface small while adding the
controls expected from a modern modular Discord music cog.
"""

from __future__ import annotations

import asyncio
import random
import shutil
import threading

import discord
from discord import app_commands
from discord.ext import commands

from core.config import MUSIC_DISABLED_MSG
from core.logging import logger
from core.permissions import can_manage_bot

try:
    import yt_dlp
except Exception:
    yt_dlp = None

try:
    import nacl  # noqa: F401
except Exception:
    nacl = None

FFMPEG = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")


def _is_enabled() -> bool:
    return bool(FFMPEG and yt_dlp and nacl)


def _search(query: str) -> tuple[str, str, str | None]:
    if yt_dlp is None:
        raise RuntimeError("yt-dlp ist nicht installiert.")
    opts = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "default_search": "ytsearch",
        "socket_timeout": 20,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(query, download=False)
        if info.get("entries"):
            info = info["entries"][0]
        url = info.get("url")
        webpage = info.get("webpage_url") or info.get("original_url")
        title = info.get("title") or query
        if not url:
            raise RuntimeError("Kein abspielbarer Audiostream gefunden.")
        return url, title, webpage


class MusicPlayer:
    def __init__(self, guild_id: int, voice_client: discord.VoiceClient, loop: asyncio.AbstractEventLoop):
        self.guild_id = guild_id
        self.vc = voice_client
        self.loop = loop
        self.queue: list[dict] = []
        self.current: dict | None = None
        self.repeat = False
        self.volume = 0.5
        self._stopping = False
        self._lock = threading.Lock()

    def source(self, track: dict):
        options = "-vn"
        before = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
        source = discord.FFmpegPCMAudio(track["url"], before_options=before, options=options)
        return discord.PCMVolumeTransformer(source, volume=self.volume)

    def play_current(self):
        if not self.current or not self.vc.is_connected():
            return
        if self.vc.is_playing() or self.vc.is_paused():
            self.vc.stop()
        self.vc.play(self.source(self.current), after=self._after)

    def _after(self, error: Exception | None):
        if error:
            logger.warning("Music error in guild %s: %s", self.guild_id, error)
        if self._stopping:
            return
        asyncio.run_coroutine_threadsafe(self.advance(error), self.loop)

    async def advance(self, error: Exception | None = None):
        if self._stopping:
            return
        if self.repeat and self.current:
            self.play_current()
            return
        if self.queue:
            self.current = self.queue.pop(0)
            try:
                self.play_current()
            except Exception as exc:
                logger.warning("Could not start next track: %s", exc)
                if self.queue:
                    await self.advance(exc)
                else:
                    self.current = None
        else:
            self.current = None

    async def stop(self):
        self._stopping = True
        self.queue.clear()
        self.current = None
        if self.vc.is_playing() or self.vc.is_paused():
            self.vc.stop()


PLAYERS: dict[int, MusicPlayer] = {}


class MusicCog(commands.Cog):
    """Modern lightweight music controls."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @staticmethod
    def _disabled_embed():
        return discord.Embed(title="🎵 Musik nicht verfügbar", description=MUSIC_DISABLED_MSG, color=discord.Color.red())

    @staticmethod
    def _same_voice_channel(interaction: discord.Interaction, player: MusicPlayer | None) -> bool:
        """Prevent users in other voice channels from controlling the player."""
        if not player or not player.vc or not player.vc.is_connected():
            return False
        user_voice = getattr(interaction.user, "voice", None)
        return bool(user_voice and user_voice.channel and player.vc.channel and user_voice.channel.id == player.vc.channel.id)

    async def _can_control(self, interaction: discord.Interaction, player: MusicPlayer | None) -> bool:
        if not interaction.guild or player is None:
            return False
        if can_manage_bot(interaction.user):
            return True
        return self._same_voice_channel(interaction, player)

    async def _get_player(self, interaction: discord.Interaction, connect: bool = False) -> MusicPlayer | None:
        guild = interaction.guild
        if not guild:
            return None
        player = PLAYERS.get(guild.id)
        vc = guild.voice_client
        if player and vc and vc.is_connected():
            player.vc = vc
            return player
        if not connect:
            return player
        if not interaction.user.voice or not interaction.user.voice.channel:
            return None
        if vc and vc.is_connected():
            if vc.channel.id != interaction.user.voice.channel.id:
                # Do not let ordinary users hijack the bot from another channel.
                if not can_manage_bot(interaction.user):
                    return None
                await vc.move_to(interaction.user.voice.channel)
        else:
            vc = await interaction.user.voice.channel.connect()
        player = MusicPlayer(guild.id, vc, asyncio.get_running_loop())
        PLAYERS[guild.id] = player
        return player

    async def _deny(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "❌ Du musst im selben Voice-Channel wie der Bot sein (oder den Bot verwalten).",
            ephemeral=True,
        )

    @app_commands.command(name="play", description="Spielt einen Song oder Link ab")
    @app_commands.describe(query="Songname oder unterstützter Musik-Link")
    async def play(self, interaction: discord.Interaction, query: str):
        if not _is_enabled():
            await interaction.response.send_message(embed=self._disabled_embed(), ephemeral=True)
            return
        if not interaction.guild or not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("Du musst in einem Voice-Channel sein.", ephemeral=True)
            return
        existing = PLAYERS.get(interaction.guild.id)
        if existing and not await self._can_control(interaction, existing):
            await self._deny(interaction)
            return
        await interaction.response.defer()
        try:
            url, title, webpage = await asyncio.to_thread(_search, query)
            player = await self._get_player(interaction, connect=True)
            if player is None:
                raise RuntimeError("Voice-Verbindung konnte nicht hergestellt werden oder der Bot ist in einem anderen Voice-Channel.")
            track = {"url": url, "title": title, "webpage": webpage, "requester": interaction.user.display_name}
            if player.current:
                player.queue.append(track)
                await interaction.followup.send(f"🎶 **{title}** wurde auf Position **{len(player.queue)}** gesetzt.")
            else:
                player.current = track
                player.play_current()
                await interaction.followup.send(f"▶️ Spiele jetzt: **{title}**")
        except Exception as exc:
            logger.exception("Music play failed", exc_info=exc)
            await interaction.followup.send(f"❌ Wiedergabe fehlgeschlagen: `{str(exc)[:300]}`", ephemeral=True)

    @app_commands.command(name="pause", description="Pausiert die Musik")
    async def pause(self, interaction: discord.Interaction):
        player = PLAYERS.get(interaction.guild_id)
        if not await self._can_control(interaction, player):
            await self._deny(interaction)
            return
        if not player.vc.is_playing():
            await interaction.response.send_message("Nichts läuft.", ephemeral=True)
            return
        player.vc.pause()
        await interaction.response.send_message("⏸️ Musik pausiert.")

    @app_commands.command(name="resume", description="Setzt die Musik fort")
    async def resume(self, interaction: discord.Interaction):
        player = PLAYERS.get(interaction.guild_id)
        if not await self._can_control(interaction, player):
            await self._deny(interaction)
            return
        if not player.vc.is_paused():
            await interaction.response.send_message("Die Musik ist nicht pausiert.", ephemeral=True)
            return
        player.vc.resume()
        await interaction.response.send_message("▶️ Musik fortgesetzt.")

    @app_commands.command(name="skip", description="Überspringt den aktuellen Song")
    async def skip(self, interaction: discord.Interaction):
        player = PLAYERS.get(interaction.guild_id)
        if not await self._can_control(interaction, player):
            await self._deny(interaction)
            return
        if not player.current:
            await interaction.response.send_message("Nichts läuft.", ephemeral=True)
            return
        player.vc.stop()
        await interaction.response.send_message("⏭️ Übersprungen.")

    @app_commands.command(name="stop", description="Stoppt die Musik und leert die Queue")
    async def stop(self, interaction: discord.Interaction):
        player = PLAYERS.get(interaction.guild_id)
        if not await self._can_control(interaction, player):
            await self._deny(interaction)
            return
        player = PLAYERS.pop(interaction.guild_id, None)
        if not player:
            await interaction.response.send_message("Keine Musik-Session aktiv.", ephemeral=True)
            return
        await player.stop()
        if player.vc.is_connected():
            try:
                await player.vc.disconnect()
            except Exception as exc:
                logger.warning("Music disconnect failed: %s", exc)
        await interaction.response.send_message("⏹️ Musik gestoppt.")

    @app_commands.command(name="queue", description="Zeigt die Warteschlange")
    async def queue(self, interaction: discord.Interaction):
        player = PLAYERS.get(interaction.guild_id)
        if not player:
            await interaction.response.send_message("📭 Queue ist leer.", ephemeral=True)
            return
        lines = []
        if player.current:
            lines.append(f"▶️ **Jetzt:** {player.current['title']}")
        if player.queue:
            lines.append("")
            lines.extend(f"**{i}.** {track['title']}" for i, track in enumerate(player.queue[:20], 1))
        embed = discord.Embed(title="🎶 Musik-Queue", description="\n".join(lines) or "Leer", color=discord.Color.blurple())
        embed.set_footer(text=f"Repeat: {'AN' if player.repeat else 'AUS'} · {len(player.queue)} Titel warten")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="remove", description="Entfernt einen Song aus der Queue")
    @app_commands.describe(position="Position in der Queue, beginnend bei 1")
    async def remove(self, interaction: discord.Interaction, position: app_commands.Range[int, 1, 100]):
        player = PLAYERS.get(interaction.guild_id)
        if not await self._can_control(interaction, player):
            await self._deny(interaction)
            return
        if not player or position > len(player.queue):
            await interaction.response.send_message("Diese Queue-Position existiert nicht.", ephemeral=True)
            return
        track = player.queue.pop(position - 1)
        await interaction.response.send_message(f"🗑️ **{track['title']}** entfernt.")

    @app_commands.command(name="clear", description="Leert die Warteschlange")
    async def clear(self, interaction: discord.Interaction):
        player = PLAYERS.get(interaction.guild_id)
        if not await self._can_control(interaction, player):
            await self._deny(interaction)
            return
        if not player:
            await interaction.response.send_message("Queue ist bereits leer.", ephemeral=True)
            return
        count = len(player.queue)
        player.queue.clear()
        await interaction.response.send_message(f"🧹 **{count}** Titel aus der Queue entfernt.")

    @app_commands.command(name="shuffle", description="Mischt die Warteschlange")
    async def shuffle(self, interaction: discord.Interaction):
        player = PLAYERS.get(interaction.guild_id)
        if not await self._can_control(interaction, player):
            await self._deny(interaction)
            return
        if not player or len(player.queue) < 2:
            await interaction.response.send_message("Nicht genug Titel zum Mischen.", ephemeral=True)
            return
        random.shuffle(player.queue)
        await interaction.response.send_message("🔀 Queue gemischt.")

    @app_commands.command(name="loop", description="Aktiviert/deaktiviert Repeat für den aktuellen Song")
    @app_commands.describe(enabled="Repeat an oder aus")
    async def loop(self, interaction: discord.Interaction, enabled: bool):
        player = PLAYERS.get(interaction.guild_id)
        if not await self._can_control(interaction, player):
            await self._deny(interaction)
            return
        if not player or not player.current:
            await interaction.response.send_message("Nichts läuft.", ephemeral=True)
            return
        player.repeat = enabled
        await interaction.response.send_message(f"🔁 Repeat **{'aktiviert' if enabled else 'deaktiviert'}**.")

    @app_commands.command(name="volume", description="Setzt die Musiklautstärke")
    @app_commands.describe(percent="0 bis 100")
    async def volume(self, interaction: discord.Interaction, percent: app_commands.Range[int, 0, 100]):
        player = PLAYERS.get(interaction.guild_id)
        if not await self._can_control(interaction, player):
            await self._deny(interaction)
            return
        if not player:
            await interaction.response.send_message("Keine Musik-Session aktiv.", ephemeral=True)
            return
        player.volume = percent / 100
        if player.vc.source and isinstance(player.vc.source, discord.PCMVolumeTransformer):
            player.vc.source.volume = player.volume
        await interaction.response.send_message(f"🔊 Lautstärke auf **{percent}%** gesetzt.")

    @app_commands.command(name="nowplaying", description="Zeigt den aktuellen Song")
    async def nowplaying(self, interaction: discord.Interaction):
        player = PLAYERS.get(interaction.guild_id)
        if not player or not player.current:
            await interaction.response.send_message("Nichts läuft.", ephemeral=True)
            return
        track = player.current
        embed = discord.Embed(title="🎵 Jetzt läuft", description=f"**{track['title']}**", color=discord.Color.blurple())
        embed.add_field(name="Angefordert von", value=track.get("requester", "unbekannt"), inline=True)
        embed.add_field(name="Repeat", value="AN" if player.repeat else "AUS", inline=True)
        if track.get("webpage"):
            embed.url = track["webpage"]
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(MusicCog(bot))
