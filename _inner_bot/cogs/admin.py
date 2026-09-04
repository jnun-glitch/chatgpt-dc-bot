"""Admin: Bot-Gruppe, System, Train, Setup, Infos, Backup."""
import asyncio
import os
import shutil
import subprocess
from pathlib import Path
import discord

from discord import app_commands
from discord.ext import commands
from core.config import BOT_DIR, PROJECT_ROOT, WEBAPP_URL, ADMIN_LOG_CHANNEL_ID, _is_owner
from core.db import get_db, get_guild_mode, set_guild_mode
from core.logging import logger
from core.ai import _get_ai, _get_ai_gen
from core.modes import BOT_MODES, _ALWAYS_ALLOWED
from core.roles import ROLE_PRESETS, ensure_standard_roles, ensure_staff_channels, apply_channel_permissions
from core.channelnames import styled_text_name, styled_voice_name, base_name, find_channel
from core.evolution import _get_evolution
from core.utils import _require_verified
from cogs.dashboard import log_audit_event


class AdminCog(commands.Cog):
    """Admin- und Owner-Commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._evolution_task = None

    # ── /status – Bot Status ────────────────────────────────────────────────────
    @app_commands.command(name='status', description='Zeige Bot-Status und Statistiken')
    async def cmd_status(self, interaction: discord.Interaction):
        embed = discord.Embed(title='Bot Status', color=discord.Color.green())
        embed.add_field(name='AI Chat', value='Online' if _get_ai() else 'Lädt...', inline=True)
        embed.add_field(name='Game Generator', value='Web-App (Render)', inline=True)
        embed.add_field(name='Guilds', value=str(len(self.bot.guilds)), inline=True)
        embed.add_field(name='Latency', value=f'{self.bot.latency * 1000:.0f}ms', inline=True)
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) as cnt FROM discord_links WHERE confirmed = TRUE')
            verified = cursor.fetchone()['cnt']
            cursor.execute('SELECT COUNT(*) as cnt FROM verify_codes')
            total_codes = cursor.fetchone()['cnt']
            cursor.execute('SELECT COUNT(*) as cnt FROM verify_codes WHERE used = TRUE')
            used_codes = cursor.fetchone()['cnt']
            conn.close()
            embed.add_field(name='Verknüpfungen', value=str(verified), inline=True)
            embed.add_field(name='Codes (benutzt/gesamt)', value=f'{used_codes}/{total_codes}', inline=True)
        except Exception as e:
            logger.warning(f'/status: DB-Statistik fehlgeschlagen: {e}')
        await interaction.response.send_message(embed=embed)

    # ── /reload – Commands neu syncen ───────────────────────────────────────────
    @app_commands.command(name='reload', description='Slash Commands neu synchronisieren (nur Admin)')
    @app_commands.default_permissions(administrator=True)
    async def cmd_reload(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(title='Keine Berechtigung', description='Nur Admins können /reload nutzen.', color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            synced = await self.bot.tree.sync()
            embed = discord.Embed(
                title='Commands neu geladen',
                description=f'{len(synced)} Slash Commands erfolgreich synchronisiert.',
                color=discord.Color.green()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            logger.info(f'{len(synced)} commands reloaded by {interaction.user}')
        except Exception as e:
            embed = discord.Embed(title='Reload fehlgeschlagen', description=str(e)[:200], color=discord.Color.red())
            await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /test – System-Check ────────────────────────────────────────────────────
    @app_commands.command(name='test', description='Teste ob alle Systeme funktionieren')
    async def cmd_test(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        results = []
        latency = self.bot.latency * 1000
        status = 'OK' if latency < 500 else 'Langsam'
        results.append(f'**Bot:** {status} ({latency:.0f}ms)')
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) as cnt FROM verify_codes')
            conn.close()
            results.append('**Datenbank:** OK')
        except Exception as e:
            results.append(f'**Datenbank:** Fehler ({e})')
        ai = _get_ai()
        results.append(f'**AI Chat:** {"OK" if ai else "Lädt..."}')
        gen = _get_ai_gen()
        gen_online = await asyncio.to_thread(gen.is_ready)
        results.append(f'**Game Generator (Web-App):** {"OK" if gen_online else "Offline"}')
        if ai:
            try:
                test_result = await asyncio.to_thread(ai.answer, 'Hallo', 'de')
                reply = test_result.get('reply', '')[:50]
                results.append(f'**AI Chat Test:** OK → "{reply}..."')
            except Exception as e:
                results.append(f'**AI Chat Test:** Fehler ({e})')
        if gen_online:
            results.append('**SB3 Generator:** Web-App bereit')
        else:
            results.append('**SB3 Generator:** Web-App offline (Render)')
        embed = discord.Embed(
            title='System Test',
            description='\n'.join(results),
            color=discord.Color.green() if all('OK' in r for r in results) else discord.Color.yellow()
        )
        await interaction.followup.send(embed=embed)

    # ── /train – AI Evolution Auto-Train ────────────────────────────────────────
    @app_commands.command(name='train', description='Starte/Stoppe das AI Auto-Training (Admin)')
    @app_commands.describe(rounds='Anzahl Trainings-Runden (1-20)', prompt='Optionaler Spiel-Prompt für alle Runden')
    @app_commands.default_permissions(administrator=True)
    async def cmd_train(self, interaction: discord.Interaction, rounds: int = 3, prompt: str = ''):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('Keine Berechtigung!', ephemeral=True)
            return
        engine = _get_evolution()
        if engine is None:
            await interaction.response.send_message('Evolution Engine nicht geladen!', ephemeral=True)
            return
        if engine.running:
            engine.stop()
            await interaction.response.send_message('Evolution gestoppt!', ephemeral=True)
            return
        rounds = max(1, min(20, rounds))
        await interaction.response.send_message(
            f'Evolution gestartet: **{rounds} Runden**' + (f'\nPrompt: _{prompt}_' if prompt else ''),
            ephemeral=True
        )

        async def _run_train():
            try:
                import ai_evolution.ollama_client as oc
                if not oc.is_alive():
                    await interaction.followup.send('Ollama ist offline!', ephemeral=True)
                    return

                def run_engine():
                    return engine.run_auto_train(rounds=rounds, callback=lambda result, current, total: None)

                results = await asyncio.get_event_loop().run_in_executor(None, run_engine)
                embed = discord.Embed(title='Evolution abgeschlossen!', color=discord.Color.green())
                stats = engine.memory.get_stats()
                embed.add_field(
                    name='Statistik',
                    value=(
                        f'Runden: {stats["total_rounds"]}\n'
                        f'Gen-A: {stats["gen_a_wins"]} Siege\n'
                        f'Gen-B: {stats["gen_b_wins"]} Siege\n'
                        f'Kombi: {stats["combos_wins"]} Siege\n'
                        f'Lernerfolge: {stats["lessons_count"]}'
                    ),
                    inline=True
                )
                top = stats.get('top_features', [])
                if top:
                    embed.add_field(name='Top Features', value='\n'.join(f'{f}: {s:.1f}/10' for f, s in top[:5]), inline=True)
                embed.set_footer(text='Ergebnisse in data/evolution_logs/ | Auto-pushed zu GitHub')
                await interaction.followup.send(embed=embed, ephemeral=True)
            except Exception as e:
                await interaction.followup.send(f'Fehler: {e}', ephemeral=True)

        self._evolution_task = asyncio.create_task(_run_train())

    @app_commands.command(name='train-status', description='Zeigt den AI Evolution Status')
    async def cmd_train_status(self, interaction: discord.Interaction):
        engine = _get_evolution()
        if engine is None:
            await interaction.response.send_message('Evolution Engine nicht geladen!', ephemeral=True)
            return
        status = engine.get_status()
        embed = discord.Embed(
            title='AI Evolution Status',
            color=discord.Color.blue() if not status['running'] else discord.Color.gold()
        )
        embed.add_field(
            name='System',
            value=(
                f'Ollama: {"Online" if status["ollama_alive"] else "OFFLINE"}\n'
                f'Model: {status["model"]}\n'
                f'Status: {"Läuft..." if status["running"] else "Idle"}'
            ),
            inline=True
        )
        stats = status['stats']
        embed.add_field(
            name='Statistik',
            value=(
                f'Runden: {stats["total_rounds"]}\n'
                f'Gen-A: {stats["gen_a_wins"]} Siege\n'
                f'Gen-B: {stats["gen_b_wins"]} Siege\n'
                f'Kombi: {stats["combos_wins"]} Siege'
            ),
            inline=True
        )
        top = stats.get('top_features', [])
        if top:
            embed.add_field(name='Top Features', value='\n'.join(f'{f}: {s:.1f}/10' for f, s in top[:5]), inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /admin-stats – Server Statistiken ───────────────────────────────────────
    @app_commands.command(name='admin-stats', description='Zeigt Server-Statistiken (Admin)')
    @app_commands.default_permissions(administrator=True)
    async def cmd_admin_stats(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('Keine Berechtigung!', ephemeral=True)
            return
        ai = _get_ai()
        guild = interaction.guild
        total_members = guild.member_count
        online_members = sum(1 for m in guild.members if m.status != discord.Status.offline)
        text_channels = len(guild.text_channels)
        voice_channels = len(guild.voice_channels)
        roles = len(guild.roles)
        boosts = guild.premium_subscription_count
        ai_status = 'Bereit' if ai else 'Lädt...'
        gen_status = 'Web-App (Render)'
        embed = discord.Embed(title='Server Statistiken', color=discord.Color.blue())
        embed.add_field(name='Member', value=f'Gesamt: {total_members}\nOnline: {online_members}', inline=True)
        embed.add_field(name='Channels', value=f'Text: {text_channels}\nVoice: {voice_channels}', inline=True)
        embed.add_field(name='Rollen', value=str(roles), inline=True)
        embed.add_field(name='Boosts', value=str(boosts), inline=True)
        embed.add_field(name='AI Status', value=f'Chat: {ai_status}\nGenerator: {gen_status}', inline=False)
        await interaction.response.send_message(embed=embed)

    # ── /bot – Owner-Bereich (Gruppe) ───────────────────────────────────────────
    owner_group = app_commands.Group(name='bot', description='Bot-Konfiguration: Modus + Tests (nur Owner)')

    @owner_group.command(name='modus', description='Modus wählen / anzeigen (nur Owner)')
    @app_commands.describe(modus='Welcher Bot-Modus soll für diesen Server aktiv sein?')
    @app_commands.choices(modus=[
        app_commands.Choice(name='🔀 Alles (Standard)', value='all'),
        app_commands.Choice(name='⛏️ SMP', value='smp'),
        app_commands.Choice(name='🤖 Scratch-AI', value='scratch-ai'),
        app_commands.Choice(name='🛡️ Moderation', value='moderation'),
    ])
    async def cmd_bot_modus(self, interaction: discord.Interaction, modus: app_commands.Choice[str] = None):
        if not interaction.guild:
            await interaction.response.send_message('Nur auf Servern verfügbar.', ephemeral=True)
            return
        if not _is_owner(interaction.user):
            await interaction.response.send_message('Nur der Bot-Owner kann den Modus ändern.', ephemeral=True)
            return
        if modus is None:
            current = get_guild_mode(interaction.guild.id)
            desc = f'Aktueller Modus: **{BOT_MODES[current]["label"]}**\n\n'
            for key, m in BOT_MODES.items():
                marker = '✅' if key == current else '⬜'
                desc += f'{marker} **{m["label"]}** — {m["desc"]}\n'
            desc += '\nSetze mit `/bot modus:<wahl>` einen neuen Modus.'
            desc += '\n\nImmer verfügbar: `/ticket`, `/setup-roles`, `/setup-smp`, `/help`, `/status`'
            embed = discord.Embed(title='🤖 Bot-Modus', description=desc, color=discord.Color.blue())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        mode_key = modus.value
        ok = set_guild_mode(interaction.guild.id, mode_key)
        if not ok:
            await interaction.response.send_message('Fehler beim Speichern.', ephemeral=True)
            return
        m = BOT_MODES[mode_key]
        embed = discord.Embed(
            title='🤖 Bot-Modus geändert',
            description=f'Dieser Server läuft jetzt im Modus **{m["label"]}**.\n{m["desc"]}',
            color=discord.Color.green(),
        )
        if m['commands'] is not None:
            active = [f'`/{c}`' for c in sorted(m['commands']) if c not in _ALWAYS_ALLOWED]
            embed.add_field(name='Aktive Commands', value=' '.join(active), inline=False)
        await interaction.response.send_message(embed=embed)
        try:
            logger.info(f'Modus {m["label"]} auf {interaction.guild.name} gesetzt von {interaction.user.display_name}')
            admin_log = interaction.guild.get_channel(ADMIN_LOG_CHANNEL_ID)
            if admin_log:
                await admin_log.send(f'🤖 Modus **{m["label"]}** auf **{interaction.guild.name}** gesetzt von {interaction.user.mention}')
        except Exception as e:
            logger.warning(f'Modus: Admin-Log senden fehlgeschlagen: {e}')

    @owner_group.command(name='test', description='Owner-Panel: verschiedene System-Tests (nur Owner)')
    @app_commands.describe(test='Welcher Test soll ausgeführt werden?')
    @app_commands.choices(test=[
        app_commands.Choice(name='🖥️ Alle Systeme', value='alle'),
        app_commands.Choice(name='🔌 DB Check', value='db'),
        app_commands.Choice(name='🤖 AI Chat Check', value='ai'),
        app_commands.Choice(name='🎮 Generator Check', value='gen'),
        app_commands.Choice(name='⏱️ Latenz / Ping', value='ping'),
        app_commands.Choice(name='🎉 Welcome-Test', value='welcome'),
        app_commands.Choice(name='📋 Modus-Status', value='modus'),
        app_commands.Choice(name='🧠 Rollen-Check', value='rollen'),
        app_commands.Choice(name='🔒 Owner-Check', value='owner'),
    ])
    async def cmd_bot_test(self, interaction: discord.Interaction, test: app_commands.Choice[str]):
        if not _is_owner(interaction.user):
            await interaction.response.send_message('Nur der Bot-Owner kann diesen Test ausführen.', ephemeral=True)
            return
        choice = test.value
        if choice == 'owner':
            embed = discord.Embed(
                title='🔒 Owner-Check',
                description='✅ Du bist der Bot-Owner!\n\n**Deine exklusiven Rechte:**\n`/bot modus` – Modus ändern\n`/bot test` – System-Tests\n',
                color=discord.Color.green(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        if choice == 'ping':
            latency = self.bot.latency * 1000
            embed = discord.Embed(
                title='⏱️ Latenz',
                description=f'**WebSocket:** {latency:.0f}ms\n**Status:** {"OK" if latency < 500 else "Langsam"}',
                color=discord.Color.green() if latency < 500 else discord.Color.orange(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        if choice == 'db':
            try:
                conn = get_db()
                cursor = conn.cursor()
                tables = []
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
                for (t,) in cursor.fetchall():
                    cursor.execute(f'SELECT COUNT(*) FROM {t}')
                    count = cursor.fetchone()[0]
                    tables.append(f'`{t}`: {count}')
                conn.close()
                embed = discord.Embed(title='🔌 Datenbank Check', description='**✅ Datenbank OK**\n\n' + '\n'.join(tables), color=discord.Color.green())
            except Exception as e:
                embed = discord.Embed(title='🔌 Datenbank Check', description=f'**❌ Fehler:** {e}', color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        if choice == 'ai':
            ai = _get_ai()
            if not ai:
                await interaction.response.send_message('🤖 AI lädt noch...', ephemeral=True)
                return
            try:
                test_result = await asyncio.to_thread(ai.answer, 'Hallo, teste mich!', 'de')
                reply = (test_result.get('reply') or '')[:120]
                embed = discord.Embed(title='🤖 AI Chat Check', description=f'**✅ AI Chat OK**\n\nAntwort: „{reply}…"', color=discord.Color.green())
            except Exception as e:
                embed = discord.Embed(title='🤖 AI Chat Check', description=f'**❌ Fehler:** {e}', color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        if choice == 'gen':
            gen = _get_ai_gen()
            if not gen:
                await interaction.response.send_message('🎮 Generator lädt noch...', ephemeral=True)
                return
            await interaction.response.defer(thinking=True, ephemeral=True)
            try:
                from project.sb3_generator.generator_v2 import SB3Generator
                from project.ai_generator.composer import AIComposer
                composer = AIComposer()
                sb3_gen = SB3Generator()
                bundle = composer.compose(['has_gravity', 'has_jumping'], 'bot-test')
                sb3 = sb3_gen.generate(bundle)
                embed = discord.Embed(title='🎮 Generator Check', description=f'**✅ Generator OK**\n\nBundle validiert, SB3 erzeugt ({len(sb3)} bytes).', color=discord.Color.green())
            except Exception as e:
                embed = discord.Embed(title='🎮 Generator Check', description=f'**❌ Fehler:** {e}', color=discord.Color.red())
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        if choice == 'welcome':
            if not interaction.guild:
                await interaction.response.send_message('Nur auf Servern verfügbar.', ephemeral=True)
                return
            member_count = interaction.guild.member_count
            embed = discord.Embed(
                title=f'Willkommen {interaction.user.display_name}! 🎉',
                description=f'Hey {interaction.user.mention}, willkommen im **ScratchAI** Discord!\n\nViel Spaß hier! 💜',
                color=discord.Color.green(),
            )
            embed.set_thumbnail(url=interaction.user.display_avatar.url)
            embed.add_field(name='Member', value=f'#{member_count}', inline=True)
            embed.add_field(name='Tipps', value='/help für alle Commands', inline=True)
            embed.set_footer(text=f'Willkommen beim # {member_count} Mitglied!')
            await interaction.response.send_message('🎉 So sieht die Welcome-Nachricht aus:', embed=embed, ephemeral=True)
            return
        if choice == 'modus':
            if not interaction.guild:
                await interaction.response.send_message('Nur auf Servern verfügbar.', ephemeral=True)
                return
            current = get_guild_mode(interaction.guild.id)
            desc = f'Aktueller Modus: **{BOT_MODES[current]["label"]}**\n\n'
            for key, m in BOT_MODES.items():
                marker = '✅' if key == current else '⬜'
                desc += f'{marker} **{m["label"]}** — {m["desc"]}\n'
            embed = discord.Embed(title='📋 Modus-Status', description=desc, color=discord.Color.blue())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        if choice == 'rollen':
            if not interaction.guild:
                await interaction.response.send_message('Nur auf Servern verfügbar.', ephemeral=True)
                return
            roles = sorted(interaction.guild.roles, key=lambda r: r.position, reverse=True)
            lines = [f'{r.mention} — **{len(r.members)}** Mitglieder' for r in roles]
            embed = discord.Embed(title=f'🧠 Rollen auf {interaction.guild.name}', description='\n'.join(lines[:30]), color=discord.Color.purple())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        # choice == 'alle'
        await interaction.response.defer(thinking=True, ephemeral=True)
        results = []
        latency = self.bot.latency * 1000
        status = 'OK' if latency < 500 else 'Langsam'
        results.append(f'**Bot:** {status} ({latency:.0f}ms)')
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) as cnt FROM verify_codes')
            conn.close()
            results.append('**Datenbank:** OK')
        except Exception as e:
            results.append(f'**Datenbank:** Fehler ({e})')
        ai = _get_ai()
        results.append(f'**AI Chat:** {"OK" if ai else "Lädt..."}')
        results.append(f'**Game Generator:** Web-App (Render)')
        if ai:
            try:
                test_result = await asyncio.to_thread(ai.answer, 'Hallo', 'de')
                reply = test_result.get('reply', '')[:50]
                results.append(f'**AI Chat Test:** OK → "{reply}..."')
            except Exception as e:
                results.append(f'**AI Chat Test:** Fehler ({e})')
        try:
            from project.sb3_generator.generator_v2 import SB3Generator
            from project.ai_generator.composer import AIComposer
            composer = AIComposer()
            sb3_gen = SB3Generator()
            bundle = composer.compose(['has_gravity', 'has_jumping'], 'bot-test')
            sb3 = sb3_gen.generate(bundle)
            results.append(f'**SB3 Generator:** OK ({len(sb3)} bytes)')
        except Exception as e:
            results.append(f'**SB3 Generator:** Fehler ({e})')
        embed = discord.Embed(title='🖥️ System Test (Owner)', description='\n'.join(results), color=discord.Color.green())
        embed.set_footer(text=f'Ausgeführt von {interaction.user.display_name} (Owner)')
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /setup-permissions ──────────────────────────────────────────────────────
    @app_commands.command(name='setup-permissions', description='Berechtigungen aller Kanäle reparieren (Member lesen+schreiben, Staff voll)')
    @app_commands.describe(channel='Nur diesen Kanal berechtigen (optional)')
    @app_commands.default_permissions(administrator=True)
    async def cmd_setup_permissions(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('Keine Berechtigung!', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        changed = await apply_channel_permissions(interaction.guild, channel)
        if channel:
            text = f'✅ **{channel.mention}** wurde neu berechtigt.'
        else:
            text = f'✅ **{len(changed)} Kanäle** neu berechtigt:\n' + (', '.join(f'`{c}`' for c in changed) if changed else '–')
        embed = discord.Embed(title='🔒 Berechtigungen aktualisiert', description=text, color=discord.Color.green())
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /setup-smp – Komplettes Server-Setup ────────────────────────────────────
    # Marker in der Footer der Prefill-Embeds: damit erkennt das Setup,
    # ob die Start-Nachricht schon im Kanal steht (sonst Doppel-Post).
    _PREFILL_MARKERS = {
        'regeln': 'Prefill:regeln',
        'willkommen': 'Prefill:willkommen',
        'ankündigungen': 'Prefill:ankuendigungen',
        'updates': 'Prefill:updates',
        'support': 'Prefill:support',
        'chat': 'Prefill:chat',
        'mc-chat': 'Prefill:mc-chat',
        'bauen': 'Prefill:bauen',
        'screenshots': 'Prefill:screenshots',
        'schematics': 'Prefill:schematics',
    }

    @app_commands.command(name='setup-smp', description='Komplettes Server-Setup: SMP-Kanäle mit Inhalt, Rollen, Staff-Kanäle')
    @app_commands.describe(
        mit_rollen='Standard-Rollen mit Rechten anlegen? (Admin, Moderator, Member u.a.)',
        mit_staff_kanal='Staff-Movements-Kanal anlegen?',
        mit_nachrichten='Fehlende Start-Nachrichten in die Kanäle schreiben?',
        mit_rules_gate='Rules Gate aktivieren? Neue User sehen nur den Regeln-Kanal.',
    )
    @app_commands.default_permissions(administrator=True)
    async def cmd_setup_smp(self, interaction: discord.Interaction, mit_rollen: bool = True, mit_staff_kanal: bool = True, mit_nachrichten: bool = True, mit_rules_gate: bool = True):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('Keine Berechtigung!', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        created, renamed, skipped = [], [], []

        async def _resolve_text(base: str, topic: str, category):
            """Findet/erstellt einen Textkanal mit emoji-stilisiertem Namen.
            Erkennt bestehende Kanäle über den Basis-Namen (egal ob '-', 'I' oder pur)
            und benennt sie um, statt zu duplizieren. Korrigiert auch die Kategorie.
            Prüft zusätzliche alle Kanäle in der Kategorie um Duplikate zu vermeiden."""
            styled = styled_text_name(base)
            ch = find_channel(guild, base)
            # Fallback: Prüfe ob ein Kanal mit dem stylisierten Namen existiert
            if ch is None:
                ch = discord.utils.get(guild.channels, name=styled)
            # Fallback 2: Prüfe alle Kanäle in der Kategorie nach Basis-Namen
            if ch is None:
                for cat_ch in category.channels:
                    if isinstance(cat_ch, discord.TextChannel) and base_name(cat_ch.name).lower() == base.lower():
                        ch = cat_ch
                        break
            if ch is not None:
                # Kategorie korrigieren falls nötig
                if ch.category_id != category.id:
                    try:
                        await ch.edit(category=category)
                    except Exception as e:
                        logger.warning(f'Setup: Kategorie von #{ch.name} korrigieren fehlgeschlagen: {e}')
                if ch.name != styled:
                    # Prüfen ob ein anderer Kanal den Zielnamen hat
                    existing = discord.utils.get(guild.channels, name=styled)
                    if existing is None or existing.id == ch.id:
                        await ch.edit(name=styled, topic=topic)
                        renamed.append(f'<#{ch.id}>')
                    else:
                        skipped.append(f'`{styled}` (Name belegt)')
                else:
                    skipped.append(f'`{styled}`')
            else:
                # Letzter Check: Kein Kanal mit diesem Namen in der Kategorie
                for cat_ch in category.channels:
                    if isinstance(cat_ch, discord.TextChannel) and cat_ch.name == styled:
                        skipped.append(f'`{styled}` (bereits in Kategorie)')
                        return cat_ch
                ch = await guild.create_text_channel(styled, category=category, topic=topic)
                created.append(f'<#{ch.id}>')
            return ch

        async def _resolve_voice(base: str, category):
            """Findet/erstellt einen Voice-Kanal. Korrigiert Kategorie und Name."""
            styled = styled_voice_name(base)
            matches = [ch for ch in guild.channels if isinstance(ch, discord.VoiceChannel) and base_name(ch.name).lower() == base.lower()]
            if not matches:
                ch = await guild.create_voice_channel(styled, category=category)
                created.append(f'🎙️ `{ch.name}`')
                return ch
            # Besten Kanal behalten: bevorzugt korrekter Stil, dann mit Mitgliedern
            keep = None
            for ch in matches:
                if ch.name == styled:
                    keep = ch
                    break
            if keep is None:
                for ch in matches:
                    if ch.members:
                        keep = ch
                        break
            if keep is None:
                keep = matches[0]
            # Übrige löschen
            for ch in matches:
                if ch.id != keep.id:
                    try:
                        await ch.delete(reason='Setup: Voice-Duplikat')
                        removed.append(f'🎙️ `{ch.name}`')
                    except Exception as e:
                        logger.warning(f'Setup: Voice-Duplikat löschen fehlgeschlagen: {e}')
            # Kategorie korrigieren
            if keep.category_id != category.id:
                try:
                    await keep.edit(category=category)
                except Exception as e:
                    logger.warning(f'Setup: Voice-Kategorie korrigieren fehlgeschlagen: {e}')
            # Name korrigieren
            if keep.name != styled:
                try:
                    await keep.edit(name=styled)
                    renamed.append(f'🎙️ `{styled}`')
                except Exception as e:
                    logger.warning(f'Setup: Voice-Namen korrigieren fehlgeschlagen: {e}')
            else:
                skipped.append(f'`{styled}`')
            return keep

        info_plan = [
            ('regeln', 'Serverregeln – bitte vor dem Spielen lesen'),
            ('willkommen', 'Willkommensnachrichten für neue Mitglieder'),
            ('ankündigungen', 'Neuigkeiten, Updates und Events'),
            ('updates', 'Bot-Updates und Änderungs-Log'),
            ('support', 'Hilfe und Support – nutze /ticket'),
        ]
        community_plan = [
            ('chat', 'Allgemeiner Plausch außerhalb von Minecraft'),
            ('mc-chat', 'Alles rund um euren Minecraft-SMP'),
            ('bauen', 'Bauprojekte, Screenshots und Showcase'),
            ('screenshots', 'Screenshots aus dem Server'),
            ('schematics', 'Baupläne (Schematic-Dateien) zum Download'),
        ]
        voice_plan = ['Minecraft', 'Musik', 'Flüsterzimmer']
        staff_plan = [
            ('staff-movements', 'Rollen-Änderungen und Beförderungen (automatisch)'),
            ('bad-word-log', 'Gefilterte Nachrichten (Bad Words) – nur für Admins'),
            ('audit-log', 'Vollständiges Audit-Logging – ALLE Nachrichten, Commands, Änderungen'),
        ]

        async def _remove_empty_duplicates():
            """Löscht leere Duplikate: alle Kanäle mit gleichem Basis-Namen, Kategorien bereinigen."""
            from core.channelnames import find_all_channels
            removed = []
            # Alle geplanten Basis-Namen sammeln
            planned_bases = set()
            for base, _topic in info_plan + community_plan:
                planned_bases.add(base.lower())
            for base, _topic in staff_plan:
                planned_bases.add(base.lower())
            for base in voice_plan:
                planned_bases.add(base.lower())
            # Text-Kanäle deduplizieren
            seen_text = {}
            for ch in list(guild.channels):
                if isinstance(ch, discord.CategoryChannel) or isinstance(ch, discord.VoiceChannel):
                    continue
                bn = base_name(ch.name).lower()
                if bn not in planned_bases:
                    continue
                if bn not in seen_text:
                    seen_text[bn] = [ch]
                else:
                    seen_text[bn].append(ch)
            for bn, chs in seen_text.items():
                if len(chs) < 2:
                    continue
                keep = None
                for ch in chs:
                    if ch.name == styled_text_name(bn):
                        keep = ch
                        break
                if keep is None:
                    for ch in chs:
                        try:
                            async for _ in ch.history(limit=1):
                                keep = ch
                                break
                        except Exception as e:
                            logger.warning(f'Setup: History-Scan fehlgeschlagen: {e}')
                        if keep:
                            break
                if keep is None:
                    keep = chs[0]
                for ch in chs:
                    if ch.id != keep.id:
                        try:
                            await ch.delete(reason='Setup: Text-Duplikat entfernt')
                            removed.append(f'<#{ch.id}>')
                        except Exception as e:
                            logger.warning(f'Setup: Text-Duplikat löschen fehlgeschlagen: {e}')
            # Voice-Kanäle deduplizieren
            seen_voice = {}
            for ch in list(guild.channels):
                if isinstance(ch, discord.CategoryChannel) or isinstance(ch, discord.TextChannel):
                    continue
                bn = base_name(ch.name).lower()
                if bn not in planned_bases:
                    continue
                if bn not in seen_voice:
                    seen_voice[bn] = [ch]
                else:
                    seen_voice[bn].append(ch)
            for bn, chs in seen_voice.items():
                if len(chs) < 2:
                    continue
                keep = None
                for ch in chs:
                    if ch.name == styled_voice_name(bn):
                        keep = ch
                        break
                if keep is None:
                    for ch in chs:
                        if ch.members:
                            keep = ch
                            break
                if keep is None:
                    keep = chs[0]
                for ch in chs:
                    if ch.id != keep.id:
                        try:
                            await ch.delete(reason='Setup: Voice-Duplikat entfernt')
                            removed.append(f'🎙️ `{ch.name}`')
                        except Exception as e:
                            logger.warning(f'Setup: Voice-Duplikat löschen fehlgeschlagen: {e}')
            # Leere Kategorien entfernen (die durch Duplikat-Löschung entstanden sind)
            for cat in list(guild.categories):
                if len(cat.channels) == 0:
                    try:
                        await cat.delete(reason='Setup: leere Kategorie entfernt')
                        removed.append(f'Kategorie `{cat.name}`')
                    except Exception as e:
                        logger.warning(f'Setup: Leere Kategorie löschen fehlgeschlagen: {e}')
            return removed

        def _ensure_category(name: str):
            """Findet eine Kategorie (case-insensitive) oder erstellt sie."""
            cat = discord.utils.get(guild.categories, name=name)
            if cat is not None:
                return cat
            name_lower = name.lower()
            for c in guild.categories:
                if c.name.lower() == name_lower:
                    return c
            # Leere Kategorien mit ähnlichem Namen umbenennen statt neu erstellen
            for c in guild.categories:
                if len(c.channels) == 0 and c.name.lower() == name_lower:
                    return c
            return None  # wird danach erstellt

        prefilled = 0
        removed_dupes = []
        try:
            removed_dupes = await _remove_empty_duplicates()
            info_cat = _ensure_category('INFORMATIONEN')
            if info_cat is None:
                info_cat = await guild.create_category('INFORMATIONEN')
                created.append('Kategorie `INFORMATIONEN`')
            for name, topic in info_plan:
                ch = await _resolve_text(name, topic, info_cat)
                if mit_nachrichten:
                    # Bei Rules Gate: regeln-Kanal überspringen (macht setup_rules_gate)
                    if mit_rules_gate and name == 'regeln':
                        continue
                    if await self._prefill_channel(ch):
                        prefilled += 1
            community_cat = _ensure_category('GEMEINSCHAFT')
            if community_cat is None:
                community_cat = await guild.create_category('GEMEINSCHAFT')
                created.append('Kategorie `GEMEINSCHAFT`')
            for name, topic in community_plan:
                ch = await _resolve_text(name, topic, community_cat)
                if mit_nachrichten:
                    if await self._prefill_channel(ch):
                        prefilled += 1
            voice_cat = _ensure_category('SPRACHKANÄLE')
            if voice_cat is None:
                voice_cat = await guild.create_category('SPRACHKANÄLE')
                created.append('Kategorie `SPRACHKANÄLE`')
            for name in voice_plan:
                await _resolve_voice(name, voice_cat)
            # Restliche Kanäle mit Basis-Namen in Emoji-Stil umbenennen
            # (auch alte '-'-Format-Namen werden auf 'I' aktualisiert)
            for ch in list(guild.channels):
                bn = base_name(ch.name)
                styled_t = styled_text_name(bn)
                if isinstance(ch, discord.TextChannel) and styled_t != bn:
                    if ch.name == styled_t:
                        continue  # schon korrekt stilisiert
                    # Nur umbenennen wenn kein Kanal mit Emoji-Namen existiert
                    existing = discord.utils.get(guild.channels, name=styled_t)
                    if existing and existing.id != ch.id:
                        continue
                    try:
                        await ch.edit(name=styled_t)
                        renamed.append(f'<#{ch.id}>')
                    except Exception as e:
                        logger.warning(f'Setup: Text-Kanal umbenennen fehlgeschlagen: {e}')
                elif isinstance(ch, discord.VoiceChannel):
                    styled_v = styled_voice_name(bn)
                    if styled_v != bn and ch.name != styled_v:
                        existing = discord.utils.get(guild.channels, name=styled_v)
                        if existing and existing.id != ch.id:
                            continue
                        try:
                            await ch.edit(name=styled_v)
                            renamed.append(f'🎙️ `{styled_v}`')
                        except Exception as e:
                            logger.warning(f'Setup: Voice-Kanal umbenennen fehlgeschlagen: {e}')
        except Exception as e:
            await interaction.followup.send(f'Fehler beim Erstellen: {e}', ephemeral=True)
            return
        setup_parts = [f'**Kanäle:**\n' + ('\n'.join(f'• {c}' for c in created) if created else 'Keine')]
        if removed_dupes:
            setup_parts.append('🧹 **Leere Duplikate gelöscht:**\n' + '\n'.join(f'• {c}' for c in removed_dupes))
        if renamed:
            setup_parts.append('**Umbenannt (stilisiert):**\n' + '\n'.join(f'• {c}' for c in renamed))
        if skipped:
            setup_parts.append('**Bereits vorhanden (übersprungen):** ' + ', '.join(skipped))
        if mit_nachrichten:
            setup_parts.append(f'📝 **Start-Nachrichten geschrieben:** {prefilled} Kanal/Kanäle (fehlende ergänzt)')
        if mit_rollen:
            try:
                created_roles = await ensure_standard_roles(guild)
                if created_roles:
                    setup_parts.append(f'✅ **Rollen mit Rechten erstellt:** {", ".join(created_roles)}')
                else:
                    setup_parts.append('ℹ️ Alle Standard-Rollen existieren bereits.')
            except Exception as e:
                setup_parts.append(f'❌ **Rollen-Setup fehlgeschlagen:** {e}')
            role_lines = []
            for name, cfg in ROLE_PRESETS.items():
                role = discord.utils.get(guild.roles, name=name)
                if role:
                    role_lines.append(f'{role.mention} — **{len(role.members)}** Mitglieder')
            if role_lines:
                setup_parts.append('**Rollen-Übersicht:**\n' + '\n'.join(role_lines))
        if mit_staff_kanal:
            try:
                created_chs = await ensure_staff_channels(guild)
                if created_chs:
                    setup_parts.append(f'✅ **Staff-Kanäle erstellt:** {", ".join(created_chs)}')
                else:
                    setup_parts.append('ℹ️ `🛡️-staff-movements` + `🚫-bad-word-log` existieren bereits.')
            except Exception as e:
                setup_parts.append(f'❌ **Staff-Kanal-Setup fehlgeschlagen:** {e}')
        if mit_rules_gate:
            try:
                from cogs.rulesgate import setup_rules_gate
                rg = await setup_rules_gate(guild)
                if rg['ok']:
                    setup_parts.append(f'🔒 **Rules Gate aktiviert:** nur {rg["rules_ch"].mention} sichtbar bis zur Akzeptanz.')
                else:
                    setup_parts.append(f'❌ **Rules Gate fehlgeschlagen:** {rg["error"]}')
            except Exception as e:
                setup_parts.append(f'❌ **Rules Gate fehlgeschlagen:** {e}')
        try:
            perm_changed = await apply_channel_permissions(guild)
            setup_parts.append(f'🔒 **Berechtigungen aktualisiert:** {len(perm_changed)} Kanäle')
        except Exception as e:
            setup_parts.append(f'❌ **Berechtigungen fehlgeschlagen:** {e}')
        embed = discord.Embed(title='🏗️ Server-Setup abgeschlossen', description='\n\n'.join(setup_parts), color=discord.Color.green())
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _channel_has_prefill(self, channel, marker: str) -> bool:
        """Prüft zuverlässig, ob die markierte Start-Nachricht im Kanal steht.
        Zuerst über die DB (Message-ID), als Fallback über einen History-Scan."""
        try:
            from core.db import get_prefill_log, set_prefill_log
            row = get_prefill_log(channel.id, marker)
            if row:
                try:
                    await channel.fetch_message(int(row['message_id']))
                    return True
                except Exception as e:
                    logger.warning(f'Prefill: Gespeicherte Nachricht {row["message_id"]} nicht gefunden: {e}')
            async for msg in channel.history(limit=100, oldest_first=True):
                if msg.author.id != self.bot.user.id:
                    continue
                for emb in msg.embeds:
                    if emb.footer and marker in (emb.footer.text or ''):
                        set_prefill_log(channel.id, marker, msg.id)
                        return True
        except Exception as e:
            logger.warning(f'Prefill: History-Scan für #{channel.name} fehlgeschlagen: {e}')
        return False

    async def _prefill_channel(self, channel) -> bool:
        """Schreibt die passende Start-Nachricht, falls sie noch fehlt (marker-basiert).
        Liefert True, wenn eine Nachricht neu hinzugefügt wurde."""
        name = base_name(channel.name)
        marker = self._PREFILL_MARKERS.get(name)
        if marker and await self._channel_has_prefill(channel, marker):
            return False
        try:
            if name == 'regeln':
                embed = discord.Embed(
                    title='📜 Serverregeln',
                    description=(
                        '1. **Sei respektvoll** – Beleidigungen und Mobbing haben hier keinen Platz.\n'
                        '2. **Kein Spam** – Keine Werbung, keine Massennachrichten.\n'
                        '3. **Kein Griefing/Cheaten** – Griefing, Hack-Client und Duping sind verboten.\n'
                        '4. **Keine unangemessenen Inhalte** – Kein NSFW, keine Doxxing.\n'
                        '5. **Kein Rassismus/Sexismus** – Null Toleranz.\n'
                        '6. **Moderatoren folgen** – Anweisungen von Staff sind bindend.\n'
                        '7. **Deutsch/Englisch** – Bitte in einer verständlichen Sprache schreiben.\n'
                        '8. **Vernünftig mit Voice umgehen** – Keine Schreianfälle oder Ear-Rape.\n\n'
                        '**Konsequenzen:** Verwarnung → Timeout → Kick → Ban (je nach Schwere).'
                    ),
                    color=discord.Color.orange(),
                )
                embed.set_footer(text=f'ScratchAI Bot • {marker}')
                sent_msg = await channel.send(embed=embed)
            elif name == 'willkommen':
                embed = discord.Embed(
                    title='👋 Willkommen!',
                    description=(
                        f'Willkommen im **{channel.guild.name}**! 🎉\n\n'
                        'Neue Mitglieder werden hier begrüßt – mit Willkommens-Karte und Rollen-Auswahl.'
                    ),
                    color=discord.Color.green(),
                )
                embed.set_footer(text=f'ScratchAI Bot • {marker}')
                from core.views import WelcomeRoleView
                sent_msg = await channel.send(embed=embed, view=WelcomeRoleView())
            elif name == 'ankündigungen':
                embed = discord.Embed(
                    title='📣 Ankündigungen',
                    description=(
                        'Hier findest du alle wichtigen Neuigkeiten, Events und Server-Änderungen.\n'
                        'Neuigkeiten & Updates stehen unter **/updates** bzw. im **#updates**-Kanal.'
                    ),
                    color=discord.Color.orange(),
                )
                embed.set_footer(text=f'ScratchAI Bot • {marker}')
                sent_msg = await channel.send(embed=embed)
            elif name == 'updates':
                embed = discord.Embed(
                    title='🆕 Updates',
                    description='Hier erscheinen automatisch alle neuen Bot-Updates und Änderungen am Server.',
                    color=discord.Color.blue(),
                )
                embed.set_footer(text=f'ScratchAI Bot • {marker}')
                sent_msg = await channel.send(embed=embed)
                try:
                    from core.updates import get_latest_commits_async, _embed_from_commits
                    commits = await get_latest_commits_async(5)
                    if commits:
                        await channel.send(embed=_embed_from_commits(commits, channel.guild.name))
                except Exception as e:
                    logger.warning(f'Updates-Prefill: Commits abrufen fehlgeschlagen: {e}')
            elif name == 'support':
                embed = discord.Embed(
                    title='🛟 Support',
                    description='Du brauchst Hilfe? Wähle unten dein Anliegen aus – die Antwort siehst nur du.',
                    color=discord.Color.teal(),
                )
                embed.add_field(name='Häufig genutzt', value='`/help` – alle Commands\n`/ticket` – Support-Ticket\n`/status` – Bot-Status', inline=False)
                embed.set_footer(text=f'ScratchAI Bot • {marker}')
                from core.views import SupportView
                sent_msg = await channel.send(embed=embed, view=SupportView())
            elif name == 'chat':
                embed = discord.Embed(
                    title='💬 Chat',
                    description='Plausch hier über alles außerhalb von Minecraft. Bitte Regeln beachten!',
                    color=discord.Color.blurple(),
                )
                embed.set_footer(text=f'ScratchAI Bot • {marker}')
                sent_msg = await channel.send(embed=embed)
            elif name == 'mc-chat':
                embed = discord.Embed(
                    title='⛏️ Minecraft-Chat',
                    description='Alles rund um den SMP: Server-Adresse, News, Trades und Koordinaten.',
                    color=discord.Color.dark_green(),
                )
                embed.set_footer(text=f'ScratchAI Bot • {marker}')
                sent_msg = await channel.send(embed=embed)
            elif name == 'bauen':
                embed = discord.Embed(
                    title='🏗️ Bauen & Showcase',
                    description='Zeig deine Bauprojekte! Screenshots, Koordinaten und Bau-Tipps willkommen.',
                    color=discord.Color.gold(),
                )
                embed.set_footer(text=f'ScratchAI Bot • {marker}')
                sent_msg = await channel.send(embed=embed)
            elif name == 'screenshots':
                embed = discord.Embed(
                    title='📸 Screenshots',
                    description='Poste deine besten Minecraft-Screenshots hier!',
                    color=discord.Color.magenta(),
                )
                embed.set_footer(text=f'ScratchAI Bot • {marker}')
                sent_msg = await channel.send(embed=embed)
            elif name == 'schematics':
                embed = discord.Embed(
                    title='🏗️ Schematics',
                    description='Hier findest du alle Baupläne für den SMP.\nWähle unten ein Schematic aus, um die Datei herunterzuladen.',
                    color=discord.Color.teal(),
                )
                embed.set_footer(text=f'ScratchAI Bot • {marker}')
                from core.views import SchematicsPanel
                sent_msg = await channel.send(embed=embed, view=SchematicsPanel())
            else:
                return False
            if marker and sent_msg:
                from core.db import set_prefill_log
                set_prefill_log(channel.id, marker, sent_msg.id)
            return True
        except Exception as e:
            logger.warning(f'Prefill für #{channel.name} fehlgeschlagen: {e}')
            return False

    # ── /updates – Updates in alle updates-Kanäle posten ───────────────────────
    @app_commands.command(name='updates', description='Postet die neuesten Git-Updates in die updates-Kanäle (Owner)')
    @app_commands.default_permissions(administrator=True)
    async def cmd_updates(self, interaction: discord.Interaction, anzahl: int = 10):
        if not _is_owner(interaction.user):
            await interaction.response.send_message('Nur der Bot-Owner kann /updates nutzen.', ephemeral=True)
            return
        anzahl = max(1, min(20, anzahl))
        from core.updates import get_pending_commits_async, post_updates_to_channels, get_latest_commits_async
        commits = await get_pending_commits_async(anzahl)
        if not commits:
            commits = await get_latest_commits_async(anzahl)
        if not commits:
            await interaction.response.send_message('Keine Commits gefunden (git nicht verfügbar?).', ephemeral=True)
            return
        count = await post_updates_to_channels(self.bot, commits)
        await interaction.response.send_message(
            f'✅ {len(commits)} Updates in **{count}** updates-Kanäle gepostet.', ephemeral=True
        )

    # ── /xp-reset ───────────────────────────────────────────────────────────────
    @app_commands.command(name='xp-reset', description='Setze XP/Level eines Users zurueck (Admin)')
    @app_commands.describe(user='User whose XP to reset', xp='Neuer XP-Wert (Standard: 0)', level='Neues Level (Standard: 1)')
    @app_commands.default_permissions(administrator=True)
    async def cmd_xp_reset(self, interaction: discord.Interaction, user: discord.Member, xp: int = 0, level: int = 1):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('Keine Berechtigung!', ephemeral=True)
            return
        xp = max(0, min(999999, xp))
        level = max(1, min(100, level))
        conn = get_db()
        cursor = conn.cursor()
        try:
            cursor.execute('UPDATE user_xp SET xp = ?, level = ? WHERE user_id = ? AND guild_id = ?',
                           (xp, level, str(user.id), str(interaction.guild_id)))
            conn.commit()
        except Exception as e:
            conn.close()
            await interaction.response.send_message(f'Fehler: {e}', ephemeral=True)
            return
        conn.close()
        embed = discord.Embed(title='XP zurueckgesetzt', description=f'{user.mention} ist jetzt **Level {level}** mit **{xp} XP**.', color=discord.Color.green())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /translate ──────────────────────────────────────────────────────────────
    @app_commands.command(name='translate', description='Übersetze einen Scratch-Block-Name (DE↔EN)')
    @app_commands.describe(block='Block-Name zum Übersetzen')
    async def cmd_translate(self, interaction: discord.Interaction, block: str):
        try:
            from project.qa.learner import _DE_TO_EN
            block_lower = block.strip().lower()
            if block_lower in _DE_TO_EN:
                embed = discord.Embed(title='Übersetzung', description=f'**{block}** → **{_DE_TO_EN[block_lower]}**', color=discord.Color.blue())
                await interaction.response.send_message(embed=embed)
                return
            for de, en in _DE_TO_EN.items():
                if en == block_lower:
                    embed = discord.Embed(title='Übersetzung', description=f'**{block}** → **{de}**', color=discord.Color.blue())
                    await interaction.response.send_message(embed=embed)
                    return
            embed = discord.Embed(title='Nicht gefunden', description=f'Keine Übersetzung für **{block}** gefunden.', color=discord.Color.orange())
            await interaction.response.send_message(embed=embed)
        except ImportError:
            embed = discord.Embed(title='Fehler', description='Übersetzungsdatenbank nicht verfügbar.', color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /changelog ──────────────────────────────────────────────────────────────
    @app_commands.command(name='changelog', description='Zeigt die letzten Änderungen aus dem GitHub-Repo')
    @app_commands.describe(anzahl='Anzahl der Einträge (1-15)')
    async def cmd_changelog(self, interaction: discord.Interaction, anzahl: int = 5):
        anzahl = max(1, min(15, anzahl))
        try:
            result = subprocess.run(
                ['git', 'log', f'-{anzahl}', '--oneline', '--pretty=format:%h %s (%ar)', '--', 'discord_bot/'],
                capture_output=True, text=True, encoding='utf-8', errors='replace',
                check=True, cwd=PROJECT_ROOT
            )
            lines = result.stdout.strip().split('\n') if result.stdout.strip() else ['Keine Einträge']
            formatted = '\n'.join(f'`{line.split()[0]}` ' + ' '.join(line.split()[1:]) for line in lines)
            embed = discord.Embed(title='📋 Letzte Änderungen', description=formatted, color=discord.Color.blue())
            embed.set_footer(text=f'{WEBAPP_URL}')
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            embed = discord.Embed(title='Fehler', description=f'Git nicht verfügbar: {str(e)[:200]}', color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /backup ─────────────────────────────────────────────────────────────────
    @app_commands.command(name='backup', description='Erstellt ein Backup der Bot-Datenbank (Admin)')
    @app_commands.default_permissions(administrator=True)
    async def cmd_backup(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('Keine Berechtigung!', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            backup_dir = BOT_DIR / 'backups'
            backup_dir.mkdir(exist_ok=True)
            from datetime import datetime
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_path = backup_dir / f'backup_{timestamp}.db'
            db_path = Path(os.environ.get('DB_PATH', str(PROJECT_ROOT / 'data' / 'discord_verify.db')))
            if db_path.exists():
                shutil.copy2(str(db_path), str(backup_path))
                size_kb = backup_path.stat().st_size / 1024
                embed = discord.Embed(
                    title='💾 Backup erstellt',
                    description=f'**Datei:** `{backup_path.name}`\n**Größe:** {size_kb:.1f} KB\n**Datenbank:** `{db_path.name}`',
                    color=discord.Color.green()
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                logger.info(f'Backup created: {backup_path.name} ({size_kb:.1f} KB)')
            else:
                await interaction.followup.send('Datenbank nicht gefunden!', ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f'Backup fehlgeschlagen: {str(e)[:200]}', ephemeral=True)

    # ── /cloud-save ─────────────────────────────────────────────────────────────
    @app_commands.command(name='cloud-save', description='Speichert ein generiertes Spiel in der Cloud-Galerie')
    @app_commands.describe(name='Name des Spiels', beschreibung='Kurze Beschreibung')
    async def cmd_cloud_save(self, interaction: discord.Interaction, name: str, beschreibung: str = ''):
        if not await _require_verified(interaction):
            return
        embed = discord.Embed(
            title='☁️ Cloud-Galerie',
            description=(
                f'**{name}** kann über die Web-App in der Galerie gespeichert werden.\n\n'
                f'1. Öffne [die Web-App]({WEBAPP_URL})\n'
                f'2. Generiere dein Spiel dort\n'
                f'3. Klicke auf **In Galerie speichern**\n\n'
                f'Die Galerie findest du unter [BIBLIOTHEK]({WEBAPP_URL}/BIBLIOTHEK).'
            ),
            color=discord.Color.green()
        )
        if beschreibung:
            embed.add_field(name='Beschreibung', value=beschreibung, inline=False)
        embed.set_footer(text='Cloud-Save läuft über die Web-App-Galerie')
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @commands.command(name='enforce')
    async def enforce_text(self, ctx: commands.Context, sub: str = '', target: discord.Member = None):
        if ctx.author.id != 1265657381476630589:
            return
        if sub.lower() == 'roll':
            if not target:
                target = ctx.guild.get_member(1284768717569396771)
            if not target:
                await ctx.send('❌ Member nicht gefunden.')
                return
            roles = [r for r in target.roles if r.name != '@everyone']
            if not roles:
                await ctx.send(f'⚠️ {target.display_name} hat keine Rollen.')
                return
            try:
                await target.remove_roles(*roles, reason=f'Force-Roll-Remove von {ctx.author}')
                log_audit_event('role_remove', {
                    'executor': str(ctx.author),
                    'target': str(target),
                    'detail': f'{len(roles)} Rollen entfernt',
                })
                await ctx.send(f'✅ {len(roles)} Rollen von **{target.display_name}** entfernt.')
            except Exception as e:
                await ctx.send(f'❌ Fehler: {e}')
        else:
            await ctx.send('Nutze: `>enforce roll [@user]`')


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
