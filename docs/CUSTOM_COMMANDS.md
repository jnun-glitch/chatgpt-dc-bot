# 🧩 ScratchAI Custom Commands

ScratchAI uses one Discord application-command root for the whole Custom-Command system:

```text
/custom
```

The commands created by the server are normal message commands:

```text
!welcome
!rules
!serverinfo
```

No `/welcome`, `/rules`, `/serverinfo`, etc. are registered dynamically. This keeps the Discord global application-command count low.

> The existing `!tag` system remains separate. Custom Commands do not replace or migrate tags automatically.

---

## 1. Architecture

```text
Discord
│
├── /custom                         ← exactly one global root
│   ├── panel
│   ├── create
│   ├── edit
│   ├── delete
│   ├── enable / disable
│   ├── list / search
│   ├── info / test / settings
│   ├── alias / unalias
│   ├── cooldown
│   ├── stats / audit
│   ├── response ...
│   ├── role ...
│   ├── channel ...
│   └── manager ...
│
└── Message Listener                ← resolves !<name>
    ├── ignore bots / DMs
    ├── built-in prefix command wins
    ├── find custom command or alias
    ├── role policy
    ├── channel policy
    ├── cooldown
    ├── choose response (weighted random)
    ├── render placeholders
    ├── send text / embed
    └── record usage
```

The message router deliberately refuses to shadow an existing normal prefix command. If ScratchAI already has `!ping`, a custom `!ping` cannot override it.

---

## 2. Create the first command

```text
/custom create
```

Example values:

```text
name: welcome
response_text: 👋 Willkommen {user} auf {server}!
description: Begrüßt neue Mitglieder
```

The result is:

```text
!welcome
```

Use it in Discord:

```text
!welcome
```

---

## 3. Placeholders

The template renderer supports these safe placeholders:

```text
{user}
{user.mention}
{user.id}
{user.name}
{user.display_name}
{username}
{display_name}
{mention}
{author}
{author.mention}
{author.id}
{author.name}

{server}
{server.name}
{server.id}
{server.member_count}
{guild}
{guild.name}
{guild.id}

{channel}
{channel.name}
{channel.id}

{message}
{message.id}

{args}
{args.0}
{args.1}
{args.2}
{arg0}
{arg1}
{arg2}
```

Example:

```text
!say Hallo Welt
```

with a response template:

```text
Du hast geschrieben: {args}
Erstes Wort: {args.0}
```

Unknown placeholders are left unchanged instead of evaluating arbitrary Python expressions.

---

## 4. Rollenregeln — das wichtigste Permission-System

Jeder Custom Command kann eigene Rollenregeln bekommen.

### Erlauben

```text
/custom role allow
name: giveaway
rolle: @Event-Team
```

Now only members with `@Event-Team` (or another allowed role) can use `!giveaway`.

### Verbieten

```text
/custom role deny
name: giveaway
rolle: @Muted
```

A member with `@Muted` cannot use it.

### Regel entfernen

```text
/custom role remove
name: giveaway
rolle: @Event-Team
regel: allow
```

### Regeln ansehen

```text
/custom role list
name: giveaway
```

### Semantics

The evaluation order is:

1. A `deny` role always blocks.
2. If at least one `allow` role exists, the user must have at least one of those roles.
3. If no `allow` roles exist, there is no role whitelist.
4. Administrators bypass the role whitelist/deny checks for emergency administration, but an explicit channel deny still blocks them.

This gives configurations such as:

```text
Allow:  @Moderator, @Event-Team
Deny:   @Muted
```

or simply:

```text
Deny:   @Newbie
```

---

## 5. Manager-Rollen

There are two different concepts:

### Command-use roles
These decide **who may execute one particular custom command**.

### Manager roles
These decide **who may manage the custom-command system**.

Set a manager role:

```text
/custom manager add
rolle: @Custom Manager
```

Only administrators may add or remove manager roles.

