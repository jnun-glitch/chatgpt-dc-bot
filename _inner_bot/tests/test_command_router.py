"""Regression tests for ScratchAI's application-command safety layer."""

from __future__ import annotations

import sys
from pathlib import Path


BOT_DIR = Path(__file__).resolve().parents[1]
if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))

# sitecustomize normally loads during interpreter startup. Importing it here
# makes the test explicit and keeps it independent from the test runner's path.
import sitecustomize  # noqa: F401,E402

import discord  # noqa: E402
from discord import app_commands  # noqa: E402
from discord.ext import commands  # noqa: E402


def test_global_command_router_keeps_tree_under_discord_limit():
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())

    for index in range(105):
        async def callback(interaction: discord.Interaction):
            await interaction.response.send_message("ok", ephemeral=True)

        command = app_commands.Command(
            name=f"router-test-{index}",
            description="Command router regression test",
            callback=callback,
        )
        bot.tree.add_command(command)

    roots = bot.tree.get_commands()
    assert len(roots) <= 100
    assert any(isinstance(command, app_commands.Group) for command in roots)

    grouped = [
        command
        for root in roots
        if isinstance(root, app_commands.Group)
        for command in root.commands
    ]
    assert len(grouped) == 25
