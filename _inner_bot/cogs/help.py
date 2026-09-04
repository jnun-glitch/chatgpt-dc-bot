"""Dynamic help system that reads currently loaded Discord commands."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


CATEGORY_EMOJIS = {
    "moderation": "🛡️",
    "admin": "⚙️",
    "ticket": "🎫",
    "automod": "🤖",
    "music": "🎵",
    "voice": "🎙️",
    "server": "🌐",
    "level": "⭐",
    "giveaway": "🎉",
    "reactionroles": "🎭",
    "schematics": "🏗️",
}


def _root_name(command) -> str:
    qualified = getattr(command, "qualified_name", getattr(command, "name", "unknown"))
    return str(qualified).split()[0].lower()


def _description(command) -> str:
    return getattr(command, "description", None) or getattr(command, "help", None) or "Keine Beschreibung"


def _all_app_commands(bot: commands.Bot):
    return [cmd for cmd in bot.tree.walk_commands() if not isinstance(cmd, app_commands.Group)]


def _all_prefix_commands(bot: commands.Bot):
    return list(bot.walk_commands())


def _all_entries(bot: commands.Bot):
    entries = []
    seen = set()
    for command in _all_app_commands(bot):
        key = ("/", getattr(command, "qualified_name", command.name))
        if key not in seen:
            seen.add(key)
            entries.append((key, "/" + key[1], _description(command), _root_name(command)))
    for command in _all_prefix_commands(bot):
        if getattr(command, "hidden", False):
            continue
        key = ("!", getattr(command, "qualified_name", command.name))
        if key not in seen:
            seen.add(key)
            entries.append((key, "!" + key[1], _description(command), _root_name(command)))
    return sorted(entries, key=lambda x: x[1].casefold())


def _categories(bot: commands.Bot):
    categories = {}
    for _key, name, desc, root in _all_entries(bot):
        categories.setdefault(root, []).append((name, desc))
    return categories


def _build_main_embed(bot: commands.Bot) -> discord.Embed:
    entries = _all_entries(bot)
    cats = _categories(bot)
    preview = []
    for root, commands_list in sorted(cats.items(), key=lambda item: item[0]):
        emoji = CATEGORY_EMOJIS.get(root, "📦")
        preview.append(f"{emoji} **{root.title()}** — {len(commands_list)} Commands")
    embed = discord.Embed(
        title="📚 ScratchAI Hilfe",
        description=(
            "Die Hilfe wird automatisch aus den aktuell geladenen Cogs aufgebaut.\n\n"
            + "\n".join(preview[:20])
            + f"\n\n**Insgesamt:** {len(entries)} Commands\n"
            "Nutze `/help category:<name>` oder `/help query:<begriff>`."
        ),
        color=discord.Color.blurple(),
    )
    embed.set_footer(text="Dynamisches Help-System")
    return embed


def _build_category_embed(bot: commands.Bot, key: str) -> discord.Embed | None:
    cats = _categories(bot)
    matches = cats.get(key.casefold())
    if not matches:
        return None
    emoji = CATEGORY_EMOJIS.get(key.casefold(), "📦")
    embed = discord.Embed(title=f"{emoji} {key.title()}", color=discord.Color.blurple())
    for name, desc in matches[:25]:
        embed.add_field(name=f"`{name}`", value=desc, inline=False)
    if len(matches) > 25:
        embed.set_footer(text=f"… und {len(matches) - 25} weitere Commands")
    return embed


def _search(bot: commands.Bot, query: str):
    q = query.casefold()
    return [
        (name, desc, root)
        for _key, name, desc, root in _all_entries(bot)
        if q in name.casefold() or q in desc.casefold() or q in root.casefold()
    ]


class HelpSelect(discord.ui.Select):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        options = []
        for key in sorted(_categories(bot))[:25]:
            options.append(discord.SelectOption(
                label=key.title()[:100],
                value=key,
                emoji=CATEGORY_EMOJIS.get(key, "📦"),
            ))
        if not options:
            options = [discord.SelectOption(label="Keine Commands", value="none", emoji="❌")]
        super().__init__(placeholder="Wähle eine Kategorie…", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        key = self.values[0]
        embed = _build_category_embed(self.bot, key)
        if embed is None:
            await interaction.response.send_message("Kategorie nicht gefunden.", ephemeral=True)
            return
        await interaction.response.edit_message(embed=embed, view=HelpView(self.bot))


class HelpView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=120)
        self.bot = bot
        self.add_item(HelpSelect(bot))

    @discord.ui.button(label="🏠 Hauptmenü", style=discord.ButtonStyle.secondary, row=1)
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=_build_main_embed(self.bot), view=HelpView(self.bot))


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Zeigt die dynamische Hilfe")
    @app_commands.describe(category="Kategorie bzw. Command-Gruppe", query="Command oder Beschreibung durchsuchen")
    async def cmd_help(self, interaction: discord.Interaction, category: str | None = None, query: str | None = None):
        if query:
            results = _search(self.bot, query)
            if not results:
                await interaction.response.send_message(f"Keine Commands für `{query}` gefunden.", ephemeral=True)
                return
            embed = discord.Embed(title=f"🔎 Suche: {query}", color=discord.Color.blurple())
            for name, desc, root in results[:25]:
                embed.add_field(name=f"`{name}`", value=f"{desc}\n*Kategorie: {root}*", inline=False)
            if len(results) > 25:
                embed.set_footer(text=f"… und {len(results) - 25} weitere Treffer")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if category:
            embed = _build_category_embed(self.bot, category)
            if embed is None:
                categories = ", ".join(sorted(_categories(self.bot))) or "Keine"
                await interaction.response.send_message(f"Kategorie nicht gefunden. Verfügbar: {categories}", ephemeral=True)
                return
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await interaction.response.send_message(embed=_build_main_embed(self.bot), view=HelpView(self.bot), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(HelpCog(bot))