List them:

```text
/custom manager list
```

A user can then manage Custom Commands when they are:

- Administrator
- `Manage Server`
- member of a configured Custom-Manager role

This keeps `/custom create`, `/custom delete`, role rules, cooldowns, etc. away from normal members.

---

## 6. Channel rules

Custom Commands can also be restricted to channels.

Allow a channel:

```text
/custom channel allow
name: rules
kanal: #faq
```

Deny a channel:

```text
/custom channel deny
name: rules
kanal: #random
```

List:

```text
/custom channel list
name: rules
```

If allow channels exist, the command must be used in one of them. Deny always wins.

---

## 7. Multiple responses

A command may have many responses.

```text
/custom response add
name: hallo
text: 👋 Hey {user}!
weight: 70
```

```text
/custom response add
name: hallo
text: 😎 Yo {user}!
weight: 20
```

```text
/custom response add
name: hallo
text: 🎉 Willkommen {user}!
weight: 10
```

ScratchAI picks one active response using weighted random selection.

This makes:

```text
!hallo
```

feel less repetitive while remaining completely database driven.

List responses:

```text
/custom response list
name: hallo
```

Delete one:

```text
/custom response delete
name: hallo
response_id: 12
```

---

## 8. Embeds

An Embed can be stored as a response too:

```text
/custom response embed
name: welcome
 title: Willkommen!
 description: Schön, dass du auf {server} bist.
 footer: ScratchAI
 weight: 1
```

Supported fields in V1:

- title
- description
- footer
- URL
- weighted selection

Placeholders are rendered inside the supported Embed text fields as well.

---

## 9. Cooldowns

One cooldown can be configured per Custom Command.

Scopes:

```text
user
channel
guild
global
```

Example:

```text
/custom cooldown
name: meme
sekunden: 15
scope: user
```

Meaning: each user can run `!meme` once every 15 seconds.

Other examples:

```text
scope: channel  → one cooldown per channel
scope: guild    → one cooldown per server
scope: global   → one cooldown for the entire bot
```

Set `sekunden: 0` to remove the cooldown.

Cooldown state is stored in SQLite, so it survives a bot restart.

---

## 10. Message behaviour

Use `/custom settings` to control:

```text
delete_trigger
```

Deletes the `!command` message after the response if the bot has the required permission.

```text
delete_reply_after
```

Automatically deletes the generated response after a number of seconds.

The allowed mention policy is also stored per command:

```text
user mentions
role mentions
@everyone / @here
```

User mentions are enabled by default. Role mentions and mass mentions are disabled by default and must be explicitly enabled.

---

## 11. Aliases

A command can have additional names:

```text
/custom alias
name: welcome
alias: hi
```

Now both work:

```text
!welcome
!hi
```

Remove one:

```text
/custom unalias
name: welcome
alias: hi
```

Aliases are stored separately, so changing the main command does not duplicate response data.

---

## 12. Search / info / test

Search:

```text
/custom search
query: wel
```

Detailed configuration:

```text
/custom info
name: welcome
```

Test without sending a normal response:

```text
/custom test
name: welcome
argumente: Max
```

The test renders the template in an ephemeral preview and does not increment usage or consume the normal cooldown.

---

## 13. Stats and audit

Server overview:

```text
/custom stats
```

Single command:

```text
/custom stats
name: welcome
```

Administrative history:

```text
/custom audit
```

The audit trail stores actions such as:

```text
create
edit
delete
enable
disable
settings
alias_add
alias_remove
response_add
response_delete
response_embed_add
role_allow
role_deny
role_remove
channel_allow
channel_deny
channel_remove
manager_role_add
manager_role_remove
cooldown
```

Detailed audit history is retained for 180 days. Cooldown-hit rows older than one day are cleaned up.

---

## 14. Database

Implementation file:

```text
_inner_bot/core/custom_commands_db.py
```

