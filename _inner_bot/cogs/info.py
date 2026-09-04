"""Info: /info Command - interaktive Info-Seite mit Dropdown-Auswahl."""
import discord
import platform
from discord import app_commands
from discord.ext import commands


INFO_SECTIONS = {
    'commands': {
        'title': 'Alle Commands',
        'description': (
            'ScratchAI hat **110+ Commands** in diesen Kategorien:\n\n'
            'Moderation: `/ban` `/kick` `/warn` `/timeout` `/purge` `/lock` `/role`\n'
            'Admin: `/status` `/reload` `/test` `/setup-smp` `/backup`\n'
            'KI & AI: `/ask` `/generate` `/analyze` `/refine` `/suggest` `/tip`\n'
            'Musik: `/play` `/skip` `/stop` `/queue` `/nowplaying`\n'
            'Fun: `/roll` `/coinflip` `/meme` `/trivia` `/rps` `/slot`\n'
            'Community: `/level` `/poll` `/remind` `/leaderboard`\n'
            'Tickets: Ticket-System mit Panels\n'
            'Verifizierung: `/verify` `/verified` `/verify-link`\n'
            'Stats: `/stats` `/system` `/growth`\n'
            'Extras: `/schematics` `/giveaway` `/reactionroles` `/starboard`\n\n'
            'Nutze `/help` fuer eine vollstaendige Liste mit Details.'
        ),
        'color': 0x5865F2,
    },
    'about': {
        'title': 'Ueber ScratchAI',
        'description': (
            '**ScratchAI** ist ein KI-gestuetzter Discord-Bot speziell fuer Scratch-Communities.\n\n'
            'Was kann der Bot?\n'
            '- KI-gestuetzte Antworten zu Scratch & Game-Entwicklung\n'
            '- Automatische Spiel-Generierung aus Text-Beschreibungen\n'
            '- SB3-Dateien analysieren und verbessern\n'
            '- Komplette Moderation (Ban, Kick, Warn, Timeout)\n'
            '- Musik-Player mit YouTube-Suche\n'
            '- Level-System mit XP & Leaderboard\n'
            '- Ticket-Support-System\n'
            '- Auto-Moderation & Anti-Spam\n'
            '- Reaction Roles & Starboard\n'
            '- Web-Dashboard mit Live-Statistiken\n\n'
            'Web-App: scratch-ai-24bv.onrender.com\n'
            'GitHub: github.com/jnun-glitch/scratch-ai'
        ),
        'color': 0x57F287,
    },
    'warnsystem': {
        'title': 'Warn-System',
        'description': (
            'Das Warn-System ist **automatisch** und konfigurierbar:\n\n'
            '**Standard-Schwellen:**\n'
            '- **3 Warns** -> Automatischer Timeout (60 Min.)\n'
            '- **5 Warns** -> Automatischer Kick\n\n'
            '**Wie es funktioniert:**\n'
            '1. Admin gibt `/warn @user Grund`\n'
            '2. Bei **3 Warns**: User wird automatisch fuer 60 Min. gemutet\n'
            '3. Bei **5 Warns**: User wird automatisch gekickt\n\n'
            '**Commands:**\n'
            '- `/warn @user Grund` - Verwarnt einen User\n'
            '- `/warnings @user` - Zeigt alle Verwarnungen\n'
            '- `/warn-clear @user` - Loescht alle Verwarnungen\n\n'
            '**Admins sind geschuetzt** - Admins bekommen kein Auto-Timeout/Kick.\n'
            '**Whitelist** - User in `mute_immune.txt` sind ebenfalls geschuetzt.\n\n'
            '**Anpassbar** ueber `/config-set`:\n'
            '- `warn_timeout_at` - Ab wie vielen Warns Timeout (Standard: 3)\n'
            '- `warn_kick_at` - Ab wie vielen Warns Kick (Standard: 5)\n'
            '- `warn_timeout_minutes` - Dauer des Auto-Timeouts (Standard: 60 Min.)'
        ),
        'color': 0xFEE75C,
    },
    'features': {
        'title': 'Features',
        'description': (
            '**KI-Systeme:**\n'
            '- Ollama-basierte KI fuer Scratch-Fragen\n'
            '- KI Spiel-Generierung (generiert echte .sb3 Dateien!)\n'
            '- Auto-Training mit Nutzer-Feedback\n'
            '- YouTube-Transkript-Analyse fuer Lerninhalte\n\n'
            '**Moderation:**\n'
            '- Auto-Moderation (Links, Spam, Schimpfwoerter)\n'
            '- Audit-Log fuer alle Admin-Aktionen\n'
            '- Slowmode, Lock/Unlock Channels\n'
            '- Rollen-Verwaltung (erstellen, loeschen, Farben)\n\n'
            '**Musik:**\n'
            '- YouTube-Suche & Abspielen\n'
            '- Warteschlange (Queue)\n'
            '- Skip, Stop, Now-Playing\n\n'
            '**Fun & Community:**\n'
            '- Level-System mit XP & Leaderboard\n'
            '- Giveaways, Reaction Roles, Starboard\n'
            '- Geburtstage, AFK-System, Zaehlspiel\n'
            '- Minecraft Server Status\n\n'
            '**Support:**\n'
            '- Ticket-System mit Panels\n'
            '- Verifizierung mit Website-Link\n'
            '- Rules-Gate (Regeln akzeptieren)'
        ),
        'color': 0xEB459E,
    },
    'system': {
        'title': 'System-Info',
        'description': (
            '**Laufzeit:** {uptime}\n'
            '**Python:** {python_version}\n'
            '**Discord.py:** {discordpy}\n'
            '**Plattform:** {platform_name}\n'
            '**Guilds:** {guilds}\n'
            '**User:** {users}\n'
            '**Cogs geladen:** {cogs}\n'
            '**Commands registriert:** 110+'
        ),
        'color': 0x00ACEE,
    },
    'links': {
        'title': 'Links & Ressourcen',
        'description': (
            '**Web-App:** https://scratch-ai-24bv.onrender.com\n'
            '**GitHub:** https://github.com/jnun-glitch/scratch-ai\n'
            '**Docs:** README.md im Repository\n\n'
            '**Hilfe bekommen:**\n'
            '- Nutze `/help` fuer Command-Details\n'
            '- Nutze `/support` fuer ein Support-Ticket\n'
            '- Nutze `/suggestion` fuer Feature-Requests\n\n'
            '**Community beitreten:**\n'
            '- Scratch-Projekte teilen in der Bibliothek\n'
            '- Level aufsteigen und auf dem Leaderboard erscheinen\n'
            '- Schematics mit anderen teilen'
        ),
        'color': 0x57F287,
    },
}


class InfoSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label='Commands', value='commands', emoji='📋', description='Alle Bot-Commands anzeigen'),
            discord.SelectOption(label='Ueber ScratchAI', value='about', emoji='ℹ️', description='Was kann der Bot?'),
            discord.SelectOption(label='Warn-System', value='warnsystem', emoji='⚠️', description='Wie Warns funktionieren'),
            discord.SelectOption(label='Features', value='features', emoji='✨', description='Alle Features im Ueberblick'),
            discord.SelectOption(label='System', value='system', emoji='💻', description='Bot-Status & Technik'),
            discord.SelectOption(label='Links', value='links', emoji='🔗', description='GitHub, Web-App & mehr'),
        ]
        super().__init__(placeholder='Waehle ein Thema...', min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        key = self.values[0]
        embed = _build_info_embed(key, interaction.client)
        await interaction.response.edit_message(embed=embed, view=InfoView())


def _build_info_embed(key, bot=None):
    section = INFO_SECTIONS[key]
    desc = section['description']

    if key == 'system' and bot:
        import datetime
        uptime_delta = datetime.datetime.utcnow() - getattr(bot, 'uptime', datetime.datetime.utcnow())
        hours, remainder = divmod(int(uptime_delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        desc = desc.format(
            uptime=f'{hours}h {minutes}m {seconds}s',
            python_version=platform.python_version(),
            discordpy=discord.__version__,
            platform_name=platform.system(),
            guilds=len(bot.guilds),
            users=sum(g.member_count or 0 for g in bot.guilds),
            cogs=len(bot.cogs),
        )

    embed = discord.Embed(title=section['title'], description=desc, color=section['color'])
    embed.set_footer(text='ScratchAI /info')
    return embed


class InfoView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(InfoSelect())

    @discord.ui.button(label='Haupatmenue', style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = _build_main_embed()
        await interaction.response.edit_message(embed=embed, view=InfoView())

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


def _build_main_embed():
    embed = discord.Embed(
        title='ScratchAI Info',
        description=(
            'Willkommen bei **ScratchAI** - dein KI-gestuetzter Discord-Bot fuer Scratch-Communities!\n\n'
            'Waehle ein Thema aus dem Dropdown-Menue unten fuer weitere Informationen.'
        ),
        color=discord.Color.blurple(),
    )
    for key, section in INFO_SECTIONS.items():
        embed.add_field(name=section['title'], value=f'`/info` -> {key}', inline=True)
    embed.set_footer(text='ScratchAI /info')
    return embed


class InfoCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name='info', description='Interaktive Informationen ueber ScratchAI')
    @app_commands.describe(section='Direkt zu einem Bereich springen')
    @app_commands.choices(section=[
        app_commands.Choice(name='Commands', value='commands'),
        app_commands.Choice(name='Ueber ScratchAI', value='about'),
        app_commands.Choice(name='Warn-System', value='warnsystem'),
        app_commands.Choice(name='Features', value='features'),
        app_commands.Choice(name='System', value='system'),
        app_commands.Choice(name='Links', value='links'),
    ])
    async def cmd_info(self, interaction: discord.Interaction, section: str = None):
        if section and section in INFO_SECTIONS:
            embed = _build_info_embed(section, self.bot)
        else:
            embed = _build_main_embed()
        await interaction.response.send_message(embed=embed, view=InfoView(), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(InfoCog(bot))
