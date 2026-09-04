"""Minecraft Server-Status: !server, !server set/unset (eigener Socket-Ping)."""
import asyncio
import re
import socket
import struct

import discord
from discord.ext import commands
from core.db import get_guild_config, set_guild_config
from core.logging import logger

_PING_TIMEOUT = 5
_DEFAULT_PORT = 25565
_MOTD_COLOR_RE = re.compile(r'\u00a7[0-9a-fk-or]')


def _write_varint(buf: bytearray, value: int):
    while True:
        b = value & 0x7F
        value >>= 7
        if value:
            buf.append(b | 0x80)
        else:
            buf.append(b)
            return


def _read_varint(data: bytes, offset: int):
    value = 0
    shift = 0
    while True:
        b = data[offset]
        offset += 1
        value |= (b & 0x7F) << shift
        if not (b & 0x80):
            return value, offset
        shift += 7


def _ping(host: str, port: int):
    """Minecraft-Server-Ping (Protokoll-Status). Gibt dict oder wirft Exception."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(_PING_TIMEOUT)
    try:
        sock.connect((host, port))
        host_bytes = host.encode('utf-8')
        packet = bytearray()
        _write_varint(packet, 0x00)
        _write_varint(packet, 47)
        _write_varint(packet, len(host_bytes))
        packet += host_bytes
        packet += struct.pack('>H', port)
        _write_varint(packet, 1)
        handshake = bytes(packet)

        frame = bytearray()
        _write_varint(frame, len(handshake))
        frame += handshake
        sock.sendall(bytes(frame))

        sock.sendall(bytes([1, 0x00]))

        def _read_until():
            buf = b''
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    raise ConnectionError('Verbindung geschlossen')
                buf += chunk
                if len(buf) >= 1:
                    length, offset = _read_varint(buf, 0)
                    if len(buf) >= length + offset:
                        return buf[offset:length + offset]

        payload = _read_until()
        if payload and payload[0] == 0x00:
            length, offset = _read_varint(payload, 1)
            raw = payload[offset:offset + length].decode('utf-8', errors='replace')
        else:
            raw = payload[1:].decode('utf-8', errors='replace')
        import json
        return json.loads(raw)
    finally:
        sock.close()


class MCStatus(commands.Cog):
    """Minecraft Server-Status-Command mit eigenem Status-Ping."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _config(self, guild_id: int):
        cfg = get_guild_config(guild_id)
        host = (cfg.get('server_ip') or '').strip()
        port = _DEFAULT_PORT
        try:
            port = int(cfg.get('server_port') or _DEFAULT_PORT)
        except Exception:
            pass
        return host, port

    @commands.group(name='server', invoke_without_subcommand=True, help='Zeigt den Minecraft-Server-Status')
    async def server(self, ctx: commands.Context):
        host, port = self._config(ctx.guild.id)
        if not host:
            embed = discord.Embed(
                title='⛏️ Minecraft Server',
                description='Kein Server konfiguriert.\nAdmin: `!server set <ip> [port]`',
                color=discord.Color.orange()
            )
            return await ctx.send(embed=embed)
        await ctx.typing()
        try:
            status = await asyncio.to_thread(_ping, host, port)
            version = status.get('version', {}).get('name', 'unbekannt')
            motd = _MOTD_COLOR_RE.sub('', status.get('description', {}).get('text', '')) if isinstance(
                status.get('description'), dict) else _MOTD_COLOR_RE.sub('', str(status.get('description', '')))
            players = status.get('players', {})
            online = players.get('online', 0)
            max_players = players.get('max', 0)
            sample = players.get('sample', [])
            names = '\n'.join(p.get('name', '') for p in sample[:10]) or '*niemand online*'

            embed = discord.Embed(
                title=f'⛏️ {host}:{port}',
                description=motd[:1000] or 'Minecraft Server',
                color=discord.Color.green()
            )
            embed.add_field(name='Version', value=version[:50], inline=True)
            embed.add_field(name='Spieler', value=f'{online}/{max_players}', inline=True)
            embed.add_field(name='Online', value=names, inline=False)
        except Exception:
            embed = discord.Embed(
                title=f'⛏️ {host}:{port}',
                description='❌ Server nicht erreichbar (offline oder falsche IP/Port).',
                color=discord.Color.red()
            )
        await ctx.send(embed=embed)

    @server.command(name='set', help='Setzt IP und Port: !server set <ip> [port] (Admin)')
    @commands.has_permissions(administrator=True)
    async def server_set(self, ctx: commands.Context, host: str, port: int = _DEFAULT_PORT):
        if not re.match(r'^[\w.\-]+$', host):
            return await ctx.send('⚠️ Ungültige IP/Adresse.')
        set_guild_config(ctx.guild.id, 'server_ip', host)
        set_guild_config(ctx.guild.id, 'server_port', port)
        await ctx.send(f'✅ Server gesetzt: `{host}:{port}`')

    @server.command(name='unset', help='Entfernt den Server (Admin)')
    @commands.has_permissions(administrator=True)
    async def server_unset(self, ctx: commands.Context):
        set_guild_config(ctx.guild.id, 'server_ip', None)
        set_guild_config(ctx.guild.id, 'server_port', None)
        await ctx.send('✅ Server-Config entfernt.')


async def setup(bot):
    await bot.add_cog(MCStatus(bot))
