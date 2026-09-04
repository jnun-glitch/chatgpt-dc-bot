"""Ticket-Helfer: Transcripts, n8n-Webhook, Owner-Benachrichtigung."""
import json
import urllib.request
import urllib.error
import asyncio
from core.config import BOT_DIR, OWNER_ID, ADMIN_LOG_CHANNEL_ID, N8N_WEBHOOK_URL
from core.db import get_db
from core.logging import logger

import discord


async def save_ticket_transcript(channel_id: str, guild):
    """Speichert ein HTML-Transcript des Tickets."""
    channel = guild.get_channel(int(channel_id))
    if not channel:
        return None
    try:
        messages = []
        async for msg in channel.history(limit=500, oldest_first=True):
            embeds_html = ''
            for embed in msg.embeds:
                embed_title = embed.title or ''
                embed_desc = embed.description or ''
                embeds_html += f'<div class="embed"><b>{embed_title}</b><br>{embed_desc}</div>'
            
            attachments = ''
            for att in msg.attachments:
                attachments += f'<div class="attachment">📎 <a href="{att.url}" target="_blank">{att.filename}</a></div>'
            
            messages.append({
                'author': str(msg.author.display_name),
                'avatar': str(msg.author.display_avatar.url) if msg.author.display_avatar else '',
                'content': msg.content,
                'embeds': embeds_html,
                'attachments': attachments,
                'timestamp': msg.created_at.strftime('%d.%m.%Y %H:%M:%S'),
                'is_bot': msg.author.bot,
            })
        
        betreff = channel.topic.split('|')[1].strip() if channel.topic and '|' in channel.topic else 'Kein Betreff'
        kategorie = 'Sonstiges'
        if channel.topic and 'Kategorie:' in channel.topic:
            try:
                kategorie = channel.topic.split('Kategorie:')[1].split('|')[0].strip()
            except (IndexError, ValueError):
                pass
        
        messages_html = ''
        for msg in messages:
            bot_class = ' bot-message' if msg['is_bot'] else ''
            embed_html = msg['embeds']
            attachment_html = msg['attachments']
            avatar_html = f'<img src="{msg["avatar"]}" class="avatar" alt="Avatar">' if msg['avatar'] else '<div class="avatar avatar-default"></div>'
            
            messages_html += f'''
            <div class="message{bot_class}">
                {avatar_html}
                <div class="message-content">
                    <div class="message-header">
                        <span class="author">{msg['author']}</span>
                        <span class="timestamp">{msg['timestamp']}</span>
                    </div>
                    <div class="message-body">{msg['content']}</div>
                    {embed_html}
                    {attachment_html}
                </div>
            </div>'''
        
        html = f'''<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ticket #{channel.name}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #36393f;
            color: #dcddde;
            line-height: 1.6;
        }}
        .header {{
            background: #202225;
            padding: 20px;
            border-bottom: 2px solid #5865f2;
            text-align: center;
        }}
        .header h1 {{ color: #5865f2; font-size: 24px; }}
        .header .meta {{ color: #72767d; margin-top: 8px; font-size: 14px; }}
        .container {{
            max-width: 900px;
            margin: 20px auto;
            padding: 0 20px;
        }}
        .message {{
            display: flex;
            padding: 12px 16px;
            margin: 4px 0;
            border-radius: 4px;
            transition: background 0.1s;
        }}
        .message:hover {{ background: #32353b; }}
        .bot-message {{ background: #2f3136; border-left: 3px solid #5865f2; }}
        .avatar {{
            width: 40px;
            height: 40px;
            border-radius: 50%;
            margin-right: 16px;
            flex-shrink: 0;
        }}
        .avatar-default {{
            background: #5865f2;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .message-content {{ flex: 1; min-width: 0; }}
        .message-header {{
            display: flex;
            align-items: baseline;
            gap: 8px;
            margin-bottom: 4px;
        }}
        .author {{
            font-weight: 600;
            color: #fff;
        }}
        .timestamp {{
            font-size: 12px;
            color: #72767d;
        }}
        .message-body {{
            word-wrap: break-word;
            white-space: pre-wrap;
        }}
        .embed {{
            background: #2f3136;
            border-left: 4px solid #5865f2;
            padding: 12px;
            margin-top: 8px;
            border-radius: 4px;
            max-width: 520px;
        }}
        .attachment {{
            margin-top: 8px;
            padding: 8px;
            background: #2f3136;
            border-radius: 4px;
            display: inline-block;
        }}
        .attachment a {{
            color: #00aff4;
            text-decoration: none;
        }}
        .attachment a:hover {{ text-decoration: underline; }}
        .footer {{
            text-align: center;
            padding: 20px;
            color: #72767d;
            font-size: 12px;
            border-top: 1px solid #2f3136;
            margin-top: 20px;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>📋 Ticket Transcript: {channel.name}</h1>
        <div class="meta">
            <strong>Kategorie:</strong> {kategorie} | 
            <strong>Betreff:</strong> {betreff} | 
            <strong>Nachrichten:</strong> {len(messages)} |
            <strong>Erstellt:</strong> {messages[0]['timestamp'] if messages else 'Unbekannt'}
        </div>
    </div>
    <div class="container">
        {messages_html}
    </div>
    <div class="footer">
        Generiert am {__import__('datetime').datetime.now().strftime('%d.%m.%Y %H:%M:%S')} | Ticket {channel.name}
    </div>
</body>
</html>'''
        
        transcript_path = BOT_DIR / 'transcripts'
        transcript_path.mkdir(exist_ok=True)
        filename = f'ticket_{channel_id}.html'
        with open(transcript_path / filename, 'w', encoding='utf-8') as f:
            f.write(html)
        return str(transcript_path / filename)
    except Exception as e:
        logger.error(f'Transcript error: {e}')
        return None


