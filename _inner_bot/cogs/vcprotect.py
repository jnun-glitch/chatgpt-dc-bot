"""VC-Schutz: Verhindert Kicken aus VC + Auto-Mute-Blockierung via mute_immune.txt."""
import discord
from discord.ext import commands
from core.muteimmune import IMMUNE_USERS, is_mute_immune, add_immune, remove_immune, _load_immune


class VCProtect(commands.Cog):
    """Voice Channel Schutz - Kicks verhindern + Auto-Mute blockieren."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._protected_channels = set()

    def _load_protected(self, guild_id: str):
        from core.db import get_guild_config
        cfg = get_guild_config(int(guild_id))
        raw = cfg.get('vc_protected_channels')
        self._protected_channels = set(int(c) for c in raw.split(',') if c.strip()) if raw else set()

    def _save_protected(self, guild_id: str):
        from core.db import set_guild_config
        set_guild_config(int(guild_id), 'vc_protected_channels', ','.join(str(c) for c in self._protected_channels))

    @commands.command(name='vc-schutz', help='Aktiviere/Deaktiviere VC-Schutz: !vc-schutz #voice-channel')
    @commands.has_permissions(administrator=True)
    async def cmd_vc_protect(self, ctx: commands.Context, channel: discord.VoiceChannel = None):
        if not channel:
            return await ctx.send('Nutze: `!vc-schutz #voice-channel`')

        self._load_protected(str(ctx.guild.id))

        if channel.id in self._protected_channels:
            self._protected_channels.discard(channel.id)
            self._save_protected(str(ctx.guild.id))
            await ctx.send(f'🔓 **{channel.name}** ist nicht mehr geschützt.')
        else:
            self._protected_channels.add(channel.id)
            self._save_protected(str(ctx.guild.id))
            await ctx.send(f'🔒 **{channel.name}** ist jetzt geschützt.')

    @commands.command(name='vc-schutz-list', help='Zeigt geschützte Voice Channels')
    async def cmd_vc_protect_list(self, ctx: commands.Context):
        self._load_protected(str(ctx.guild.id))

        if not self._protected_channels:
            return await ctx.send('Keine geschützten Channels.')

        lines = []
        for ch_id in self._protected_channels:
            ch = ctx.guild.get_channel(ch_id)
            lines.append(f'🔒 {ch.name if ch else f"Unbekannt ({ch_id})"}')

        embed = discord.Embed(title='🔒 Geschützte Voice Channels', description='\n'.join(lines),
                              color=discord.Color.blue())
        await ctx.send(embed=embed)

    @commands.command(name='mute-immune', help='Füge User zur Auto-Mute-Whitelist hinzu: !mute-immune @user')
    @commands.has_permissions(administrator=True)
    async def cmd_mute_immune(self, ctx: commands.Context, user: discord.Member = None):
        if not user:
            return await ctx.send('Nutze: `!mute-immune @user`')

        add_immune(user.id)

        embed = discord.Embed(
            title='🛡️ Auto-Mute-Schutz aktiviert',
            description=f'{user.mention} (`{user.id}`) kann jetzt nicht mehr durch Auto-Mute gemutet werden.\n'
                       f'Gespeichert in `mute_immune.txt`.',
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)

    @commands.command(name='mute-unimmune', help='Entferne User von der Auto-Mute-Whitelist: !mute-unimmune @user')
    @commands.has_permissions(administrator=True)
    async def cmd_mute_unimmune(self, ctx: commands.Context, user: discord.Member = None):
        if not user:
            return await ctx.send('Nutze: `!mute-unimmune @user`')

        remove_immune(user.id)
        await ctx.send(f'✅ {user.mention} ist nicht mehr vor Auto-Mute geschützt. (aus `mute_immune.txt` entfernt)')

    @commands.command(name='mute-whitelist', help='Zeigt alle geschützten Users')
    async def cmd_mute_whitelist(self, ctx: commands.Context):
        if not IMMUNE_USERS:
            return await ctx.send('Keine Users auf der Auto-Mute-Whitelist.')

        lines = []
        for uid in IMMUNE_USERS:
            member = ctx.guild.get_member(uid)
            name = member.display_name if member else f'User {uid}'
            lines.append(f'🛡️ **{name}** (`{uid}`)')

        embed = discord.Embed(title='🛡️ Auto-Mute-Whitelist', description='\n'.join(lines),
                              color=discord.Color.green())
        embed.set_footer(text=f'{len(IMMUNE_USERS)} Users geschützt | Datei: mute_immune.txt')
        await ctx.send(embed=embed)

    @commands.command(name='mute-reload', help='Lädt mute_immune.txt neu')
    @commands.has_permissions(administrator=True)
    async def cmd_mute_reload(self, ctx: commands.Context):
        new_ids = _load_immune()
        IMMUNE_USERS.clear()
        IMMUNE_USERS.update(new_ids)
        await ctx.send(f'✅ `mute_immune.txt` neu geladen. **{len(IMMUNE_USERS)}** Users auf der Whitelist.')

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if not before.channel:
            return

        if before.channel.id in self._protected_channels:
            if after.channel is None or after.channel.id != before.channel.id:
                try:
                    await member.move_to(before.channel, reason='VC-Schutz: Channel ist geschützt')
                except Exception:
                    pass


async def setup(bot: commands.Bot):
    await bot.add_cog(VCProtect(bot))
