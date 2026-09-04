"""Link-Polling: prüft die Webapp nach neuen Link-Requests und sendet DMs."""
import asyncio
import discord
from core.config import WEBAPP_URL, BOT_SECRET
from core.logging import logger
from core.views import LinkConfirmView

_processed_link_ids = set()
_MAX_PROCESSED_IDS = 500
_link_poll_failures = 0


async def poll_pending_links(bot):
    """Pollt die Webapp nach neuen Link-Requests und schickt DMs."""
    global _link_poll_failures
    while True:
        wait = min(30 + (_link_poll_failures * 60), 600)
        await asyncio.sleep(wait)
        if not WEBAPP_URL or not BOT_SECRET:
            return
        try:
            def _fetch_pending():
                import urllib.request
                api_url = f'{WEBAPP_URL}/api/discord/link-pending'
                req = urllib.request.Request(api_url, headers={'Content-Type': 'application/json', 'X-Bot-Secret': BOT_SECRET})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    import json as _j
                    return _j.loads(resp.read())
            data = await asyncio.to_thread(_fetch_pending)

            for entry in data.get('pending', []):
                entry_id = entry['id']
                if entry_id in _processed_link_ids:
                    continue
                _processed_link_ids.add(entry_id)

                if len(_processed_link_ids) > _MAX_PROCESSED_IDS:
                    to_remove = list(_processed_link_ids)[:_MAX_PROCESSED_IDS // 2]
                    for rid in to_remove:
                        _processed_link_ids.discard(rid)

                discord_username = entry['discord_username']
                website_username = entry['website_username']

                user = None
                for guild in bot.guilds:
                    member = discord.utils.find(
                        lambda m: m.name.lower() == discord_username.lower() or m.display_name.lower() == discord_username.lower(),
                        guild.members
                    )
                    if member:
                        user = member
                        break

                if not user:
                    logger.warning(f'Link: Discord-User "{discord_username}" nicht gefunden')
                    continue

                try:
                    dm = await user.create_dm()
                    embed = discord.Embed(
                        title='🎮 Account-Verknüpfung',
                        description=(
                            f'Jemand möchte sich mit deinem Website-Account **{website_username}** verknüpfen.\n\n'
                            f'Bist du das?'
                        ),
                        color=discord.Color.blurple()
                    )
                    view = LinkConfirmView(website_username)
                    await dm.send(embed=embed, view=view)
                    logger.info(f'Link DM sent to {user} for website user {website_username}')
                except discord.Forbidden:
                    logger.warning(f'Link: Keine DM an {user} möglich')
                except Exception as e:
                    logger.error(f'Link DM error: {e}')

            _link_poll_failures = 0

        except Exception as e:
            _link_poll_failures += 1
            if _link_poll_failures <= 3:
                logger.warning(f'Poll link error ({_link_poll_failures}x): {e}')
