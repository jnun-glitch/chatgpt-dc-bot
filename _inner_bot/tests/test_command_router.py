"""Regression tests for ScratchAI's application-command safety layer."""
from __future__ import annotations

import sys
from pathlib import Path

BOT_DIR = Path(__file__).resolve().parents[1]
if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))

import discord
from discord import app_commands
from discord.ext import commands


def test_sitecustomize_does_not_monkey_patch_command_tree():
    original = commands.Bot(command_prefix="!", intents=discord.Intents.none()).tree.add_command
    import sitecustomize  # noqa: F401
    current = commands.Bot(command_prefix="!", intents=discord.Intents.none()).tree.add_command
    assert type(current).__func__ is type(original).__func__


def test_command_tree_can_hold_more_than_router_headroom_before_compaction():
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    for index in range(91):
        async def callback(interaction: discord.Interaction):
            await interaction.response.send_message("ok", ephemeral=True)

        bot.tree.add_command(app_commands.Command(
            name=f"router-test-{index}",
            description="Command router regression test",
            callback=callback,
        ))
    assert len(bot.tree.get_commands()) == 91