The schema is intentionally normalized. Instead of putting everything into one giant JSON object, data is split into dedicated tables.

### `custom_commands`

Stores the command itself:

```text
guild_id
name
description
enabled
delete_trigger
delete_reply_after
allow_user_mentions
allow_role_mentions
allow_everyone_mentions
created_by
updated_by
created_at
updated_at
last_used_at
uses
```

Unique key:

```text
(guild_id, name)
```

This guarantees server isolation.

### `custom_command_responses`

Stores every possible response:

```text
command_id
content
embed_json
weight
position
enabled
created_at
```

A command can therefore have up to 100 stored responses in the command-management layer.

### `custom_command_aliases`

Maps extra names to the same command:

```text
command_id
alias
```

### `custom_command_role_rules`

Stores both allow and deny rules:

```text
command_id
role_id
rule
```

`rule` is strictly limited to:

```text
allow
deny
```

### `custom_command_channel_rules`

Same idea for channels:

```text
command_id
channel_id
rule
```

### `custom_command_cooldowns`

Stores one cooldown definition per command:

```text
command_id
scope
seconds
```

### `custom_command_cooldown_hits`

Stores the current cooldown timestamps:

```text
command_id
scope_key
last_used_at
```

This is what lets user/channel/server/global cooldowns survive a process restart.

### `custom_command_manager_roles`

Stores which roles are allowed to manage Custom Commands:

```text
guild_id
role_id
```

### `custom_command_usage`

Per-user/per-channel usage statistics:

```text
command_id
guild_id
user_id
channel_id
uses
last_used_at
```

### `custom_command_audit`

Change history:

```text
guild_id
command_id
action
actor_id
details
created_at
```

The important relationships use SQLite foreign keys with cascade/delete-set-null behaviour so removing a command cleans up its dependent configuration instead of leaving orphan rows.

---

## 15. Security model

Custom Commands intentionally do **not** evaluate arbitrary code.

Not supported and should stay unsupported:

```text
eval()
exec()
shell / PowerShell
arbitrary Python
arbitrary SQL
reading .env / secrets
loading plugins from user text
filesystem access
unrestricted HTTP fetches
permission escalation
```

The feature is a controlled template system plus explicit Discord actions. This keeps a powerful server customization feature from becoming an arbitrary-code execution mechanism.

---

## 16. Discord slash-command limit strategy

The whole system is intentionally rooted at one application command:

```text
/custom
```

So these are **not** registered dynamically:

```text
/welcome
/rules
/shop
/ip
```

Instead:

```text
!welcome
!rules
!shop
!ip
```

This is important because ScratchAI already has a global slash-command compaction system in `_inner_bot/bot.py`. The Custom-Command system avoids adding hundreds of dynamic root application commands in the first place.

---

## 17. Files

```text
_inner_bot/
├── cogs/
│   └── custom_commands.py
└── core/
    └── custom_commands_db.py

docs/
└── CUSTOM_COMMANDS.md
```

`custom_commands.py` contains Discord-facing logic and permissions.

`custom_commands_db.py` contains the persistent schema and database operations.

Keeping the storage layer separate makes future dashboard/API work possible without putting SQL directly into the Discord UI layer.

---

## 18. Example server setup

A useful community configuration could look like this:

```text
/custom create
name: rules
response_text: 📜 Lies die Serverregeln in {channel}.
description: Hinweis auf die Regeln
```

```text
/custom role allow
name: rules
rolle: @Member
```

```text
/custom channel allow
name: rules
kanal: #general
```

```text
/custom cooldown
name: rules
sekunden: 5
scope: user
```

And a staff-only command:

```text
/custom create
name: event
response_text: 🎉 Das nächste Event startet bald!
description: Event-Ankündigung
```

```text
/custom role allow
name: event
rolle: @Event-Team
```

Now:

```text
!event
```

is usable by Event Team members, while everyone else is ignored by the message router.
