# Gateway Intent Inventory

Current bot configuration uses `discord.Intents.all()` in `_inner_bot/bot.py`.

This is intentionally documented before reducing intents so no existing Cog is silently broken.

## Required intents found in the current architecture

- `message_content`: required by prefix commands (`!…`), Custom Commands, AutoMod message filters, ticket handling and message-based routing.
- `guilds`: required for guild/server metadata, channel/role lookups and normal bot operation.
- `members`: used by member-role and moderation flows, verification and join/raid protection.
- `voice_states`: required for the music/voice Cogs.
- `presences`: only needed where a Cog explicitly reads member presence/activity; this should be verified before disabling.

## Privileged intents

`message_content` and `members` are privileged intents in Discord's developer portal. Keep them enabled while the corresponding features are active.

## Safe reduction procedure

1. Search every active Cog for `message.`, `on_message`, `on_member_`, `Member`, role/member caches and voice-state access.
2. Run the complete test suite and import smoke test.
3. Change one intent at a time in both code and the Discord Developer Portal.
4. Test prefix commands, moderation, tickets, verification, Custom Commands and music after each change.
5. Only switch from `Intents.all()` once CI and runtime testing show that every feature still works.

Do not remove an intent merely because a single Cog does not use it; the inventory is repository-wide.
