# Gateway Intent Inventory

Current bot configuration uses `discord.Intents.all()` in `_inner_bot/bot.py`.

This inventory is kept before reducing intents so no existing Cog is silently broken.

## Required intents found in the current architecture

- `message_content`: required by prefix commands (`!…`), Custom Commands, AutoMod message filters, ticket handling and message-based routing.
- `guilds`: required for guild/server metadata, channel/role lookups and normal bot operation.
- `members`: used by member-role and moderation flows, verification and join/raid protection.
- `voice_states`: required for the music/voice Cogs.
- `presences`: only needed where a Cog explicitly reads member presence/activity; verify this before disabling.

## Privileged intents

`message_content` and `members` are privileged intents in Discord's developer portal. Keep them enabled while corresponding features are active.

## Safe reduction procedure

Search every active Cog for message/member/voice-state access, run the complete test suite and import smoke test, then reduce one intent at a time while testing prefix commands, moderation, tickets, verification and music in a real Discord environment.
