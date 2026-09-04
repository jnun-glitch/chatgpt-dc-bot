"""Advanced AutoMod with link, spam and raid protection.

The module is intentionally conservative: moderators can tune limits per server,
while administrators retain an allowlist for trusted domains/channels/roles.
"""
from __future__ import annotations

import re
import time
import unicodedata
from collections import defaultdict, deque
from datetime import timedelta
from urllib.parse import unquote, urlparse

import discord
from discord import app_commands
from discord.ext import commands

from core.badwords import find_bad_word, _log_bad_word
from core.channelnames import find_channel
from core.db import get_db, get_automod_config, set_automod_config
from core.logging import logger


DEFAULTS = {
    "links": (True, 0),
    "invites": (True, 0),
    "spam": (True, 5),
    "mentions": (True, 5),
    "caps": (True, 80),
    "badwords": (True, 0),
    "duplicates": (True, 3),
    "emoji": (True, 20),
    "newlines": (True, 8),
    "raid": (True, 8),
}

# Trusted defaults. Every other external domain is blocked until an admin adds it.
DEFAULT_ALLOWED_DOMAINS = {
    "discord.com", "discord.gg", "discordapp.com",
    "github.com", "github.io",
    "youtube.com", "youtu.be",
    "twitch.tv",
    "reddit.com",
    "x.com", "twitter.com",
    "google.com", "google.de",
    "microsoft.com", "minecraft.net",
}

SUSPICIOUS_TLDS = {
    "zip", "mov", "click", "download", "country", "gq", "tk", "ml", "cf", "work",
}

URL_RE = re.compile(r"(?i)(?:https?://|www\.)[^\s<>\]\[(){}]+")
MARKDOWN_URL_RE = re.compile(r"(?i)\]\((https?://[^)\s]+)\)")
DISCORD_INVITE_RE = re.compile(r"(?i)(?:https?://)?(?:www\.)?(?:discord\.gg|discord(?:app)?\.com/invite)/[A-Za-z0-9-]+")


def _normalize_url_host(host: str) -> str:
    host = host.strip().lower().rstrip(".")
    try:
        host = host.encode("idna").decode("ascii")
    except Exception:
        pass
    if host.startswith("www."):
        host = host[4:]
    return host


def _extract_urls(content: str) -> list[str]:
    found = URL_RE.findall(content)
    found += MARKDOWN_URL_RE.findall(content)
    # stable de-duplication
    return list(dict.fromkeys(found))


def _url_host(url: str) -> str | None:
    raw = url if re.match(r"(?i)^https?://", url) else f"https://{url}"
    try:
        parsed = urlparse(raw)
        return _normalize_url_host(parsed.hostname or "") or None
    except Exception:
        return None


def _is_external_url(url: str) -> bool:
    host = _url_host(url)
    return bool(host)


def _is_suspicious_url(url: str) -> bool:
    """Heuristic only; Discord itself also has its own suspicious-link protections."""
    raw = url if re.match(r"(?i)^https?://", url) else f"https://{url}"
    try:
        parsed = urlparse(unquote(raw))
        host = _normalize_url_host(parsed.hostname or "")
        if not host:
            return True
        if host.startswith("xn--") or ".xn--" in host:
            return True
        if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", host):
            return True
        if parsed.username or parsed.password:
            return True
        if any(host.endswith("." + tld) for tld in SUSPICIOUS_TLDS):
            return True
        if len(host) > 80 or host.count(".") >= 6:
            return True
        return False
    except Exception:
        return True


def _is_caps(content: str, threshold: int = 80) -> bool:
    letters = [c for c in content if c.isalpha()]
    if len(letters) < 10:
        return False
    return sum(c.isupper() for c in letters) / len(letters) * 100 >= threshold


def _emoji_count(content: str) -> int:
    # Covers the common Unicode emoji blocks without attempting to parse Discord custom emoji.
    return sum(
        1
        for c in content
        if any(
            start <= ord(c) <= end
            for start, end in (
                (0x1F300, 0x1FAFF),
                (0x2600, 0x27BF),
                (0x2300, 0x23FF),
            )
        )
    )


def _clean_duplicate_text(content: str) -> str:
    text = unicodedata.normalize("NFKC", content).casefold()
    text = re.sub(r"\s+", " ", text).strip()
    return text[:500]


