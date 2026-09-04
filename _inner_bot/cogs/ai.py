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
    def __init__(self, bot: commands.Bot): self.bot = bot

    @app_commands.command(name='ask', description='Stelle eine Frage zu Scratch oder Game-Entwicklung')
    @app_commands.describe(frage='Deine Frage an die AI')
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: (i.guild_id, i.user.id))
    async def cmd_ask(self, interaction: discord.Interaction, frage: str):
        if not await _require_verified(interaction): return
        key = (interaction.guild_id, interaction.user.id)
        now = time.monotonic()
        recent = _ask_rate_limit.setdefault(key, deque())
        cutoff = now - _ASK_WINDOW
        while recent and recent[0] <= cutoff: recent.popleft()
        if len(recent) >= _ASK_LIMIT:
            await interaction.response.send_message(embed=discord.Embed(title='Rate-Limit', description='Zu viele Fragen! Warte kurz und versuch es erneut.', color=discord.Color.orange()), ephemeral=True)
            return
        recent.append(now)
        ai = _get_ai()
        if ai is None:
            await interaction.response.send_message(embed=discord.Embed(title='AI wird geladen...', description='Das AI-System startet gerade. Bitte versuch es später erneut.', color=discord.Color.yellow()), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        try:
            session_id = str(interaction.user.id)
            context_parts = []
            brain = getattr(ai, 'brain', None)
            if brain:
                session = brain.get_session(session_id)
                for h in session.get('history', [])[-3:]: context_parts.append(h.get('user', '')[:100])
                context_parts.append(f'Skill: {brain.analyze_user_skill(session_id)}')
            result = await asyncio.to_thread(ai.answer, frage, 'de', ' | '.join(context_parts) if context_parts else None)
            reply = result.get('reply', 'Keine Antwort gefunden.')
            source = result.get('source', 'unknown')
            confidence = result.get('confidence', 0)
            source_emoji = {'knowledge_base':'📚 Wissensbasis','learned':'🧠 Gelernt','docs':'📖 Dokumentation','youtube':'🎬 YouTube','wikipedia':'🌐 Wikipedia','normal':'💬 Standard','extensions':'🔧 Erweiterung','render':'🌐 Render AI'}.get(source, source)
            embed = discord.Embed(title='AI Antwort', description=reply[:2000], color=discord.Color.blue())
            embed.set_footer(text=f'Quelle: {source_emoji} | Vertrauen: {confidence:.0%}')
            if brain:
                skill = brain.analyze_user_skill(session_id)
                embed.add_field(name='Dein Level', value={'anfaenger':'🟢 Anfänger','mittel':'🟡 Mittel','fortgeschritten':'🔴 Fortgeschritten'}.get(skill, skill), inline=True)
            await interaction.followup.send(embed=embed)
        except Exception:
            logger.exception('AI error')
            await interaction.followup.send(embed=discord.Embed(title='Fehler', description='Die AI-Anfrage ist fehlgeschlagen. Bitte versuch es später erneut.', color=discord.Color.red()))

    @app_commands.command(name='tip', description='Erhalte einen Tipp zur Game-Entwicklung')
    async def cmd_tip(self, interaction: discord.Interaction):
        if not await _require_verified(interaction): return
        tips = ['🎮 **Tipp:** Nutze `broadcast` um zwischen Leveln zu wechseln!','🎨 **Tipp:** Verschiedene Costumes machen deine Animationen lebendiger!','🔊 **Tipp:** Sound-Effekte machen jedes Spiel professioneller!','⚡ **Tipp:** Nutze Variablen für Score, Leben und Timer!','🎯 **Tipp:** Clones ermöglichen Massen von Gegnern!','🌟 **Tipp:** Power-Ups machen das Spiel abwechslungsreicher!','🏃 **Tipp:** Schwerkraft + Springen = klassischer Platformer!','🎬 **Tipp:** Kostüm-Wechsel erzeugt flüssige Animationen!','🏰 **Tipp:** Mit `backdrop` kannst du verschiedene Level erstellen!','🤖 **Tipp:** Gegner die den Spieler verfolgen machen das Spiel spannend!','💎 **Tipp:** Sammelgegenstände motivieren Spieler erkunden zu gehen!','🎵 **Tipp:** Musik im Hintergrund erhöht die Atmosphäre enorm!','⏱️ **Tipp:** Timer erzeugt Druck und macht Spiele herausfordernder!','🌙 **Tipp:** Tag/Nacht-Wechsel gibt dem Spiel mehr Tiefe!','🔥 **Tipp:** Boss-Kämpfe am Ende eines Levels sind episch!','🛡️ **Tipp:** Mache Gegner unterschiedlich stark für mehr Abwechslung!','🧲 **Tipp:** Magneten können Gegner anziehen oder abstoßen!','🌊 **Tipp:** Wasser-Physik macht Spiele einzigartig!','🎈 **Tipp:** Luftballons als Gegner sind lustig und bunt!','🚩 **Tipp:** Checkpoints verhindern Frust bei langen Levels!','🎨 **Tipp:** Verwende Farbverläufe für professionelle Hintergründe!','🕹️ **Tipp:** WASD-Tasten sind alternativ zu Pfeiltasten!','🧪 **Tipp:** Experimentiere mit verschiedenen Gegnertypen!','🏆 **Tipp:** Highscores motivieren Spieler zum Verbessern!','🎵 **Tipp:** Sound-Pitch kann Geschwindigkeit signalisieren!','⚡ **Tipp:** Blitz-Effekte machen Angriffe dramatischer!','🌍 **Tipp:** Verschiedene Biome machen levels abwechslungsreicher!','🪙 **Tipp:** Münzen als Währung für Upgrades!','🎪 **Tipp:** Zirkus-Theme mit Clown-Gegnern!','🚀 **Tipp:** Raketen-Power-Up für temporäre Schnelligkeit!','🐉 **Tipp:** Drache als Endboss ist immer episch!','🧊 **Tipp:** Eis-Level mit rutschigen Oberflächen!','🔥 **Tipp:** Feuer-Trail hinter dem Spieler!','🌙 **Tipp:** Stealth-Elemente für mehr Strategie!','🎯 **Tipp:** Zielen mit der Maus für Schießspiele!']
        import random
        await interaction.response.send_message(embed=discord.Embed(title='Tages-Tipp', description=random.choice(tips), color=discord.Color.gold()))

    @app_commands.command(name='generate', description='Generiere ein Scratch-Spiel aus einer Beschreibung')
    @app_commands.describe(beschreibung='Beschreibung des Spiels', sprache='Sprache')
    @app_commands.choices(sprache=[app_commands.Choice(name='Deutsch', value='de'),app_commands.Choice(name='English', value='en'),app_commands.Choice(name='Français', value='fr'),app_commands.Choice(name='Español', value='es'),app_commands.Choice(name='Italiano', value='it'),app_commands.Choice(name='Svenska', value='sv')])
    async def cmd_generate(self, interaction: discord.Interaction, beschreibung: str, sprache: app_commands.Choice[str] = None):
        if not await _require_verified(interaction): return
        await interaction.response.defer(thinking=True)
        try:
            session_id = str(interaction.user.id)
            sb3_bytes, metadata = await asyncio.to_thread(_get_ai_gen().generate, beschreibung, session_id)
            if not sb3_bytes or len(sb3_bytes) < 100: await interaction.followup.send(embed=discord.Embed(title='Generierung fehlgeschlagen', color=discord.Color.red())); return
            if len(sb3_bytes) > 8 * 1024 * 1024: await interaction.followup.send(embed=discord.Embed(title='Zu groß', description='Die SB3-Datei ist zu groß für Discord (max 8MB).', color=discord.Color.red())); return
            features = metadata.get('features', []); details = metadata.get('details', {})
            detail_parts = [f'Leben: {details["num_lives"]}' for _ in [0] if details.get('num_lives')]
            if details.get('num_levels'): detail_parts.append(f'Level: {details["num_levels"]}')
            if details.get('timer_seconds'): detail_parts.append(f'Timer: {details["timer_seconds"]}s')
            if details.get('has_boss'): detail_parts.append('Boss: Ja')
            embed = discord.Embed(title='Spiel generiert', description=f'**Beschreibung:** {beschreibung[:200]}\n**Features:** {", ".join(features[:8]) or "Keine"}\n**Details:** {" | ".join(detail_parts) or "Keine"}\n**Skill-Level:** {metadata.get("skill_level", "unbekannt")}\n**Sprache:** {sprache.value if sprache else "de"}', color=discord.Color.green())
            await interaction.followup.send(embed=embed, file=discord.File(io.BytesIO(sb3_bytes), filename='mein_spiel.sb3'), view=FeedbackView(session_id, features))
        except Exception:
            logger.exception('Generate error')
            await interaction.followup.send(embed=discord.Embed(title='Generierungsfehler', description='Die Spiel-Generierung ist fehlgeschlagen.', color=discord.Color.red()))

    @app_commands.command(name='analyze', description='Lade eine SB3-Datei hoch und erhalte eine Analyse')
    @app_commands.describe(datei='Deine .sb3 Scratch-Datei')
    async def cmd_analyze(self, interaction: discord.Interaction, datei: discord.Attachment):
        if not await _require_verified(interaction): return
        if not datei.filename.lower().endswith('.sb3') or (datei.size and datei.size > 8 * 1024 * 1024):
            await interaction.response.send_message('❌ Bitte lade eine gültige `.sb3` Datei bis maximal 8 MB hoch.', ephemeral=True); return
        await interaction.response.defer(thinking=True)
        try:
            sb3_bytes = await datei.read()
            with zipfile.ZipFile(io.BytesIO(sb3_bytes)) as zf:
                project_json = json.loads(zf.read('project.json'))
                targets = project_json.get('targets', []); sprites = [t for t in targets if not t.get('isStage', False)]; stage = next((t for t in targets if t.get('isStage', False)), None)
                total_costumes = sum(len(t.get('costumes', [])) for t in targets); total_sounds = sum(len(t.get('sounds', [])) for t in targets); total_blocks = sum(len(t.get('blocks', {})) for t in targets)
                embed = discord.Embed(title='SB3 Analyse', description=f'**Datei:** {datei.filename}\n**Größe:** {len(sb3_bytes)/1024:.1f} KB', color=discord.Color.blue())
                for name, value in [('Sprites',len(sprites)),('Bühne','Ja' if stage else 'Nein'),('Blöcke',total_blocks),('Kostüme',total_costumes),('Sounds',total_sounds),('SVG-Dateien',sum(n.endswith('.svg') for n in zf.namelist())),('WAV-Dateien',sum(n.endswith('.wav') for n in zf.namelist()))]: embed.add_field(name=name,value=str(value),inline=True)
                if sprites: embed.add_field(name='Sprite-Liste', value='\n'.join(f'• {s.get("name","Unbekannt")} ({len(s.get("costumes",[]))} Costumes)' for s in sprites[:10]), inline=False)
                await interaction.followup.send(embed=embed)
        except zipfile.BadZipFile: await interaction.followup.send('Die Datei ist keine gültige SB3/ZIP-Datei.')
        except Exception:
            logger.exception('Analyze error'); await interaction.followup.send('Die SB3-Analyse ist fehlgeschlagen.')

    @app_commands.command(name='ai', description='Analysiere was die AI aus deinem Text versteht')
    @app_commands.describe(text='Beschreibung des Spiels die die AI analysieren soll')
    async def cmd_ai(self, interaction: discord.Interaction, text: str):
        if not await _require_verified(interaction): return
        await interaction.response.defer(thinking=True)
        try:
            analysis = await asyncio.to_thread(_get_ai_gen().analyze, text)
            probs = analysis.get('probabilities', {}); top = sorted(probs.items(), key=lambda x:x[1], reverse=True)[:8]
            embed = discord.Embed(title='AI Spiel-Analyse', description=f'**Eingabe:** {text[:200]}', color=discord.Color.blue())
            lines = [f'`{"█"*int(c*10)}{"░"*(10-int(c*10))}` **{int(c*100)}%** {f}' for f,c in top]
            embed.add_field(name=f'Erkannte Features ({analysis.get("num_features",0)})', value='\n'.join(lines) or 'Keine Features erkannt', inline=False)
            embed.set_footer(text=f'Skill-Level: {analysis.get("skill_level","unbekannt")}')
            await interaction.followup.send(embed=embed)
        except Exception:
            logger.exception('AI analysis error'); await interaction.followup.send(embed=discord.Embed(title='Fehler', description='Die AI-Analyse ist fehlgeschlagen.', color=discord.Color.red()))

    @app_commands.command(name='refine', description='Verfeinere ein generiertes Spiel')
    @app_commands.describe(aenderung='Was soll geändert werden?', sprache='Sprache')
    @app_commands.choices(sprache=[app_commands.Choice(name='Deutsch', value='de'),app_commands.Choice(name='English', value='en'),app_commands.Choice(name='Français', value='fr'),app_commands.Choice(name='Español', value='es'),app_commands.Choice(name='Italiano', value='it'),app_commands.Choice(name='Svenska', value='sv')])
    async def cmd_refine(self, interaction: discord.Interaction, aenderung: str, sprache: app_commands.Choice[str] = None):
        if not await _require_verified(interaction): return
        await interaction.response.defer(thinking=True)
        try:
            session_id = str(interaction.user.id); prompt = f'Verbessere ein bestehendes Spiel mit diesen Aenderungen: {aenderung}. Behalte die grundlegende Struktur bei und mache gezielte Verbesserungen.'
            sb3_bytes, metadata = await asyncio.to_thread(_get_ai_gen().generate, prompt, session_id)
            if not sb3_bytes or len(sb3_bytes) < 100: await interaction.followup.send(embed=discord.Embed(title='Refinement fehlgeschlagen', color=discord.Color.red())); return
            features = metadata.get('features', [])
            embed = discord.Embed(title='Spiel verfeinert', description=f'**Änderung:** {aenderung}\n**Features:** {", ".join(features[:8]) or "Keine"}\n**Sprache:** {sprache.value if sprache else "de"}', color=discord.Color.blue())
            await interaction.followup.send(embed=embed, file=discord.File(io.BytesIO(sb3_bytes), filename='verfeinertes_spiel.sb3'), view=FeedbackView(session_id, features))
        except Exception:
            logger.exception('Refine error'); await interaction.followup.send(embed=discord.Embed(title='Fehler', description='Die Verfeinerung ist fehlgeschlagen.', color=discord.Color.red()))

    @app_commands.command(name='suggest', description='AI schlägt ein Spiel basierend auf deinem Level vor')
    async def cmd_suggest(self, interaction: discord.Interaction):
        if not await _require_verified(interaction): return
        suggestion = await asyncio.to_thread(_get_ai_gen().suggest, str(interaction.user.id))
        if suggestion:
            skill = suggestion.get('skill','mittel')
            embed = discord.Embed(title='Spiel-Vorschlag', description=f'**Vorschlag:** {suggestion.get("type","Unbekannt")}\n**Features:** {", ".join(suggestion.get("features",[])[:5])}\n**Schwierigkeit:** {suggestion.get("difficulty","leicht")}\n**Dein Level:** {skill}', color=discord.Color.purple())
            await interaction.response.send_message(embed=embed)
        else: await interaction.response.send_message(embed=discord.Embed(title='Kein Vorschlag verfügbar', description='Der Generator ist gerade nicht erreichbar.', color=discord.Color.yellow()))

async def setup(bot: commands.Bot):
    await bot.add_cog(AICog(bot))