def send_ticket_to_n8n(ticket_number: int, channel_id: str, user_id: str, username: str, betreff: str, message: str):
    payload = json.dumps({
        'ticket_number': ticket_number,
        'channel_id': channel_id,
        'user_id': user_id,
        'username': username,
        'betreff': betreff,
        'message': message,
        'callback_url': 'http://127.0.0.1:5681/ticket-callback'
    }).encode('utf-8')

    req = urllib.request.Request(
        N8N_WEBHOOK_URL,
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        logger.info(f'n8n webhook OK: {resp.status} for ticket #{ticket_number:04d}')
    except urllib.error.URLError as e:
        logger.warning(f'n8n webhook failed for ticket #{ticket_number:04d}: {e}')


async def send_ticket_to_n8n_async(ticket_number: int, channel_id: str, user_id: str, username: str, betreff: str, message: str):
    """Async wrapper - blockiert den Bot NICHT."""
    await asyncio.to_thread(send_ticket_to_n8n, ticket_number, channel_id, user_id, username, betreff, message)


async def notify_owner_ticket(guild, ticket_number, channel_id, betreff, ai_verdict=''):
    """Pingt den Owner im Admin-Log Channel über neue Tickets."""
    if OWNER_ID == 0:
        return
    admin_log = guild.get_channel(ADMIN_LOG_CHANNEL_ID)
    if not admin_log:
        return
    title = f'Ticket #{ticket_number:04d}' + (' - AI Analyse' if ai_verdict else ' erstellt')
    desc = f'Channel: <#{channel_id}>\nBetreff: {betreff}'
    if ai_verdict:
        desc += f'\n\n{ai_verdict}'
    embed = discord.Embed(title=title, description=desc, color=discord.Color.blue() if ai_verdict else discord.Color.orange())
    try:
        await admin_log.send(f'<@{OWNER_ID}>', embed=embed)
    except Exception as e:
        logger.warning(f'Owner notify failed: {e}')
