"""Music: YouTube-Audio über yt-dlp + Voice. Deaktiviert sich gracewfully, wenn ffmpeg fehlt."""
import asyncio
import os
import shutil
import subprocess
import threading
import time as _time

import discord
from discord import app_commands
from discord.ext import commands

from core.config import MUSIC_DISABLED_MSG, DEFAULT_VOLUME
from core.logging import logger

try:
    import yt_dlp
    YTDLP_AVAILABLE = True
except Exception:
    yt_dlp = None
    YTDLP_AVAILABLE = False

try:
    import nacl
    NACL_AVAILABLE = True
except Exception:
    nacl = None
    NACL_AVAILABLE = False

FFMPEG = shutil.which('ffmpeg') or shutil.which('ffmpeg.exe')


class MusicPlayer:
    """Wiedergabequelle für einen Voice-Client (eigener Thread, um Blocking-Audio zu vermeiden)."""

    def __init__(self, guild_id, voice_client):
        self.guild_id = guild_id
        self.vc = voice_client
        self.queue = []
        self.current = None
        self._thread = None
        self._stop = threading.Event()

    def play_next(self):
        self.vc.play(discord.FFmpegPCMAudio(self.current['url'], before_options='-reconnect 1 -reconnect_streamed 1', options='-vn'),
                     after=lambda e: self._after(e))

    def _after(self, error):
        if error:
            logger.warning(f'Audio error in {self.guild_id}: {error}')
        if self._stop.is_set():
            return
        if self.queue:
            self.current = self.queue.pop(0)
            self.play_next()
        else:
            self.current = None


PLAYERS = {}


def _is_enabled():
    return bool(FFMPEG) and YTDLP_AVAILABLE and NACL_AVAILABLE


def _ytdlp_search(query: str):
    """Sucht einen Track via yt-dlp und liefert (url, title)."""
    if not YTDLP_AVAILABLE:
        raise RuntimeError('yt-dlp nicht installiert')
    opts = {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'default_search': 'ytsearch',
        'extract_flat': False,
        'socket_timeout': 15,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(query, download=False)
        if 'entries' in info and info['entries']:
            info = info['entries'][0]
        url = info.get('url') or info.get('webpage_url')
        title = info.get('title') or query
        return url, title


class MusicCog(commands.Cog):
    """Musik: play, skip, stop, queue, nowplaying."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @staticmethod
    def _disabled_embed():
        return discord.Embed(
            title='🎵 Musik deaktiviert',
            description=MUSIC_DISABLED_MSG,
            color=discord.Color.red(),
        )

    @app_commands.command(name='play', description='Spielt einen Song oder YouTube-Link ab')
    @app_commands.describe(query='Song-Titel oder YouTube-URL')
    async def cmd_play(self, interaction: discord.Interaction, query: str):
        if not _is_enabled():
            await interaction.response.send_message(embed=self._disabled_embed())
            return
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message('Du musst in einem Voice-Channel sein!', ephemeral=True)
            return
        vc = interaction.guild.voice_client
        if vc is None:
            try:
                vc = await interaction.user.voice.channel.connect()
            except Exception as e:
                await interaction.response.send_message(f'Konnte nicht verbinden: {e}', ephemeral=True)
                return

        await interaction.response.defer()
        try:
            url, title = await asyncio.to_thread(_ytdlp_search, query)
        except Exception as e:
            await interaction.followup.send(f'❌ Suche fehlgeschlagen: {e}', ephemeral=True)
            return

        player = PLAYERS.get(interaction.guild_id)
        if player is None or player.vc is None:
            player = MusicPlayer(interaction.guild_id, vc)
            PLAYERS[interaction.guild_id] = player

        track = {'url': url, 'title': title}
        if player.current:
            player.queue.append(track)
            await interaction.followup.send(f'🎵 **{title}** zur Warteschlange hinzugefügt.')
        else:
            player.current = track
            player.play_next()
            await interaction.followup.send(f'🎵 Spiele jetzt: **{title}**')

    @app_commands.command(name='skip', description='Überspringt den aktuellen Song')
    async def cmd_skip(self, interaction: discord.Interaction):
        if not _is_enabled():
            await interaction.response.send_message(embed=self._disabled_embed())
            return
        player = PLAYERS.get(interaction.guild_id)
        if not player or not player.current:
            await interaction.response.send_message('Nichts läuft gerade.', ephemeral=True)
            return
        vc = interaction.guild.voice_client
        if vc:
            vc.stop()
        await interaction.response.send_message('⏭️ Song übersprungen.')

    @app_commands.command(name='stop', description='Stoppt die Wiedergabe und leert die Warteschlange')
    async def cmd_stop(self, interaction: discord.Interaction):
        if not _is_enabled():
            await interaction.response.send_message(embed=self._disabled_embed())
            return
        player = PLAYERS.pop(interaction.guild_id, None)
        vc = interaction.guild.voice_client
        if player:
            player._stop.set()
        if vc:
            try:
                await vc.disconnect()
            except Exception:
                pass
        await interaction.response.send_message('⏹️ Musik gestoppt.')

    @app_commands.command(name='queue', description='Zeigt die aktuelle Warteschlange')
    async def cmd_queue(self, interaction: discord.Interaction):
        if not _is_enabled():
            await interaction.response.send_message(embed=self._disabled_embed())
            return
        player = PLAYERS.get(interaction.guild_id)
        if not player:
            await interaction.response.send_message('Keine Warteschlange.', ephemeral=True)
            return
        lines = []
        if player.current:
            lines.append(f'▶️ **{player.current["title"]}**')
        for i, t in enumerate(player.queue[:10], 1):
            lines.append(f'{i}. {t["title"]}')
        embed = discord.Embed(title='🎶 Warteschlange', description='\n'.join(lines) if lines else 'Leer', color=discord.Color.blue())
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name='nowplaying', description='Zeigt den aktuell laufenden Song')
    async def cmd_nowplaying(self, interaction: discord.Interaction):
        if not _is_enabled():
            await interaction.response.send_message(embed=self._disabled_embed())
            return
        player = PLAYERS.get(interaction.guild_id)
        if not player or not player.current:
            await interaction.response.send_message('Nichts läuft gerade.', ephemeral=True)
            return
        await interaction.response.send_message(f'🎵 Läuft gerade: **{player.current["title"]}**')


async def setup(bot):
    await bot.add_cog(MusicCog(bot))
