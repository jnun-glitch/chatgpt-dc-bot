"""Fun: Unterhaltungs-Commands für Community & Events."""
import random
import discord
from discord import app_commands
from discord.ext import commands

_TRIVIA = [
    ('Welche Farbe hat ein Smaragd?', ['Grün', 'Rot', 'Blau', 'Gelb'], 0),
    ('Wie viele Planeten hat unser Sonnensystem?', ['7', '8', '9', '10'], 1),
    ('Wer hat die Relativitätstheorie entwickelt?', ['Newton', 'Einstein', 'Hawking', 'Galilei'], 1),
    ('Wie nennt man den Vorgang bei dem Wasser zu Dampf wird?', ['Kondensation', 'Verdampfung', 'Sublimation', 'Kristallisation'], 1),
    ('Welche Sprache wird am meisten gesprochen (Muttersprachler)?', ['Englisch', 'Mandarin', 'Spanisch', 'Hindi'], 1),
    ('Wie viele Beine hat eine Spinne?', ['6', '8', '10', '12'], 1),
    ('Welches ist das größte Land der Welt (Fläche)?', ['China', 'Kanada', 'USA', 'Russland'], 3),
    ('Wie heißt die Hauptstadt von Australien?', ['Sydney', 'Melbourne', 'Canberra', 'Perth'], 2),
    ('Welche Zahl ist Primzahl?', ['15', '21', '23', '27'], 2),
    ('Wie viele Minuten hat eine Stunde?', ['60', '100', '30', '45'], 0),
]

_EMOJIS = ['🫰', '🖐️', '🤞', '✌️', '🤙', '✊', '👍', '👎', '🫵', '👌']

_8BALL_ANSWERS = [
    'Ja, auf jeden Fall!', 'Nein, auf keinen Fall.', 'Vielleicht… frag später nochmal.',
    'Definitiv nicht.', 'Klar, warum nicht?', 'Die Sterne sagen: ja.',
    'Frag mich das nicht nochmal.', 'Alle Zeichen deuten darauf hin.', 'Sehr unwahrscheinlich.',
    'Ja!', 'Nein.', 'Es ist möglich, aber unwahrscheinlich.',
]

_JOKES = [
    'Warum können Geister so schlecht lügen? – Weil sie durchsichtig sind! 👻',
    'Was sagt ein Mathematiker, wenn er frustriert ist? – „Das ist die falsche Gleichung!“ 📐',
    'Warum hat der Informatiker Angst vor Spiegeln? – Weil er dort die Rückmeldung sieht! 💻',
    'Was macht eine Java-Entwicklerin wenn sie friert? – Sie stellt den Exception-Handler wärmer! ☕',
    'Warum nehmen Programmierer keine Duschen? – Aus Angst vor dem Water-Cooler-Gespräch… 🚿',
    'Wie heißt ein Ninja der sich versteckt? – „Dich gibt’s ja gar nicht!“ 🥷',
    'Warum ging der Computer zum Arzt? – Weil er einen Virus hatte! 🦠',
    'Was ist der Unterschied zwischen Pizza und einem Bug? – Pizza wird nicht behoben, wenn man sie anschreit. 🍕',
]

_RPS_CHOICES = {
    'schere': ('✂️', 'Fels'), 'stein': ('🪨', 'Schere'), 'papier': ('📄', 'Stein'),
}
_RPS_WINS = {'schere': 'papier', 'stein': 'schere', 'papier': 'stein'}

_SLOT_SYMBOLS = ['🍒', '🍋', '🍇', '💎', '7️⃣', '⭐']
_MEMES = [
    ('Wenn der Bot 65 Slash Commands hat… und keiner nutzt /help', '😅'),
    ('Ich: „nur kurz 5 Minuten Discord" – 3 Stunden später:', '😂'),
    ('Modus auf SMP gestellt, Kanal war Minecraft. Perfekt.', '⛏️'),
    ('Wenn jemand „/ask" nutzt und die AI trotzdem antwortet', '🤖'),
    ('Level 20 ist „Master"? Ich kenne die Level noch als „Scratcher".', '🐱'),
    ('Bug gefunden? Nein, Feature! – dachte sich auch der Bot', '🐛'),
    ('Ticket erstellt, Support wartet auf n8n…', '🎫'),
    ('Wenn das generate-Spiel nur aus Sprites besteht', '🎮'),
]


