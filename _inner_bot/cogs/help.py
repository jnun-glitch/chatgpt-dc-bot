"""Help: Interaktive Hilfe mit Suchfunktion für alle Bot-Commands."""
import discord
from discord import app_commands
from discord.ext import commands

HELP_CATEGORIES = {
    'moderation': (
        '\U0001f6e1\ufe0f Moderation',
        [
            ('ban', 'Bannt einen User vom Server'),
            ('unban', 'Entbannt einen User'),
            ('kick', 'Kickt einen User vom Server'),
            ('timeout', 'Setzt einen User Timeout'),
            ('untimeout', 'Entfernt den Timeout eines Users'),
            ('warn', 'Gibt einer Verwarnung'),
            ('purge', 'Löscht Nachrichten im Kanal'),
            ('purge-user', 'Löscht Nachrichten eines bestimmten Users'),
            ('lock', 'Sperren eines Kanals'),
            ('unlock', 'Entsperren eines Kanals'),
            ('role', 'Rollenverwaltung'),
        ],
    ),
    'admin': (
        '\u2699\ufe0f Admin',
        [
            ('status', 'Zeige Bot-Status und Statistiken'),
            ('reload', 'Lädt eine Erweiterung neu'),
            ('test', 'Testet eine Bot-Funktion'),
            ('setup-smp', 'Richtet den SMP-Modus ein'),
            ('setup-roles', 'Erstellt Standard-Rollen'),
            ('updates', 'Zeigt aktuelle Updates'),
            ('dashboard', 'Öffnet das Bot-Dashboard'),
            ('xp-reset', 'Setzt die XP eines Users zurück'),
        ],
    ),
    'community': (
        '\U0001f465 Community',
        [
            ('ticket', 'Erstellt ein Support-Ticket'),
            ('suggestion', 'Schlage eine Änderung vor'),
            ('schematics', 'Verwalte Schematics'),
            ('level', 'Zeige dein aktuelles Level'),
            ('rank', 'Zeige dein Rang-Card'),
            ('leaderboard', 'Zeige die Top-Spieler'),
        ],
    ),
    'fun': (
        '\U0001f3ae Fun',
        [
            ('roll', 'Würfle mit einem Würfel'),
            ('coinflip', 'Wirf eine Münze'),
            ('meme', 'Zeige ein zufälliges Meme'),
            ('trivia', 'Starte eine Quiz-Runde'),
            ('8ball', 'Stelle eine Ja/Nein-Frage'),
            ('joke', 'Erzähle einen Witz'),
            ('rps', 'Spiele Stein-Schere-Papier'),
            ('slot', 'Ziehe am Slot-Automaten'),
            ('guess', 'Rat eine Zahl'),
        ],
    ),
    'support': (
        '\U0001f6df Support',
        [
            ('ticket', 'Erstelle ein Support-Ticket'),
            ('suggestion', 'Schlage eine Änderung vor'),
        ],
    ),
    'stats': (
        '\U0001f4ca Stats',
        [
            ('stats', 'Zeige Server-Statistiken'),
            ('system', 'Zeige System-Infos'),
            ('growth', 'Zeige Wachstums-Statistiken'),
        ],
    ),
    'schematics': (
        '\U0001f3d7\ufe0f Schematics',
        [
            ('schematics add', 'Füge ein Schematic hinzu'),
            ('schematics remove', 'Entferne ein Schematic'),
            ('schematics list', 'Zeige alle Schematics'),
            ('schematics panel', 'Öffne das Schematics-Panel'),
        ],
    ),
    'giveaways': (
        '\U0001f389 Giveaways',
        [
            ('giveaway start', 'Starte ein Giveaway'),
            ('giveaway reroll', 'Ziehe einen neuen Gewinner'),
            ('giveaway list', 'Zeige aktive Giveaways'),
        ],
    ),
    'reactionroles': (
        '\U0001f3ad Reaction Roles',
        [
            ('reactionroles create', 'Erstelle ein Reaction-Rollen-Panel'),
            ('reactionroles remove', 'Entferne ein Reaction-Rollen-Panel'),
            ('reactionroles list', 'Zeige alle Reaction-Rollen-Panels'),
        ],
    ),
    'automod': (
        '\U0001f916 Auto-Moderation',
        [
            ('automod config', 'Konfiguriere Auto-Moderation'),
        ],
    ),
}


