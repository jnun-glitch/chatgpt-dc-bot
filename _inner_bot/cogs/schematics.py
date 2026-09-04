"""Schematics: Bauplan-Bibliothek für den SMP (Owner kann Dateien hinzufügen)."""
import re
from pathlib import Path
import discord
from discord import app_commands
from discord.ext import commands
from core.config import PROJECT_ROOT, _is_owner
from core.db import (
    add_schematic,
    get_schematic_by_name,
    list_schematic_categories,
    list_schematics,
    remove_schematic,
    update_schematic_category,
)
from core.channelnames import find_channel
from core.views import SchematicsPanel, _build_panel_embed
from core.logging import logger

SCHEMATICS_DIR = PROJECT_ROOT / 'data' / 'schematics'
ALLOWED_EXTENSIONS = ('.schem', '.schematic', '.litematic', '.zip')
MAX_FILE_MB = 25


def _sanitize_filename(name: str) -> str:
    cleaned = re.sub(r'[^\w\-äöüß]+', '_', name.strip(), flags=re.IGNORECASE)
    return cleaned.strip(' _') or 'schematic'


def _size_text(size: int) -> str:
    if size >= 1024 * 1024:
        return f'{size / (1024 * 1024):.1f} MB'
    return f'{size // 1024} KB'


def _safe_extract(zip_path: Path, extract_dir: Path) -> list[str]:
    """Entpackt eine Zip sicher: verhindert Path-Traversal (Zip-Slip), nur flache Dateien."""
    import zipfile
    import shutil
    extracted = []
    with zipfile.ZipFile(zip_path, 'r') as zf:
        for member in zf.namelist():
            if member.endswith('/'):
                continue
            name = Path(member).name
            if not name or name in ('.', '..') or '..' in name or name.startswith('/'):
                raise ValueError(f'Ungültiger Dateiname in Zip: {member!r}')
            extracted.append(name)
        extract_dir.mkdir(parents=True, exist_ok=True)
        for member in extracted:
            dst = extract_dir / Path(member).name
            with zf.open(member) as src, dst.open('wb') as out:
                shutil.copyfileobj(src, out)
    return extracted


