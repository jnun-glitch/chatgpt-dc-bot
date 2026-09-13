"""Advanced AutoMod with link, spam and raid protection."""
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

from core.automod_strikes import record_strike, reset_strikes, get_strike_state
from core.badwords import find_bad_word, _log_bad_word
from core.channelnames import find_channel
from core.db import get_db, get_automod_config, set_automod_config
from core.logging import logger

DEFAULTS = {
    "links": (True, 0), "invites": (True, 0), "spam": (True, 5), "mentions": (True, 5),
    "caps": (True, 80), "badwords": (True, 0), "duplicates": (True, 3), "emoji": (True, 20),
    "newlines": (True, 8), "raid": (True, 8),
}
DEFAULT_ALLOWED_DOMAINS = {
    "discord.com", "discord.gg", "discordapp.com", "github.com", "github.io", "youtube.com",
    "youtu.be", "twitch.tv", "reddit.com", "x.com", "twitter.com", "google.com", "google.de",
    "microsoft.com", "minecraft.net",
}
SUSPICIOUS_TLDS = {"zip", "mov", "click", "download", "country", "gq", "tk", "ml", "cf", "work"}
URL_RE = re.compile(r"(?i)(?:https?://|www\.)[^\s<>\]\[(){}]+")
MARKDOWN_URL_RE = re.compile(r"(?i)\]\((https?://[^)\s]+)\)")
DISCORD_INVITE_RE = re.compile(r"(?i)(?:https?://)?(?:www\.)?(?:discord\.gg|discord(?:app)?\.com/invite)/[A-Za-z0-9-]+")


def _normalize_url_host(host: str) -> str:
    host = host.strip().lower().rstrip(".")
    try: host = host.encode("idna").decode("ascii")
    except Exception: pass
    return host[4:] if host.startswith("www.") else host


def _extract_urls(content: str) -> list[str]:
    return list(dict.fromkeys(URL_RE.findall(content) + MARKDOWN_URL_RE.findall(content)))


def _url_host(url: str) -> str | None:
    raw = url if re.match(r"(?i)^https?://", url) else f"https://{url}"
    try: return _normalize_url_host(urlparse(raw).hostname or "") or None
    except Exception: return None


def _is_suspicious_url(url: str) -> bool:
    raw = url if re.match(r"(?i)^https?://", url) else f"https://{url}"
    try:
        parsed = urlparse(unquote(raw)); host = _normalize_url_host(parsed.hostname or "")
        if not host or host.startswith("xn--") or ".xn--" in host: return True
        if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", host): return True
        if parsed.username or parsed.password: return True
        if any(host.endswith("." + tld) for tld in SUSPICIOUS_TLDS): return True
        return len(host) > 80 or host.count(".") >= 6
    except Exception: return True


def _is_caps(content: str, threshold: int = 80) -> bool:
    letters = [c for c in content if c.isalpha()]
    return len(letters) >= 10 and sum(c.isupper() for c in letters) / len(letters) * 100 >= threshold


def _emoji_count(content: str) -> int:
    return sum(1 for c in content if any(start <= ord(c) <= end for start, end in ((0x1F300,0x1FAFF),(0x2600,0x27BF),(0x2300,0x23FF))))


