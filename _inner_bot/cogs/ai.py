"""AI-Commands: ask, tip, generate, analyze, ai, refine, suggest."""
import asyncio
import io
import json
import time
import zipfile
from collections import deque

import discord
from discord import app_commands
from discord.ext import commands
from core.ai import _get_ai, _get_ai_gen
from core.utils import _require_verified
from core.views import FeedbackView
from core.logging import logger

_ask_rate_limit: dict[tuple[int | None, int], deque] = {}
_ASK_LIMIT = 5
_ASK_WINDOW = 60.0


class AICog(commands.Cog):
    """AI-Chat, Spiel-Generator und Analyse."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name='ask', description='Stelle eine Frage zu Scratch oder Game-Entwicklung')
    @app_commands.describe(frage='Deine Frage an die AI')
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.guild_id, i.user.id))
    async def cmd_ask(self, interaction: discord.Interaction, frage: str):
        if not await _require_verified(interaction):
            return

        # Rate-Limit pro User und Server. Alte Einträge werden aktiv entfernt,
        # damit der In-Memory-Cache bei vielen Nutzern nicht unendlich wächst.
        key = (interaction.guild_id, interaction.user.id)
        now = time.monotonic()
        recent = _ask_rate_limit.setdefault(key, deque())
        cutoff = now - _ASK_WINDOW
        while recent and recent[0] <= cutoff:
            recent.popleft()
        if len(recent) >= _ASK_LIMIT:
            embed = discord.Embed(title='Rate-Limit', description='Zu viele Fragen! Warte kurz und versuch es erneut.', color=discord.Color.orange())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        recent.append(now)

        ai = _get_ai()
        if ai is None:
            embed = discord.Embed(
                title='AI wird geladen...',
                description='Das AI-System startet gerade. Bitte warte 30 Sekunden und versuch es erneut.',
                color=discord.Color.yellow()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await interaction.response.defer(thinking=True)

        try:
            session_id = str(interaction.user.id)
            context_parts = []
            brain = getattr(ai, 'brain', None)
            if brain:
                session = brain.get_session(session_id)
                history = session.get('history', [])[-3:]
                for h in history:
                    context_parts.append(h.get('user', '')[:100])
                skill = brain.analyze_user_skill(session_id)
                context_parts.append(f'Skill: {skill}')

            context = ' | '.join(context_parts) if context_parts else None
            # Blockierenden HTTP-Call (bis 30s) aus dem Event-Loop auslagern
            result = await asyncio.to_thread(ai.answer, frage, 'de', context)
            reply = result.get('reply', 'Keine Antwort gefunden.')
            source = result.get('source', 'unknown')
            confidence = result.get('confidence', 0)

            source_emoji = {
                'knowledge_base': '📚 Wissensbasis',
                'learned': '🧠 Gelernt',
                'docs': '📖 Dokumentation',
                'youtube': '🎬 YouTube',
                'wikipedia': '🌐 Wikipedia',
                'normal': '💬 Standard',
                'extensions': '🔧 Erweiterung',
                'render': '🌐 Render AI',
            }.get(source, source)

            embed = discord.Embed(title='AI Antwort', description=reply[:2000], color=discord.Color.blue())
            embed.set_footer(text=f'Quelle: {source_emoji} | Vertrauen: {confidence:.0%}')

            if brain:
                skill = brain.analyze_user_skill(session_id)
                skill_emoji = {'anfaenger': '🟢 Anfänger', 'mittel': '🟡 Mittel', 'fortgeschritten': '🔴 Fortgeschritten'}
                embed.add_field(name='Dein Level', value=skill_emoji.get(skill, skill), inline=True)

            await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.error(f'AI error: {e}')
            embed = discord.Embed(title='Fehler', description='Die AI-Anfrage ist fehlgeschlagen. Bitte versuch es später erneut.', color=discord.Color.red())
            await interaction.followup.send(embed=embed)

    @app_commands.command(name='tip', description='Erhalte einen Tipp zur Game-Entwicklung')
    async def cmd_tip(self, interaction: discord.Interaction):
        if not await _require_verified(interaction):
            return
        tips = [
            '🎮 **Tipp:** Nutze `broadcast` um zwischen Leveln zu wechseln!',
            '🎨 **Tipp:** Verschiedene Costumes machen deine Animationen lebendiger!',
            '🔊 **Tipp:** Sound-Effekte machen jedes Spiel professioneller!',
            '⚡ **Tipp:** Nutze Variablen für Score, Leben und Timer!',
            '🎯 **Tipp:** Clones ermöglichen Massen von Gegnern!',
            '🌟 **Tipp:** Power-Ups machen das Spiel abwechslungsreicher!',
            '🏃 **Tipp:** Schwerkraft + Springen = klassischer Platformer!',
            '🎬 **Tipp:** Kostüm-Wechsel erzeugt flüssige Animationen!',
            '🏰 **Tipp:** Mit `backdrop` kannst du verschiedene Level erstellen!',
            '🤖 **Tipp:** Gegner die den Spieler verfolgen machen das Spiel spannend!',
            '💎 **Tipp:** Sammelgegenstände motivieren Spieler erkunden zu gehen!',
            '🎵 **Tipp:** Musik im Hintergrund erhöht die Atmosphäre enorm!',
            '⏱️ **Tipp:** Timer erzeugt Druck und macht Spiele herausfordernder!',
            '🌙 **Tipp:** Tag/Nacht-Wechsel gibt dem Spiel mehr Tiefe!',
            '🔥 **Tipp:** Boss-Kämpfe am Ende eines Levels sind episch!',
            '🛡️ **Tipp:** Mache Gegner unterschiedlich stark für mehr Abwechslung!',
            '🧲 **Tipp:** Magneten können Gegner anziehen oder abstoßen!',
            '🌊 **Tipp:** Wasser-Physik macht Spiele einzigartig!',
            '🎈 **Tipp:** Luftballons als Gegner sind lustig und bunt!',
            '🚩 **Tipp:** Checkpoints verhindern Frust bei langen Levels!',
            '🎨 **Tipp:** Verwende Farbverläufe für professionelle Hintergründe!',
            '🕹️ **Tipp:** WASD-Tasten sind alternativ zu Pfeiltasten!',
            '🧪 **Tipp:** Experimentiere mit verschiedenen Gegnertypen!',
            '🏆 **Tipp:** Highscores motivieren Spieler zum Verbessern!',
            '🎵 **Tipp:** Sound-Pitch kann Geschwindigkeit signalisieren!',
            '⚡ **Tipp:** Blitz-Effekte machen Angriffe dramatischer!',
            '🌍 **Tipp:** Verschiedene Biome machen levels abwechslungsreicher!',
            '🪙 **Tipp:** Münzen als Währung für Upgrades!',
            '🎪 **Tipp:** Zirkus-Theme mit Clown-Gegnern!',
            '🚀 **Tipp:** Raketen-Power-Up für temporäre Schnelligkeit!',
            '🐉 **Tipp:** Drache als Endboss ist immer episch!',
            '🧊 **Tipp:** Eis-Level mit rutschigen Oberflächen!',
            '🔥 **Tipp:** Feuer-Trail hinter dem Spieler!',
            '🌙 **Tipp:** Stealth-Elemente für mehr Strategie!',
            '🎯 **Tipp:** Zielen mit der Maus für Schießspiele!',
        ]
        import random
        tip = random.choice(tips)
        embed = discord.Embed(title='Tages-Tipp', description=tip, color=discord.Color.gold())
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name='generate', description='Generiere ein Scratch-Spiel aus einer Beschreibung')
    @app_commands.describe(
        beschreibung='Beschreibung des Spiels (z.B. "Jump and Run mit Gegnern und Münzen")',
        sprache='Sprache (de, en, fr, es, it)'
    )
    @app_commands.choices(sprache=[
        app_commands.Choice(name='Deutsch', value='de'),
        app_commands.Choice(name='English', value='en'),
        app_commands.Choice(name='Français', value='fr'),
        app_commands.Choice(name='Español', value='es'),
        app_commands.Choice(name='Italiano', value='it'),
        app_commands.Choice(name='Svenska', value='sv'),
    ])
    async def cmd_generate(self, interaction: discord.Interaction, beschreibung: str, sprache: app_commands.Choice[str] = None):
        if not await _require_verified(interaction):
            return
        gen = _get_ai_gen()

        await interaction.response.defer(thinking=True)

        lang = sprache.value if sprache else 'de'
        session_id = str(interaction.user.id)

        try:
            sb3_bytes, metadata = await asyncio.to_thread(gen.generate, beschreibung, session_id)

            if not sb3_bytes or len(sb3_bytes) < 100:
                embed = discord.Embed(title='Generierung fehlgeschlagen', description='Kein SB3 generiert.', color=discord.Color.red())
                await interaction.followup.send(embed=embed)
                return

            if len(sb3_bytes) > 8 * 1024 * 1024:
                embed = discord.Embed(title='Zu groß', description='Die SB3-Datei ist zu groß für Discord (max 8MB).', color=discord.Color.red())
                await interaction.followup.send(embed=embed)
                return

            features = metadata.get('features', [])
            details = metadata.get('details', {})
            skill_level = metadata.get('skill_level', 'unbekannt')
            feature_str = ', '.join(features[:8]) if features else 'Keine'

            detail_parts = []
            if details.get('num_lives'):
                detail_parts.append(f'Leben: {details["num_lives"]}')
            if details.get('num_levels'):
                detail_parts.append(f'Level: {details["num_levels"]}')
            if details.get('timer_seconds'):
                detail_parts.append(f'Timer: {details["timer_seconds"]}s')
            if details.get('has_boss'):
                detail_parts.append('Boss: Ja')
            detail_str = ' | '.join(detail_parts) if detail_parts else 'Keine'

            embed = discord.Embed(
                title='Spiel generiert',
                description=(
                    f'**Beschreibung:** {beschreibung[:200]}\n'
                    f'**Features:** {feature_str}\n'
                    f'**Details:** {detail_str}\n'
                    f'**Skill-Level:** {skill_level}\n'
                    f'**Sprache:** {lang}'
                ),
                color=discord.Color.green()
            )

            file = discord.File(io.BytesIO(sb3_bytes), filename='mein_spiel.sb3')
            view = FeedbackView(session_id, features)
            await interaction.followup.send(embed=embed, file=file, view=view)
        except Exception as e:
            logger.error(f'Generate error: {e}')
            embed = discord.Embed(title='Generierungsfehler', description='Die Spiel-Generierung ist fehlgeschlagen. Bitte versuch es später erneut.', color=discord.Color.red())
            await interaction.followup.send(embed=embed)

    @app_commands.command(name='analyze', description='Lade eine SB3-Datei hoch und erhalte eine Analyse')
    @app_commands.describe(datei='Deine .sb3 Scratch-Datei')
    async def cmd_analyze(self, interaction: discord.Interaction, datei: discord.Attachment):
        if not await _require_verified(interaction):
            return
        if not datei.filename.endswith('.sb3'):
            embed = discord.Embed(title='Falsches Format', description='Bitte lade eine `.sb3` Datei hoch.', color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if datei.size and datei.size > 8 * 1024 * 1024:
            embed = discord.Embed(title='Zu groß', description='Die Datei ist zu groß (max 8MB).', color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await interaction.response.defer(thinking=True)

        try:
            sb3_bytes = await datei.read()
            with zipfile.ZipFile(io.BytesIO(sb3_bytes)) as zf:
                project_json = None
                for name in zf.namelist():
                    if name == 'project.json':
                        project_json = json.loads(zf.read(name))
                        break

                if project_json is None:
                    await interaction.followup.send('Keine project.json in der SB3 gefunden.')
                    return

                targets = project_json.get('targets', [])
                sprites = [t for t in targets if not t.get('isStage', False)]
                stage = next((t for t in targets if t.get('isStage', False)), None)

                total_costumes = sum(len(t.get('costumes', [])) for t in targets)
                total_sounds = sum(len(t.get('sounds', [])) for t in targets)
                total_blocks = sum(len(t.get('blocks', {})) for t in targets)
                svg_files = [n for n in zf.namelist() if n.endswith('.svg')]
                wav_files = [n for n in zf.namelist() if n.endswith('.wav')]

                embed = discord.Embed(
                    title='SB3 Analyse',
                    description=f'**Datei:** {datei.filename}\n**Größe:** {len(sb3_bytes) / 1024:.1f} KB',
                    color=discord.Color.blue()
                )
                embed.add_field(name='Sprites', value=str(len(sprites)), inline=True)
                embed.add_field(name='Bühne', value='Ja' if stage else 'Nein', inline=True)
                embed.add_field(name='Blöcke', value=str(total_blocks), inline=True)
                embed.add_field(name='Kostüme', value=str(total_costumes), inline=True)
                embed.add_field(name='Sounds', value=str(total_sounds), inline=True)
                embed.add_field(name='SVG-Dateien', value=str(len(svg_files)), inline=True)
                embed.add_field(name='WAV-Dateien', value=str(len(wav_files)), inline=True)
                await interaction.followup.send(embed=embed)
        except zipfile.BadZipFile:
            await interaction.followup.send('Die Datei ist keine gültige SB3/ZIP-Datei.')
        except (json.JSONDecodeError, UnicodeDecodeError):
            await interaction.followup.send('Die project.json konnte nicht gelesen werden.')
        except Exception as e:
            logger.error(f'Analyze error: {e}')
            await interaction.followup.send('Die SB3-Analyse ist fehlgeschlagen. Bitte versuch es später erneut.')

    @app_commands.command(name='ai', description='Analysiere den aktuellen Ticket-Kontext mit der AI')
    async def cmd_ai(self, interaction: discord.Interaction):
        if not await _require_verified(interaction):
            return
        await interaction.response.send_message('🧠 Die Ticket-AI ist über das Ticket-System verfügbar.', ephemeral=True)


async def setup(bot):
    await bot.add_cog(AICog(bot))