class AutomodCog(commands.Cog):
    """Multi-layer AutoMod: links, invites, spam, raids, mentions, caps and words."""

    automod_group = app_commands.Group(name="automod", description="Auto-Moderation Einstellungen")
    config_group = app_commands.Group(
        name="config", description="AutoMod Filter konfigurieren", parent=automod_group
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._spam_cache: dict[int, dict[int, deque[float]]] = defaultdict(lambda: defaultdict(deque))
        self._message_cache: dict[int, dict[int, deque[tuple[float, str]]]] = defaultdict(
            lambda: defaultdict(deque)
        )
        self._warn_cache: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
        self._timeout_level: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
        self._joins: dict[int, deque[tuple[float, int]]] = defaultdict(deque)
        self._raid_until: dict[int, float] = {}
        self._allowlist_cache: dict[int, set[str]] = {}
        self._blocklist_cache: dict[int, set[str]] = {}

    # ---------------- configuration ----------------
    def _get_config(self, guild_id: int) -> dict:
        db_config = get_automod_config(guild_id)
        result = {}
        for name, (enabled, limit_value) in DEFAULTS.items():
            result[name] = db_config.get(name, {"enabled": enabled, "limit_value": limit_value})
        return result

    def _get_domains(self, guild_id: int) -> tuple[set[str], set[str]]:
        if guild_id in self._allowlist_cache:
            return self._allowlist_cache[guild_id], self._blocklist_cache[guild_id]
        allow = set(DEFAULT_ALLOWED_DOMAINS)
        block: set[str] = set()
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                "SELECT value FROM guild_settings WHERE guild_id = ? AND key = ?",
                (str(guild_id), "automod_allowed_domains"),
            )
            row = cur.fetchone()
            if row and row[0]:
                allow.update(_normalize_url_host(x) for x in str(row[0]).split(",") if x.strip())
            cur.execute(
                "SELECT value FROM guild_settings WHERE guild_id = ? AND key = ?",
                (str(guild_id), "automod_blocked_domains"),
            )
            row = cur.fetchone()
            if row and row[0]:
                block.update(_normalize_url_host(x) for x in str(row[0]).split(",") if x.strip())
            conn.close()
        except Exception as exc:
            logger.warning(f"AutoMod Domain-Konfiguration konnte nicht geladen werden: {exc}")
        self._allowlist_cache[guild_id] = {x for x in allow if x}
        self._blocklist_cache[guild_id] = {x for x in block if x}
        return self._allowlist_cache[guild_id], self._blocklist_cache[guild_id]

    def _save_domains(self, guild_id: int, allowed: set[str], blocked: set[str]) -> None:
        conn = get_db()
        cur = conn.cursor()
        for key, values in (
            ("automod_allowed_domains", sorted(allowed)),
            ("automod_blocked_domains", sorted(blocked)),
        ):
            cur.execute(
                "INSERT INTO guild_settings (guild_id, key, value) VALUES (?, ?, ?) "
                "ON CONFLICT(guild_id, key) DO UPDATE SET value = excluded.value",
                (str(guild_id), key, ",".join(values)),
            )
        conn.commit()
        conn.close()
        self._allowlist_cache[guild_id] = set(allowed)
        self._blocklist_cache[guild_id] = set(blocked)

    def _is_exempt(self, message: discord.Message) -> bool:
        if not message.guild or not isinstance(message.author, discord.Member):
            return False
        perms = message.author.guild_permissions
        if perms.administrator or perms.manage_guild or perms.manage_messages:
            return True
        # trusted support/mod roles can moderate without being caught by normal filters
        role_names = {r.name.casefold() for r in message.author.roles}
        return bool(role_names & {"admin", "moderator", "support"})

    def _channel_exempt(self, message: discord.Message) -> bool:
        # Staff can use a dedicated bots/links channel; administrators can add a trusted channel
        # later without disabling the server-wide filter.
        return any(
            token in getattr(message.channel, "name", "").casefold()
            for token in ("bot-commands", "mod-log", "admin-log")
        )

    # ---------------- actions ----------------
    async def _log_violation(self, guild, user, channel, reason: str, content: str, *, count: int | None = None):
        try:
            log_ch = find_channel(guild, "bad-word-log") or find_channel(guild, "admin-log")
            if not log_ch:
                return
            embed = discord.Embed(
                title=f"🛡️ AutoMod: {reason}",
                description=discord.utils.escape_markdown(content[:1800]),
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow(),
            )
            embed.set_author(name=f"{user} ({user.id})", icon_url=user.display_avatar.url)
            embed.add_field(name="Kanal", value=getattr(channel, "mention", str(channel)), inline=True)
            if count is not None:
                embed.add_field(name="Verstöße", value=str(count), inline=True)
            await log_ch.send(embed=embed)
        except Exception as exc:
            logger.warning(f"AutoMod-Log fehlgeschlagen: {exc}")

    async def _delete_message(self, message: discord.Message) -> None:
        try:
            await message.delete()
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            pass

    async def _handle_violation(self, message: discord.Message, reason: str, *, escalate: bool = True):
        guild = message.guild
        user = message.author
        if not guild or not isinstance(user, discord.Member):
            return
        await self._delete_message(message)
        gid, uid = guild.id, user.id
        self._warn_cache[gid][uid] += 1
        count = self._warn_cache[gid][uid]
        await self._log_violation(guild, user, message.channel, reason, message.content, count=count)

        if not escalate or count < 3 or user.guild_permissions.administrator:
            return

        try:
            from core.muteimmune import is_mute_immune
            if is_mute_immune(uid):
                return
        except Exception:
            pass

        level = self._timeout_level[gid][uid]
        minutes = min(10 ** level if level else 1, 40320)
        try:
            await user.timeout(timedelta(minutes=minutes), reason=f"AutoMod: {reason}")
            self._warn_cache[gid][uid] = 0
            self._timeout_level[gid][uid] = level + 1
            await self._log_violation(
                guild, user, message.channel, f"Timeout Stufe {level + 1} ({minutes} Min.)", message.content
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.warning(f"AutoMod Timeout fehlgeschlagen: {exc}")

    # ---------------- filters ----------------
    async def _check_links(self, message: discord.Message, config: dict) -> bool:
        cfg = config["links"]
        if not cfg.get("enabled", True) or self._channel_exempt(message):
            return False
        urls = _extract_urls(message.content)
        if not urls:
            return False
        allow, block = self._get_domains(message.guild.id)
        for url in urls:
            host = _url_host(url)
            if not host:
                await self._handle_violation(message, "Ungültiger Link")
                return True
            if host in block or _is_suspicious_url(url):
                await self._handle_violation(message, f"Verdächtiger externer Link ({host})")
                return True
            # Exact domain or subdomain of an allowlisted domain.
            trusted = any(host == d or host.endswith("." + d) for d in allow)
            if not trusted:
                await self._handle_violation(message, f"Externer Link nicht erlaubt ({host})")
                return True
        return False

    async def _check_invites(self, message: discord.Message, config: dict) -> bool:
        if not config["invites"].get("enabled", True):
            return False
        if DISCORD_INVITE_RE.search(message.content):
            await self._handle_violation(message, "Discord-Invite-Link")
            return True
        return False

    async def _check_spam(self, message: discord.Message, config: dict) -> bool:
        cfg = config["spam"]
        if not cfg.get("enabled", True):
            return False
        limit = max(2, int(cfg.get("limit_value") or 5))
        now = time.monotonic()
        q = self._spam_cache[message.guild.id][message.author.id]
        q.append(now)
        while q and now - q[0] > 10:
            q.popleft()
        if len(q) > limit:
            q.clear()
            await self._handle_violation(message, f"Spam ({limit}+ Nachrichten/10s)")
            return True
        return False

    async def _check_duplicates(self, message: discord.Message, config: dict) -> bool:
        cfg = config["duplicates"]
        if not cfg.get("enabled", True) or not message.content.strip():
            return False
        threshold = max(2, int(cfg.get("limit_value") or 3))
        now = time.monotonic()
        q = self._message_cache[message.guild.id][message.author.id]
        normalized = _clean_duplicate_text(message.content)
        q.append((now, normalized))
        while q and now - q[0][0] > 20:
            q.popleft()
        repeats = sum(1 for _, text in q if text == normalized)
        if repeats >= threshold:
            q.clear()
            await self._handle_violation(message, f"Wiederholungs-Spam ({repeats}x)")
            return True
        return False

    async def _check_mentions(self, message: discord.Message, config: dict) -> bool:
        cfg = config["mentions"]
        if not cfg.get("enabled", True):
            return False
        limit = max(2, int(cfg.get("limit_value") or 5))
        count = len(message.mentions) + len(message.role_mentions) + (1 if message.mention_everyone else 0)
        if count >= limit:
            await self._handle_violation(message, f"Mass-Mentions ({count})")
            return True
        return False

    async def _check_caps(self, message: discord.Message, config: dict) -> bool:
        cfg = config["caps"]
        if not cfg.get("enabled", True):
            return False
        threshold = min(100, max(50, int(cfg.get("limit_value") or 80)))
        if _is_caps(message.content, threshold):
            await self._handle_violation(message, f"Caps ({threshold}%)")
            return True
        return False

    async def _check_emoji(self, message: discord.Message, config: dict) -> bool:
        cfg = config["emoji"]
        if not cfg.get("enabled", True):
            return False
        limit = max(5, int(cfg.get("limit_value") or 20))
        if _emoji_count(message.content) >= limit:
            await self._handle_violation(message, f"Emoji-Spam ({limit}+)")
            return True
        return False

    async def _check_newlines(self, message: discord.Message, config: dict) -> bool:
        cfg = config["newlines"]
        if not cfg.get("enabled", True):
            return False
        limit = max(3, int(cfg.get("limit_value") or 8))
        if message.content.count("\n") >= limit:
            await self._handle_violation(message, f"Newline-Spam ({limit}+)" )
            return True
        return False

    async def _check_badwords(self, message: discord.Message, config: dict) -> bool:
        if not config["badwords"].get("enabled", True):
            return False
        found = find_bad_word(message.content)
        if found:
            await self._delete_message(message)
            await _log_bad_word(message.guild, message.author, message.channel, message.content)
            self._warn_cache[message.guild.id][message.author.id] += 1
            return True
        return False

    # ---------------- raid protection ----------------
    async def _enter_raid_mode(self, guild: discord.Guild, joins: int):
        until = time.monotonic() + 600
        previous = self._raid_until.get(guild.id, 0)
        self._raid_until[guild.id] = max(previous, until)
        try:
            log_ch = find_channel(guild, "admin-log") or find_channel(guild, "bad-word-log")
            if log_ch:
                embed = discord.Embed(
                    title="🚨 Möglicher Raid erkannt",
                    description=(
                        f"**{joins} Beitritte** in kurzer Zeit erkannt.\n"
                        "Raid-Schutz ist für 10 Minuten aktiv. Neue/auffällige Accounts werden strenger geprüft."
                    ),
                    color=discord.Color.red(),
                )
                await log_ch.send(embed=embed)
        except Exception as exc:
            logger.warning(f"Raid-Alarm konnte nicht gesendet werden: {exc}")

    def _raid_active(self, guild_id: int) -> bool:
        until = self._raid_until.get(guild_id, 0)
        if until <= time.monotonic():
            self._raid_until.pop(guild_id, None)
            return False
        return True

    async def _check_raid_message(self, message: discord.Message, config: dict) -> bool:
        if not config["raid"].get("enabled", True) or not self._raid_active(message.guild.id):
            return False
        if not isinstance(message.author, discord.Member) or self._is_exempt(message):
            return False
        age = discord.utils.utcnow() - message.author.created_at
        joined = discord.utils.utcnow() - (message.author.joined_at or message.author.created_at)
        # In raid mode, fresh accounts are blocked more aggressively.
        if age <= timedelta(days=1) or joined <= timedelta(minutes=10):
            await self._handle_violation(message, "Raid-Schutz: neuer Account")
            return True
        return False

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        config = self._get_config(member.guild.id)
        if not config["raid"].get("enabled", True):
            return
        now = time.monotonic()
        q = self._joins[member.guild.id]
        q.append((now, member.id))
        while q and now - q[0][0] > 20:
            q.popleft()
        threshold = max(4, int(config["raid"].get("limit_value") or 8))
        if len(q) >= threshold:
            await self._enter_raid_mode(member.guild, len(q))
        if self._raid_active(member.guild.id):
            age = discord.utils.utcnow() - member.created_at
            if age <= timedelta(hours=24):
                try:
                    await member.timeout(timedelta(minutes=10), reason="AutoMod Raid-Schutz: neuer Account")
                    await self._log_violation(
                        member.guild,
                        member,
                        member.guild.system_channel or member.guild.text_channels[0],
                        "Raid-Schutz: neuer Account automatisch eingeschränkt",
                        f"Account-Alter: {age}",
                    )
                except (discord.Forbidden, discord.HTTPException):
                    pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if self._is_exempt(message):
            return
        config = self._get_config(message.guild.id)
        checks = (
            self._check_raid_message,
            self._check_invites,
            self._check_links,
            self._check_spam,
            self._check_duplicates,
            self._check_mentions,
            self._check_caps,
            self._check_emoji,
            self._check_newlines,
            self._check_badwords,
        )
        for check in checks:
            if await check(message, config):
                return

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if after.author.bot or not after.guild or before.content == after.content:
            return
        if self._is_exempt(after):
            return
        config = self._get_config(after.guild.id)
        for check in (self._check_raid_message, self._check_invites, self._check_links,
                      self._check_mentions, self._check_caps, self._check_emoji,
                      self._check_newlines, self._check_badwords):
            if await check(after, config):
                return

    # ---------------- commands ----------------
    @config_group.command(name="show", description="Zeigt die AutoMod-Konfiguration")
    @app_commands.default_permissions(administrator=True)
    async def config_show(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Keine Berechtigung!", ephemeral=True)
            return
        config = self._get_config(interaction.guild_id)
        lines = []
        for name, cfg in config.items():
            state = "✅" if cfg.get("enabled") else "❌"
            limit = cfg.get("limit_value", 0)
            lines.append(f"{state} **{name}** — Limit `{limit}`")
        allow, block = self._get_domains(interaction.guild_id)
        lines.append(f"🔗 **Whitelist:** `{len(allow)}` Domains")
        lines.append(f"⛔ **Blocklist:** `{len(block)}` Domains")
        lines.append(f"🚨 **Raid-Modus:** {'AKTIV' if self._raid_active(interaction.guild_id) else 'AUS'}")
        embed = discord.Embed(title="🛡️ AutoMod Konfiguration", description="\n".join(lines), color=discord.Color.blue())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @config_group.command(name="toggle", description="Aktiviert/Deaktiviert einen AutoMod-Filter")
    @app_commands.describe(filter_name="Welcher Filter", enabled="Aktivieren oder deaktivieren")
    @app_commands.choices(filter_name=[
        app_commands.Choice(name="🔗 Links", value="links"),
        app_commands.Choice(name="📨 Discord-Invites", value="invites"),
        app_commands.Choice(name="💬 Spam", value="spam"),
        app_commands.Choice(name="📢 Mass-Mentions", value="mentions"),
        app_commands.Choice(name="🔠 Caps", value="caps"),
        app_commands.Choice(name="🚫 Bad Words", value="badwords"),
        app_commands.Choice(name="🔁 Wiederholungen", value="duplicates"),
        app_commands.Choice(name="😀 Emoji-Spam", value="emoji"),
        app_commands.Choice(name="↩️ Newline-Spam", value="newlines"),
        app_commands.Choice(name="🚨 Raid-Schutz", value="raid"),
    ])
    @app_commands.default_permissions(administrator=True)
    async def config_toggle(self, interaction: discord.Interaction, filter_name: app_commands.Choice[str], enabled: bool):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Keine Berechtigung!", ephemeral=True)
            return
        current = self._get_config(interaction.guild_id).get(filter_name.value, {})
        set_automod_config(
            interaction.guild_id,
            filter_name.value,
            enabled=enabled,
            limit_value=int(current.get("limit_value") or 0),
        )
        await interaction.response.send_message(
            f"✅ **{filter_name.name}** {'aktiviert' if enabled else 'deaktiviert'}.", ephemeral=True
        )

    @config_group.command(name="limit", description="Setzt den Grenzwert eines Filters")
    @app_commands.describe(filter_name="Filter", limit="Grenzwert")
    @app_commands.choices(filter_name=[
        app_commands.Choice(name="💬 Spam (Nachrichten/10s)", value="spam"),
        app_commands.Choice(name="📢 Mass-Mentions", value="mentions"),
        app_commands.Choice(name="🔠 Caps (%)", value="caps"),
        app_commands.Choice(name="🔁 Wiederholungen", value="duplicates"),
        app_commands.Choice(name="😀 Emoji-Spam", value="emoji"),
        app_commands.Choice(name="↩️ Newline-Spam", value="newlines"),
        app_commands.Choice(name="🚨 Raid-Beitritte/20s", value="raid"),
    ])
    @app_commands.default_permissions(administrator=True)
    async def config_limit(self, interaction: discord.Interaction, filter_name: app_commands.Choice[str], limit: int):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Keine Berechtigung!", ephemeral=True)
            return
        if filter_name.value == "caps":
            valid = 50 <= limit <= 100
        else:
            valid = 1 <= limit <= 100
        if not valid:
            await interaction.response.send_message("Ungültiger Grenzwert.", ephemeral=True)
            return
        current = self._get_config(interaction.guild_id).get(filter_name.value, {})
        set_automod_config(
            interaction.guild_id,
            filter_name.value,
            enabled=bool(current.get("enabled", True)),
            limit_value=limit,
        )
        await interaction.response.send_message(f"✅ Limit für **{filter_name.name}** = **{limit}**.", ephemeral=True)

    @config_group.command(name="allow-domain", description="Erlaubt eine externe Domain")
    @app_commands.describe(domain="z.B. example.com")
    @app_commands.default_permissions(administrator=True)
    async def allow_domain(self, interaction: discord.Interaction, domain: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Keine Berechtigung!", ephemeral=True)
            return
        domain = _normalize_url_host(domain)
        if not domain or "/" in domain or " " in domain:
            await interaction.response.send_message("❌ Ungültige Domain.", ephemeral=True)
            return
        allow, block = self._get_domains(interaction.guild_id)
        allow.add(domain)
        block.discard(domain)
        self._save_domains(interaction.guild_id, allow, block)
        await interaction.response.send_message(f"✅ `{domain}` zur Link-Whitelist hinzugefügt.", ephemeral=True)

    @config_group.command(name="block-domain", description="Blockiert eine Domain")
    @app_commands.describe(domain="z.B. example.com")
    @app_commands.default_permissions(administrator=True)
    async def block_domain(self, interaction: discord.Interaction, domain: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Keine Berechtigung!", ephemeral=True)
            return
        domain = _normalize_url_host(domain)
        if not domain or "/" in domain or " " in domain:
            await interaction.response.send_message("❌ Ungültige Domain.", ephemeral=True)
            return
        allow, block = self._get_domains(interaction.guild_id)
        block.add(domain)
        self._save_domains(interaction.guild_id, allow, block)
        await interaction.response.send_message(f"✅ `{domain}` zur Link-Blocklist hinzugefügt.", ephemeral=True)

    @config_group.command(name="domains", description="Zeigt Link-Whitelist und Blocklist")
    @app_commands.default_permissions(administrator=True)
    async def domains(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Keine Berechtigung!", ephemeral=True)
            return
        allow, block = self._get_domains(interaction.guild_id)
        embed = discord.Embed(title="🔗 AutoMod Domains", color=discord.Color.blue())
        embed.add_field(name="✅ Erlaubt", value="\n".join(f"`{d}`" for d in sorted(allow))[:1024] or "—", inline=False)
        embed.add_field(name="⛔ Blockiert", value="\n".join(f"`{d}`" for d in sorted(block))[:1024] or "—", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @config_group.command(name="raid-status", description="Zeigt den Raid-Schutzstatus")
    @app_commands.default_permissions(administrator=True)
    async def raid_status(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Keine Berechtigung!", ephemeral=True)
            return
        active = self._raid_active(interaction.guild_id)
        remaining = max(0, int(self._raid_until.get(interaction.guild_id, 0) - time.monotonic())) if active else 0
        recent = len(self._joins.get(interaction.guild_id, ()))
        await interaction.response.send_message(
            f"🚨 Raid-Schutz: **{'AKTIV' if active else 'AUS'}**\n"
            f"Beitritte im aktuellen Fenster: **{recent}**\n"
            f"Restzeit: **{remaining}s**",
            ephemeral=True,
        )

    @config_group.command(name="reset", description="Setzt AutoMod auf Standardwerte zurück")
    @app_commands.default_permissions(administrator=True)
    async def config_reset(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Keine Berechtigung!", ephemeral=True)
            return
        for name, (enabled, limit_value) in DEFAULTS.items():
            set_automod_config(interaction.guild_id, name, enabled=enabled, limit_value=limit_value)
        self._allowlist_cache.pop(interaction.guild_id, None)
        self._blocklist_cache.pop(interaction.guild_id, None)
        await interaction.response.send_message("✅ AutoMod auf Standardwerte zurückgesetzt.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AutomodCog(bot))