def _clean_duplicate_text(content: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", content).casefold()).strip()[:500]


class AutomodCog(commands.Cog):
    automod_group = app_commands.Group(name="automod", description="Auto-Moderation Einstellungen")
    config_group = app_commands.Group(name="config", description="AutoMod Filter konfigurieren", parent=automod_group)

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._spam_cache = defaultdict(lambda: defaultdict(deque))
        self._message_cache = defaultdict(lambda: defaultdict(deque))
        self._joins = defaultdict(deque)
        self._raid_until: dict[int, float] = {}
        self._allowlist_cache: dict[int, set[str]] = {}
        self._blocklist_cache: dict[int, set[str]] = {}

    def _get_config(self, guild_id: int) -> dict:
        db_config = get_automod_config(guild_id)
        return {name: db_config.get(name, {"enabled": enabled, "limit_value": limit}) for name, (enabled, limit) in DEFAULTS.items()}

    def _get_domains(self, guild_id: int) -> tuple[set[str], set[str]]:
        if guild_id in self._allowlist_cache: return self._allowlist_cache[guild_id], self._blocklist_cache[guild_id]
        allow, block = set(DEFAULT_ALLOWED_DOMAINS), set()
        try:
            conn = get_db(); cur = conn.cursor()
            for key, target in (("automod_allowed_domains", allow), ("automod_blocked_domains", block)):
                row = cur.execute("SELECT value FROM guild_settings WHERE guild_id=? AND key=?", (str(guild_id), key)).fetchone()
                if row and row[0]: target.update(_normalize_url_host(x) for x in str(row[0]).split(",") if x.strip())
            conn.close()
        except Exception as exc: logger.warning("AutoMod Domain-Konfiguration konnte nicht geladen werden: %s", exc)
        self._allowlist_cache[guild_id], self._blocklist_cache[guild_id] = {x for x in allow if x}, {x for x in block if x}
        return self._allowlist_cache[guild_id], self._blocklist_cache[guild_id]

    def _save_domains(self, guild_id: int, allowed: set[str], blocked: set[str]) -> None:
        conn = get_db(); cur = conn.cursor()
        for key, values in (("automod_allowed_domains", sorted(allowed)), ("automod_blocked_domains", sorted(blocked))):
            cur.execute("INSERT INTO guild_settings (guild_id,key,value) VALUES (?,?,?) ON CONFLICT(guild_id,key) DO UPDATE SET value=excluded.value", (str(guild_id), key, ",".join(values)))
        conn.commit(); conn.close(); self._allowlist_cache[guild_id], self._blocklist_cache[guild_id] = set(allowed), set(blocked)

    def _is_exempt(self, message: discord.Message) -> bool:
        if not message.guild or not isinstance(message.author, discord.Member): return False
        perms = message.author.guild_permissions
        if perms.administrator or perms.manage_guild or perms.manage_messages: return True
        return bool({r.name.casefold() for r in message.author.roles} & {"admin", "moderator", "support"})

    def _channel_exempt(self, message: discord.Message) -> bool:
        return any(token in getattr(message.channel, "name", "").casefold() for token in ("bot-commands", "mod-log", "admin-log"))

    async def _log_violation(self, guild, user, channel, reason: str, content: str, *, count: int | None = None):
        try:
            log_ch = find_channel(guild, "bad-word-log") or find_channel(guild, "admin-log")
            if not log_ch: return
            embed = discord.Embed(title=f"🛡️ AutoMod: {reason}", description=discord.utils.escape_markdown(content[:1800]), color=discord.Color.red(), timestamp=discord.utils.utcnow())
            embed.set_author(name=f"{user} ({user.id})", icon_url=user.display_avatar.url)
            embed.add_field(name="Kanal", value=getattr(channel, "mention", str(channel)), inline=True)
            if count is not None: embed.add_field(name="Verstöße", value=str(count), inline=True)
            await log_ch.send(embed=embed)
        except Exception as exc: logger.warning("AutoMod-Log fehlgeschlagen: %s", exc)

    async def _delete_message(self, message: discord.Message) -> None:
        try: await message.delete()
        except (discord.Forbidden, discord.NotFound, discord.HTTPException): pass

    async def _handle_violation(self, message: discord.Message, reason: str, *, escalate: bool = True):
        guild, user = message.guild, message.author
        if not guild or not isinstance(user, discord.Member): return
        await self._delete_message(message)
        count = record_strike(guild.id, user.id, reason)["strikes"]
        await self._log_violation(guild, user, message.channel, reason, message.content, count=count)
        if not escalate or count < 3 or user.guild_permissions.administrator: return
        state = get_strike_state(guild.id, user.id)
        try:
            from core.muteimmune import is_mute_immune
            if is_mute_immune(user.id): return
        except Exception: pass
        level = int(state["timeout_level"]); minutes = min(10 ** level if level else 1, 40320)
        try:
            await user.timeout(timedelta(minutes=minutes), reason=f"AutoMod: {reason}")
            save_level = level + 1
            reset_strikes(guild.id, user.id)
            from core.automod_strikes import save_strike_state
            save_strike_state(guild.id, user.id, 0, save_level, reason)
            await self._log_violation(guild, user, message.channel, f"Timeout Stufe {save_level} ({minutes} Min.)", message.content)
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.warning("AutoMod Timeout fehlgeschlagen: %s", exc)

    async def _check_links(self, message, config):
        cfg=config["links"]
        if not cfg.get("enabled", True) or self._channel_exempt(message): return False
        for url in _extract_urls(message.content):
            host=_url_host(url)
            if not host: await self._handle_violation(message,"Ungültiger Link"); return True
            allow, block=self._get_domains(message.guild.id)
            if host in block or _is_suspicious_url(url) or not any(host == d or host.endswith("."+d) for d in allow):
                await self._handle_violation(message,f"Externer/verdächtiger Link ({host})"); return True
        return False

    async def _check_invites(self,message,config):
        if config["invites"].get("enabled",True) and DISCORD_INVITE_RE.search(message.content): await self._handle_violation(message,"Discord-Invite-Link"); return True
        return False

    async def _check_spam(self,message,config):
        if not config["spam"].get("enabled",True): return False
        limit=max(2,int(config["spam"].get("limit_value") or 5)); now=time.monotonic(); q=self._spam_cache[message.guild.id][message.author.id]; q.append(now)
        while q and now-q[0]>10: q.popleft()
        if len(q)>limit: q.clear(); await self._handle_violation(message,f"Spam ({limit}+ Nachrichten/10s)"); return True
        return False

    async def _check_duplicates(self,message,config):
        if not config["duplicates"].get("enabled",True) or not message.content.strip(): return False
        threshold=max(2,int(config["duplicates"].get("limit_value") or 3)); now=time.monotonic(); q=self._message_cache[message.guild.id][message.author.id]; normalized=_clean_duplicate_text(message.content); q.append((now,normalized))
        while q and now-q[0][0]>20:q.popleft()
        repeats=sum(1 for _,text in q if text==normalized)
        if repeats>=threshold:q.clear(); await self._handle_violation(message,f"Wiederholungs-Spam ({repeats}x)"); return True
        return False

    async def _check_mentions(self,message,config):
        if not config["mentions"].get("enabled",True): return False
        count=len(message.mentions)+len(message.role_mentions)+(1 if message.mention_everyone else 0); limit=max(2,int(config["mentions"].get("limit_value") or 5))
        if count>=limit: await self._handle_violation(message,f"Mass-Mentions ({count})"); return True
        return False

    async def _check_caps(self,message,config):
        if not config["caps"].get("enabled",True): return False
        threshold=min(100,max(50,int(config["caps"].get("limit_value") or 80)))
        if _is_caps(message.content,threshold): await self._handle_violation(message,f"Caps ({threshold}%)"); return True
        return False

    async def _check_emoji(self,message,config):
        if not config["emoji"].get("enabled",True): return False
        limit=max(5,int(config["emoji"].get("limit_value") or 20))
        if _emoji_count(message.content)>=limit: await self._handle_violation(message,f"Emoji-Spam ({limit}+)"); return True
        return False

    async def _check_newlines(self,message,config):
        if not config["newlines"].get("enabled",True): return False
        limit=max(3,int(config["newlines"].get("limit_value") or 8))
        if message.content.count("\n")>=limit: await self._handle_violation(message,f"Newline-Spam ({limit}+)"); return True
        return False

    async def _check_badwords(self,message,config):
        if not config["badwords"].get("enabled",True): return False
        found=find_bad_word(message.content)
        if found:
            await self._delete_message(message); await _log_bad_word(message.guild,message.author,message.channel,message.content)
            record_strike(message.guild.id,message.author.id,f"Bad word: {found}"); return True
        return False

    async def _enter_raid_mode(self,guild,joins):
        self._raid_until[guild.id]=max(self._raid_until.get(guild.id,0),time.monotonic()+600)
        try:
            log_ch=find_channel(guild,"admin-log") or find_channel(guild,"bad-word-log")
            if log_ch: await log_ch.send(embed=discord.Embed(title="🚨 Möglicher Raid erkannt",description=f"**{joins} Beitritte** in kurzer Zeit erkannt. Raid-Schutz ist für 10 Minuten aktiv.",color=discord.Color.red()))
        except Exception as exc: logger.warning("Raid-Alarm konnte nicht gesendet werden: %s",exc)

    def _raid_active(self,guild_id):
        until=self._raid_until.get(guild_id,0)
        if until<=time.monotonic(): self._raid_until.pop(guild_id,None); return False
        return True

    async def _check_raid_message(self,message,config):
        if not config["raid"].get("enabled",True) or not self._raid_active(message.guild.id): return False
        if not isinstance(message.author,discord.Member) or self._is_exempt(message): return False
        if discord.utils.utcnow()-message.author.created_at<=timedelta(days=1) or discord.utils.utcnow()-(message.author.joined_at or message.author.created_at)<=timedelta(minutes=10):
            await self._handle_violation(message,"Raid-Schutz: neuer Account"); return True
        return False

    @commands.Cog.listener()
    async def on_member_join(self,member):
        config=self._get_config(member.guild.id)
        if not config["raid"].get("enabled",True): return
        now=time.monotonic(); q=self._joins[member.guild.id]; q.append((now,member.id))
        while q and now-q[0][0]>20:q.popleft()
        threshold=max(4,int(config["raid"].get("limit_value") or 8))
        if len(q)>=threshold: await self._enter_raid_mode(member.guild,len(q))
        if self._raid_active(member.guild.id) and discord.utils.utcnow()-member.created_at<=timedelta(hours=24):
            try: await member.timeout(timedelta(minutes=10),reason="AutoMod Raid-Schutz: neuer Account")
            except (discord.Forbidden,discord.HTTPException): pass

    @commands.Cog.listener()
    async def on_message(self,message):
        if message.author.bot or not message.guild or self._is_exempt(message): return
        config=self._get_config(message.guild.id)
        for check in (self._check_raid_message,self._check_invites,self._check_links,self._check_spam,self._check_duplicates,self._check_mentions,self._check_caps,self._check_emoji,self._check_newlines,self._check_badwords):
            if await check(message,config): return

    @commands.Cog.listener()
    async def on_message_edit(self,before,after):
        if after.author.bot or not after.guild or before.content==after.content or self._is_exempt(after): return
        config=self._get_config(after.guild.id)
        for check in (self._check_raid_message,self._check_invites,self._check_links,self._check_mentions,self._check_caps,self._check_emoji,self._check_newlines,self._check_badwords):
            if await check(after,config): return

    @config_group.command(name="show",description="Zeigt die AutoMod-Konfiguration")
    @app_commands.default_permissions(administrator=True)
    async def config_show(self,interaction):
        if not interaction.user.guild_permissions.administrator: await interaction.response.send_message("Keine Berechtigung!",ephemeral=True); return
        config=self._get_config(interaction.guild_id); lines=[f"{'✅' if c.get('enabled') else '❌'} **{n}** — Limit `{c.get('limit_value',0)}`" for n,c in config.items()]; allow,block=self._get_domains(interaction.guild_id)
        lines += [f"🔗 **Whitelist:** `{len(allow)}` Domains",f"⛔ **Blocklist:** `{len(block)}` Domains",f"🚨 **Raid-Modus:** {'AKTIV' if self._raid_active(interaction.guild_id) else 'AUS'}"]
        await interaction.response.send_message(embed=discord.Embed(title="🛡️ AutoMod Konfiguration",description="\n".join(lines),color=discord.Color.blue()),ephemeral=True)

    @config_group.command(name="toggle",description="Aktiviert/Deaktiviert einen AutoMod-Filter")
    @app_commands.describe(filter_name="Welcher Filter",enabled="Aktivieren oder deaktivieren")
    @app_commands.choices(filter_name=[app_commands.Choice(name=n,value=v) for n,v in [("🔗 Links","links"),("📨 Discord-Invites","invites"),("💬 Spam","spam"),("📢 Mass-Mentions","mentions"),("🔠 Caps","caps"),("🚫 Bad Words","badwords"),("🔁 Wiederholungen","duplicates"),("😀 Emoji-Spam","emoji"),("↩️ Newline-Spam","newlines"),("🚨 Raid-Schutz","raid")]])
    @app_commands.default_permissions(administrator=True)
    async def config_toggle(self,interaction,filter_name,enabled):
        if not interaction.user.guild_permissions.administrator: await interaction.response.send_message("Keine Berechtigung!",ephemeral=True); return
        current=self._get_config(interaction.guild_id).get(filter_name.value,{}); set_automod_config(interaction.guild_id,filter_name.value,enabled=enabled,limit_value=int(current.get("limit_value") or 0)); await interaction.response.send_message(f"✅ **{filter_name.name}** {'aktiviert' if enabled else 'deaktiviert'}.",ephemeral=True)

    @config_group.command(name="limit",description="Setzt den Grenzwert eines Filters")
    @app_commands.describe(filter_name="Filter",limit="Grenzwert")
    @app_commands.choices(filter_name=[app_commands.Choice(name=n,value=v) for n,v in [("💬 Spam (Nachrichten/10s)","spam"),("📢 Mass-Mentions","mentions"),("🔠 Caps (%)","caps"),("🔁 Wiederholungen","duplicates"),("😀 Emoji-Spam","emoji"),("↩️ Newline-Spam","newlines"),("🚨 Raid-Beitritte/20s","raid")]])
    @app_commands.default_permissions(administrator=True)
    async def config_limit(self,interaction,filter_name,limit):
        if not interaction.user.guild_permissions.administrator: await interaction.response.send_message("Keine Berechtigung!",ephemeral=True); return
        valid=50<=limit<=100 if filter_name.value=="caps" else 1<=limit<=100
        if not valid: await interaction.response.send_message("Ungültiger Grenzwert.",ephemeral=True); return
        current=self._get_config(interaction.guild_id).get(filter_name.value,{}); set_automod_config(interaction.guild_id,filter_name.value,enabled=bool(current.get("enabled",True)),limit_value=limit); await interaction.response.send_message(f"✅ Limit für **{filter_name.name}** = **{limit}**.",ephemeral=True)

    @config_group.command(name="allow-domain",description="Erlaubt eine externe Domain")
    @app_commands.default_permissions(administrator=True)
    async def allow_domain(self,interaction,domain:str):
        if not interaction.user.guild_permissions.administrator: await interaction.response.send_message("Keine Berechtigung!",ephemeral=True); return
        domain=_normalize_url_host(domain)
        if not domain or "/" in domain or " " in domain: await interaction.response.send_message("❌ Ungültige Domain.",ephemeral=True); return
        allow,block=self._get_domains(interaction.guild_id); allow.add(domain); block.discard(domain); self._save_domains(interaction.guild_id,allow,block); await interaction.response.send_message(f"✅ `{domain}` zur Link-Whitelist hinzugefügt.",ephemeral=True)

    @config_group.command(name="block-domain",description="Blockiert eine Domain")
    @app_commands.default_permissions(administrator=True)
    async def block_domain(self,interaction,domain:str):
        if not interaction.user.guild_permissions.administrator: await interaction.response.send_message("Keine Berechtigung!",ephemeral=True); return
        domain=_normalize_url_host(domain)
        if not domain or "/" in domain or " " in domain: await interaction.response.send_message("❌ Ungültige Domain.",ephemeral=True); return
        allow,block=self._get_domains(interaction.guild_id); block.add(domain); self._save_domains(interaction.guild_id,allow,block); await interaction.response.send_message(f"✅ `{domain}` zur Link-Blocklist hinzugefügt.",ephemeral=True)

    @config_group.command(name="domains",description="Zeigt Link-Whitelist und Blocklist")
    @app_commands.default_permissions(administrator=True)
    async def domains(self,interaction):
        if not interaction.user.guild_permissions.administrator: await interaction.response.send_message("Keine Berechtigung!",ephemeral=True); return
        allow,block=self._get_domains(interaction.guild_id); embed=discord.Embed(title="🔗 AutoMod Domains",color=discord.Color.blue()); embed.add_field(name="✅ Erlaubt",value="\n".join(f"`{d}`" for d in sorted(allow))[:1024] or "—",inline=False); embed.add_field(name="⛔ Blockiert",value="\n".join(f"`{d}`" for d in sorted(block))[:1024] or "—",inline=False); await interaction.response.send_message(embed=embed,ephemeral=True)

    @config_group.command(name="raid-status",description="Zeigt den Raid-Schutzstatus")
    @app_commands.default_permissions(administrator=True)
    async def raid_status(self,interaction):
        if not interaction.user.guild_permissions.administrator: await interaction.response.send_message("Keine Berechtigung!",ephemeral=True); return
        active=self._raid_active(interaction.guild_id); remaining=max(0,int(self._raid_until.get(interaction.guild_id,0)-time.monotonic())) if active else 0; recent=len(self._joins.get(interaction.guild_id,()))
        await interaction.response.send_message(f"🚨 Raid-Schutz: **{'AKTIV' if active else 'AUS'}**\nBeitritte im aktuellen Fenster: **{recent}**\nRestzeit: **{remaining}s**",ephemeral=True)

    @config_group.command(name="reset",description="Setzt AutoMod auf Standardwerte zurück")
    @app_commands.default_permissions(administrator=True)
    async def config_reset(self,interaction):
        if not interaction.user.guild_permissions.administrator: await interaction.response.send_message("Keine Berechtigung!",ephemeral=True); return
        for name,(enabled,limit) in DEFAULTS.items(): set_automod_config(interaction.guild_id,name,enabled=enabled,limit_value=limit)
        self._allowlist_cache.pop(interaction.guild_id,None); self._blocklist_cache.pop(interaction.guild_id,None); await interaction.response.send_message("✅ AutoMod auf Standardwerte zurückgesetzt.",ephemeral=True)


async def setup(bot):
    await bot.add_cog(AutomodCog(bot))