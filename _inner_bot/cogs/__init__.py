"""Cogs (Command-Module) des Discord-Bots.

The package is imported before any individual Cog. Import the ScratchAI
command router here so the Discord global application-command limit is handled
before the first feature Cog registers its slash commands.
"""

# sitecustomize.py contains the command-registration safety patch. Importing it
# explicitly is important because Python does not always auto-load
# sitecustomize in every launcher/IDE configuration.
try:
    import sitecustomize  # noqa: F401
except Exception as exc:
    # Keep Cog imports resilient; discord.py will still enforce its normal
    # limits if the optional router cannot be initialized.
    print(f"[COMMAND-ROUTER] konnte nicht aktiviert werden: {exc}")