class SchematicsCog(commands.Cog):
    """Schematic-Bibliothek: Owner fügt Dateien hinzu, alle laden sie per Dropdown."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    group = app_commands.Group(name='schematics', description='Schematic-Bibliothek für den SMP')

    async def _require_manager(self, interaction: discord.Interaction):
        """Erlaubt Bot-Owner, Server-Owner und Admins (der Owner soll immer können)."""
        allowed = (
            _is_owner(interaction.user)
            or interaction.user.guild_permissions.administrator
            or (interaction.guild is not None and interaction.user.id == interaction.guild.owner_id)
        )
        if not allowed:
            await interaction.response.send_message('Nur der Owner oder Admins können diese Aktion ausführen.', ephemeral=True)
            return False
        return True

    @staticmethod
    def _upload_limit(interaction: discord.Interaction) -> int:
        """Echtes Attachment-Limit des Servers (Fallback 25 MB)."""
        return int(getattr(interaction, 'filesize_limit', 0) or 0) or (MAX_FILE_MB * 1024 * 1024)

    async def _unpack_zip(self, interaction: discord.Interaction, attachment: discord.Attachment, name: str,
                          kategorie: str = '', beschreibung: str = '', title: str = '✅ Zip entpackt') -> bool:
        """Speichert + entpackt eine Zip direkt in die Bibliothek. Sendet Fehler ephemeral."""
        suffix = Path(attachment.filename or '').suffix.lower()
        if suffix != '.zip':
            await interaction.response.send_message(f'Nur `.zip`-Dateien erlaubt. Du hast `{suffix or "?"}` hochgeladen.', ephemeral=True)
            return False
        if attachment.size > self._upload_limit(interaction):
            limit_mb = self._upload_limit(interaction) // (1024 * 1024)
            await interaction.response.send_message(f'Die Datei ist zu groß (max. {limit_mb} MB laut Server).', ephemeral=True)
            return False
        if not name.strip():
            name = Path(attachment.filename).stem
        name = name.strip()
        if len(name) > 80:
            name = name[:80]
        if get_schematic_by_name(name):
            await interaction.response.send_message(f'Ein Schematic namens **{name}** existiert bereits.', ephemeral=True)
            return False
        try:
            SCHEMATICS_DIR.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            await interaction.response.send_message(f'Speicherordner konnte nicht angelegt werden: {e}', ephemeral=True)
            return False
        zip_path = SCHEMATICS_DIR / f'{_sanitize_filename(name)}.zip'
        try:
            await attachment.save(zip_path)
        except Exception as e:
            await interaction.response.send_message(f'Zip konnte nicht gespeichert werden: {e}', ephemeral=True)
            return False
        import zipfile
        import shutil
        extract_dir = SCHEMATICS_DIR / _sanitize_filename(name)
        extracted = []
        try:
            extracted = _safe_extract(zip_path, extract_dir)
            zip_path.unlink()  # Zip nach Entpacken löschen
        except zipfile.BadZipFile:
            zip_path.unlink()
            shutil.rmtree(extract_dir, ignore_errors=True)
            await interaction.response.send_message('Die Datei ist keine gültige Zip-Datei.', ephemeral=True)
            return False
        except Exception as e:
            zip_path.unlink()
            shutil.rmtree(extract_dir, ignore_errors=True)
            await interaction.response.send_message(f'Entpacken fehlgeschlagen: {e}', ephemeral=True)
            return False
        if not add_schematic(name, beschreibung, str(extract_dir), attachment.size, str(interaction.user), kategorie.strip()):
            shutil.rmtree(extract_dir, ignore_errors=True)
            await interaction.response.send_message('Datenbank-Eintrag fehlgeschlagen.', ephemeral=True)
            return False
        embed = discord.Embed(
            title=title,
            description=f'**{name}** — {len(extracted)} Dateien entpackt.',
            color=discord.Color.green(),
        )
        if kategorie.strip():
            embed.add_field(name='Kategorie', value=kategorie.strip(), inline=True)
        file_list = '\n'.join(f'• `{f}`' for f in extracted[:15])
        if len(extracted) > 15:
            file_list += f'\n• ... und {len(extracted) - 15} weitere'
        embed.add_field(name='Dateien', value=file_list or '–', inline=False)
        embed.add_field(name='Speicherort', value=f'`{extract_dir.name}/`', inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return True

    @group.command(name='add', description='Füge eine Schematic-Datei zur Bibliothek hinzu (Owner)')
    @app_commands.describe(name='Name (optional, sonst Dateiname)', kategorie='Kategorie (optional)', beschreibung='Kurze Beschreibung', datei='Die Datei (.schem, .schematic, .litematic, .zip)')
    async def add(self, interaction: discord.Interaction, datei: discord.Attachment, name: str = '', kategorie: str = '', beschreibung: str = ''):
        if not await self._require_manager(interaction):
            return
        if datei is None:
            await interaction.response.send_message('Bitte eine Datei anhängen.', ephemeral=True)
            return
        suffix = Path(datei.filename or '').suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            await interaction.response.send_message(
                f'Ungültiges Dateiformat `{suffix or "?"}`. Erlaubt: ' + ', '.join(f'`{e}`' for e in ALLOWED_EXTENSIONS),
                ephemeral=True,
            )
            return
        if datei.size > self._upload_limit(interaction):
            limit_mb = self._upload_limit(interaction) // (1024 * 1024)
            await interaction.response.send_message(f'Die Datei ist zu groß (max. {limit_mb} MB laut Server).', ephemeral=True)
            return
        # Name: wenn leer, Dateiname ohne Endung nehmen
        if not name.strip():
            name = Path(datei.filename).stem
        name = name.strip()
        if len(name) > 80:
            name = name[:80]
        if get_schematic_by_name(name):
            await interaction.response.send_message(f'Ein Schematic namens **{name}** existiert bereits.', ephemeral=True)
            return
        try:
            SCHEMATICS_DIR.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            await interaction.response.send_message(f'Speicherordner konnte nicht angelegt werden: {e}', ephemeral=True)
            return
        filename = f'{_sanitize_filename(name)}{suffix}'
        target = SCHEMATICS_DIR / filename
        try:
            await datei.save(target)
        except Exception as e:
            logger.error(f'Schematic-Save fehlgeschlagen: {e}')
            await interaction.response.send_message(f'Datei konnte nicht gespeichert werden: {e}', ephemeral=True)
            return
        # Bei Zip: Dateien entpacken
        extracted = []
        if suffix == '.zip':
            import zipfile
            extract_dir = SCHEMATICS_DIR / _sanitize_filename(name)
            try:
                extracted = _safe_extract(target, extract_dir)
                # Zip löschen nach Entpacken
                target.unlink()
                file_count = len(extracted)
                size_text = f'{file_count} Dateien entpackt'
            except Exception as e:
                logger.error(f'Zip-Entpacken fehlgeschlagen: {e}')
                try:
                    target.unlink()
                    import shutil
                    shutil.rmtree(extract_dir, ignore_errors=True)
                except Exception:
                    pass
                await interaction.response.send_message(f'Zip konnte nicht entpackt werden: {e}', ephemeral=True)
                return
        else:
            size_text = _size_text(datei.size)
        if not add_schematic(name, beschreibung, str(target) if suffix != '.zip' else str(extract_dir), datei.size, str(interaction.user), kategorie.strip()):
            try:
                target.unlink()
            except Exception:
                pass
            await interaction.response.send_message('Datenbank-Eintrag fehlgeschlagen.', ephemeral=True)
            return
        embed = discord.Embed(
            title='✅ Schematic hinzugefügt',
            description=f'**{name}** ({size_text}) wurde zur Bibliothek hinzugefügt.',
            color=discord.Color.green(),
        )
        if extracted and suffix == '.zip':
            file_list = '\n'.join(f'• `{f}`' for f in extracted[:10])
            if len(extracted) > 10:
                file_list += f'\n• ... und {len(extracted) - 10} weitere'
            embed.add_field(name='Dateien', value=file_list, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @group.command(name='folder-add', description='Lade einen ganzen Ordner als Zip hoch (wird automatisch entpackt)')
    @app_commands.describe(name='Name (optional, sonst Dateiname)', kategorie='Kategorie (optional)', beschreibung='Kurze Beschreibung', zip_datei='Die .zip-Datei mit deinen Schematics')
    async def folder_add(self, interaction: discord.Interaction, zip_datei: discord.Attachment, name: str = '', kategorie: str = '', beschreibung: str = ''):
        if not await self._require_manager(interaction):
            return
        await self._unpack_zip(interaction, zip_datei, name, kategorie, beschreibung, title='✅ Ordner hinzugefügt')

    @group.command(name='remove', description='Entferne ein Schematic aus der Bibliothek (Owner)')
    @app_commands.describe(name='Name des Schematics')
    async def remove(self, interaction: discord.Interaction, name: str):
        if not await self._require_manager(interaction):
            return
        schema = get_schematic_by_name(name)
        if not schema:
            await interaction.response.send_message(f'**{name}** wurde nicht gefunden.', ephemeral=True)
            return
        try:
            p = Path(schema['file_path'])
            if p.is_dir():
                import shutil
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink()
        except Exception:
            pass
        remove_schematic(schema['id'])
        embed = discord.Embed(title='🗑️ Schematic entfernt', description=f'**{schema["name"]}** wurde gelöscht.', color=discord.Color.orange())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @remove.autocomplete('name')
    async def remove_autocomplete(self, interaction: discord.Interaction, current: str):
        schems = list_schematics(25)
        return [
            app_commands.Choice(name=s['name'][:80], value=s['name'])
            for s in schems
            if current.lower() in s['name'].lower()
        ][:25]

    @app_commands.command(name='unpack', description='Entpacke eine Zip direkt in die Schematics-Bibliothek')
    @app_commands.describe(zip_datei='Die .zip-Datei', name='Name (optional, sonst Dateiname)', kategorie='Kategorie (optional)')
    async def unpack(self, interaction: discord.Interaction, zip_datei: discord.Attachment, name: str = '', kategorie: str = ''):
        if not await self._require_manager(interaction):
            return
        if zip_datei is None:
            await interaction.response.send_message('Bitte eine .zip-Datei anhängen.', ephemeral=True)
            return
        await self._unpack_zip(interaction, zip_datei, name, kategorie)

    @unpack.autocomplete('kategorie')
    async def unpack_cat_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self._category_autocomplete(interaction, current)

    @group.command(name='list', description='Zeige alle Schematics in der Bibliothek')
    async def list_cmd(self, interaction: discord.Interaction):
        schems = list_schematics(100)
        if not schems:
            await interaction.response.send_message('📭 Die Bibliothek ist noch leer. Der Owner kann mit `/schematics add` Dateien hinzufügen.', ephemeral=True)
            return
        embed = discord.Embed(title='🏗️ Schematics-Bibliothek', color=discord.Color.teal())
        uncategorized = [s for s in schems if not s.get('category')]
        grouped = {}
        for s in schems:
            if s.get('category'):
                grouped.setdefault(s['category'], []).append(s)
        if grouped:
            for cat in sorted(grouped, key=str.lower):
                lines = []
                for s in grouped[cat][:6]:
                    size = _size_text(int(s.get('file_size', 0) or 0))
                    lines.append(f'• **{s["name"][:80]}** ({size})')
                if len(grouped[cat]) > 6:
                    lines.append(f'• ... und {len(grouped[cat]) - 6} weitere')
                lines.append(f'→ `/schematics category list`')
                embed.add_field(name=f'📂 {cat}', value='\n'.join(lines), inline=False)
        if uncategorized:
            lines = []
            for s in uncategorized[:6]:
                size = _size_text(int(s.get('file_size', 0) or 0))
                lines.append(f'• **{s["name"][:80]}** ({size})')
            if len(uncategorized) > 6:
                lines.append(f'• ... und {len(uncategorized) - 6} weitere')
            lines.append(f'→ Vergib Kategorien mit `/schematics category assign`')
            embed.add_field(name='🗃️ Ohne Kategorie', value='\n'.join(lines), inline=False)
        embed.set_footer(text=f'{len(schems)} Schematics · {len(grouped)} Kategorien')
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _category_autocomplete(self, interaction: discord.Interaction, current: str):
        cats = list_schematic_categories()
        return [
            app_commands.Choice(name=c['name'][:80], value=c['name'])
            for c in cats
            if current.lower() in c['name'].lower()
        ][:25]

    category = app_commands.Group(name='category', description='Schematics nach Kategorien verwalten')
    group.add_command(category)

    @category.command(name='list', description='Zeige alle Kategorien mit Anzahl')
    async def category_list(self, interaction: discord.Interaction):
        cats = list_schematic_categories()
        if not cats:
            await interaction.response.send_message('📂 Noch keine Kategorien vorhanden. Erstelle eine mit `/schematics category create`.', ephemeral=True)
            return
        embed = discord.Embed(title='📂 Schematics-Kategorien', color=discord.Color.teal())
        for c in cats:
            embed.add_field(name=c['name'][:90], value=f'{c["count"]} Schematics', inline=True)
        embed.set_footer(text=f'{sum(c["count"] for c in cats)} Schematics in Kategorien')
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @category.command(name='create', description='Erstelle eine neue Kategorie')
    @app_commands.describe(name='Name der Kategorie')
    async def category_create(self, interaction: discord.Interaction, name: str):
        if not await self._require_manager(interaction):
            return
        name = name.strip()
        if not name:
            await interaction.response.send_message('Bitte einen Namen angeben.', ephemeral=True)
            return
        if len(name) > 80:
            name = name[:80]
        for c in list_schematic_categories():
            if c['name'].lower() == name.lower():
                await interaction.response.send_message(f'Die Kategorie **{name}** existiert bereits.', ephemeral=True)
                return
        embed = discord.Embed(title='📂 Kategorie erstellt', description=f'**{name}** wurde angelegt.', color=discord.Color.green())
        embed.add_field(name='Tipp', value='Vergib sie mit `/schematics category assign`.', inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @category.command(name='rename', description='Benenne eine Kategorie um')
    @app_commands.describe(alt='Aktueller Name', neu='Neuer Name')
    async def category_rename(self, interaction: discord.Interaction, alt: str, neu: str):
        if not await self._require_manager(interaction):
            return
        alt = alt.strip()
        neu = neu.strip()
        if not alt or not neu:
            await interaction.response.send_message('Bitte alten und neuen Namen angeben.', ephemeral=True)
            return
        for c in list_schematic_categories():
            if c['name'].lower() == alt.lower():
                schems = list_schematics(500, category=c['name'])
                for s in schems:
                    update_schematic_category(s['id'], neu)
                embed = discord.Embed(title='📂 Kategorie umbenannt', description=f'**{alt}** → **{neu}**', color=discord.Color.green())
                embed.add_field(name='Betroffen', value=f'{len(schems)} Schematics', inline=False)
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
        await interaction.response.send_message(f'Die Kategorie **{alt}** wurde nicht gefunden.', ephemeral=True)

    @category.command(name='delete', description='Lösche eine Kategorie (Schematics bleiben erhalten)')
    @app_commands.describe(name='Name der Kategorie')
    async def category_delete(self, interaction: discord.Interaction, name: str):
        if not await self._require_manager(interaction):
            return
        name = name.strip()
        for c in list_schematic_categories():
            if c['name'].lower() == name.lower():
                schems = list_schematics(500, category=c['name'])
                for s in schems:
                    update_schematic_category(s['id'], '')
                embed = discord.Embed(title='📂 Kategorie gelöscht', description=f'**{name}** wurde entfernt.', color=discord.Color.orange())
                embed.add_field(name='Hinweis', value=f'{len(schems)} Schematics sind jetzt ohne Kategorie.', inline=False)
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
        await interaction.response.send_message(f'Die Kategorie **{name}** wurde nicht gefunden.', ephemeral=True)

    @category.command(name='assign', description='Ordne einem Schematic eine Kategorie zu')
    @app_commands.describe(schematic='Name des Schematics', kategorie='Name der Kategorie')
    async def category_assign(self, interaction: discord.Interaction, schematic: str, kategorie: str):
        if not await self._require_manager(interaction):
            return
        schema = get_schematic_by_name(schematic)
        if not schema:
            await interaction.response.send_message(f'**{schematic}** wurde nicht gefunden.', ephemeral=True)
            return
        kategorie = kategorie.strip()
        update_schematic_category(schema['id'], kategorie)
        embed = discord.Embed(title='📂 Kategorie zugewiesen', description=f'**{schema["name"]}** → **{kategorie}**', color=discord.Color.green())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @category.command(name='remove', description='Entferne ein Schematic aus seiner Kategorie')
    @app_commands.describe(schematic='Name des Schematics')
    async def category_remove(self, interaction: discord.Interaction, schematic: str):
        if not await self._require_manager(interaction):
            return
        schema = get_schematic_by_name(schematic)
        if not schema:
            await interaction.response.send_message(f'**{schematic}** wurde nicht gefunden.', ephemeral=True)
            return
        if not schema.get('category'):
            await interaction.response.send_message(f'**{schema["name"]}** hat keine Kategorie.', ephemeral=True)
            return
        update_schematic_category(schema['id'], '')
        embed = discord.Embed(title='📂 Kategorie entfernt', description=f'**{schema["name"]}** ist jetzt ohne Kategorie.', color=discord.Color.orange())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @category_assign.autocomplete('kategorie')
    @category_delete.autocomplete('name')
    @category_rename.autocomplete('alt')
    async def category_name_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self._category_autocomplete(interaction, current)

    @category_assign.autocomplete('schematic')
    @category_remove.autocomplete('schematic')
    async def schematic_name_autocomplete(self, interaction: discord.Interaction, current: str):
        schems = list_schematics(50)
        return [
            app_commands.Choice(name=s['name'][:80], value=s['name'])
            for s in schems
            if current.lower() in s['name'].lower()
        ][:25]

    @group.command(name='panel', description='Postet das interaktive Auswahl-Panel in den schematics-Kanal (Admin)')
    async def panel(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator and not _is_owner(interaction.user):
            await interaction.response.send_message('Nur Admins oder der Owner können das Panel posten.', ephemeral=True)
            return
        target = find_channel(interaction.guild, 'schematics') or interaction.channel
        embed = _build_panel_embed()
        try:
            await target.send(embed=embed, view=SchematicsPanel())
            await interaction.response.send_message(f'Panel gepostet in {target.mention}.', ephemeral=True)
        except Exception as e:
            logger.error(f'Panel-Post fehlgeschlagen: {e}')
            await interaction.response.send_message(f'Panel konnte nicht gepostet werden: {e}', ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(SchematicsCog(bot))
