"""Auto-Moderation: Link-Filter, Spam-Schutz, Mass-Mentions, Caps, Bad-Words."""
import re
import time
from collections import defaultdict
from datetime import timedelta
from urllib.parse import urlparse

import discord
from discord import app_commands
from discord.ext import commands

from core.db import get_db, get_automod_config, set_automod_config
from core.channelnames import find_channel
from core.logging import logger
from core.badwords import _BAD_WORD_RE, _log_bad_word

# Standard-Konfiguration: Filter-Name → (enabled, limit_value)
_AUTOMOD_DEFAULTS = {
    'links':       (True, 0),
    'spam':        (True, 5),
    'mentions':    (True, 5),
    'caps':        (True, 80),
    'badwords':    (True, 0),
}

_WHITELISTED_DOMAINS = {
    'discord.com', 'discord.gg', 'discordapp.com',
    'youtube.com', 'youtu.be',
    'github.com', 'github.io',
    'twitch.tv',
    'twitter.com', 'x.com',
    'reddit.com',
}

_LINK_RE = re.compile(r'https?://\S+', re.IGNORECASE)


def _is_whitelisted_url(url: str) -> bool:
    """Prüft ob eine URL eine erlaubte Domain enthält."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ''
        if host.startswith('www.'):
            host = host[4:]
        return host in _WHITELISTED_DOMAINS
    except Exception:
        return False


def _is_caps(message_content: str, threshold: int = 80) -> bool:
    """Prüft ob eine Nachricht mindestens `threshold`% Großbuchstaben enthält (bei 10+ Zeichen)."""
    letters = [c for c in message_content if c.isalpha()]
    if len(letters) < 10:
        return False
    uppercase = sum(1 for c in letters if c.isupper())
    return (uppercase / len(letters)) * 100 >= threshold


class AutomodCog(commands.Cog):
    """Auto-Moderation: Filter für Links, Spam, Erwähnungen, Großbuchstaben und Schimpfwörter."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # In-Memory Spam-Tracking: {guild_id: {user_id: [timestamps]}}
        self._spam_cache: dict[int, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
        # In-Memory Warn-Counter: {guild_id: {user_id: warn_count}}
        self._warn_cache: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
        # Eskalations-Level: {guild_id: {user_id: level}} (0=basis, 1=1min, 2=10min, 3=100min...)
        self._timeout_level: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))

    def _get_config(self, guild_id: int) -> dict:
        """Lädt die AutoMod-Konfiguration eines Servers (mit Fallback auf Defaults)."""
        db_config = get_automod_config(guild_id)
        result = {}
        for name, (default_enabled, default_limit) in _AUTOMOD_DEFAULTS.items():
            if name in db_config:
                result[name] = db_config[name]
            else:
                result[name] = {'enabled': default_enabled, 'limit_value': default_limit}
        return result

    async def _log_violation(self, guild: discord.Guild, user: discord.Member,
                             channel: discord.abc.Messageable, reason: str, content: str):
        """Loggt einen Verstoß in #bad-word-log."""
        try:
            log_ch = find_channel(guild, 'bad-word-log')
            if log_ch:
                embed = discord.Embed(
                    title=f'🛡️ AutoMod: {reason}',
                    description=content[:1500],
                    color=discord.Color.red(),
                    timestamp=discord.utils.utcnow(),
                )
                embed.set_author(name=f'{user} ({user.id})', icon_url=user.display_avatar.url)
                embed.add_field(name='Kanal', value=channel.mention if hasattr(channel, 'mention') else str(channel), inline=True)
                await log_ch.send(embed=embed)
        except Exception as e:
            logger.warning(f'AutoMod-Log fehlgeschlagen: {e}')

    async def _handle_violation(self, message: discord.Message, reason: str):
        """Löscht die Nachricht, warnt den User und prüft auf Timeout (eskalierend)."""
        guild = message.guild
        user = message.author
        content = message.content

        # Nachricht löschen
        try:
            await message.delete()
        except Exception:
            pass

        # User per DM warnen
        try:
            await user.send(
                f'🛡️ **AutoMod Warnung** in **{guild.name}**\n'
                f'Grund: **{reason}**\n'
                f'Deine Nachricht wurde gelöscht. Bei weiteren Verstößen droht ein Timeout.'
            )
        except Exception:
            pass

        # In #bad-word-log loggen
        await self._log_violation(guild, user, message.channel, reason, content)

        # Warn-Counter erhöhen
        gid = guild.id
        uid = user.id
        self._warn_cache[gid][uid] += 1
        warn_count = self._warn_cache[gid][uid]

        # 3 Warns → eskalierender Timeout
        if warn_count >= 3:
            # Check mute_immune.txt
            try:
                from core.muteimmune import is_mute_immune
                if is_mute_immune(user.id):
                    return
            except Exception:
                pass

            level = self._timeout_level[gid][uid]
            # Timeout-Dauer: Level 0=1min, 1=10min, 2=100min, 3=1000min...
            timeout_minutes = 10 ** level if level > 0 else 1
            timeout_minutes = min(timeout_minutes, 40320)  # Discord max: 28 Tage = 40320 min

            try:
                until = (discord.utils.utcnow() + timedelta(minutes=timeout_minutes)).isoformat()
                await user.edit(
                    communication_disabled_until=until,
                    reason=f'AutoMod: {warn_count} Verstöße – Timeout Stufe {level + 1}'
                )

                # DM an User
                if timeout_minutes >= 60:
                    time_text = f'{timeout_minutes // 60} Stunden'
                else:
                    time_text = f'{timeout_minutes} Minuten'
                try:
                    await user.send(
                        f'⏱️ **Timeout für {time_text}** in **{guild.name}**\n'
                        f'Du hast {warn_count} AutoMod-Verstöße begangen.\n'
                        f'Nächste Stufe: **{self._next_timeout(level + 1)}**'
                    )
                except Exception:
                    pass

                # Log in admin-log
                log_ch = find_channel(guild, 'admin-log')
                if log_ch:
                    embed = discord.Embed(
                        title=f'⏱️ AutoMod Timeout – Stufe {level + 1}',
                        description=(
                            f'{user.mention} wurde für **{time_text}** gemutet.\n'
                            f'Verstöße: {warn_count} · Nächste Stufe: {self._next_timeout(level + 2)}'
                        ),
                        color=discord.Color.red()
                    )
                    embed.set_thumbnail(url=user.display_avatar.url)
                    await log_ch.send(embed=embed)

            except Exception as e:
                logger.warning(f'AutoMod-Timeout fehlgeschlagen: {e}')

            # Counter zurücksetzen, Level erhöhen
            self._warn_cache[gid][uid] = 0
            self._timeout_level[gid][uid] = level + 1

    def _next_timeout(self, next_level: int) -> str:
        """Liefert den Text für die nächste Timeout-Stufe."""
        minutes = 10 ** (next_level - 1) if next_level > 1 else 1
        if minutes >= 60:
            return f'{minutes // 60} Stunden'
        return f'{minutes} Minuten'

    # ── Filter: Links ───────────────────────────────────────────────────────────
    async def _check_links(self, message: discord.Message, config: dict) -> bool:
        """Blockiert externe Links von Nicht-Admins (whitelisted Domains ausgenommen)."""
        if not config.get('links', {}).get('enabled', True):
            return False
        if message.author.guild_permissions.administrator:
            return False
        urls = _LINK_RE.findall(message.content)
        for url in urls:
            if not _is_whitelisted_url(url):
                await self._handle_violation(message, 'Externer Link')
                return True
        return False

    # ── Filter: Spam ────────────────────────────────────────────────────────────
    async def _check_spam(self, message: discord.Message, config: dict) -> bool:
        """Blockiert 5+ Nachrichten in 10 Sekunden vom selben User."""
        spam_cfg = config.get('spam', {})
        if not spam_cfg.get('enabled', True):
            return False
        threshold = spam_cfg.get('limit_value', 5) or 5
        now = time.time()
        uid = message.author.id
        gid = message.guild.id
        self._spam_cache[gid][uid].append(now)
        # Alte Einträge entfernen (>10 Sekunden)
        self._spam_cache[gid][uid] = [t for t in self._spam_cache[gid][uid] if now - t < 10]
        if len(self._spam_cache[gid][uid]) > threshold:
            self._spam_cache[gid][uid] = []
            await self._handle_violation(message, 'Spam')
            return True
        return False

    # ── Filter: Mass-Mentions ───────────────────────────────────────────────────
    async def _check_mentions(self, message: discord.Message, config: dict) -> bool:
        """Blockiert 5+ Erwähnungen in einer Nachricht."""
        mentions_cfg = config.get('mentions', {})
        if not mentions_cfg.get('enabled', True):
            return False
        threshold = mentions_cfg.get('limit_value', 5) or 5
        mention_count = (len(message.mentions) + len(message.role_mentions)
                         + (1 if message.mention_everyone else 0))
        if mention_count >= threshold:
            await self._handle_violation(message, f'Mass-Mentions ({mention_count})')
            return True
        return False

    # ── Filter: Caps ────────────────────────────────────────────────────────────
    async def _check_caps(self, message: discord.Message, config: dict) -> bool:
        """Blockiert Nachrichten mit 80%+ Großbuchstaben (min. 10 Zeichen)."""
        caps_cfg = config.get('caps', {})
        if not caps_cfg.get('enabled', True):
            return False
        threshold = caps_cfg.get('limit_value', 80) or 80
        if _is_caps(message.content, threshold):
            await self._handle_violation(message, f'Caps ({threshold}%)')
            return True
        return False

    # ── Filter: Bad Words ──────────────────────────────────────────────────────
    async def _check_badwords(self, message: discord.Message, config: dict) -> bool:
        """Blockiert Nachrichten mit Schimpfwörtern."""
        if not config.get('badwords', {}).get('enabled', True):
            return False
        if _BAD_WORD_RE.search(message.content):
            try:
                await message.delete()
            except Exception:
                pass
            try:
                await message.author.send(
                    f'🛡️ **AutoMod Warnung** in **{message.guild.name}**\n'
                    f'Grund: **Schimpfwort**\n'
                    f'Deine Nachricht wurde gelöscht.'
                )
            except Exception:
                pass
            await _log_bad_word(message.guild, message.author, message.channel, message.content)
            return True
        return False

    # ── On-Message Listener ─────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Prüft alle AutoMod-Filter bei jeder Nachricht."""
        if message.author.bot:
            return
        if not message.guild:
            return

        config = self._get_config(message.guild.id)

        # Reihenfolge: Spam → Links → Mentions → Caps → Bad Words
        if await self._check_spam(message, config):
            return
        if await self._check_links(message, config):
            return
        if await self._check_mentions(message, config):
            return
        if await self._check_caps(message, config):
            return
        if await self._check_badwords(message, config):
            return

    # ── On-Message-Edit Listener ────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        """Prüft editierten Inhalt erneut – verhindert Filter-Bypass per Edit."""
        if after.author.bot:
            return
        if not after.guild:
            return
        if before.content == after.content:
            return

        config = self._get_config(after.guild.id)

        # Links → Mentions → Caps → Bad Words (Spam-Check entfällt bei Edits)
        if await self._check_links(after, config):
            return
        if await self._check_mentions(after, config):
            return
        if await self._check_caps(after, config):
            return
        if await self._check_badwords(after, config):
            return

    # ── /automod config ────────────────────────────────────────────────────────
    automod_group = app_commands.Group(name='automod', description='Auto-Moderation Einstellungen')
    config_group = app_commands.Group(name='config', description='AutoMod Filter konfigurieren', parent=automod_group)

    @config_group.command(name='show', description='Zeigt die aktuelle AutoMod-Konfiguration')
    @app_commands.default_permissions(administrator=True)
    async def config_show(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('Keine Berechtigung!', ephemeral=True)
            return
        config = self._get_config(interaction.guild_id)
        lines = []
        for name, cfg in config.items():
            status = '✅ Aktiviert' if cfg['enabled'] else '❌ Deaktiviert'
            limit = f' (Limit: {cfg["limit_value"]})' if cfg['limit_value'] else ''
            lines.append(f'**{name.title()}**: {status}{limit}')
        embed = discord.Embed(
            title='🛡️ AutoMod Konfiguration',
            description='\n'.join(lines),
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @config_group.command(name='toggle', description='Aktiviert/Deaktiviert einen AutoMod-Filter')
    @app_commands.describe(
        filter_name='Welcher Filter',
        enabled='Aktivieren oder deaktivieren',
    )
    @app_commands.choices(filter_name=[
        app_commands.Choice(name='🔗 Links', value='links'),
        app_commands.Choice(name='💬 Spam', value='spam'),
        app_commands.Choice(name='📢 Mass-Mentions', value='mentions'),
        app_commands.Choice(name='🔠 Caps', value='caps'),
        app_commands.Choice(name='🚫 Bad Words', value='badwords'),
    ])
    @app_commands.default_permissions(administrator=True)
    async def config_toggle(self, interaction: discord.Interaction,
                            filter_name: app_commands.Choice[str], enabled: bool):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('Keine Berechtigung!', ephemeral=True)
            return
        set_automod_config(interaction.guild_id, filter_name.value, enabled=enabled)
        status = 'aktiviert' if enabled else 'deaktiviert'
        embed = discord.Embed(
            title='🛡️ AutoMod Filter',
            description=f'Filter **{filter_name.name}** wurde **{status}**.',
            color=discord.Color.green() if enabled else discord.Color.red(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @config_group.command(name='limit', description='Setzt den Grenzwert für einen AutoMod-Filter')
    @app_commands.describe(
        filter_name='Welcher Filter',
        limit='Neuer Grenzwert (0 = Standard)',
    )
    @app_commands.choices(filter_name=[
        app_commands.Choice(name='💬 Spam (Nachrichten/10s)', value='spam'),
        app_commands.Choice(name='📢 Mass-Mentions', value='mentions'),
        app_commands.Choice(name='🔠 Caps (% Großbuchstaben)', value='caps'),
    ])
    @app_commands.default_permissions(administrator=True)
    async def config_limit(self, interaction: discord.Interaction,
                           filter_name: app_commands.Choice[str], limit: int):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('Keine Berechtigung!', ephemeral=True)
            return
        if limit < 0 or limit > 100:
            await interaction.response.send_message('Limit muss zwischen 0 und 100 liegen.', ephemeral=True)
            return
        # Aktuellen Status beibehalten
        current = self._get_config(interaction.guild_id).get(filter_name.value, {})
        set_automod_config(interaction.guild_id, filter_name.value,
                           enabled=current.get('enabled', True), limit_value=limit)
        embed = discord.Embed(
            title='🛡️ AutoMod Limit',
            description=f'Limit für **{filter_name.name}** auf **{limit}** gesetzt.',
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @config_group.command(name='whitelist', description='Zeigt die whitelisteten Domains')
    @app_commands.default_permissions(administrator=True)
    async def config_whitelist(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('Keine Berechtigung!', ephemeral=True)
            return
        embed = discord.Embed(
            title='🛡️ AutoMod Whitelist',
            description='Diese Domains sind vom Link-Filter ausgenommen:\n' +
                        '\n'.join(f'• `{d}`' for d in sorted(_WHITELISTED_DOMAINS)),
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @config_group.command(name='reset', description='Setzt alle AutoMod-Einstellungen zurück')
    @app_commands.default_permissions(administrator=True)
    async def config_reset(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('Keine Berechtigung!', ephemeral=True)
            return
        for name, (enabled, limit) in _AUTOMOD_DEFAULTS.items():
            set_automod_config(interaction.guild_id, name, enabled=enabled, limit_value=limit)
        embed = discord.Embed(
            title='🛡️ AutoMod Reset',
            description='Alle Einstellungen wurden auf die Standardwerte zurückgesetzt.',
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AutomodCog(bot))
