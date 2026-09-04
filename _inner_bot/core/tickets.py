"""Ticket helpers: HTML transcripts, n8n webhook and owner notifications."""
import asyncio
import html
import json
import urllib.error
import urllib.request

import discord

from core.config import ADMIN_LOG_CHANNEL_ID, BOT_DIR, N8N_WEBHOOK_URL, OWNER_ID, TRANSCRIPTS_DIR
from core.logging import logger


async def save_ticket_transcript(channel_id: str, guild):
    """Save an HTML transcript with user-controlled content safely escaped."""
    channel = guild.get_channel(int(channel_id))
    if not channel:
        return None
    try:
        messages = []
        async for msg in channel.history(limit=500, oldest_first=True):
            embeds_html = ""
            for embed in msg.embeds:
                embed_title = html.escape(embed.title or "")
                embed_desc = html.escape(embed.description or "").replace("\n", "<br>")
                embeds_html += f'<div class="embed"><b>{embed_title}</b><br>{embed_desc}</div>'

            attachments = ""
            for att in msg.attachments:
                url = html.escape(att.url, quote=True)
                filename = html.escape(att.filename)
                attachments += f'<div class="attachment">📎 <a href="{url}" target="_blank" rel="noopener noreferrer">{filename}</a></div>'

            messages.append({
                "author": html.escape(str(msg.author.display_name)),
                "avatar": html.escape(str(msg.author.display_avatar.url), quote=True) if msg.author.display_avatar else "",
                "content": html.escape(msg.content).replace("\n", "<br>"),
                "embeds": embeds_html,
                "attachments": attachments,
                "timestamp": msg.created_at.strftime("%d.%m.%Y %H:%M:%S"),
                "is_bot": msg.author.bot,
            })

        topic = channel.topic or ""
        parts = [part.strip() for part in topic.split("|")]
        betreff = html.escape(parts[1] if len(parts) > 1 else "Kein Betreff")
        kategorie = "Sonstiges"
        for part in parts:
            if part.startswith("Kategorie:"):
                kategorie = html.escape(part.split(":", 1)[1].strip() or "Sonstiges")
                break
        channel_name = html.escape(channel.name)

        messages_html = ""
        for msg in messages:
            bot_class = " bot-message" if msg["is_bot"] else ""
            avatar_html = (
                f'<img src="{msg["avatar"]}" class="avatar" alt="Avatar">'
                if msg["avatar"] else '<div class="avatar avatar-default"></div>'
            )
            messages_html += f"""
            <div class="message{bot_class}">
                {avatar_html}
                <div class="message-content">
                    <div class="message-header">
                        <span class="author">{msg['author']}</span>
                        <span class="timestamp">{msg['timestamp']}</span>
                    </div>
                    <div class="message-body">{msg['content']}</div>
                    {msg['embeds']}
                    {msg['attachments']}
                </div>
            </div>"""

        html_doc = f"""<!doctype html>
<html lang="de"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Ticket {channel_name}</title>
<style>
* {{ box-sizing:border-box; }} body {{ font-family:system-ui,sans-serif;background:#36393f;color:#dcddde;line-height:1.6;margin:0; }}
.header {{ background:#202225;padding:20px;border-bottom:2px solid #5865f2;text-align:center; }}
.header h1 {{ color:#5865f2;font-size:24px;margin:0; }} .meta {{ color:#a0a4aa;margin-top:8px;font-size:14px; }}
.container {{ max-width:900px;margin:20px auto;padding:0 20px; }} .message {{ display:flex;padding:12px 16px;margin:4px 0;border-radius:4px; }}
.message:hover {{ background:#32353b; }} .bot-message {{ background:#2f3136;border-left:3px solid #5865f2; }}
.avatar {{ width:40px;height:40px;border-radius:50%;margin-right:16px;flex-shrink:0; }} .avatar-default {{ background:#5865f2; }}
.message-content {{ flex:1;min-width:0; }} .message-header {{ display:flex;align-items:baseline;gap:8px;margin-bottom:4px; }}
.author {{ font-weight:600;color:#fff; }} .timestamp {{ font-size:12px;color:#72767d; }} .message-body {{ word-wrap:break-word;white-space:pre-wrap; }}
.embed {{ background:#2f3136;border-left:4px solid #5865f2;padding:12px;margin-top:8px;border-radius:4px;max-width:520px; }}
.attachment {{ margin-top:8px;padding:8px;background:#2f3136;border-radius:4px;display:inline-block; }}
.attachment a {{ color:#00aff4;text-decoration:none; }} .footer {{ text-align:center;padding:20px;color:#72767d;font-size:12px;border-top:1px solid #2f3136;margin-top:20px; }}
</style></head><body>
<div class="header"><h1>📋 Ticket Transcript: {channel_name}</h1><div class="meta"><strong>Kategorie:</strong> {kategorie} | <strong>Betreff:</strong> {betreff} | <strong>Nachrichten:</strong> {len(messages)}</div></div>
<div class="container">{messages_html}</div>
<div class="footer">Generiert am {__import__('datetime').datetime.now().strftime('%d.%m.%Y %H:%M:%S')}</div>
</body></html>"""

        transcript_path = TRANSCRIPTS_DIR
        transcript_path.mkdir(parents=True, exist_ok=True)
        filename = f"ticket_{channel_id}.html"
        target = transcript_path / filename
        target.write_text(html_doc, encoding="utf-8")
        return str(target)
    except Exception as exc:
        logger.exception("Transcript error", exc_info=exc)
        return None


def send_ticket_to_n8n(ticket_number: int, channel_id: str, user_id: str, username: str, betreff: str, message: str):
    payload = json.dumps({
        "ticket_number": ticket_number,
        "channel_id": channel_id,
        "user_id": user_id,
        "username": username,
        "betreff": betreff,
        "message": message,
        "callback_url": "http://127.0.0.1:5681/ticket-callback",
    }).encode("utf-8")
    req = urllib.request.Request(N8N_WEBHOOK_URL, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            logger.info("n8n webhook OK: %s for ticket #%04d", resp.status, ticket_number)
    except urllib.error.URLError as exc:
        logger.warning("n8n webhook failed for ticket #%04d: %s", ticket_number, exc)


async def send_ticket_to_n8n_async(ticket_number: int, channel_id: str, user_id: str, username: str, betreff: str, message: str):
    await asyncio.to_thread(send_ticket_to_n8n, ticket_number, channel_id, user_id, username, betreff, message)


async def notify_owner_ticket(guild, ticket_number, channel_id, betreff, ai_verdict=""):
    if OWNER_ID == 0:
        return
    admin_log = guild.get_channel(ADMIN_LOG_CHANNEL_ID)
    if not admin_log:
        return
    title = f"Ticket #{ticket_number:04d}" + (" - AI Analyse" if ai_verdict else " erstellt")
    desc = f"Channel: <#{channel_id}>\nBetreff: {betreff}"
    if ai_verdict:
        desc += f"\n\n{ai_verdict}"
    embed = discord.Embed(title=title, description=desc[:4096], color=discord.Color.blue() if ai_verdict else discord.Color.orange())
    try:
        await admin_log.send(f"<@{OWNER_ID}>", embed=embed)
    except Exception as exc:
        logger.warning("Owner notify failed: %s", exc)