class FunCog(commands.Cog):
    """Unterhaltung: Würfel, Münze, Memes, Quiz."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name='roll', description='Würfle mit einem Würfel')
    @app_commands.describe(seiten='Anzahl der Seiten (2-100)', anzahl='Anzahl der Würfel (1-10)')
    async def cmd_roll(self, interaction: discord.Interaction, seiten: int = 6, anzahl: int = 1):
        seiten = max(2, min(100, seiten))
        anzahl = max(1, min(10, anzahl))
        rolls = [random.randint(1, seiten) for _ in range(anzahl)]
        embed = discord.Embed(
            title='🎲 Würfelwurf',
            description=f'**{anzahl}x W{seiten}** → ' + ', '.join(f'`{r}`' for r in rolls),
            color=discord.Color.blue()
        )
        if anzahl > 1:
            embed.add_field(name='Summe', value=str(sum(rolls)), inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name='coinflip', description='Wirf eine Münze')
    @app_commands.describe(anzahl='Wie oft werfen? (1-10)')
    async def cmd_coinflip(self, interaction: discord.Interaction, anzahl: int = 1):
        anzahl = max(1, min(10, anzahl))
        flips = [random.choice(['Kopf', 'Zahl']) for _ in range(anzahl)]
        heads = flips.count('Kopf')
        embed = discord.Embed(
            title='🪙 Münzwurf',
            description=' → '.join('🦅' if f == 'Kopf' else '💠' for f in flips),
            color=discord.Color.gold()
        )
        embed.add_field(name='Ergebnis', value=f'{heads}x Kopf · {anzahl - heads}x Zahl', inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name='meme', description='Zeigt einen zufälligen Meme-Spruch')
    async def cmd_meme(self, interaction: discord.Interaction):
        text, emoji = random.choice(_MEMES)
        embed = discord.Embed(title=f'{emoji} Meme', description=f'> {text}', color=discord.Color.purple())
        embed.set_footer(text=f'Memes: {len(_MEMES)} · Zufallsgenerator')
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name='trivia', description='Beantworte eine Wissensfrage')
    async def cmd_trivia(self, interaction: discord.Interaction):
        question, options, correct = random.choice(_TRIVIA)
        letters = ['A', 'B', 'C', 'D']
        embed = discord.Embed(title='🧠 Trivia', description=f'**{question}**', color=discord.Color.teal())
        embed.add_field(name='Optionen', value='\n'.join(f'{letters[i]}) {o}' for i, o in enumerate(options)), inline=False)
        await interaction.response.send_message(embed=embed)
        await interaction.channel.send(f'Die richtige Antwort ist: **{letters[correct]}) {options[correct]}**')

    @app_commands.command(name='minigames', description='Zeigt verfügbare Minigames')
    async def cmd_minigames(self, interaction: discord.Interaction):
        embed = discord.Embed(title='🎮 Minigames', color=discord.Color.blue())
        embed.add_field(name='Verfügbar', value='`/roll` – Würfeln\n`/coinflip` – Münze werfen\n`/meme` – Zufalls-Meme\n`/trivia` – Wissensquiz\n`/8ball` – Zauberkugel\n`/joke` – Witz\n`/rps` – Schere-Stein-Papier\n`/slot` – Slotmaschine\n`/guess` – Zahl raten', inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name='8ball', description='Die Zauberkugel beantwortet deine Frage')
    @app_commands.describe(frage='Deine Frage')
    async def cmd_8ball(self, interaction: discord.Interaction, frage: str):
        if not frage.endswith('?'):
            frage = frage + '?'
        embed = discord.Embed(
            title='🔮 Zauberkugel',
            description=f'> {frage}\n\n**{random.choice(_8BALL_ANSWERS)}**',
            color=discord.Color.purple()
        )
        embed.set_footer(text='Die Kugel hat gesprochen.')
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name='joke', description='Erzählt einen zufälligen Witz')
    async def cmd_joke(self, interaction: discord.Interaction):
        embed = discord.Embed(title='😂 Witz', description=random.choice(_JOKES), color=discord.Color.gold())
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name='rps', description='Spiele Schere-Stein-Papier gegen den Bot')
    @app_commands.describe(wahl='Deine Wahl')
    @app_commands.choices(wahl=[
        app_commands.Choice(name='✂️ Schere', value='schere'),
        app_commands.Choice(name='🪨 Stein', value='stein'),
        app_commands.Choice(name='📄 Papier', value='papier'),
    ])
    async def cmd_rps(self, interaction: discord.Interaction, wahl: app_commands.Choice[str]):
        bot_choice = random.choice(list(_RPS_CHOICES.keys()))
        user_choice = wahl.value
        bot_emoji = _RPS_CHOICES[bot_choice][0]
        user_emoji = _RPS_CHOICES[user_choice][0]

        if user_choice == bot_choice:
            result = 'Unentschieden! 🤝'
            color = discord.Color.greyple()
        elif _RPS_WINS[user_choice] == bot_choice:
            result = 'Du gewinnst! 🎉'
            color = discord.Color.green()
        else:
            result = 'Ich gewinne! 😏'
            color = discord.Color.red()

        embed = discord.Embed(
            title='✂️ Schere-Stein-Papier',
            description=f'Du: {user_emoji} {wahl.name} vs. Ich: {bot_emoji} **{bot_choice}**\n\n**{result}**',
            color=color
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name='slot', description='Spiele an der Slotmaschine')
    async def cmd_slot(self, interaction: discord.Interaction):
        result = [random.choice(_SLOT_SYMBOLS) for _ in range(3)]
        if result[0] == result[1] == result[2]:
            if result[0] == '7️⃣':
                verdict = '🎉 JACKPOT! Drei Siebenen!'
            else:
                verdict = '🎉 Volltreffer! Du gewinnst!'
        elif result[0] == result[1] or result[1] == result[2]:
            verdict = '✨ Fast geschafft! Noch ein Versuch.'
        else:
            verdict = '💔 Leider nichts. Viel Glück beim nächsten Mal!'
        embed = discord.Embed(title='🎰 Slotmaschine', description=' | '.join(result), color=discord.Color.blue())
        embed.add_field(name='Ergebnis', value=verdict, inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name='guess', description='Rate eine Zahl zwischen 1 und 10')
    @app_commands.describe(zahl='Deine Zahl (1-10)')
    async def cmd_guess(self, interaction: discord.Interaction, zahl: int):
        target = random.randint(1, 10)
        if zahl < 1 or zahl > 10:
            await interaction.response.send_message('Bitte eine Zahl zwischen 1 und 10.', ephemeral=True)
            return
        if zahl == target:
            embed = discord.Embed(title='🎯 Treffer!', description=f'Meine Zahl war **{target}**. Du hast richtig geraten!', color=discord.Color.green())
        else:
            embed = discord.Embed(title='🤔 Daneben!', description=f'Meine Zahl war **{target}** – du hast **{zahl}** getippt.', color=discord.Color.red())
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(FunCog(bot))
