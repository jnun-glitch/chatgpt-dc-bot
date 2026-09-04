"""Persistente Discord-UI-Views: Tickets, Welcome-Rollen, Link-Confirm, Feedback."""
import json
import asyncio
from pathlib import Path
import discord
from core.config import WEBAPP_URL, BOT_SECRET
from core.db import (
    get_ticket_by_channel,
    close_ticket_db,
    get_schematic,
    list_schematic_categories,
    list_schematics,
)
from core.tickets import save_ticket_transcript
from core.ai import _get_ai_gen
from core.logging import logger


class TicketView(discord.ui.View):
    """Buttons für Tickets: Schließen, AI-Analyse, Als gelöst markieren (persistent via DB)."""
    def __init__(self, ticket_channel_id: int, ticket_number: int):
        super().__init__(timeout=None)
        self.ticket_channel_id = ticket_channel_id
        self.ticket_number = ticket_number

    def _lookup_ticket(self, channel_id):
        """Ticket-Info aus DB holen (damit View nach Restart funktioniert)."""
        ticket = get_ticket_by_channel(str(channel_id))
        if ticket:
            return ticket.get('ticket_number', 0), ticket.get('username', 'Unbekannt')
        return self.ticket_number, 'Unbekannt'

    @discord.ui.button(label='Ticket schließen', style=discord.ButtonStyle.danger, emoji='🔒', custom_id='ticket_close')
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_admin = interaction.user.guild_permissions.administrator
        support_role = discord.utils.get(interaction.guild.roles, name='Support')
        is_support = support_role in interaction.user.roles if support_role else False
        if not is_admin and not is_support:
            from core.db import format_msg
            await interaction.response.send_message(format_msg(interaction.guild_id, 'no_perm_msg'), ephemeral=True)
            return

        channel = interaction.guild.get_channel(interaction.channel_id)
        if not channel:
            await interaction.response.send_message('Channel nicht gefunden.', ephemeral=True)
            return

        transcript_path = await save_ticket_transcript(str(interaction.channel_id), interaction.guild)
        close_ticket_db(str(interaction.channel_id))

        from core.db import format_msg
        close_text = format_msg(interaction.guild_id, 'ticket_close',
                                name=interaction.user.display_name,
                                mention=interaction.user.mention)
        embed = discord.Embed(
            title='Ticket geschlossen',
            description=close_text + (f'\n📝 Transcript gespeichert.' if transcript_path else ''),
            color=discord.Color.greyple()
        )
        await interaction.response.send_message(embed=embed)
        await asyncio.sleep(2)
        await channel.delete(reason=f'Ticket closed by {interaction.user}')

    @discord.ui.button(label='AI-Analyse', style=discord.ButtonStyle.primary, emoji='🔍', custom_id='ticket_ai_analyze')
    async def ai_analyze(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        channel = interaction.guild.get_channel(interaction.channel_id)
        if not channel:
            await interaction.followup.send('Channel nicht gefunden.', ephemeral=True)
            return

        t_number, _ = self._lookup_ticket(interaction.channel_id)

        messages = []
        async for msg in channel.history(limit=50):
            if not msg.author.bot:
                messages.append(f'{msg.author.display_name}: {msg.content}')
        messages.reverse()

        betreff = channel.topic.split('|')[1].strip() if channel.topic and '|' in channel.topic else 'Kein Betreff'

        ersteller = interaction.user.display_name
        if channel.topic and 'Ticket von' in channel.topic:
            try:
                ersteller = channel.topic.split('Ticket von')[1].split('|')[0].strip()
            except (IndexError, ValueError):
                pass

        loading = discord.Embed(
            title='🔍 AI-Analyse läuft...',
            description='Die KI analysiert das Ticket. Einen Moment bitte.',
            color=discord.Color.gold()
        )
        loading_msg = await interaction.followup.send(embed=loading, ephemeral=True, wait=True)

        try:
            prompt = (
                f'Du bist ein Discord Support-Analyst.\n\n'
                f'Analysiere das Ticket:\n'
                f'Ticket Nummer: {t_number}\n'
                f'Erstellt von: {ersteller}\n'
                f'Betreff: {betreff}\n'
                f'Nachricht: {chr(10).join(messages) if messages else "Keine Nachrichten"}\n\n'
                f'Antworte auf Deutsch mit diesem Format:\n\n'
                f'Legitimitaet: Legitim / Verdacht / Spam\n'
                f'Kategorie: Bug / Feature Request / Nutzungshilfe / Sonstiges\n'
                f'Wahrscheinliche Ursache: kurz erklaeren\n'
                f'Empfehlung: Direkt loesen / Admin kontaktieren / User nach Details fragen\n\n'
                f'Maximal 150 Woerter.'
            )

            def call_ollama():
                payload = json.dumps({
                    'model': 'llama3.2',
                    'prompt': prompt,
                    'stream': False,
                    'options': {'temperature': 0.3, 'num_predict': 300}
                }).encode('utf-8')
                import urllib.request
                req = urllib.request.Request(
                    'http://127.0.0.1:11434/api/generate',
                    data=payload,
                    headers={'Content-Type': 'application/json'},
                    method='POST'
                )
                resp = urllib.request.urlopen(req, timeout=120)
                return json.loads(resp.read().decode('utf-8'))

            data = await asyncio.to_thread(call_ollama)
            ai_response = data.get('response', 'Keine Antwort von AI erhalten.')[:4096]

            embed = discord.Embed(
                title=f'AI-Analyse - Ticket #{t_number:04d}',
                description=ai_response,
                color=discord.Color.blue()
            )
            await loading_msg.edit(embed=embed)
            await channel.send(embed=embed)

        except Exception as e:
            logger.error(f'AI Analyse Fehler: {e}', exc_info=True)
            embed = discord.Embed(
                title='AI-Analyse fehlgeschlagen',
                description=f'Fehler: {str(e)[:200]}',
                color=discord.Color.red()
            )
            await channel.send(embed=embed)

    @discord.ui.button(label='Als gelöst markieren', style=discord.ButtonStyle.success, emoji='✅', custom_id='ticket_resolved')
    async def mark_resolved(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_admin = interaction.user.guild_permissions.administrator
        support_role = discord.utils.get(interaction.guild.roles, name='Support')
        is_support = support_role in interaction.user.roles if support_role else False
        if not is_admin and not is_support:
            from core.db import format_msg
            await interaction.response.send_message(format_msg(interaction.guild_id, 'no_perm_msg'), ephemeral=True)
            return

        channel = interaction.guild.get_channel(interaction.channel_id)
        if not channel:
            await interaction.response.send_message('Channel nicht gefunden.', ephemeral=True)
            return

        close_ticket_db(str(interaction.channel_id))

        from core.db import format_msg
        resolve_text = format_msg(interaction.guild_id, 'ticket_resolve',
                                  name=interaction.user.display_name,
                                  mention=interaction.user.mention)
        embed = discord.Embed(
            title='Ticket als gelöst markiert',
            description=resolve_text,
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)
        await asyncio.sleep(5)
        await channel.delete(reason=f'Ticket resolved by {interaction.user}')


class WelcomeRoleView(discord.ui.View):
    """Buttons für Rollen-Auswahl beim Join."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='📢 Neuigkeiten', style=discord.ButtonStyle.primary, custom_id='welcome_news')
    async def add_news(self, interaction: discord.Interaction, button: discord.ui.Button):
        role = discord.utils.get(interaction.guild.roles, name='News')
        if not role:
            await interaction.response.send_message('Rolle "News" existiert nicht.', ephemeral=True)
            return
        if role in interaction.user.roles:
            await interaction.user.remove_roles(role, reason='Rolle entfernt via Welcome')
            await interaction.response.send_message('📢 News-Rolle **entfernt**!', ephemeral=True)
        else:
            await interaction.user.add_roles(role, reason='Rolle via Welcome')
            await interaction.response.send_message('📢 News-Rolle **hinzugefügt**!', ephemeral=True)

    @discord.ui.button(label='🔧 Dev Updates', style=discord.ButtonStyle.success, custom_id='welcome_dev')
    async def add_dev(self, interaction: discord.Interaction, button: discord.ui.Button):
        role = discord.utils.get(interaction.guild.roles, name='Dev Updates')
        if not role:
            await interaction.response.send_message('Rolle "Dev Updates" existiert nicht.', ephemeral=True)
            return
        if role in interaction.user.roles:
            await interaction.user.remove_roles(role, reason='Rolle entfernt via Welcome')
            await interaction.response.send_message('🔧 Dev-Rolle **entfernt**!', ephemeral=True)
        else:
            await interaction.user.add_roles(role, reason='Rolle via Welcome')
            await interaction.response.send_message('🔧 Dev-Rolle **hinzugefügt**!', ephemeral=True)

    @discord.ui.button(label='🎮 Events', style=discord.ButtonStyle.secondary, custom_id='welcome_events')
    async def add_events(self, interaction: discord.Interaction, button: discord.ui.Button):
        role = discord.utils.get(interaction.guild.roles, name='Events')
        if not role:
            await interaction.response.send_message('Rolle "Events" existiert nicht.', ephemeral=True)
            return
        if role in interaction.user.roles:
            await interaction.user.remove_roles(role, reason='Rolle entfernt via Welcome')
            await interaction.response.send_message('🎮 Events-Rolle **entfernt**!', ephemeral=True)
        else:
            await interaction.user.add_roles(role, reason='Rolle via Welcome')
            await interaction.response.send_message('🎮 Events-Rolle **hinzugefügt**!', ephemeral=True)


class RulesGateView(discord.ui.View):
    """Button zum Akzeptieren der Serverregeln (Rules Gate)."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='✅ Regeln akzeptieren', style=discord.ButtonStyle.success, custom_id='rules_gate_accept')
    async def accept_rules(self, interaction: discord.Interaction, button: discord.ui.Button):
        from core.db import get_rules_gate
        gate = get_rules_gate(interaction.guild_id)
        if not gate or not gate.get('enabled'):
            await interaction.response.send_message('Das Rules Gate ist auf diesem Server deaktiviert.', ephemeral=True)
            return

        member_role = None
        if gate.get('member_role_id'):
            member_role = interaction.guild.get_role(int(gate['member_role_id']))
        if member_role is None:
            member_role = discord.utils.get(interaction.guild.roles, name='Member')
        if member_role is None:
            await interaction.response.send_message('Member-Rolle nicht gefunden. Bitte Admin kontaktieren.', ephemeral=True)
            return

        if member_role in interaction.user.roles:
            await interaction.response.send_message('Du bist bereits **Member**!', ephemeral=True)
            return

        # Selbst-Heilung: Bot-Rolle über die Member-Rolle schieben (falls nötig)
        try:
            from core.roles import ensure_bot_role_hierarchy
            await ensure_bot_role_hierarchy(interaction.guild)
        except Exception:
            pass

        try:
            await interaction.user.add_roles(member_role, reason='Regeln akzeptiert (Rules Gate)')
            embed = discord.Embed(
                title='✅ Regeln akzeptiert!',
                description=f'Willkommen, {interaction.user.mention}! Du hast jetzt die Rolle **{member_role.name}** und siehst alle Kanäle.',
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            logger.info(f'Rules Gate: {interaction.user} akzeptierte Regeln in {interaction.guild.name}')
        except Exception as e:
            logger.warning(f'Rules Gate Rollenvergabe fehlgeschlagen: {e}')
            if isinstance(e, discord.Forbidden):
                await interaction.response.send_message(
                    'Die Rolle konnte nicht vergeben werden – die **Bot-Rolle steht zu tief**.\n'
                    'Bitte verschiebe die Bot-Rolle in den Server-Einstellungen **über** die Member-Rolle '
                    '(oder gib ihr `Rollen verwalten`), dann klappt es direkt wieder.',
                    ephemeral=True
                )
            else:
                await interaction.response.send_message('Rolle konnte nicht vergeben werden. Bitte Admin kontaktieren.', ephemeral=True)


class LinkConfirmView(discord.ui.View):
    """Ja/Nein Buttons für Discord Account-Linking."""
    def __init__(self, website_username: str):
        super().__init__(timeout=300)
        self.website_username = website_username

    @discord.ui.button(label='✅ Ja, verknüpfen', style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            def _api_call():
                import urllib.request
                api_url = f'{WEBAPP_URL}/api/discord/link-confirm'
                payload = json.dumps({
                    'website_username': self.website_username,
                    'discord_user_id': str(interaction.user.id),
                    'discord_username': str(interaction.user),
                    'accepted': True,
                }).encode('utf-8')
                req = urllib.request.Request(api_url, data=payload, headers={'Content-Type': 'application/json', 'X-Bot-Secret': BOT_SECRET})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return json.loads(resp.read())
            result = await asyncio.to_thread(_api_call)

            if result.get('valid'):
                embed = discord.Embed(
                    title='✅ Verknüpft!',
                    description=f'Du bist jetzt mit **{self.website_username}** auf der Website verbunden.',
                    color=discord.Color.green()
                )
            else:
                embed = discord.Embed(
                    title='Fehler',
                    description=result.get('error', 'Verknüpfung fehlgeschlagen.'),
                    color=discord.Color.red()
                )
        except Exception as e:
            logger.error(f'Link confirm API error: {e}')
            embed = discord.Embed(title='Fehler', description='Website nicht erreichbar.', color=discord.Color.red())

        await interaction.response.edit_message(embed=embed, view=None)

    @discord.ui.button(label='❌ Nein, ablehnen', style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            def _api_call():
                import urllib.request
                api_url = f'{WEBAPP_URL}/api/discord/link-confirm'
                payload = json.dumps({
                    'website_username': self.website_username,
                    'discord_user_id': str(interaction.user.id),
                    'discord_username': str(interaction.user),
                    'accepted': False,
                }).encode('utf-8')
                req = urllib.request.Request(api_url, data=payload, headers={'Content-Type': 'application/json', 'X-Bot-Secret': BOT_SECRET})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return json.loads(resp.read())
            await asyncio.to_thread(_api_call)
        except Exception as e:
            logger.error(f'Link reject API error: {e}')

        embed = discord.Embed(
            title='❌ Abgelehnt',
            description='Die Verknüpfung wurde abgelehnt.',
            color=discord.Color.greyple()
        )
        await interaction.response.edit_message(embed=embed, view=None)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class FeedbackView(discord.ui.View):
    def __init__(self, session_id: str, features: list):
        super().__init__(timeout=120)
        self.session_id = session_id
        self.features = features
        self.responded = False

    @discord.ui.button(label='👍 Gut', style=discord.ButtonStyle.success)
    async def thumbs_up(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.responded:
            await interaction.response.send_message('Bereits bewertet!', ephemeral=True)
            return
        self.responded = True
        gen = _get_ai_gen()
        if gen and hasattr(gen, 'brain') and gen.brain:
            gen.brain.record_game_feedback(self.session_id, self.features, True)
        embed = discord.Embed(title='Feedback gespeichert', description='Danke! Das hilft der AI, bessere Spiele zu machen.', color=discord.Color.green())
        await interaction.response.edit_message(embed=interaction.message.embeds[0], view=None)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label='👎 Schlecht', style=discord.ButtonStyle.danger)
    async def thumbs_down(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.responded:
            await interaction.response.send_message('Bereits bewertet!', ephemeral=True)
            return
        self.responded = True
        gen = _get_ai_gen()
        if gen and hasattr(gen, 'brain') and gen.brain:
            gen.brain.record_game_feedback(self.session_id, self.features, False)
        embed = discord.Embed(title='Feedback gespeichert', description='Danke! Die AI wird es beim nächsten Mal besser machen.', color=discord.Color.orange())
        await interaction.response.edit_message(embed=interaction.message.embeds[0], view=None)
        await interaction.followup.send(embed=embed, ephemeral=True)


# Gemerkte Kategorie pro Panel-Nachricht (Message-ID -> Kategorie), damit Refresh
# und Download die aktive Filterauswahl behalten (Message hat kein .view-Attribut).
_panel_categories: dict = {}
_MAX_PANEL_CATEGORIES = 500


def _remember_panel_category(message_id, category):
    """Speichert die Kategorie einer Panel-Nachricht (gedeckelt gegen Memory-Leak)."""
    _panel_categories[message_id] = category
    if len(_panel_categories) > _MAX_PANEL_CATEGORIES:
        _panel_categories.pop(next(iter(_panel_categories)))


def _build_panel_embed(category=None):
    """Baut das Embed für das Schematics-Panel (kategoriefiltert oder alle)."""
    if category:
        schems = list_schematics(500, category=category)
        embed = discord.Embed(
            title=f'🏗️ {category}',
            description=f'Wähle ein Schematic aus der Kategorie **{category}**.',
            color=discord.Color.teal(),
        )
        if schems:
            embed.set_footer(text=f'{len(schems)} Schematic{"s" if len(schems) != 1 else ""} gefunden')
        else:
            embed.set_footer(text=f'Keine Schematics in „{category}"')
    else:
        cats = list_schematic_categories()
        total = sum(c['count'] for c in cats)
        embed = discord.Embed(
            title='🏗️ Schematics-Bibliothek',
            description='Wähle zuerst eine Kategorie (oder „Alle Kategorien"), dann ein Schematic aus dem zweiten Dropdown.',
            color=discord.Color.teal(),
        )
        if total:
            embed.set_footer(text=f'{total} Schematic{"s" if total != 1 else ""} · {len(cats)} Kategorien')
        else:
            embed.set_footer(text='Noch keine Schematics – Owner: /schematics add')
    return embed


async def _send_schematic_files(interaction: discord.Interaction, files: list) -> int:
    """Sendet Dateien best-effort in Batches (max. 10 pro Nachricht, große Dateien einzeln)."""
    limit = int(getattr(interaction, 'filesize_limit', 0) or 0) or (25 * 1024 * 1024)
    batches = []
    current = []
    for f in files:
        try:
            big = f.stat().st_size >= limit
        except OSError:
            big = True
        if big:
            if current:
                batches.append(current)
                current = []
            batches.append([f])
        else:
            current.append(f)
            if len(current) >= 10:
                batches.append(current)
                current = []
    if current:
        batches.append(current)
    sent = 0
    for batch in batches:
        try:
            atts = [discord.File(str(f), filename=f.name) for f in batch]
            await interaction.followup.send(files=atts, ephemeral=True)
            sent += len(batch)
        except Exception as e:
            names = ', '.join(f'`{f.name}`' for f in batch[:5])
            try:
                await interaction.followup.send(f'❌ Konnte {names} nicht senden: {e}', ephemeral=True)
            except Exception:
                pass
    return sent


class SchematicFilePicker(discord.ui.View):
    """Einzelauswahl von Dateien aus einem entpackten Ordner (nicht persistent)."""
    PAGE_SIZE = 25

    def __init__(self, files: list, page: int = 0):
        super().__init__(timeout=300)
        self.files = list(files)
        self.page = page
        total_pages = max(1, (len(self.files) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        page_files = self.files[page * self.PAGE_SIZE:(page + 1) * self.PAGE_SIZE]
        self.add_item(SchematicFileSelect(page_files, page, total_pages))
        if total_pages > 1:
            if page > 0:
                self.add_item(SchematicPageButton('◀', page - 1))
            if page + 1 < total_pages:
                self.add_item(SchematicPageButton('▶', page + 1))
        if self.files:
            self.add_item(SchematicSendAllButton())
        self.add_item(SchematicCloseButton())


class SchematicFileSelect(discord.ui.Select):
    def __init__(self, files, page, total_pages):
        options = []
        for i, f in enumerate(files):
            desc = f'{f.stat().st_size // 1024} KB' if f.exists() else 'fehlt'
            options.append(discord.SelectOption(label=f.name[:90], description=desc[:100], value=str(i)))
        super().__init__(
            placeholder=f'Dateien wählen (Seite {page + 1}/{total_pages})…',
            min_values=1,
            max_values=max(1, len(options)),
            options=options,
        )
        self.disabled = not options

    async def callback(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.HTTPException:
            pass
        try:
            view = self.view
            page_files = view.files[view.page * view.PAGE_SIZE:(view.page + 1) * view.PAGE_SIZE]
            selected = [page_files[int(v)] for v in self.values if v.isdigit()]
            await _send_schematic_files(interaction, selected)
            await interaction.edit_original_response(view=SchematicFilePicker(view.files, view.page))
        except Exception as e:
            try:
                await interaction.followup.send(f'❌ Fehler: {e}', ephemeral=True)
            except Exception:
                pass


class SchematicPageButton(discord.ui.Button):
    def __init__(self, label, page):
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self.page = page

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        await interaction.response.edit_message(view=SchematicFilePicker(view.files, self.page))


class SchematicSendAllButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label='Alle senden', style=discord.ButtonStyle.primary, emoji='📦')

    async def callback(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.HTTPException:
            pass
        await _send_schematic_files(interaction, self.view.files)
        try:
            view = self.view
            await interaction.edit_original_response(view=SchematicFilePicker(view.files, view.page))
        except Exception:
            pass


class SchematicCloseButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label='Schließen', style=discord.ButtonStyle.secondary, emoji='❌')

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(view=None)


class SchematicsCategorySelect(discord.ui.Select):
    """Kategorie-Auswahl: filtert das Schematic-Dropdown (persistent)."""
    def __init__(self, current_category=None):
        cats = list_schematic_categories()
        total = sum(c['count'] for c in cats)
        options = [discord.SelectOption(
            label='📂 Alle Kategorien', value='__all__',
            description=f'{total} Schematics',
            default=(current_category in (None, '')),
        )]
        for c in cats:
            options.append(discord.SelectOption(
                label=c['name'][:80],
                value=c['name'][:80],
                description=f'{c["count"]} Schematics',
                default=(c['name'] == current_category),
            ))
        super().__init__(
            custom_id='schematics_cat_select',
            placeholder='1. Kategorie wählen…',
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        value = self.values[0]
        category = None if value == '__all__' else value
        _remember_panel_category(interaction.message.id, category)
        embed = _build_panel_embed(category)
        await interaction.response.edit_message(embed=embed, view=SchematicsPanel(category=category))


class SchematicsSelect(discord.ui.Select):
    """Dropdown zum Auswählen & Herunterladen eines Schematics (persistent)."""
    def __init__(self, options, category=None):
        placeholder = f'Wähle ein Schematic aus „{category}"…' if category else 'Wähle ein Schematic…'
        super().__init__(
            custom_id='schematics_select',
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=options or [discord.SelectOption(label='Keine Schematics', value='none', description='Füge zuerst welche hinzu.')],
        )
        self.disabled = not options

    async def callback(self, interaction: discord.Interaction):
        # Früh defern: verhindert den 3s-Timeout, falls große Ordner länger brauchen
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.HTTPException:
            pass
        try:
            if not self.values or self.values[0] == 'none':
                await interaction.followup.send('Es gibt noch keine Schematics.', ephemeral=True)
                return
            schema = get_schematic(int(self.values[0]))
            if not schema:
                await interaction.followup.send('Schematic nicht gefunden.', ephemeral=True)
                return
            path = Path(schema['file_path'])
            if not path.exists():
                await interaction.followup.send('Die Datei ist auf dem Server nicht mehr vorhanden.', ephemeral=True)
                return
            size_kb = int(schema.get('file_size', 0) or 0) // 1024
            embed = discord.Embed(title=f"🏗️ {schema['name']}", color=discord.Color.teal())
            if schema.get('description'):
                embed.add_field(name='Beschreibung', value=schema['description'][:1000], inline=False)
            embed.add_field(name='Größe', value=f'{size_kb} KB', inline=True)
            if schema.get('uploaded_by'):
                embed.add_field(name='Von', value=schema['uploaded_by'], inline=True)
            # Ordner: Dateien einzeln auswählbar machen (kein Massenversand)
            if path.is_dir():
                files = sorted([f for f in path.rglob('*') if f.is_file()], key=lambda p: p.name.lower())
                if not files:
                    await interaction.followup.send('Der Ordner enthält keine Dateien.', ephemeral=True)
                    return
                embed.add_field(name='📁 Dateien', value=f'{len(files)} Dateien', inline=True)
                await interaction.followup.send(embed=embed, view=SchematicFilePicker(files), ephemeral=True)
            else:
                await interaction.followup.send(
                    embed=embed,
                    file=discord.File(str(path), filename=path.name),
                    ephemeral=True
                )
            # Panel aktualisieren
            try:
                category = _panel_categories.get(interaction.message.id, None)
                embed = _build_panel_embed(category)
                await interaction.message.edit(embed=embed, view=SchematicsPanel(category=category))
            except Exception:
                pass
        except Exception as e:
            try:
                await interaction.followup.send(f'❌ Fehler beim Laden des Schematics: {e}', ephemeral=True)
            except Exception:
                pass


class SchematicsRefreshButton(discord.ui.Button):
    def __init__(self):
        super().__init__(style=discord.ButtonStyle.secondary, label='Aktualisieren', emoji='🔄', custom_id='schematics_refresh')

    async def callback(self, interaction: discord.Interaction):
        try:
            category = _panel_categories.get(interaction.message.id, None)
            embed = _build_panel_embed(category)
            await interaction.response.edit_message(embed=embed, view=SchematicsPanel(category=category))
        except Exception:
            try:
                await interaction.response.defer()
            except Exception:
                pass


class SchematicsPanel(discord.ui.View):
    """Interaktives Panel der Schematics-Bibliothek (persistent über Restarts)."""
    def __init__(self, category=None):
        super().__init__(timeout=None)
        self.category = category
        self.add_item(SchematicsCategorySelect(category))
        schems = list_schematics(25, category=category or '')
        options = [
            discord.SelectOption(
                label=s['name'][:80],
                description=(s.get('description') or '')[:90] if s.get('description') else f'{int(s.get("file_size", 0) or 0) // 1024} KB',
                value=str(s['id']),
            )
            for s in schems
        ]
        self.add_item(SchematicsSelect(options, category))
        self.add_item(SchematicsRefreshButton())


_SUPPORT_REPLIES = {
    'ticket': (
        '📩 **Support-Ticket**\n'
        'Erstelle ein Ticket mit `/ticket` und beschreibe dein Anliegen. '
        'Unser Team antwortet dir direkt im Ticket-Kanal.'
    ),
    'warn': (
        '🚫 **Warn / Ban / Timeout**\n'
        'Fragen zu Strafen? Erstelle ein Ticket mit `/ticket` (Betreff z.B. „Warn-Anfechtung") '
        'und unser Staff prüft deinen Fall.'
    ),
    'bug': (
        '🐛 **Bug melden**\n'
        'Nutze `/ticket` mit Betreff „Bug". Beschreibe Schritt für Schritt, was passiert ist – '
        'so können wir es schneller beheben.'
    ),
    'account': (
        '🔗 **Account / Verknüpfung**\n'
        'Probleme mit deinem Account oder der Website-Verknüpfung? '
        'Erstelle ein Ticket mit `/ticket` und wir helfen dir.'
    ),
    'general': (
        '💬 **Allgemeine Fragen**\n'
        'Fragen zur Community? Frag einfach in `#chat`, oder erstelle ein Ticket mit `/ticket`, '
        'wenn du Hilfe vom Team brauchst.'
    ),
}


class SupportSelect(discord.ui.Select):
    """Themen-Auswahl im Support-Kanal; Antwort ist nur für den Klickenden sichtbar."""
    def __init__(self):
        super().__init__(
            custom_id='support_select',
            placeholder='Wähle dein Anliegen…',
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label='🎫 Support-Ticket erstellen', value='ticket', description='Erstelle ein Ticket für dein Anliegen'),
                discord.SelectOption(label='🚫 Warn / Ban / Timeout', value='warn', description='Fragen zu Strafen auf dem Server'),
                discord.SelectOption(label='🐛 Bug / Fehler melden', value='bug', description='Technische Probleme oder Fehler'),
                discord.SelectOption(label='🔗 Account / Verknüpfung', value='account', description='Probleme mit Account oder Website-Link'),
                discord.SelectOption(label='💬 Allgemeine Fragen', value='general', description='Alles andere'),
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        choice = self.values[0] if self.values else 'general'
        await interaction.response.send_message(_SUPPORT_REPLIES.get(choice, _SUPPORT_REPLIES['general']), ephemeral=True)


class SupportView(discord.ui.View):
    """Persistentes Auswahl-Panel für den Support-Kanal."""
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(SupportSelect())