def _build_main_embed() -> discord.Embed:
    """Erstelle das Haupt-Hilfe-Embed."""
    embed = discord.Embed(
        title='\U0001f4d6 ScratchAI Hilfe',
        description=(
            'Wähle eine Kategorie aus dem Dropdown-Menü unten, '
            'oder nutze `/help <Kategorie>` für sofortige Hilfe.\n\n'
            '**Suche:** Nutze `/help search <Begriff>` um Commands zu durchsuchen.'
        ),
        color=discord.Color.blurple(),
    )
    for key, (title, _) in HELP_CATEGORIES.items():
        embed.add_field(name=title, value=f'`/help {key}`', inline=True)
    embed.set_footer(text='ScratchAI Help System')
    return embed


def _build_category_embed(key: str) -> discord.Embed:
    """Erstelle ein Embed für eine bestimmte Kategorie."""
    title, commands_list = HELP_CATEGORIES[key]
    embed = discord.Embed(
        title=f'{title} – Commands',
        color=discord.Color.blurple(),
    )
    for name, desc in commands_list:
        embed.add_field(name=f'`/{name}`', value=desc, inline=False)
    embed.set_footer(text=f'Nutze /help search <Begriff> zum Suchen')
    return embed


def _search_commands(query: str) -> list[tuple[str, str, str]]:
    """Durchsuche alle Commands nach Name oder Beschreibung."""
    results = []
    q = query.lower()
    for cat_key, (cat_title, cmds) in HELP_CATEGORIES.items():
        for name, desc in cmds:
            if q in name.lower() or q in desc.lower():
                results.append((cat_title, name, desc))
    return results


class HelpSelect(discord.ui.Select):
    """Dropdown-Menü zur Auswahl einer Help-Kategorie."""

    def __init__(self):
        options = [
            discord.SelectOption(label=title.replace('\u200b', ''), value=key, emoji=title[0] if len(title) > 1 else None)
            for key, (title, _) in HELP_CATEGORIES.items()
        ]
        super().__init__(
            placeholder='Wähle eine Kategorie…',
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        key = self.values[0]
        embed = _build_category_embed(key)
        await interaction.response.edit_message(embed=embed, view=HelpView())


class HelpView(discord.ui.View):
    """Persistente View mit Dropdown für die Hilfe."""

    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(HelpSelect())

    @discord.ui.button(label='\U0001f3e0 Hauptmenü', style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = _build_main_embed()
        await interaction.response.edit_message(embed=embed, view=HelpView())

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class HelpCog(commands.Cog):
    """Interaktive Hilfe mit Suchfunktion."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name='help', description='Zeige die interaktive Hilfe')
    @app_commands.describe(category='Kategorie für sofortige Hilfe', query='Suchbegriff für Command-Suche')
    async def cmd_help(
        self,
        interaction: discord.Interaction,
        category: str | None = None,
        query: str | None = None,
    ):
        if query:
            await self._handle_search(interaction, query)
            return
        if category:
            key = category.lower().strip()
            if key in HELP_CATEGORIES:
                embed = _build_category_embed(key)
                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                embed = discord.Embed(
                    title='Kategorie nicht gefunden',
                    description=f'`{category}` existiert nicht.\nVerfügbare Kategorien: {", ".join(HELP_CATEGORIES.keys())}',
                    color=discord.Color.red(),
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        embed = _build_main_embed()
        await interaction.response.send_message(embed=embed, view=HelpView(), ephemeral=True)

    async def _handle_search(self, interaction: discord.Interaction, query: str):
        """Behandle die Suche nach Commands."""
        results = _search_commands(query)
        if not results:
            embed = discord.Embed(
                title='Keine Ergebnisse',
                description=f'Für `{query}` wurden keine Commands gefunden.',
                color=discord.Color.orange(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        embed = discord.Embed(
            title=f'Suchergebnisse für "{query}"',
            color=discord.Color.blurple(),
        )
        for cat_title, name, desc in results[:25]:
            embed.add_field(name=f'`/{name}`', value=f'{desc}\n*Kategorie: {cat_title}*', inline=False)
        if len(results) > 25:
            embed.set_footer(text=f'…und {len(results) - 25} weitere Ergebnisse')
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(HelpCog(bot))
