import discord
from discord.ext import commands, tasks
from discord import app_commands
import datetime
import json
import os
import asyncio

DATA_FILE = "active_data.json"
CONFIG_FILE = "active_config.json"
PENDING_FILE = "active_pending.json"


def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}


def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def load_pending():
    if os.path.exists(PENDING_FILE):
        with open(PENDING_FILE, "r") as f:
            return json.load(f)
    return []


def save_pending(pending):
    with open(PENDING_FILE, "w") as f:
        json.dump(pending, f, indent=2)


class ActiveButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Ich bin aktiv!",
        style=discord.ButtonStyle.green,
        emoji="\u2705",
        custom_id="active_confirm",
    )
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = load_data()
        user_id = str(interaction.user.id)
        guild_id = str(interaction.guild_id)
        now = datetime.datetime.now().isoformat()

        if user_id not in data:
            data[user_id] = {}

        data[user_id]["last_active"] = now
        data[user_id]["name"] = str(interaction.user)
        data[user_id]["guild"] = guild_id
        data[user_id]["clicks"] = data[user_id].get("clicks", 0) + 1
        save_data(data)

        embed = discord.Embed(
            title="Aktivitaets-Check",
            description=(
                f"Du bist jetzt als **aktiv** markiert!\n\n"
                f"Letzte Aktivitaet: {now[:16].replace('T', ' ')} Uhr\n"
                f"Klicks gesamt: {data[user_id]['clicks']}\n\n"
                f"Diese Nachricht loescht sich in 24h."
            ),
            color=0x2E7D32,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class ActiveCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_inactivity.start()
        self.bot.loop.create_task(self._restore_pending_tasks())
        self.bot.loop.create_task(self._register_persistent_view())

    async def _register_persistent_view(self):
        self.bot.add_view(ActiveButton())

    async def _restore_pending_tasks(self):
        await self.bot.wait_until_ready()
        pending = load_pending()
        restored = []

        for item in pending:
            try:
                channel = self.bot.get_channel(int(item["channel_id"]))
                if not channel:
                    continue
                msg = await channel.fetch_message(int(item["message_id"]))
                expire = datetime.datetime.fromisoformat(item["expires_at"])
                now = datetime.datetime.now()

                if expire <= now:
                    await self._process_inactive(item)
                    try:
                        await msg.delete()
                    except Exception:
                        pass
                else:
                    delay = (expire - now).total_seconds()
                    restored.append(item)
                    self.bot.loop.create_task(
                        self._schedule_check_and_delete(delay, item)
                    )
            except Exception:
                pass

        save_pending(restored)

    async def _schedule_check_and_delete(self, delay, item):
        await asyncio.sleep(delay)
        await self._process_inactive(item)
        try:
            channel = self.bot.get_channel(int(item["channel_id"]))
            if channel:
                msg = await channel.fetch_message(int(item["message_id"]))
                await msg.delete()
        except Exception:
            pass

        pending = load_pending()
        pending = [
            p for p in pending
            if p.get("message_id") != item.get("message_id")
        ]
        save_pending(pending)

    async def _process_inactive(self, item):
        data = load_data()
        cfg = load_config()
        guild_id = item["guild_id"]
        gcfg = cfg.get(guild_id, {})
        warn_hours = gcfg.get("warn_hours", 24)

        try:
            guild = self.bot.get_guild(int(guild_id))
            if not guild:
                return
        except Exception:
            return

        role_id = gcfg.get("inactive_role_id")
        channel_id = gcfg.get("notify_channel_id")
        action = gcfg.get("action", "none")

        now = datetime.datetime.now()
        threshold = now - datetime.timedelta(hours=warn_hours)
        kick_threshold = now - datetime.timedelta(hours=warn_hours * 2)

        inactive_members = []
        for member in guild.members:
            if member.bot:
                continue
            user_id = str(member.id)
            if user_id not in data or "last_active" not in data[user_id]:
                inactive_members.append(member)
                continue
            last = datetime.datetime.fromisoformat(data[user_id]["last_active"])
            if last < threshold:
                inactive_members.append(member)

        for member in inactive_members:
            if action == "remove_role" and role_id:
                role = guild.get_role(int(role_id))
                if role and role in member.roles:
                    try:
                        await member.remove_roles(role, reason="Inaktiv - Activity-Check")
                    except Exception:
                        pass

            if action == "kick":
                user_id = str(member.id)
                if user_id in data and "last_active" in data[user_id]:
                    last = datetime.datetime.fromisoformat(data[user_id]["last_active"])
                    if last < kick_threshold:
                        try:
                            await member.kick(reason="Inaktiv zu lang - Activity-Check")
                        except Exception:
                            pass

        if inactive_members and channel_id:
            channel = guild.get_channel(int(channel_id))
            if channel:
                names = [str(m) for m in inactive_members[:15]]
                embed = discord.Embed(
                    title="Inaktive Mitglieder",
                    description="\n".join(names),
                    color=0xF14C4C,
                    timestamp=now,
                )
                embed.add_field(
                    name="Aktion",
                    value={"none": "Nur Benachrichtigung", "remove_role": "Rolle entfernt", "kick": "Gekickt"}.get(action, action),
                )
                await channel.send(embed=embed)

    @tasks.loop(hours=1)
    async def check_inactivity(self):
        pass

    @check_inactivity.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    @app_commands.command(
        name="active",
        description="Aktivitaets-Check: Bist du noch da? (loescht sich in 24h)",
    )
    async def cmd_active(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Aktivitaets-Check",
            description=(
                "Klicke auf den Button um zu zeigen dass du noch aktiv bist!\n\n"
                "**Was passiert?**\n"
                "- Klickst du -> Du bist **aktiv**\n"
                "- Klickst du NICHT -> Nach 24h wird geprueft\n"
                "- Diese Nachricht loescht sich **automatisch in 24h**\n\n"
                "**Wichtig:** Du MUSST auf den Button klicken!"
            ),
            color=0x007ACC,
            timestamp=datetime.datetime.now(),
        )
        embed.set_footer(text="ScratchAI Activity-System | Loescht sich in 24h")

        view = ActiveButton()
        msg = await interaction.response.send_message(embed=embed, view=view)

        expire = datetime.datetime.now() + datetime.timedelta(hours=24)
        pending = load_pending()
        pending.append({
            "guild_id": str(interaction.guild_id),
            "channel_id": str(interaction.channel_id),
            "message_id": str((await interaction.original_response()).id),
            "expires_at": expire.isoformat(),
        })
        save_pending(pending)

        delay = 24 * 3600
        self.bot.loop.create_task(
            self._schedule_check_and_delete(delay, pending[-1])
        )

    @app_commands.command(
        name="active-config",
        description="Activity-System konfigurieren (Admin only)",
    )
    @app_commands.describe(
        warn_hours="Stunden bis Warnung (Standard: 24)",
        action="Was mit Inaktiven passieren soll",
        inactive_role="Rolle die Inaktiven entfernt wird",
        notify_channel="Channel fuer Benachrichtigungen",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="Nichts (nur warnen)", value="none"),
            app_commands.Choice(name="Rolle entfernen", value="remove_role"),
            app_commands.Choice(name="Kicken", value="kick"),
        ]
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def cmd_active_config(
        self,
        interaction: discord.Interaction,
        warn_hours: int = 24,
        action: str = "none",
        inactive_role: discord.Role = None,
        notify_channel: discord.TextChannel = None,
    ):
        guild_id = str(interaction.guild.id)
        cfg = load_config()

        if guild_id not in cfg:
            cfg[guild_id] = {}

        cfg[guild_id]["warn_hours"] = warn_hours
        cfg[guild_id]["action"] = action
        cfg[guild_id]["inactive_role_id"] = str(inactive_role.id) if inactive_role else None
        cfg[guild_id]["notify_channel_id"] = str(notify_channel.id) if notify_channel else None
        save_config(cfg)

        embed = discord.Embed(title="Activity-Config gespeichert", color=0x2E7D32)
        embed.add_field(name="Warnung nach", value=f"{warn_hours} Stunden")
        embed.add_field(
            name="Aktion",
            value={
                "none": "Nur warnen",
                "remove_role": f"Rolle entfernen ({inactive_role.mention if inactive_role else '?'})",
                "kick": "Kicken nach doppelter Zeit",
            }.get(action, action),
        )
        embed.add_field(
            name="Benachrichtigung",
            value=notify_channel.mention if notify_channel else "Keiner",
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="active-list",
        description="Zeigt alle aktiven und inaktiven Mitglieder",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def cmd_active_list(self, interaction: discord.Interaction):
        data = load_data()
        guild = interaction.guild
        now = datetime.datetime.now()
        threshold_24h = now - datetime.timedelta(hours=24)
        threshold_7d = now - datetime.timedelta(days=7)

        active = []
        inactive_24h = []
        inactive_7d = []
        unknown = []

        for member in guild.members:
            if member.bot:
                continue
            user_id = str(member.id)
            if user_id in data and "last_active" in data[user_id]:
                last = datetime.datetime.fromisoformat(data[user_id]["last_active"])
                if last > threshold_24h:
                    active.append(f"{member.mention} ({last.strftime('%d.%m %H:%M')})")
                elif last > threshold_7d:
                    inactive_24h.append(f"{member.mention} ({last.strftime('%d.%m %H:%M')})")
                else:
                    inactive_7d.append(f"{member.mention} ({last.strftime('%d.%m %H:%M')})")
            else:
                unknown.append(str(member.mention))

        embed = discord.Embed(title="Aktivitaets-Liste", color=0x007ACC)
        if active:
            embed.add_field(
                name=f"Aktiv (< 24h) [{len(active)}]",
                value="\n".join(active[:15]) + ("..." if len(active) > 15 else ""),
                inline=False,
            )
        if inactive_24h:
            embed.add_field(
                name=f"Warnung (24h-7d) [{len(inactive_24h)}]",
                value="\n".join(inactive_24h[:15]) + ("..." if len(inactive_24h) > 15 else ""),
                inline=False,
            )
        if inactive_7d:
            embed.add_field(
                name=f"Inaktiv (> 7d) [{len(inactive_7d)}]",
                value="\n".join(inactive_7d[:15]) + ("..." if len(inactive_7d) > 15 else ""),
                inline=False,
            )
        if unknown:
            embed.add_field(
                name=f"Noch nie geklickt [{len(unknown)}]",
                value=str(len(unknown)) + " Mitglieder",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="active-reset",
        description="Setzt alle Aktivitaets-Daten zurueck",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def cmd_active_reset(self, interaction: discord.Interaction):
        save_data({})
        save_pending([])
        await interaction.response.send_message(
            "Alle Aktivitaets-Daten wurden zurueckgesetzt.", ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(ActiveCog(bot))
