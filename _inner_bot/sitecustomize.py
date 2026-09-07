"""Early ScratchAI runtime setup.

This module is imported by Python during interpreter startup when `_inner_bot`
is on ``sys.path``. It keeps local environment loading in one place and adds a
small command-registration guard so Cogs cannot fail halfway through startup
when the Discord global application-command limit is reached.

The command router is ScratchAI-specific code. It does not copy implementation
from another bot; it only uses discord.py's public application-command API.
"""
from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

BOT_DIR = Path(__file__).resolve().parent
load_dotenv(BOT_DIR / ".env", override=False)


# Discord currently allows 100 global top-level slash commands.  Keep a
# deliberate safety margin so a new Cog cannot make every later Cog fail to
# load. Overflow commands are placed into normal Discord command groups.
try:
    from discord import app_commands
    from discord.app_commands import CommandTree, Group

    _ORIGINAL_ADD_COMMAND = CommandTree.add_command
    _ROUTER_ROOT_LIMIT = 80
    _GROUP_CHILD_LIMIT = 25
    _GROUP_PREFIX = "scratchai-more"
    _routing_groups: dict[int, Group] = {}

    def _module_key(command) -> str:
        binding = getattr(command, "binding", None)
        if binding is None:
            return "generic"
        module = getattr(binding.__class__, "__module__", "")
        return module.rsplit(".", 1)[-1].casefold() or "generic"

    def _next_group(tree: CommandTree, key: str) -> Group:
        tree_id = id(tree)
        group_key = hash((tree_id, key))
        existing = _routing_groups.get(group_key)
        if existing is not None and len(existing.commands) < _GROUP_CHILD_LIMIT:
            return existing

        index = 1
        while True:
            name = f"{_GROUP_PREFIX}-{key}-{index}"[:32]
            if tree.get_command(name) is None:
                group = Group(name=name, description=f"Weitere {key}-Befehle")
                _ORIGINAL_ADD_COMMAND(tree, group)
                _routing_groups[group_key] = group
                return group
            index += 1

    def _safe_add_command(self, command, /, *, guild=None, guilds=app_commands.MISSING, override=False):
        # Guild-scoped commands have their own namespace and are not part of
        # the global command budget handled here.
        if guild is not None or guilds is not app_commands.MISSING:
            return _ORIGINAL_ADD_COMMAND(
                self, command, guild=guild, guilds=guilds, override=override
            )

        # Context menus use a different Discord limit and are deliberately
        # left to discord.py's normal validation.
        if isinstance(command, app_commands.ContextMenu):
            return _ORIGINAL_ADD_COMMAND(
                self, command, guild=guild, guilds=guilds, override=override
            )

        # Commands that are already nested are handled by their parent group.
        if getattr(command, "parent", None) is not None:
            return _ORIGINAL_ADD_COMMAND(
                self, command, guild=guild, guilds=guilds, override=override
            )

        current = len(self.get_commands())
        if current < _ROUTER_ROOT_LIMIT:
            return _ORIGINAL_ADD_COMMAND(
                self, command, guild=guild, guilds=guilds, override=override
            )

        # Once the safety margin is reached, keep loading Cogs by routing the
        # new command into a normal Discord group. Each group has its own 25
        # subcommand capacity.
        key = _module_key(command)
        group = _next_group(self, key)
        group.add_command(command, override=override)
        print(f"[COMMAND-ROUTER] /{group.name} {command.name}")

    CommandTree.add_command = _safe_add_command
except Exception:
    # Startup must never fail just because this optional guard is unavailable.
    # discord.py will still enforce its normal command limits.
    pass
