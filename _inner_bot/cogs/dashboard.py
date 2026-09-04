"""Dashboard-Webinterface für den Bot-Owner – komplett überarbeitet."""
import asyncio
import json
import os
import secrets
import threading
import time as _time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from queue import Queue

import discord
from discord import app_commands
from discord.ext import commands
from flask import Flask, request, render_template, Blueprint, jsonify, Response

from core.config import OWNER_ID, BOT_DIR
from core.logging import logger
from core.db import get_db, get_command_usage, get_guild_config, set_guild_config, list_schematics

DATA_DIR = BOT_DIR.parent / 'data'
TOKEN_FILE = DATA_DIR / 'dashboard_token.txt'


def _load_dashboard_token() -> str:
    """Lädt das Dashboard-Token aus Env oder Token-Datei (erstellt es sonst)."""
    token = os.environ.get('DASHBOARD_TOKEN', '')
    if token:
        return token
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if TOKEN_FILE.exists():
            token = TOKEN_FILE.read_text(encoding='utf-8').strip()
            if token:
                return token
        token = secrets.token_urlsafe(32)
        TOKEN_FILE.write_text(token, encoding='utf-8')
        return token
    except Exception as e:
        logger.warning(f'Dashboard-Token laden fehlgeschlagen: {e}')
        return token


_DASHBOARD_TOKEN = _load_dashboard_token()


def _h(value) -> str:
    """HTML-escaping für alle dynamischen, server-gerenderten Inhalte (XSS-Schutz)."""
    return str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;').replace("'", '&#39;')


dashboard_bp = Blueprint('dashboard', __name__)

_bot = None
_start_time = None

# ── Message Buffer ─────────────────────────────────────────────────────────────
# Speichert die letzten 3000 Nachrichten für das Dashboard-Live-View.
_message_buffer: deque = deque(maxlen=3000)

# ── Audit Buffer ───────────────────────────────────────────────────────────────
_audit_events: deque = deque(maxlen=500)


def log_audit_event(event_type: str, data: dict):
    _audit_events.append({
        'type': event_type,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        **data,
    })


# ── SSE Live Stream ────────────────────────────────────────────────────────────
_sse_clients: list = []
_sse_lock = threading.Lock()


def _sse_broadcast(event_type: str, data: dict):
    msg = f'event: {event_type}\ndata: {json.dumps(data)}\n\n'
    with _sse_lock:
        dead = []
        for q in _sse_clients:
            try:
                q.put_nowait(msg)
            except Exception:
                dead.append(q)
        for d in dead:
            _sse_clients.remove(d)


def _store_message(message):
    """Speichert eine Nachricht im Puffer für das Dashboard."""
    if not message or message.author.bot:
        return
    entry = {
        'id': str(message.id),
        'channel_id': str(message.channel.id),
        'channel_name': getattr(message.channel, 'name', 'DM'),
        'guild_id': str(message.guild.id) if message.guild else None,
        'guild_name': message.guild.name if message.guild else 'DM',
        'author_id': str(message.author.id),
        'author_name': str(message.author),
        'author_avatar': str(message.author.display_avatar.url) if message.author.display_avatar else None,
        'content': message.content[:2000],
        'timestamp': message.created_at.isoformat(),
        'attachments': [a.url for a in message.attachments],
        'attachment_names': [a.filename for a in message.attachments],
        'embed_count': len(message.embeds),
        'edited': message.edited_at.isoformat() if message.edited_at else None,
    }
    _message_buffer.append(entry)
    _sse_broadcast('message', entry)


# ── Auto-Mute Loop ────────────────────────────────────────────────────────────
_auto_mutes: dict = {}


def _start_auto_mute(user_id: int, guild_id: int, user_name: str):
    if user_id in _auto_mutes and _auto_mutes[user_id].get('active'):
        return False
    # Check mute_immune.txt whitelist
    try:
        from core.muteimmune import is_mute_immune
        if is_mute_immune(user_id):
            return False  # User ist geschützt
    except Exception as e:
        logger.error(f'Fehler beim mute_immune-Check: {e}')
    _auto_mutes[user_id] = {'active': True, 'guild_id': guild_id, 'user_name': user_name}
    if _bot:
        asyncio.run_coroutine_threadsafe(_auto_mute_loop(user_id, guild_id), _bot.loop)
    return True


def _stop_auto_mute(user_id: int):
    if user_id in _auto_mutes:
        _auto_mutes[user_id]['active'] = False
        return True
    return False


async def _auto_mute_loop(user_id: int, guild_id: int):
    """Hält den Timeout eines Users kontinuierlich (Refresh alle 30 s statt 100 ms)."""
    while _auto_mutes.get(user_id, {}).get('active'):
        try:
            # Check mute_immune.txt whitelist each iteration
            from core.muteimmune import is_mute_immune
            if is_mute_immune(user_id):
                _auto_mutes[user_id]['active'] = False
                break

            guild = _bot.get_guild(guild_id)
            if not guild:
                break
            member = guild.get_member(user_id)
            if not member:
                break
            import datetime as _dt
            until = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=24)
            await member.timeout(until, reason='Auto-Mute Loop aktiv')
            log_audit_event('fullmute', {
                'executor': 'Auto-Mute-Loop',
                'target': str(member),
                'reason': 'Kontinuierlicher Auto-Mute',
            })
        except discord.Forbidden:
            logger.error(f'Auto-Mute: Keine Berechtigung für User {user_id}')
            _auto_mutes[user_id]['active'] = False
            break
        except Exception as e:
            logger.error(f'Auto-Mute Loop Fehler (User {user_id}): {e}')
        await asyncio.sleep(30)

# ── Token ──────────────────────────────────────────────────────────────────────


# ── CSS ────────────────────────────────────────────────────────────────────────

CSS = """
:root{--bg:#0b0e14;--bg2:#111620;--card:#151c28;--card2:#1a2233;--border:#1e2a3d;--border2:#2a3a52;
--text:#d4dae6;--text2:#6b7a94;--text3:#4a5568;--accent:#5b9cf5;--accent2:#3d7dd4;--green:#2ecc71;
--red:#e74c3c;--yellow:#f1c40f;--purple:#9b59b6;--cyan:#1abc9c;--pink:#e91e63;--orange:#e67e22;}
*{margin:0;padding:0;box-sizing:border-box;}
body{background:var(--bg);color:var(--text);font-family:'Inter','Segoe UI',system-ui,sans-serif;line-height:1.5;}
.container{max-width:1200px;margin:0 auto;padding:20px;}
a{color:var(--accent);text-decoration:none;}
a:hover{text-decoration:underline;}
h1{font-size:1.6rem;font-weight:700;margin-bottom:20px;display:flex;align-items:center;gap:10px;}
h1 span{font-size:1.8rem;}
h2{font-size:1.1rem;font-weight:600;color:var(--text);margin-bottom:12px;}

/* NAV */
.nav{display:flex;gap:4px;margin-bottom:24px;background:var(--card);border:1px solid var(--border);
border-radius:12px;padding:4px;flex-wrap:wrap;}
.nav a{padding:10px 18px;border-radius:8px;font-weight:500;font-size:0.9rem;color:var(--text2);
transition:all .15s;display:flex;align-items:center;gap:6px;}
.nav a:hover{background:var(--card2);color:var(--text);text-decoration:none;}
.nav a.active{background:var(--accent);color:#fff;}

/* CARDS */
.card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px;margin-bottom:16px;}
.card-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;}

/* STATS */
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:20px;}
.stat{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:18px;text-align:center;
transition:border-color .2s;}
.stat:hover{border-color:var(--accent);}
.stat .val{font-size:2rem;font-weight:700;background:linear-gradient(135deg,var(--accent),var(--purple));
-webkit-background-clip:text;-webkit-text-fill-color:transparent;}
.stat .lbl{color:var(--text2);font-size:0.8rem;margin-top:4px;text-transform:uppercase;letter-spacing:0.5px;}

/* TABLE */
table{width:100%;border-collapse:collapse;}
th{text-align:left;padding:10px 14px;color:var(--text2);font-weight:600;font-size:0.8rem;
text-transform:uppercase;letter-spacing:0.5px;border-bottom:2px solid var(--border);}
td{padding:10px 14px;border-bottom:1px solid var(--border);font-size:0.9rem;}
tr:hover{background:rgba(91,156,245,0.04);}

/* BADGES */
.badge{display:inline-block;padding:3px 10px;border-radius:20px;font-size:0.75rem;font-weight:600;}
.badge-green{background:rgba(46,204,113,0.15);color:var(--green);}
.badge-red{background:rgba(231,76,60,0.15);color:var(--red);}
.badge-yellow{background:rgba(241,196,15,0.15);color:var(--yellow);}
.badge-purple{background:rgba(155,89,182,0.15);color:var(--purple);}
.badge-cyan{background:rgba(26,188,156,0.15);color:var(--cyan);}

/* LOG */
.log-entry{font-family:'Cascadia Code','Fira Code',monospace;font-size:0.78rem;padding:4px 8px;
border-bottom:1px solid var(--border);color:var(--text2);border-radius:4px;}
.log-entry:hover{background:var(--card2);}
.log-entry .time{color:var(--text3);}
.log-entry .lvl-INFO{color:var(--green);}
.log-entry .lvl-WARNING{color:var(--yellow);}
.log-entry .lvl-ERROR{color:var(--red);}
.log-entry .lvl-CRITICAL{color:var(--red);font-weight:700;}
.empty{color:var(--text3);font-style:italic;padding:24px;text-align:center;}

/* FORMS */
select,input[type=text],textarea{background:var(--bg2);border:1px solid var(--border);color:var(--text);
padding:8px 12px;border-radius:8px;font-size:0.9rem;width:100%;}
select:focus,input:focus,textarea:focus{outline:none;border-color:var(--accent);}
button,.btn{background:var(--accent);color:#fff;border:none;padding:10px 20px;border-radius:8px;
cursor:pointer;font-weight:600;font-size:0.9rem;transition:all .15s;}
button:hover,.btn:hover{background:var(--accent2);transform:translateY(-1px);}

/* MEMBER LIST */
.member{display:flex;align-items:center;gap:10px;padding:8px 12px;border-bottom:1px solid var(--border);}
.member:last-child{border-bottom:none;}
.member img{width:32px;height:32px;border-radius:50%;}
.member .name{font-weight:500;}
.member .id{color:var(--text3);font-size:0.8rem;}
.member .roles{display:flex;gap:4px;flex-wrap:wrap;margin-left:auto;}
.role-dot{width:12px;height:12px;border-radius:50%;display:inline-block;}

/* CHANNEL LIST */
.ch-item{display:flex;align-items:center;gap:10px;padding:10px 14px;border-bottom:1px solid var(--border);}
.ch-item:last-child{border-bottom:none;}
.ch-icon{font-size:1.2rem;width:24px;text-align:center;}
.ch-name{font-weight:500;}
.ch-cat{color:var(--text3);font-size:0.8rem;margin-left:auto;}

/* SCHEMATIC */
.schem-card{background:var(--card2);border:1px solid var(--border);border-radius:10px;padding:14px;
display:flex;align-items:center;gap:14px;margin-bottom:8px;}
.schem-card:hover{border-color:var(--accent);}
.schem-icon{font-size:2rem;width:48px;text-align:center;}
.schem-info{flex:1;}
.schem-name{font-weight:600;font-size:1rem;}
.schem-meta{color:var(--text2);font-size:0.8rem;margin-top:2px;}
"""

NAV = """
<div class="nav">
  <a href="/" class="{c1}">📊 Übersicht</a>
  <a href="/editor" class="{c15}">📝 Editor</a>
  <a href="/messages" class="{c9}">💬 Nachrichten</a>
  <a href="/exec" class="{c10}">⚡ Executor</a>
  <a href="/guilds" class="{c2}">🏠 Server</a>
  <a href="/members" class="{c3}">👥 Members</a>
  <a href="/logs" class="{c5}">📋 Logs</a>
  <a href="/commands" class="{c6}">📈 Cmd Stats</a>
  <a href="/config" class="{c8}">⚙️ Config</a>
  <a href="/enforce" class="{c11}">🛡️ Enforce</a>
  <a href="/audit" class="{c12}">📋 Audit</a>
</div>"""

def _layout(title, token, body, active=''):
    nav = NAV.format(t=token,
        c1='active' if active=='home' else '',
        c2='active' if active=='guilds' else '',
        c3='active' if active=='members' else '',
        c4='active' if active=='channels' else '',
        c5='active' if active=='logs' else '',
        c6='active' if active=='commands' else '',
        c7='active' if active=='schematics' else '',
        c8='active' if active=='config' else '',
        c9='active' if active=='messages' else '',
        c10='active' if active=='exec' else '',
        c11='active' if active=='enforce' else '',
        c12='active' if active=='audit' else '',
        c13='active' if active=='manage-channels' else '',
        c14='active' if active=='manage-roles' else '',
        c15='active' if active=='editor' else '',
    )
    return f"""<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} – ScratchAI Dashboard</title><style>{CSS}</style></head>
<body><div class="container">
<h1><span>🤖</span> ScratchAI Dashboard</h1>
{nav}
{body}
<p style="color:var(--text3);font-size:0.75rem;margin-top:32px;text-align:center;">
Generiert um {datetime.now().strftime('%H:%M:%S')}</p>
</div></body></html>"""

# ── Auth ───────────────────────────────────────────────────────────────────────

@dashboard_bp.before_request
def _auth():
    if request.remote_addr not in ('127.0.0.1', '::1'):
        return '<!DOCTYPE html><html><body style="background:#0b0e14;color:#d4dae6;font-family:system-ui;display:flex;justify-content:center;align-items:center;height:100vh"><div style="text-align:center"><h1 style="color:#e74c3c;font-size:3rem">⛔</h1><h2>Zugriff verweigert</h2><p style="color:#6b7a94">Nur lokal über 127.0.0.1 zugänglich.</p></div></body></html>', 403
    # API-Routen zusätzlich per Token absichern (Cookie wird von den Seiten gesetzt)
    if request.path.startswith('/api/') and _DASHBOARD_TOKEN:
        tok = request.headers.get('X-Dashboard-Token') or request.cookies.get('dash_token')
        if not tok or tok != _DASHBOARD_TOKEN:
            return jsonify(ok=False, error='Ungültiges Dashboard-Token'), 403


@dashboard_bp.after_request
def _set_token_cookie(response):
    """Setzt das Token-Cookie auf Seitenantworten, damit API-Calls es mitsenden."""
    if not request.path.startswith('/api/') and _DASHBOARD_TOKEN:
        response.set_cookie('dash_token', _DASHBOARD_TOKEN, httponly=True, samesite='Lax')
    return response

# ── Routes ─────────────────────────────────────────────────────────────────────

@dashboard_bp.route('/')
def index():
    return render_template('dashboard.html')


@dashboard_bp.route('/guilds')
def guilds():
    token = ''
    bot = _bot
    if not bot:
        return _layout('Server', token, '<div class="card empty">Bot nicht verbunden.</div>', 'guilds')

    rows = ''
    for g in sorted(bot.guilds, key=lambda x: x.member_count or 0, reverse=True):
        owner = g.owner.display_name if g.owner else '–'
        rows += f"""<tr>
          <td><b>{_h(g.name)}</b></td><td style="color:var(--text3)">{g.id}</td>
          <td>{g.member_count or 0}</td><td>{len(g.channels)}</td>
          <td>{len(g.roles)}</td><td>{_h(owner)}</td></tr>"""

    body = f"""<div class="card"><h2>🏠 Server ({len(bot.guilds)})</h2>
    <table><thead><tr><th>Name</th><th>ID</th><th>Members</th><th>Kanäle</th><th>Rollen</th><th>Owner</th></tr></thead>
    <tbody>{rows}</tbody></table></div>"""
    return _layout('Server', token, body, 'guilds')


@dashboard_bp.route('/members')
def members():
    token = ''
    bot = _bot
    if not bot:
        return _layout('Members', token, '<div class="card empty">Bot nicht verbunden.</div>', 'members')

    gid = request.args.get('guild_id', '')
    guild = None
    if gid:
        guild = bot.get_guild(int(gid))
    if not guild and bot.guilds:
        guild = bot.guilds[0]

    guild_opts = ''.join(
        f'<option value="{g.id}" {"selected" if guild and g.id==guild.id else ""}>{_h(g.name)}</option>'
        for g in bot.guilds
    )

    member_rows = ''
    if guild:
        for m in sorted(guild.members, key=lambda x: x.joined_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)[:100]:
            roles_html = ''.join(
                f'<span class="role-dot" style="background:{"#"+str(r.color) if r.color.value else "#6b7a94"}" title="{_h(r.name)}"></span>'
                for r in m.roles[:8] if r != guild.default_role
            )
            status = '🟢' if str(m.status) == 'online' else '🟡' if str(m.status) == 'idle' else '🔴'
            member_rows += f"""<div class="member">
              <img src="{m.display_avatar.url}" alt="">
              <div><div class="name">{status} {_h(m.display_name)}</div>
              <div class="id">{m.id} · {'Bot' if m.bot else 'User'}</div></div>
              <div class="roles">{roles_html}</div></div>"""
        if not member_rows:
            member_rows = '<div class="empty">Keine Members gefunden.</div>'

    body = f"""
    <div class="card"><h2>👥 Members</h2>
    <form method="GET" style="margin-bottom:16px;display:flex;gap:8px;align-items:end">
      <div style="flex:1"><label style="color:var(--text2);font-size:0.8rem">Server</label>
      <select name="guild_id" onchange="this.form.submit()">{guild_opts}</select></div>
    </form>
    {member_rows}</div>"""
    return _layout('Members', token, body, 'members')


@dashboard_bp.route('/channels')
def channels():
    token = ''
    bot = _bot
    if not bot:
        return _layout('Kanäle', token, '<div class="card empty">Bot nicht verbunden.</div>', 'channels')

    gid = request.args.get('guild_id', '')
    guild = None
    if gid:
        guild = bot.get_guild(int(gid))
    if not guild and bot.guilds:
        guild = bot.guilds[0]

    guild_opts = ''.join(
        f'<option value="{g.id}" {"selected" if guild and g.id==guild.id else ""}>{g.name}</option>'
        for g in bot.guilds
    )

    ch_rows = ''
    if guild:
        for ch in guild.channels:
            if isinstance(ch, discord.CategoryChannel):
                continue
            icon = '💬' if isinstance(ch, discord.TextChannel) else '🔊' if isinstance(ch, discord.VoiceChannel) else '📁'
            cat = ch.category.name if ch.category else '–'
            members = len(ch.members) if isinstance(ch, discord.VoiceChannel) else '–'
            ch_rows += f"""<div class="ch-item">
              <span class="ch-icon">{icon}</span>
              <span class="ch-name">{_h(ch.name)}</span>
              <span class="ch-cat">{_h(cat)}</span></div>"""
        if not ch_rows:
            ch_rows = '<div class="empty">Keine Kanäle gefunden.</div>'

    body = f"""
    <div class="card"><h2>💬 Kanäle ({len(guild.text_channels) if guild else 0} Text / {len(guild.voice_channels) if guild else 0} Voice)</h2>
    <form method="GET" style="margin-bottom:16px;display:flex;gap:8px;align-items:end">
      <div style="flex:1"><label style="color:var(--text2);font-size:0.8rem">Server</label>
      <select name="guild_id" onchange="this.form.submit()">{guild_opts}</select></div>
    </form>
    {ch_rows}</div>"""
    return _layout('Kanäle', token, body, 'channels')


@dashboard_bp.route('/logs')
def logs():
    token = ''
    log_file = BOT_DIR / 'bot.log'
    lines = []
    if log_file.exists():
        try:
            raw = log_file.read_text(encoding='utf-8', errors='replace')
            lines = raw.strip().splitlines()[-150:]
        except Exception as e:
            logger.warning(f'Dashboard /logs: bot.log lesen fehlgeschlagen: {e}')

    entries = ''
    for line in lines:
        lvl = ''
        for l in ('CRITICAL','ERROR','WARNING','INFO','DEBUG'):
            if l in line:
                lvl = l; break
        esc = line.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
        entries += f'<div class="log-entry"><span class="lvl-{lvl}">{esc}</span></div>'
    if not entries:
        entries = '<div class="empty">Keine Logs gefunden.</div>'

    body = f"""<div class="card"><h2>📋 Letzte 150 Log-Zeilen</h2>
    <div style="max-height:500px;overflow-y:auto">{entries}</div></div>"""
    return _layout('Logs', token, body, 'logs')


@dashboard_bp.route('/commands')
def commands_page():
    token = ''
    usage = get_command_usage(50)
    total = sum(r['used'] for r in usage)

    rows = ''
    for i, r in enumerate(usage, 1):
        pct = (r['used'] / total * 100) if total else 0
        rows += f"""<tr><td>{i}</td><td><code>{r["command"]}</code></td>
        <td><b>{r["used"]}</b></td><td>{pct:.1f}%</td>
        <td style="color:var(--text3)">{(r["last_used"] or "")[:16]}</td></tr>"""
    if not rows:
        rows = '<tr><td colspan="5" class="empty">Keine Daten.</td></tr>'

    body = f"""
    <div class="stats">
      <div class="stat"><div class="val">{len(usage)}</div><div class="lbl">Commands</div></div>
      <div class="stat"><div class="val">{total}</div><div class="lbl">Gesamt</div></div>
    </div>
    <div class="card"><h2>⚡ Command-Statistiken</h2>
    <table><thead><tr><th>#</th><th>Command</th><th>Aufrufe</th><th>Anteil</th><th>Zuletzt</th></tr></thead>
    <tbody>{rows}</tbody></table></div>"""
    return _layout('Commands', token, body, 'commands')


@dashboard_bp.route('/schematics')
def schematics():
    token = ''
    schems = list_schematics(100)

    cards = ''
    for s in schems:
        size = int(s.get('file_size', 0) or 0)
        if size >= 1024*1024:
            size_txt = f'{size/(1024*1024):.1f} MB'
        else:
            size_txt = f'{size//1024} KB'
        cards += f"""<div class="schem-card">
          <div class="schem-icon">🧩</div>
          <div class="schem-info">
            <div class="schem-name">{_h(s['name'])}</div>
            <div class="schem-meta">{size_txt} · {_h(s.get('uploaded_by', '–'))} · {_h((s.get('description') or ''))[:80]}</div>
          </div></div>"""
    if not cards:
        cards = '<div class="empty">Noch keine Schematics. Nutze /schematics add im Discord.</div>'

    body = f"""<div class="card"><h2>🏗️ Schematics-Bibliothek ({len(schems)})</h2>{cards}</div>"""
    return _layout('Schematics', token, body, 'schematics')


@dashboard_bp.route('/config', methods=['GET','POST'])
def config():
    token = ''
    bot = _bot
    msg = ''

    if request.method == 'POST':
        gid = request.form.get('guild_id','').strip()
        key = request.form.get('key','').strip()
        value = request.form.get('value','').strip()
        if gid and key:
            try:
                set_guild_config(int(gid), key, value if value else None)
                msg = f'<div class="card" style="border-color:var(--green)">✅ {key} aktualisiert.</div>'
            except Exception as e:
                msg = f'<div class="card" style="border-color:var(--red)">❌ {e}</div>'

    guild_opts = ''.join(f'<option value="{g.id}">{_h(g.name)}</option>' for g in (bot.guilds if bot else []))
    sel = request.args.get('guild_id','')
    cfg_html = ''
    if sel:
        try:
            cfg = get_guild_config(int(sel))
            if cfg:
                rows = ''.join(f'<tr><td><code>{_h(k)}</code></td><td>{_h(v) if v else "–"}</td></tr>' for k,v in cfg.items())
                cfg_html = f"""<div class="card"><h2>Aktuelle Config</h2>
                <table><thead><tr><th>Key</th><th>Wert</th></tr></thead><tbody>{rows}</tbody></table></div>"""
        except Exception as e:
            logger.warning(f'Dashboard Config: Guild-Config laden fehlgeschlagen: {e}')

    body = f"""{msg}
    <div class="card"><h2>⚙️ Config bearbeiten</h2>
    <form method="POST" style="display:flex;gap:10px;flex-wrap:wrap;align-items:end;margin-top:12px">
      <div style="flex:1;min-width:200px"><label style="color:var(--text2);font-size:0.8rem">Guild</label>
        <select name="guild_id">{guild_opts}</select></div>
      <div style="flex:1;min-width:200px"><label style="color:var(--text2);font-size:0.8rem">Key</label>
        <input type="text" name="key" placeholder="welcome_channel_id" required></div>
      <div style="flex:1;min-width:200px"><label style="color:var(--text2);font-size:0.8rem">Wert</label>
        <input type="text" name="value"></div>
      <button type="submit">Speichern</button>
    </form></div>{cfg_html}"""
    return _layout('Config', token, body, 'config')


# ── API ────────────────────────────────────────────────────────────────────────

@dashboard_bp.route('/api/messages')
def api_messages():
    channel_id = request.args.get('channel_id', '')
    guild_id = request.args.get('guild_id', '')
    limit = min(int(request.args.get('limit', 100)), 500)
    msgs = list(_message_buffer)
    if guild_id:
        msgs = [m for m in msgs if m['guild_id'] == guild_id]
    if channel_id:
        msgs = [m for m in msgs if m['channel_id'] == channel_id]
    return jsonify(msgs[-limit:])


@dashboard_bp.route('/api/channels')
def api_channels():
    guild_id = request.args.get('guild_id', '')
    if not _bot:
        return jsonify([])
    guild = _bot.get_guild(int(guild_id)) if guild_id else None
    if not guild:
        guilds = _bot.guilds
        channels = []
        for g in guilds:
            for ch in g.text_channels:
                channels.append({
                    'id': str(ch.id),
                    'name': f'{g.name} / #{ch.name}',
                    'guild_id': str(g.id),
                    'guild_name': g.name,
                    'type': 'text',
                })
        return jsonify(channels[:100])
    channels = []
    for ch in guild.text_channels:
        channels.append({
            'id': str(ch.id),
            'name': f'#{ch.name}',
            'guild_id': str(guild.id),
            'guild_name': guild.name,
            'type': 'text',
        })
    return jsonify(channels)


@dashboard_bp.route('/api/guilds')
def api_guilds():
    if not _bot:
        return jsonify([])
    return jsonify([{
        'id': str(g.id),
        'name': g.name,
        'member_count': g.member_count or 0,
    } for g in _bot.guilds])


@dashboard_bp.route('/api/send', methods=['POST'])
def api_send():
    data = request.json or {}
    channel_id = data.get('channel_id', '').strip()
    content = data.get('content', '').strip()
    if not channel_id or not content:
        return jsonify({'ok': False, 'error': 'channel_id und content erforderlich'}), 400
    if not _bot:
        return jsonify({'ok': False, 'error': 'Bot nicht verbunden'}), 503
    channel = _bot.get_channel(int(channel_id))
    if not channel:
        return jsonify({'ok': False, 'error': f'Kanal {channel_id} nicht gefunden'}), 404
    try:
        future = asyncio.run_coroutine_threadsafe(channel.send(content), _bot.loop)
        result = future.result(timeout=15)
        return jsonify({'ok': True, 'message_id': str(result.id)})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@dashboard_bp.route('/api/exec', methods=['POST'])
def api_exec():
    data = request.json or {}
    requestor_id = int(data.get('requestor_id', 0) or 0)
    if OWNER_ID and requestor_id != OWNER_ID:
        return jsonify({'ok': False, 'error': 'Nur der Owner darf Command-Infos abrufen.'}), 403
    command_name = data.get('command', '').strip().lower()
    args_str = data.get('args', '').strip()
    guild_id = data.get('guild_id', '')
    channel_id = data.get('channel_id', '')
    if not command_name:
        return jsonify({'ok': False, 'error': 'Command-Name erforderlich'}), 400
    if not _bot:
        return jsonify({'ok': False, 'error': 'Bot nicht verbunden'}), 503
    # Versuche Slash-Command über tree
    cmd = _bot.tree.get_command(command_name)
    if cmd:
        return jsonify({
            'ok': True,
            'type': 'slash',
            'info': f'Slash-Command `/{command_name}` gefunden. Nutze den Discord-Client zur Ausführung.',
            'params': [p.name for p in cmd.parameters] if hasattr(cmd, 'parameters') else [],
        })
    # Versuche Text-Command
    text_cmd = _bot.get_command(command_name)
    if text_cmd:
        return jsonify({
            'ok': True,
            'type': 'text',
            'info': f'Text-Command `!{command_name}` gefunden.',
            'usage': str(text_cmd.signature) if hasattr(text_cmd, 'signature') else '',
        })
    return jsonify({'ok': False, 'error': f'Command `{command_name}` nicht gefunden'}), 404


@dashboard_bp.route('/api/stats')
def api_stats():
    if not _bot:
        return jsonify({})
    guilds = _bot.guilds
    members = sum(g.member_count or 0 for g in guilds)
    channels = sum(len(g.channels) for g in guilds)
    uptime = ''
    if _start_time:
        d = datetime.now(timezone.utc) - _start_time
        h, rem = divmod(d.seconds, 3600)
        m, s = divmod(rem, 60)
        uptime = f'{d.days}d {h}h {m}m'
    return jsonify({
        'guilds': len(guilds),
        'members': members,
        'channels': channels,
        'uptime': uptime,
        'messages_buffered': len(_message_buffer),
        'latency': f'{_bot.latency * 1000:.0f}ms' if _bot else '–',
    })


@dashboard_bp.route('/api/audit')
def api_audit():
    limit = int(request.args.get('limit', 100))
    evts = list(_audit_events)[-limit:]
    evts.reverse()
    return jsonify(evts)


@dashboard_bp.route('/api/audit/all')
def api_audit_all():
    limit = int(request.args.get('limit', 100))
    evts = list(_audit_events)[-limit:]
    evts.reverse()
    return jsonify(evts)


@dashboard_bp.route('/api/sse')
def api_sse():
    q = Queue()
    with _sse_lock:
        _sse_clients.append(q)

    def stream():
        try:
            yield 'event: connected\ndata: {}\n\n'
            while True:
                try:
                    msg = q.get(timeout=30)
                    yield msg
                except Exception:
                    yield ': keepalive\n\n'
        except GeneratorExit:
            pass
        finally:
            with _sse_lock:
                if q in _sse_clients:
                    _sse_clients.remove(q)

    return Response(stream(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@dashboard_bp.route('/api/automute/start', methods=['POST'])
def api_automute_start():
    data = request.get_json(force=True)
    user_id = int(data.get('user_id', 0))
    guild_id = int(data.get('guild_id', 0))
    user_name = data.get('user_name', '?')
    if not user_id or not guild_id:
        return jsonify(ok=False, error='user_id und guild_id erforderlich'), 400
    # Check mute_immune.txt
    try:
        from core.muteimmune import is_mute_immune
        if is_mute_immune(user_id):
            return jsonify(ok=False, error='User ist vor Auto-Mute geschützt (mute_immune.txt)', protected=True)
    except Exception as e:
        logger.error(f'Fehler beim mute_immune-Check: {e}')
    ok = _start_auto_mute(user_id, guild_id, user_name)
    return jsonify(ok=True, started=ok, user_id=user_id)


@dashboard_bp.route('/api/automute/stop', methods=['POST'])
def api_automute_stop():
    data = request.get_json(force=True)
    user_id = int(data.get('user_id', 0))
    if not user_id:
        return jsonify(ok=False, error='user_id erforderlich'), 400
    ok = _stop_auto_mute(user_id)
    return jsonify(ok=True, stopped=ok, user_id=user_id)


@dashboard_bp.route('/api/automute/status')
def api_automute_status():
    active = {str(k): v for k, v in _auto_mutes.items() if v.get('active')}
    return jsonify(active=active, count=len(active))


# ── Messages Page ──────────────────────────────────────────────────────────────

@dashboard_bp.route('/messages')
def messages_page():
    token = ''
    body = """
    <style>
    .msg-wrap{display:flex;gap:12px;height:calc(100vh - 180px);min-height:500px;}
    .msg-side{width:260px;flex-shrink:0;}
    .msg-center{flex:1;display:flex;flex-direction:column;}
    .msg-list{flex:1;overflow-y:auto;background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:10px;display:flex;flex-direction:column;gap:1px;}
    .msg-row{display:flex;gap:8px;padding:5px 8px;border-radius:6px;}
    .msg-row:hover{background:var(--card2);}
    .msg-av{width:32px;height:32px;border-radius:50%;flex-shrink:0;}
    .msg-bd{flex:1;min-width:0;}
    .msg-hd{display:flex;align-items:baseline;gap:6px;}
    .msg-au{font-weight:600;font-size:0.85rem;color:var(--accent);}
    .msg-tm{font-size:0.68rem;color:var(--text3);}
    .msg-ct{font-size:0.85rem;color:var(--text);word-wrap:break-word;white-space:pre-wrap;margin-top:1px;}
    .msg-at{margin-top:3px;}
    .msg-at a{font-size:0.78rem;color:var(--accent);background:var(--card2);padding:1px 6px;border-radius:3px;margin-right:3px;}
    .msg-em{font-size:0.72rem;color:var(--purple);margin-top:1px;}
    .msg-send{display:flex;gap:6px;margin-top:10px;}
    .ch-sel{padding:6px 10px;border-radius:6px;background:var(--bg2);border:1px solid var(--border);color:var(--text);font-size:0.85rem;}
    .ch-item2{padding:7px 10px;cursor:pointer;border-radius:6px;font-size:0.82rem;color:var(--text2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
    .ch-item2:hover{background:var(--card2);color:var(--text);}
    .ch-item2.act{background:var(--accent);color:#fff;}
    .status-bar{display:flex;gap:12px;font-size:0.72rem;color:var(--text3);margin-bottom:6px;}
    </style>

    <div class="msg-wrap">
      <div class="msg-side">
        <div class="card" style="height:100%;display:flex;flex-direction:column;padding:10px;overflow:hidden;">
          <h2 style="margin-bottom:6px;font-size:0.95rem;">📡 Kanäle</h2>
          <select id="guildSel" class="ch-sel" onchange="loadCh()" style="margin-bottom:6px;"><option value="">Alle Server</option></select>
          <div id="chList" style="flex:1;overflow-y:auto;"></div>
        </div>
      </div>
      <div class="msg-center">
        <div class="card" style="flex:1;display:flex;flex-direction:column;padding:10px;overflow:hidden;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
            <h2 id="chTitle" style="margin:0;font-size:0.95rem;">💬 Nachrichten</h2>
            <div class="status-bar"><span id="mCnt">0</span><span id="mUpd">–</span></div>
          </div>
          <div id="msgBox" class="msg-list"></div>
          <div class="msg-send">
            <select id="sendCh" class="ch-sel" style="flex:1;"></select>
            <input type="text" id="sendIn" placeholder="Nachricht eingeben..." style="flex:2;background:var(--bg2);border:1px solid var(--border);color:var(--text);padding:8px 12px;border-radius:8px;font-size:0.88rem;" onkeydown="if(event.key==='Enter'){doSend();event.preventDefault();}">
            <button onclick="doSend()" style="padding:8px 16px;">📤</button>
          </div>
        </div>
      </div>
    </div>

    <script>
    let selCh='',chans=[];
    async function A(u){return(await fetch(u)).json();}
    function H(s){return s?s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'):'';}

    async function loadG(){
      const g=await A('/api/guilds');
      const s=document.getElementById('guildSel');
      g.forEach(x=>{const o=document.createElement('option');o.value=x.id;o.textContent=x.name;s.appendChild(o);});
      loadCh();
    }
    async function loadCh(){
      const gid=document.getElementById('guildSel').value;
      chans=await A('/api/channels'+(gid?'?guild_id='+gid:''));
      const cl=document.getElementById('chList'),ss=document.getElementById('sendCh');
      cl.innerHTML='';ss.innerHTML='';
      chans.forEach(c=>{
        const d=document.createElement('div');d.className='ch-item2'+(c.id===selCh?' act':'');
        d.textContent=c.name;d.onclick=()=>pickCh(c.id,c.name);cl.appendChild(d);
        const o=document.createElement('option');o.value=c.id;o.textContent=c.name;ss.appendChild(o);
      });
      if(!selCh&&chans.length>0)pickCh(chans[0].id,chans[0].name);
      loadMsg();
    }
    function pickCh(id,nm){
      selCh=id;document.getElementById('chTitle').textContent='💬 '+nm;
      document.querySelectorAll('.ch-item2').forEach(e=>e.classList.remove('act'));
      if(event&&event.target)event.target.classList.add('act');
      loadMsg();
    }
    async function loadMsg(){
      if(!selCh)return;
      const ms=await A('/api/messages?channel_id='+selCh+'&limit=200');
      const box=document.getElementById('msgBox');
      const atBot=box.scrollHeight-box.scrollTop-box.clientHeight<60;
      box.innerHTML=ms.map(m=>{
        const t=new Date(m.timestamp);
        const ts=t.toLocaleTimeString('de-DE',{hour:'2-digit',minute:'2-digit'});
        const av=m.author_avatar||'https://cdn.discordapp.com/embed/avatars/0.png';
        let ct=H(m.content).replace(/\\n/g,'<br>');
        let att='';
        if(m.attachment_names&&m.attachment_names.length>0){
          att='<div class="msg-at">'+m.attachment_names.map((n,i)=>'<a href="'+(m.attachments[i]||'#')+'" target="_blank">📎 '+H(n)+'</a>').join('')+'</div>';
        }
        let em=m.embed_count>0?'<div class="msg-em">📎 '+m.embed_count+' Embed</div>':'';
        return '<div class="msg-row"><img class="msg-av" src="'+av+'" onerror="this.src=\'https://cdn.discordapp.com/embed/avatars/0.png\'"><div class="msg-bd"><div class="msg-hd"><span class="msg-au">'+H(m.author_name)+'</span><span class="msg-tm">'+ts+'</span></div><div class="msg-ct">'+ct+'</div>'+att+em+'</div></div>';
      }).join('');
      document.getElementById('mCnt').textContent=ms.length+' Nachrichten';
      document.getElementById('mUpd').textContent='🔄 '+new Date().toLocaleTimeString('de-DE');
      if(atBot)box.scrollTop=box.scrollHeight;
    }
    function appendMsg(m){
      if(selCh&&m.channel_id!==selCh)return;
      const box=document.getElementById('msgBox');
      const atBot=box.scrollHeight-box.scrollTop-box.clientHeight<60;
      const t=new Date(m.timestamp);
      const ts=t.toLocaleTimeString('de-DE',{hour:'2-digit',minute:'2-digit'});
      const av=m.author_avatar||'https://cdn.discordapp.com/embed/avatars/0.png';
      let ct=H(m.content).replace(/\\n/g,'<br>');
      let att='';
      if(m.attachment_names&&m.attachment_names.length>0){
        att='<div class="msg-at">'+m.attachment_names.map((n,i)=>'<a href="'+(m.attachments[i]||'#')+'" target="_blank">📎 '+H(n)+'</a>').join('')+'</div>';
      }
      let em=m.embed_count>0?'<div class="msg-em">📎 '+m.embed_count+' Embed</div>':'';
      const div=document.createElement('div');
      div.className='msg-row';
      div.innerHTML='<img class="msg-av" src="'+av+'" onerror="this.src=\'https://cdn.discordapp.com/embed/avatars/0.png\'"><div class="msg-bd"><div class="msg-hd"><span class="msg-au">'+H(m.author_name)+'</span><span class="msg-tm">'+ts+'</span></div><div class="msg-ct">'+ct+'</div>'+att+em+'</div></div>';
      box.appendChild(div);
      const cnt=box.querySelectorAll('.msg-row').length;
      document.getElementById('mCnt').textContent=cnt+' Nachrichten';
      document.getElementById('mUpd').textContent='🔴 LIVE '+new Date().toLocaleTimeString('de-DE');
      if(atBot)box.scrollTop=box.scrollHeight;
    }
    function connectSSE(){
      const es=new EventSource('/api/sse');
      es.addEventListener('message',e=>{try{appendMsg(JSON.parse(e.data));}catch(x){}});
      es.onerror=()=>{setTimeout(connectSSE,3000);};
    }
    async function doSend(){
      const inp=document.getElementById('sendIn'),ch=document.getElementById('sendCh').value;
      const ct=inp.value.trim();if(!ct||!ch)return;
      const r=await fetch('/api/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({channel_id:ch,content:ct})});
      const d=await r.json();if(d.ok){inp.value='';setTimeout(loadMsg,500);}else{alert(d.error||'Fehler');}
    }
    loadG();connectSSE();
    </script>
    """
    return _layout('Nachrichten', token, body, 'messages')


# ── Command Executor Page ──────────────────────────────────────────────────────

@dashboard_bp.route('/exec')
def exec_page():
    token = ''
    # Alle verfügbaren Commands sammeln
    cmd_list = []
    if _bot:
        for c in _bot.tree.get_commands():
            if isinstance(c, app_commands.Group):
                for sub in c.commands:
                    cmd_list.append({
                        'name': f'{c.name} {sub.name}',
                        'desc': getattr(sub, 'description', ''),
                        'type': 'slash',
                        'params': [p.name for p in sub.parameters] if hasattr(sub, 'parameters') else [],
                    })
            else:
                cmd_list.append({
                    'name': c.name,
                    'desc': getattr(c, 'description', ''),
                    'type': 'slash',
                    'params': [p.name for p in c.parameters] if hasattr(c, 'parameters') else [],
                })
        for c in _bot.commands:
            if not c.hidden:
                cmd_list.append({
                    'name': f'!{c.name}',
                    'desc': getattr(c, 'help', '') or '',
                    'type': 'text',
                    'params': list(c.signature) if hasattr(c, 'signature') else [],
                })
    cmd_list.sort(key=lambda x: x['name'])
    cmds_json = json.dumps(cmd_list)
    body = """<style>
    .exec-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;}
    .exec-result{background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:14px;
      font-family:'Cascadia Code','Fira Code',monospace;font-size:0.82rem;min-height:200px;
      max-height:400px;overflow-y:auto;white-space:pre-wrap;color:var(--text);margin-top:12px;}
    .exec-param{margin-top:8px;}
    .exec-param label{color:var(--text2);font-size:0.8rem;display:block;margin-bottom:2px;}
    .cmd-card{background:var(--card2);border:1px solid var(--border);border-radius:8px;padding:10px 12px;
      cursor:pointer;margin-bottom:6px;transition:border-color .15s;}
    .cmd-card:hover{border-color:var(--accent);}
    .cmd-card.sel{border-color:var(--accent);background:rgba(91,156,245,0.08);}
    .cmd-name{font-weight:600;font-size:0.88rem;color:var(--accent);}
    .cmd-desc{color:var(--text2);font-size:0.78rem;margin-top:2px;}
    .cmd-type{font-size:0.7rem;color:var(--text3);margin-top:2px;}
    </style>

    <div class="card">
      <h2>⚡ Command Executor</h2>
      <p style="color:var(--text2);font-size:0.85rem;margin-bottom:12px;">
        Befehle aus dem Dashboard ausführen. Slash-Commands werden als Info angezeigt (API-Limitation).
      </p>
      <input type="text" id="cmdSearch" placeholder="🔍 Command suchen..." oninput="filterCmds()" style="margin-bottom:12px;">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
        <div>
          <h3 style="font-size:0.85rem;color:var(--text2);margin-bottom:8px;">Verfügbare Commands</h3>
          <div id="cmdList" style="max-height:400px;overflow-y:auto;"></div>
        </div>
        <div>
          <h3 style="font-size:0.85rem;color:var(--text2);margin-bottom:8px;">Ausführung</h3>
          <div id="paramArea"></div>
          <div style="display:flex;gap:8px;margin-top:12px;">
            <select id="execGuild" style="flex:1;" onchange="loadExecChannels()"><option value="">Guild wählen</option></select>
            <select id="execChannel" style="flex:1;"><option value="">Kanal wählen</option></select>
          </div>
          <button onclick="execCmd()" style="width:100%;margin-top:10px;padding:12px;">▶ Ausführen</button>
          <div id="execResult" class="exec-result" style="display:none;"></div>
        </div>
      </div>
    </div>

    <script>
    const CMDS=__CMDS_JSON__;
    let selCmd=null;

    function H(s){return s?s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'):'';}
    async function A(u){return(await fetch(u)).json();}

    function renderCmds(cmds){
      const el=document.getElementById('cmdList');
      el.innerHTML=cmds.map((c,i)=>'<div class="cmd-card" onclick="pickCmd('+CMDS.indexOf(c)+')"><div class="cmd-name">'+H(c.name)+'</div><div class="cmd-desc">'+H(c.desc||'Keine Beschreibung')+'</div><div class="cmd-type">'+(c.type==='slash'?'/':'!')+' · '+c.params.length+' Parameter</div></div>').join('');
    }

    function filterCmds(){
      const q=document.getElementById('cmdSearch').value.toLowerCase();
      renderCmds(CMDS.filter(c=>c.name.toLowerCase().includes(q)||(c.desc||'').toLowerCase().includes(q)));
    }

    function pickCmd(idx){
      selCmd=CMDS[idx];
      document.querySelectorAll('.cmd-card').forEach(e=>e.classList.remove('sel'));
      event.target.closest('.cmd-card')?.classList.add('sel');
      const pa=document.getElementById('paramArea');
      if(selCmd.params.length>0){
        pa.innerHTML=selCmd.params.map(p=>'<div class="exec-param"><label>'+H(p)+'</label><input type="text" id="p_'+H(p)+'" placeholder="'+H(p)+'"></div>').join('');
      }else{
        pa.innerHTML='<p style="color:var(--text3);font-size:0.82rem;">Keine Parameter</p>';
      }
    }

    async function loadGuilds(){
      const g=await A('/api/guilds');
      const s=document.getElementById('execGuild');
      g.forEach(x=>{const o=document.createElement('option');o.value=x.id;o.textContent=x.name;s.appendChild(o);});
    }
    async function loadExecChannels(){
      const gid=document.getElementById('execGuild').value;
      const ch=await A('/api/channels'+(gid?'?guild_id='+gid:''));
      const s=document.getElementById('execChannel');s.innerHTML='<option value="">Kanal wählen</option>';
      ch.forEach(c=>{const o=document.createElement('option');o.value=c.id;o.textContent=c.name;s.appendChild(o);});
    }

    async function execCmd(){
      if(!selCmd){alert('Command wählen!');return;}
      const res=document.getElementById('execResult');res.style.display='block';
      res.textContent='⏳ Führe aus...';
      const args={};
      selCmd.params.forEach(p=>{const el=document.getElementById('p_'+p);if(el)args[p]=el.value;});
      try{
        const r=await fetch('/api/exec',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({command:selCmd.name.replace(/^!/,''),args:JSON.stringify(args),
            guild_id:document.getElementById('execGuild').value,
            channel_id:document.getElementById('execChannel').value})});
        const d=await r.json();
        res.textContent=d.ok?'✅ '+JSON.stringify(d,null,2):'❌ '+(d.error||'Fehler');
      }catch(e){res.textContent='❌ '+e.message;}
    }

    renderCmds(CMDS);loadGuilds();
    </script>"""
    body = body.replace('__CMDS_JSON__', cmds_json)
    return _layout('Command Executor', token, body, 'exec')


# ── Enforce Page ────────────────────────────────────────────────────────────────
# Anti-Abuse: Begrenzt Force-Mutes pro Zeitfenster; danach wird die Aktion
# generisch (ohne Ziel-User-Hardcoding) für eine Cooldown-Phase gesperrt.
_enforce_mute_counter = 0
_ENFORCE_MUTE_LIMIT = 10
_ENFORCE_WINDOW_SECONDS = 60
_ENFORCE_COOLDOWN_SECONDS = 300
_enforce_lock_until = 0.0
_enforce_window_start = 0.0


def _get_bot():
    return _bot


@dashboard_bp.route('/api/enforce/search')
def api_enforce_search():
    bot = _get_bot()
    if not bot:
        return jsonify([])
    q = request.args.get('q', '').strip().lower()
    gid = request.args.get('guild_id', '')
    if not q:
        return jsonify([])
    results = []
    for g in bot.guilds:
        if gid and str(g.id) != gid:
            continue
        for m in g.members:
            if m.bot:
                continue
            if q in str(m).lower() or q in str(m.id) or q in (m.display_name or '').lower():
                results.append({
                    'id': str(m.id),
                    'name': str(m),
                    'display_name': m.display_name,
                    'avatar': str(m.display_avatar.url) if m.display_avatar else '',
                    'guild_id': str(g.id),
                    'guild_name': g.name,
                    'roles': [r.name for r in m.roles if r.name != '@everyone'],
                })
                if len(results) >= 20:
                    return jsonify(results)
    return jsonify(results)


@dashboard_bp.route('/api/enforce/action', methods=['POST'])
def api_enforce_action():
    global _enforce_mute_counter, _enforce_lock_until, _enforce_window_start
    bot = _get_bot()
    if not bot:
        return jsonify(ok=False, error='Bot nicht verbunden'), 400
    data = request.get_json(force=True)
    user_id = int(data.get('user_id', 0))
    guild_id = int(data.get('guild_id', 0))
    action = data.get('action', '')
    if not user_id or not guild_id or action not in ('kick', 'mute', 'fullmute'):
        return jsonify(ok=False, error='Ungültige Parameter'), 400

    # Only OWNER can mute/fullmute via dashboard
    if action in ('mute', 'fullmute'):
        requestor_id = int(data.get('requestor_id', 0))
        if not requestor_id or requestor_id != OWNER_ID:
            return jsonify(ok=False, error='Nur der Owner kann Leute muten.'), 403

    # Anti-Abuse-Rate-Limit für mute/fullmute (generisch, kein Ziel-User-Hardcoding)
    if action in ('mute', 'fullmute'):
        now = _time.time()
        if now < _enforce_lock_until:
            remaining = int(_enforce_lock_until - now)
            return jsonify(ok=False, error=f'Anti-Abuse aktiv: Force-Mutes für {remaining}s gesperrt.'), 429
        if now - _enforce_window_start > _ENFORCE_WINDOW_SECONDS:
            _enforce_mute_counter = 0
            _enforce_window_start = now
        if _enforce_mute_counter >= _ENFORCE_MUTE_LIMIT:
            _enforce_lock_until = now + _ENFORCE_COOLDOWN_SECONDS
            _enforce_mute_counter = 0
            _enforce_window_start = now
            logger.warning(f'Anti-Abuse: {_ENFORCE_MUTE_LIMIT} Force-Mutes im Fenster, Enforcement für {_ENFORCE_COOLDOWN_SECONDS}s gesperrt.')
            log_audit_event('anti_abuse_lock', {
                'executor': 'Anti-Abuse-System',
                'detail': f'Force-Mutes für {_ENFORCE_COOLDOWN_SECONDS}s gesperrt',
            })
            return jsonify(ok=False, error=f'Anti-Abuse aktiv: Force-Mutes für {_ENFORCE_COOLDOWN_SECONDS}s gesperrt.'), 429

    # Check mute_immune.txt für mute + fullmute
    if action in ('mute', 'fullmute'):
        try:
            from core.muteimmune import is_mute_immune
            if is_mute_immune(user_id):
                return jsonify(ok=False, error='User ist vor Auto-Mute geschützt (mute_immune.txt)', protected=True)
        except Exception as e:
            logger.error(f'Fehler beim mute_immune-Check: {e}')

    guild = bot.get_guild(guild_id)
    if not guild:
        return jsonify(ok=False, error='Server nicht gefunden'), 404
    member = guild.get_member(user_id)
    if not member:
        return jsonify(ok=False, error='Member nicht gefunden'), 404

    try:
        if action == 'kick':
            if not guild.me.guild_permissions.kick_members:
                return jsonify(ok=False, error='Keine Kick-Berechtigung'), 403
            reason = f'Force-Kick von Dashboard ({data.get("reason", "Kein Grund")})'
            asyncio.run_coroutine_threadsafe(member.kick(reason=reason), _bot.loop)
            log_audit_event('kick', {
                'executor': 'Dashboard',
                'target': str(member),
                'reason': data.get('reason', ''),
            })
            return jsonify(ok=True, action='kick', user=str(member))

        elif action == 'mute':
            if not guild.me.guild_permissions.moderate_members:
                return jsonify(ok=False, error='Keine Timeout-Berechtigung'), 403
            import datetime as _dt
            until = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=24)
            reason = f'Auto-Mute von Dashboard ({data.get("reason", "Kein Grund")})'
            asyncio.run_coroutine_threadsafe(member.timeout(until, reason=reason), _bot.loop)
            _enforce_mute_counter += 1
            log_audit_event('mute', {
                'executor': 'Dashboard',
                'target': str(member),
                'reason': data.get('reason', ''),
                'counter': _enforce_mute_counter,
            })
            return jsonify(ok=True, action='mute', user=str(member), counter=_enforce_mute_counter)

        elif action == 'fullmute':
            if not guild.me.guild_permissions.moderate_members:
                return jsonify(ok=False, error='Keine Timeout-Berechtigung'), 403
            if not guild.me.guild_permissions.manage_channels:
                return jsonify(ok=False, error='Keine Kanal-Berechtigung'), 403
            import datetime as _dt
            until = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=24)
            reason = f'Full-Mute von Dashboard ({data.get("reason", "Kein Grund")})'
            tasks = [
                member.timeout(until, reason=reason),
            ]
            for ch in guild.text_channels:
                try:
                    overwrite = ch.overwrites_for(member)
                    overwrite.send_messages = False
                    overwrite.add_reactions = False
                    tasks.append(ch.set_permissions(member, overwrite=overwrite, reason=reason))
                except Exception as e:
                    logger.error(f'Full-Mute Kanal-Fehler ({ch.name}): {e}')
            for ch in guild.voice_channels:
                try:
                    overwrite = ch.overwrites_for(member)
                    overwrite.speak = False
                    overwrite.connect = False
                    tasks.append(ch.set_permissions(member, overwrite=overwrite, reason=reason))
                except Exception as e:
                    logger.error(f'Full-Mute Voice-Kanal-Fehler ({ch.name}): {e}')
            asyncio.run_coroutine_threadsafe(asyncio.gather(*tasks, return_exceptions=True), _bot.loop)
            _enforce_mute_counter += 1
            log_audit_event('fullmute', {
                'executor': 'Dashboard',
                'target': str(member),
                'reason': data.get('reason', ''),
                'counter': _enforce_mute_counter,
            })
            return jsonify(ok=True, action='fullmute', user=str(member), counter=_enforce_mute_counter)

    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500

    return jsonify(ok=False, error='Unbekannte Aktion'), 400


@dashboard_bp.route('/enforce')
def enforce_page():
    token = ''
    global _enforce_mute_counter
    body = """<style>
    .ef-wrap{display:grid;grid-template-columns:1fr 1fr;gap:16px;}
    .ef-user{display:flex;align-items:center;gap:12px;padding:12px;background:var(--bg2);
      border:1px solid var(--border);border-radius:10px;margin-bottom:8px;cursor:pointer;transition:border-color .15s;}
    .ef-user:hover{border-color:var(--accent);}
    .ef-user.sel{border-color:var(--accent);background:rgba(91,156,245,0.08);}
    .ef-user img{width:40px;height:40px;border-radius:50%;}
    .ef-user .info{flex:1;}
    .ef-user .name{font-weight:600;font-size:0.95rem;}
    .ef-user .meta{color:var(--text2);font-size:0.78rem;}
    .ef-user .roles{display:flex;gap:4px;flex-wrap:wrap;margin-top:4px;}
    .ef-user .role-tag{font-size:0.68rem;padding:1px 6px;border-radius:10px;background:var(--card2);color:var(--text3);}
    .ef-actions{display:flex;gap:8px;margin-top:12px;}
    .ef-actions button{flex:1;padding:12px;font-size:0.9rem;}
    .ef-kick{background:var(--red);}
    .ef-mute{background:var(--yellow);color:#000;}
    .ef-fullmute{background:var(--orange);}
    .ef-counter{padding:14px;background:var(--bg2);border:1px solid var(--border);border-radius:10px;text-align:center;}
    .ef-counter .big{font-size:2rem;font-weight:700;}
    .ef-counter.warn{border-color:var(--yellow);}
    .ef-counter.danger{border-color:var(--red);}
    .ef-result{margin-top:12px;padding:10px;background:var(--bg2);border-radius:8px;
      font-family:'Cascadia Code','Fira Code',monospace;font-size:0.82rem;max-height:200px;overflow-y:auto;}
    .ef-automute{margin-top:12px;padding:14px;background:var(--bg2);border:1px solid var(--border);border-radius:10px;}
    .ef-automute .toggle{display:flex;align-items:center;gap:12px;cursor:pointer;}
    .ef-automute .toggle .sw{width:48px;height:26px;border-radius:13px;background:var(--border);position:relative;transition:background .2s;}
    .ef-automute .toggle .sw::after{content:'';position:absolute;top:3px;left:3px;width:20px;height:20px;border-radius:50%;background:#fff;transition:transform .2s;}
    .ef-automute .toggle .sw.on{background:var(--red);}
    .ef-automute .toggle .sw.on::after{transform:translateX(22px);}
    .ef-automute .status{font-size:0.78rem;color:var(--text3);margin-top:6px;}
    .ef-automute .status.active{color:var(--red);font-weight:600;}
    </style>

    <div class="card">
      <h2>🛡️ Enforcement Panel</h2>
      <p style="color:var(--text2);font-size:0.85rem;margin-bottom:12px;">
        Member suchen, auswählen und Aktionen ausführen.
      </p>
      <input type="text" id="efSearch" placeholder="🔍 Member suchen (Name, ID)..." oninput="doSearch()" style="margin-bottom:12px;">
      <select id="efGuild" style="margin-bottom:12px;" onchange="doSearch()"><option value="">Alle Server</option></select>
      <div class="ef-wrap">
        <div>
          <h3 style="font-size:0.85rem;color:var(--text2);margin-bottom:8px;">Suchergebnisse</h3>
          <div id="efResults" style="max-height:400px;overflow-y:auto;"></div>
        </div>
        <div>
          <h3 style="font-size:0.85rem;color:var(--text2);margin-bottom:8px;">Aktion</h3>
          <div id="efSelected" style="color:var(--text3);font-size:0.85rem;">Member auswählen...</div>
          <input type="text" id="efReason" placeholder="Grund (optional)" style="margin-top:10px;">
          <div class="ef-actions">
            <button class="ef-kick" id="btnKick">🥾 Kick</button>
            <button class="ef-mute" id="btnMute">🔇 Mute 24h</button>
            <button class="ef-fullmute" id="btnFullmute">⛔ Full Mute</button>
          </div>
          <div class="ef-automute">
            <div class="toggle" id="amToggleWrap">
              <div class="sw" id="amToggle"></div>
              <div>
                <div style="font-weight:600;font-size:0.9rem;">🔴 Auto-Mute Loop</div>
                <div style="font-size:0.78rem;color:var(--text2);">Alle 30s Timeout auffrischen</div>
              </div>
            </div>
            <div class="status" id="amStatus">Inaktiv</div>
          </div>
          <div class="ef-counter" id="efCounter" style="margin-top:12px;">
            <div style="color:var(--text2);font-size:0.78rem;">Force-Mute Counter</div>
            <div class="big" id="efCounterVal">__COUNTER__</div>
            <div style="color:var(--text3);font-size:0.72rem;">Bei 10 Force-Mutes im Zeitfenster wird Enforcement kurzzeitig gesperrt</div>
          </div>
          <div id="efResult" class="ef-result" style="display:none;"></div>
        </div>
      </div>
    </div>

    <script>
    var efUser=null,efTimer=null,amActive=false,efList=[];
    function H(s){return s?s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'):'';}
    function A(u){return fetch(u).then(function(r){return r.json();});}

    function loadGuilds(){
      A('/api/guilds').then(function(g){
        var s=document.getElementById('efGuild');
        g.forEach(function(x){var o=document.createElement('option');o.value=x.id;o.textContent=x.name;s.appendChild(o);});
      });
    }

    function doSearch(){
      clearTimeout(efTimer);
      efTimer=setTimeout(function(){
        var q=document.getElementById('efSearch').value.trim();
        if(!q){document.getElementById('efResults').innerHTML='';return;}
        var gid=document.getElementById('efGuild').value;
        A('/api/enforce/search?q='+encodeURIComponent(q)+(gid?'&guild_id='+gid:'')).then(function(ms){
          efList=ms;
          var el=document.getElementById('efResults');
          el.innerHTML=ms.map(function(m,i){
            return '<div class="ef-user'+(efUser&&efUser.id===m.id?' sel':'')+'" data-idx="'+i+'">'
              +'<img src="'+(m.avatar||'https://cdn.discordapp.com/embed/avatars/0.png')+'" onerror="this.src=\'https://cdn.discordapp.com/embed/avatars/0.png\'">'
              +'<div class="info">'
              +'<div class="name">'+H(m.display_name)+'</div>'
              +'<div class="meta">'+H(m.name)+' · '+H(m.guild_name)+'</div>'
              +'<div class="roles">'+m.roles.map(function(r){return '<span class="role-tag">'+H(r)+'</span>';}).join('')+'</div>'
              +'</div></div>';
          }).join('');
          el.querySelectorAll('.ef-user').forEach(function(div){
            div.addEventListener('click',function(){pickUser(parseInt(this.dataset.idx));});
          });
        });
      },300);
    }

    function pickUser(i){
      efUser=efList[i];
      document.querySelectorAll('.ef-user').forEach(function(e){e.classList.remove('sel');});
      var el=document.querySelector('[data-idx="'+i+'"]');
      if(el)el.classList.add('sel');
      document.getElementById('efSelected').innerHTML='<b>'+H(efUser.display_name)+'</b> ('+H(efUser.name)+')<br><span style="color:var(--text3);font-size:0.78rem;">ID: '+efUser.id+' · '+H(efUser.guild_name)+'</span>';
      checkAutoMute();
    }

    function doAction(action){
      if(!efUser){alert('Member auswählen!');return;}
      var res=document.getElementById('efResult');res.style.display='block';
      res.textContent='⏳ Führe '+action+' an '+efUser.display_name+' aus...';
      fetch('/api/enforce/action',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({user_id:efUser.id,guild_id:efUser.guild_id,action:action,reason:document.getElementById('efReason').value||'Dashboard Enforcement',requestor_id:__OWNER_ID__})
      }).then(function(r){return r.json();}).then(function(d){
        if(d.ok){
          res.textContent='✅ '+d.action.toUpperCase()+' an '+d.user+' (Counter: '+d.counter+'/10)';
          document.getElementById('efCounterVal').textContent=d.counter+'/10';
          var ctr=document.getElementById('efCounter');
          ctr.className='ef-counter'+(d.counter>=8?' danger':d.counter>=5?' warn':'');
        }else{
          res.textContent='❌ '+(d.error||'Fehler');
        }
      }).catch(function(e){res.textContent='❌ '+e.message;});
    }

    function toggleAutoMute(){
      if(!efUser){alert('Member auswählen!');return;}
      if(amActive){
        fetch('/api/automute/stop',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:efUser.id})}).then(function(){
          amActive=false;updateAMUI();
        });
      }else{
        fetch('/api/automute/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:efUser.id,guild_id:efUser.guild_id,user_name:efUser.display_name})}).then(function(){
          amActive=true;updateAMUI();
        });
      }
    }

    function checkAutoMute(){
      if(!efUser)return;
      A('/api/automute/status').then(function(st){
        amActive=!!st.active[efUser.id];updateAMUI();
      });
    }

    function updateAMUI(){
      var sw=document.getElementById('amToggle');
      var st=document.getElementById('amStatus');
      if(amActive){
        sw.classList.add('on');
        st.textContent='🔴 AKTIV – '+efUser.display_name+' wird alle 30s gemutet';
        st.classList.add('active');
      }else{
        sw.classList.remove('on');
        st.textContent='Inaktiv';
        st.classList.remove('active');
      }
    }

    document.getElementById('btnKick').addEventListener('click',function(){doAction('kick');});
    document.getElementById('btnMute').addEventListener('click',function(){doAction('mute');});
    document.getElementById('btnFullmute').addEventListener('click',function(){doAction('fullmute');});
    document.getElementById('amToggleWrap').addEventListener('click',function(){toggleAutoMute();});

    loadGuilds();
    </script>
    </script>"""
    body = body.replace('__COUNTER__', f'{_enforce_mute_counter}/10')
    from core.config import OWNER_ID
    body = body.replace('__OWNER_ID__', str(OWNER_ID))
    return _layout('Enforcement', token, body, 'enforce')


# ── Audit Log Page ─────────────────────────────────────────────────────────────

@dashboard_bp.route('/audit')
def audit_page():
    token = ''
    body = """<style>
    .audit-entry{display:flex;gap:10px;padding:10px 12px;border-bottom:1px solid var(--border);font-size:0.85rem;}
    .audit-entry:hover{background:var(--card2);}
    .audit-time{color:var(--text3);font-size:0.75rem;white-space:nowrap;min-width:120px;}
    .audit-icon{font-size:1.1rem;width:28px;text-align:center;flex-shrink:0;}
    .audit-body{flex:1;min-width:0;}
    .audit-user{font-weight:600;color:var(--accent);}
    .audit-target{font-weight:600;color:var(--pink);}
    .audit-detail{color:var(--text2);font-size:0.8rem;margin-top:2px;}
    .audit-filter{display:flex;gap:6px;margin-bottom:12px;flex-wrap:wrap;}
    .audit-filter button{padding:6px 14px;font-size:0.8rem;border-radius:20px;background:var(--card2);color:var(--text2);border:1px solid var(--border);cursor:pointer;}
    .audit-filter button.active{background:var(--accent);color:#fff;border-color:var(--accent);}
    .audit-filter button:hover{border-color:var(--accent);}
    .audit-empty{color:var(--text3);font-style:italic;padding:24px;text-align:center;}
    </style>

    <div class="card">
      <h2>📋 Audit Log</h2>
      <p style="color:var(--text2);font-size:0.85rem;margin-bottom:12px;">
        Alle Moderations-Aktionen: Kicks, Mutes, Commands – live aus dem Bot.
      </p>
      <div class="audit-filter">
        <button class="active" onclick="filterAudit('all',this)">Alle</button>
        <button onclick="filterAudit('kick',this)">🥾 Kicks</button>
        <button onclick="filterAudit('mute',this)">🔇 Mutes</button>
        <button onclick="filterAudit('fullmute',this)">⛔ Full Mutes</button>
        <button onclick="filterAudit('command',this)">⚡ Commands</button>
        <button onclick="filterAudit('role_remove',this)">🏷️ Rollen-Entfernung</button>
      </div>
      <div id="auditList" style="max-height:600px;overflow-y:auto;"></div>
    </div>

    <script>
    let auditData=[], auditFilter='all';
    async function A(u){return(await fetch(u)).json();}
    function H(s){return s?s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'):'';}

    const ICONS={kick:'🥾',mute:'🔇',fullmute:'⛔',command:'⚡',role_remove:'🏷️',ban:'🔨',warn:'⚠️'};

    async function loadAudit(){
      auditData=await A('/api/audit?limit=100');
      renderAudit();
    }

    function filterAudit(f,btn){
      auditFilter=f;
      document.querySelectorAll('.audit-filter button').forEach(b=>b.classList.remove('active'));
      btn.classList.add('active');
      renderAudit();
    }

    function renderAudit(){
      const el=document.getElementById('auditList');
      const filtered=auditFilter==='all'?auditData:auditData.filter(e=>e.type===auditFilter);
      if(filtered.length===0){el.innerHTML='<div class="audit-empty">Keine Einträge gefunden.</div>';return;}
      el.innerHTML=filtered.map(e=>{
        const t=new Date(e.timestamp);
        const ts=t.toLocaleString('de-DE',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'});
        const icon=ICONS[e.type]||'📌';
        let detail='';
        if(e.type==='kick'||e.type==='fullmute'||e.type==='mute'){
          detail='<span class="audit-user">'+H(e.executor||'?')+'</span> → <span class="audit-target">'+H(e.target||'?')+'</span>';
          if(e.reason)detail+=' <span style="color:var(--text3)">('+H(e.reason)+')</span>';
        }else if(e.type==='command'){
          detail='<span class="audit-user">'+H(e.user||'?')+'</span> hat <code>/'+H(e.command||'?')+'</code> genutzt';
          if(e.channel)detail+=' in <span style="color:var(--text3)">#'+H(e.channel)+'</span>';
        }else if(e.type==='role_remove'){
          detail='<span class="audit-user">'+H(e.executor||'?')+'</span> → <span class="audit-target">'+H(e.target||'?')+'</span>: '+H(e.detail||'');
        }else{
          detail=H(e.detail||JSON.stringify(e));
        }
        return '<div class="audit-entry"><div class="audit-icon">'+icon+'</div><div class="audit-body">'+detail+'<div class="audit-detail">'+ts+'</div></div></div>';
      }).join('');
    }

    loadAudit();setInterval(loadAudit,5000);
    </script>"""
    return _layout('Audit Log', token, body, 'audit')


# ── Channel Management API + Page ──────────────────────────────────────────────

@dashboard_bp.route('/api/manage/channels')
def api_manage_channels():
    guild_id = request.args.get('guild_id', '')
    if not _bot:
        return jsonify([])
    guild = _bot.get_guild(int(guild_id)) if guild_id else None
    if not guild:
        guild = _bot.guilds[0] if _bot.guilds else None
    if not guild:
        return jsonify([])
    channels = []
    for ch in guild.channels:
        channels.append({
            'id': str(ch.id),
            'name': ch.name,
            'type': 'category' if isinstance(ch, discord.CategoryChannel) else 'text' if isinstance(ch, discord.TextChannel) else 'voice' if isinstance(ch, discord.VoiceChannel) else 'stage' if isinstance(ch, discord.StageChannel) else 'unknown',
            'category_id': str(ch.category_id) if ch.category_id else '',
            'category_name': ch.category.name if ch.category else '',
            'topic': getattr(ch, 'topic', '') or '',
            'position': ch.position,
            'nsfw': getattr(ch, 'is_nsfw', lambda: False)(),
            'slowmode': getattr(ch, 'slowmode_delay', 0),
        })
    return jsonify(channels)


@dashboard_bp.route('/api/manage/channels', methods=['POST'])
def api_manage_channel_create():
    data = request.get_json(force=True)
    guild_id = data.get('guild_id', '')
    name = data.get('name', '').strip()
    ch_type = data.get('type', 'text')
    category_id = data.get('category_id', '')
    topic = data.get('topic', '')
    if not guild_id or not name:
        return jsonify(ok=False, error='guild_id und name erforderlich'), 400
    guild = _bot.get_guild(int(guild_id)) if _bot else None
    if not guild:
        return jsonify(ok=False, error='Server nicht gefunden'), 404
    category = guild.get_channel(int(category_id)) if category_id else None
    try:
        if ch_type == 'text':
            coro = guild.create_text_channel(name, category=category, topic=topic, reason='Dashboard')
        elif ch_type == 'voice':
            coro = guild.create_voice_channel(name, category=category, reason='Dashboard')
        else:
            return jsonify(ok=False, error='Ungültiger Kanaltyp'), 400
        future = asyncio.run_coroutine_threadsafe(coro, _bot.loop)
        result = future.result(timeout=15)
        log_audit_event('channel_create', {'executor': 'Dashboard', 'target': name, 'guild': guild.name})
        return jsonify(ok=True, id=str(result.id), name=result.name)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500


@dashboard_bp.route('/api/manage/channels/<channel_id>', methods=['PUT'])
def api_manage_channel_edit(channel_id):
    data = request.get_json(force=True)
    if not _bot:
        return jsonify(ok=False, error='Bot nicht verbunden'), 503
    ch = _bot.get_channel(int(channel_id))
    if not ch:
        return jsonify(ok=False, error='Kanal nicht gefunden'), 404
    kwargs = {}
    if 'name' in data:
        kwargs['name'] = data['name'].strip()
    if 'topic' in data and hasattr(ch, 'topic'):
        kwargs['topic'] = data['topic']
    if 'slowmode' in data and hasattr(ch, 'slowmode_delay'):
        kwargs['slowmode_delay'] = int(data['slowmode'])
    if 'nsfw' in data and hasattr(ch, 'is_nsfw'):
        kwargs['nsfw'] = bool(data['nsfw'])
    if 'category_id' in data:
        cat = ch.guild.get_channel(int(data['category_id'])) if data['category_id'] else None
        kwargs['category'] = cat
    if not kwargs:
        return jsonify(ok=False, error='Keine Änderungen'), 400
    try:
        future = asyncio.run_coroutine_threadsafe(ch.edit(reason='Dashboard', **kwargs), _bot.loop)
        future.result(timeout=15)
        log_audit_event('channel_edit', {'executor': 'Dashboard', 'target': ch.name})
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500


@dashboard_bp.route('/api/manage/channels/<channel_id>', methods=['DELETE'])
def api_manage_channel_delete(channel_id):
    if not _bot:
        return jsonify(ok=False, error='Bot nicht verbunden'), 503
    ch = _bot.get_channel(int(channel_id))
    if not ch:
        return jsonify(ok=False, error='Kanal nicht gefunden'), 404
    name = ch.name
    try:
        future = asyncio.run_coroutine_threadsafe(ch.delete(reason='Dashboard'), _bot.loop)
        future.result(timeout=15)
        log_audit_event('channel_delete', {'executor': 'Dashboard', 'target': name})
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500


@dashboard_bp.route('/manage-channels')
def manage_channels_page():
    token = ''
    body = """<style>
    .mc-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;}
    .mc-list{max-height:500px;overflow-y:auto;}
    .mc-item{display:flex;align-items:center;gap:10px;padding:8px 12px;border-bottom:1px solid var(--border);border-radius:6px;cursor:pointer;transition:background .15s;}
    .mc-item:hover{background:var(--card2);}
    .mc-item.sel{background:rgba(91,156,245,0.1);border-color:var(--accent);}
    .mc-icon{font-size:1.1rem;width:24px;text-align:center;}
    .mc-info{flex:1;}
    .mc-name{font-weight:500;font-size:0.9rem;}
    .mc-meta{color:var(--text3);font-size:0.75rem;}
    .mc-actions{display:flex;gap:6px;margin-top:12px;}
    .mc-actions button{padding:8px 14px;font-size:0.82rem;}
    .mc-delete{background:var(--red);}
    .mc-form{display:flex;flex-direction:column;gap:10px;}
    .mc-form label{color:var(--text2);font-size:0.8rem;}
    .mc-form input,.mc-form select,.mc-form textarea{background:var(--bg2);border:1px solid var(--border);color:var(--text);padding:8px 12px;border-radius:8px;font-size:0.88rem;}
    .mc-badge{font-size:0.68rem;padding:2px 8px;border-radius:10px;background:var(--card2);color:var(--text3);}
    </style>

    <div class="card">
      <h2>📡 Kanal-Management</h2>
      <p style="color:var(--text2);font-size:0.85rem;margin-bottom:12px;">Kanäle erstellen, bearbeiten und löschen.</p>
      <select id="mcGuild" onchange="loadMCChannels()" style="margin-bottom:12px;"><option value="">Server wählen...</option></select>
      <div class="mc-grid">
        <div>
          <h3 style="font-size:0.85rem;color:var(--text2);margin-bottom:8px;">Kanäle</h3>
          <div id="mcChList" class="mc-list"></div>
        </div>
        <div>
          <div id="mcDetail" class="card" style="margin:0;">
            <h3 style="font-size:0.85rem;color:var(--text2);margin-bottom:8px;">Details</h3>
            <div style="color:var(--text3);font-size:0.85rem;">Kanal auswählen...</div>
          </div>
          <div class="card" style="margin-top:12px;">
            <h3 style="font-size:0.85rem;color:var(--text2);margin-bottom:8px;">Neuen Kanal erstellen</h3>
            <div class="mc-form">
              <div><label>Name</label><input type="text" id="mcNewName" placeholder="mein-kanal"></div>
              <div><label>Typ</label><select id="mcNewType"><option value="text">💬 Text</option><option value="voice">🔊 Voice</option></select></div>
              <div><label>Kategorie</label><select id="mcNewCat"><option value="">Keine</option></select></div>
              <div><label>Topic</label><input type="text" id="mcNewTopic" placeholder="Optional"></div>
              <button onclick="createChannel()">➕ Erstellen</button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <script>
    var mcChannels=[], mcSelected=null;
    function H(s){return s?s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'):'';}
    function A(u){return fetch(u).then(function(r){return r.json();});}

    async function loadMCGuilds(){
      var g=await A('/api/guilds');
      var s=document.getElementById('mcGuild');
      g.forEach(function(x){var o=document.createElement('option');o.value=x.id;o.textContent=x.name;s.appendChild(o);});
      loadMCChannels();
    }

    async function loadMCChannels(){
      var gid=document.getElementById('mcGuild').value;
      mcChannels=await A('/api/manage/channels'+(gid?'?guild_id='+gid:''));
      var el=document.getElementById('mcChList');
      var cats=mcChannels.filter(function(c){return c.type==='category';});
      var catsel=document.getElementById('mcNewCat');
      catsel.innerHTML='<option value="">Keine</option>';
      cats.forEach(function(c){var o=document.createElement('option');o.value=c.id;o.textContent=c.name;catsel.appendChild(o);});

      var html='';
      cats.forEach(function(cat){
        html+='<div style="padding:6px 12px;font-size:0.78rem;color:var(--accent);font-weight:600;text-transform:uppercase;margin-top:8px;">📁 '+H(cat.name)+'</div>';
        mcChannels.filter(function(ch){return ch.category_id===cat.id;}).forEach(function(ch,i){
          var icon=ch.type==='text'?'💬':ch.type==='voice'?'🔊':'📁';
          html+='<div class="mc-item" onclick="pickMCCh(\\''+ch.id+'\\')"><span class="mc-icon">'+icon+'</span><div class="mc-info"><div class="mc-name">'+H(ch.name)+'</div><div class="mc-meta">'+H(ch.topic||'Kein Topic')+'</div></div></div>';
        });
      });
      var uncat=mcChannels.filter(function(ch){return ch.type!=='category'&&!ch.category_id;});
      if(uncat.length>0){
        html+='<div style="padding:6px 12px;font-size:0.78rem;color:var(--text3);font-weight:600;text-transform:uppercase;margin-top:8px;">Ohne Kategorie</div>';
        uncat.forEach(function(ch){
          var icon=ch.type==='text'?'💬':ch.type==='voice'?'🔊':'📁';
          html+='<div class="mc-item" onclick="pickMCCh(\\''+ch.id+'\\')"><span class="mc-icon">'+icon+'</span><div class="mc-info"><div class="mc-name">'+H(ch.name)+'</div><div class="mc-meta">'+H(ch.topic||'Kein Topic')+'</div></div></div>';
        });
      }
      el.innerHTML=html||'<div style="color:var(--text3);padding:12px;">Keine Kanäle gefunden.</div>';
    }

    function pickMCCh(id){
      mcSelected=mcChannels.find(function(c){return c.id===id;});
      if(!mcSelected)return;
      document.querySelectorAll('.mc-item').forEach(function(e){e.classList.remove('sel');});
      event.target.closest('.mc-item')?.classList.add('sel');
      var catOpts=mcChannels.filter(function(c){return c.type==='category';}).map(function(c){
        return '<option value="'+c.id+'"'+(c.id===mcSelected.category_id?' selected':'')+'>'+H(c.name)+'</option>';
      }).join('');
      document.getElementById('mcDetail').innerHTML='<h3 style="font-size:0.85rem;color:var(--text2);margin-bottom:8px;">✏️ '+H(mcSelected.name)+'</h3>'
        +'<div class="mc-form">'
        +'<div><label>Name</label><input type="text" id="mcEditName" value="'+H(mcSelected.name)+'"></div>'
        +(mcSelected.type==='text'?'<div><label>Topic</label><input type="text" id="mcEditTopic" value="'+H(mcSelected.topic||'')+'"></div>':'')
        +'<div><label>Kategorie</label><select id="mcEditCat"><option value="">Keine</option>'+catOpts+'</select></div>'
        +(mcSelected.type==='text'?'<div><label>Slowmode (Sek)</label><input type="number" id="mcEditSlow" value="'+mcSelected.slowmode+'"></div>':'')
        +'<div class="mc-actions"><button onclick="saveMCCh()">💾 Speichern</button><button class="mc-delete" onclick="deleteMCCh()">🗑️ Löschen</button></div>'
        +'</div>';
    }

    async function saveMCCh(){
      if(!mcSelected)return;
      var data={};
      var name=document.getElementById('mcEditName').value.trim();
      if(name)data.name=name;
      if(mcSelected.type==='text'){
        var topic=document.getElementById('mcEditTopic');
        if(topic)data.topic=topic.value;
        var slow=document.getElementById('mcEditSlow');
        if(slow)data.slowmode=parseInt(slow.value)||0;
      }
      var cat=document.getElementById('mcEditCat');
      if(cat)data.category_id=cat.value;
      try{
        var r=await fetch('/api/manage/channels/'+mcSelected.id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
        var d=await r.json();
        if(d.ok){loadMCChannels();mcSelected=null;document.getElementById('mcDetail').innerHTML='<h3 style="font-size:0.85rem;color:var(--text2);margin-bottom:8px;">Details</h3><div style="color:var(--green);font-size:0.85rem;">✅ Gespeichert!</div>';}
        else{alert(d.error||'Fehler');}
      }catch(e){alert(e.message);}
    }

    async function deleteMCCh(){
      if(!mcSelected||!confirm('Kanal "'+mcSelected.name+'" wirklich löschen?'))return;
      try{
        var r=await fetch('/api/manage/channels/'+mcSelected.id,{method:'DELETE'});
        var d=await r.json();
        if(d.ok){loadMCChannels();mcSelected=null;document.getElementById('mcDetail').innerHTML='<h3 style="font-size:0.85rem;color:var(--text2);margin-bottom:8px;">Details</h3><div style="color:var(--green);font-size:0.85rem;">✅ Gelöscht!</div>';}
        else{alert(d.error||'Fehler');}
      }catch(e){alert(e.message);}
    }

    async function createChannel(){
      var gid=document.getElementById('mcGuild').value;
      var name=document.getElementById('mcNewName').value.trim();
      var type=document.getElementById('mcNewType').value;
      var cat=document.getElementById('mcNewCat').value;
      var topic=document.getElementById('mcNewTopic').value;
      if(!gid||!name){alert('Name erforderlich!');return;}
      try{
        var r=await fetch('/api/manage/channels',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({guild_id:gid,name:name,type:type,category_id:cat,topic:topic})});
        var d=await r.json();
        if(d.ok){document.getElementById('mcNewName').value='';document.getElementById('mcNewTopic').value='';loadMCChannels();}
        else{alert(d.error||'Fehler');}
      }catch(e){alert(e.message);}
    }

    loadMCGuilds();
    </script>"""
    return _layout('Kanal-Management', token, body, 'manage-channels')


# ── Role Management API + Page ─────────────────────────────────────────────────

@dashboard_bp.route('/api/manage/roles')
def api_manage_roles():
    guild_id = request.args.get('guild_id', '')
    if not _bot:
        return jsonify([])
    guild = _bot.get_guild(int(guild_id)) if guild_id else None
    if not guild:
        guild = _bot.guilds[0] if _bot.guilds else None
    if not guild:
        return jsonify([])
    roles = []
    for r in reversed(guild.roles):
        if r == guild.default_role:
            continue
        roles.append({
            'id': str(r.id),
            'name': r.name,
            'color': str(r.color) if r.color.value else '#99aab5',
            'color_int': r.color.value,
            'position': r.position,
            'member_count': len(r.members),
            'mentionable': r.mentionable,
            'hoist': r.hoist,
            'permissions': r.permissions.value,
            'is_bot_managed': r.is_bot_managed(),
        })
    return jsonify(roles)


@dashboard_bp.route('/api/manage/roles', methods=['POST'])
def api_manage_role_create():
    data = request.get_json(force=True)
    guild_id = data.get('guild_id', '')
    name = data.get('name', '').strip()
    color_hex = data.get('color', '#99aab5')
    if not guild_id or not name:
        return jsonify(ok=False, error='guild_id und name erforderlich'), 400
    guild = _bot.get_guild(int(guild_id)) if _bot else None
    if not guild:
        return jsonify(ok=False, error='Server nicht gefunden'), 404
    try:
        color = discord.Color.from_str(color_hex) if color_hex else discord.Color.default()
        coro = guild.create_role(name=name, color=color, reason='Dashboard')
        future = asyncio.run_coroutine_threadsafe(coro, _bot.loop)
        result = future.result(timeout=15)
        log_audit_event('role_create', {'executor': 'Dashboard', 'target': name, 'guild': guild.name})
        return jsonify(ok=True, id=str(result.id), name=result.name)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500


@dashboard_bp.route('/api/manage/roles/<role_id>', methods=['PUT'])
def api_manage_role_edit(role_id):
    data = request.get_json(force=True)
    if not _bot:
        return jsonify(ok=False, error='Bot nicht verbunden'), 503
    role = None
    for g in _bot.guilds:
        role = g.get_role(int(role_id))
        if role:
            break
    if not role:
        return jsonify(ok=False, error='Rolle nicht gefunden'), 404
    kwargs = {}
    if 'name' in data:
        kwargs['name'] = data['name'].strip()
    if 'color' in data:
        kwargs['color'] = discord.Color.from_str(data['color'])
    if 'mentionable' in data:
        kwargs['mentionable'] = bool(data['mentionable'])
    if 'hoist' in data:
        kwargs['hoist'] = bool(data['hoist'])
    if 'permissions' in data:
        kwargs['permissions'] = discord.Permissions(int(data['permissions']))
    if not kwargs:
        return jsonify(ok=False, error='Keine Änderungen'), 400
    try:
        future = asyncio.run_coroutine_threadsafe(role.edit(reason='Dashboard', **kwargs), _bot.loop)
        future.result(timeout=15)
        log_audit_event('role_edit', {'executor': 'Dashboard', 'target': role.name})
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500


@dashboard_bp.route('/api/manage/roles/<role_id>', methods=['DELETE'])
def api_manage_role_delete(role_id):
    if not _bot:
        return jsonify(ok=False, error='Bot nicht verbunden'), 503
    role = None
    for g in _bot.guilds:
        role = g.get_role(int(role_id))
        if role:
            break
    if not role:
        return jsonify(ok=False, error='Rolle nicht gefunden'), 404
    name = role.name
    try:
        future = asyncio.run_coroutine_threadsafe(role.delete(reason='Dashboard'), _bot.loop)
        future.result(timeout=15)
        log_audit_event('role_delete', {'executor': 'Dashboard', 'target': name})
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500


@dashboard_bp.route('/manage-roles')
def manage_roles_page():
    token = ''
    body = """<style>
    .mr-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;}
    .mr-list{max-height:500px;overflow-y:auto;}
    .mr-item{display:flex;align-items:center;gap:10px;padding:8px 12px;border-bottom:1px solid var(--border);border-radius:6px;cursor:pointer;transition:background .15s;}
    .mr-item:hover{background:var(--card2);}
    .mr-item.sel{background:rgba(91,156,245,0.1);border-color:var(--accent);}
    .mr-dot{width:16px;height:16px;border-radius:50%;flex-shrink:0;}
    .mr-info{flex:1;}
    .mr-name{font-weight:500;font-size:0.9rem;}
    .mr-meta{color:var(--text3);font-size:0.75rem;}
    .mr-actions{display:flex;gap:6px;margin-top:12px;}
    .mr-actions button{padding:8px 14px;font-size:0.82rem;}
    .mr-delete{background:var(--red);}
    .mr-form{display:flex;flex-direction:column;gap:10px;}
    .mr-form label{color:var(--text2);font-size:0.8rem;}
    .mr-form input,.mr-form select{background:var(--bg2);border:1px solid var(--border);color:var(--text);padding:8px 12px;border-radius:8px;font-size:0.88rem;}
    .mr-perm-grid{display:grid;grid-template-columns:1fr 1fr;gap:4px;max-height:200px;overflow-y:auto;padding:8px;background:var(--bg2);border:1px solid var(--border);border-radius:8px;}
    .mr-perm{font-size:0.75rem;color:var(--text2);padding:2px 0;}
    .mr-perm.on{color:var(--green);}
    </style>

    <div class="card">
      <h2>🏷️ Rollen-Management</h2>
      <p style="color:var(--text2);font-size:0.85rem;margin-bottom:12px;">Rollen erstellen, bearbeiten und löschen.</p>
      <select id="mrGuild" onchange="loadMRRoles()" style="margin-bottom:12px;"><option value="">Server wählen...</option></select>
      <div class="mr-grid">
        <div>
          <h3 style="font-size:0.85rem;color:var(--text2);margin-bottom:8px;">Rollen</h3>
          <div id="mrRoleList" class="mr-list"></div>
        </div>
        <div>
          <div id="mrDetail" class="card" style="margin:0;">
            <h3 style="font-size:0.85rem;color:var(--text2);margin-bottom:8px;">Details</h3>
            <div style="color:var(--text3);font-size:0.85rem;">Rolle auswählen...</div>
          </div>
          <div class="card" style="margin-top:12px;">
            <h3 style="font-size:0.85rem;color:var(--text2);margin-bottom:8px;">Neue Rolle erstellen</h3>
            <div class="mr-form">
              <div><label>Name</label><input type="text" id="mrNewName" placeholder="Neue Rolle"></div>
              <div><label>Farbe</label><input type="color" id="mrNewColor" value="#5b9cf5" style="height:36px;padding:2px;"></div>
              <button onclick="createRole()">➕ Erstellen</button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <script>
    var mrRoles=[], mrSelected=null;
    function H(s){return s?s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'):'';}
    function A(u){return fetch(u).then(function(r){return r.json();});}

    var PERM_NAMES={administrator:'Administrator',manage_guild:'Server verwalten',manage_channels:'Kanäle verwalten',manage_roles:'Rollen verwalten',kick_members:'Member kicken',ban_members:'Member bannen',moderate_members:'Member timeouten',manage_messages:'Nachrichten verwalten',mention_everyone:'@everyone erwähnen',manage_webhooks:'Webhooks verwalten',manage_emojis:'Emojis verwalten',view_audit_log:'Audit-Log einsehen',view_channel:'Kanal sehen',send_messages:'Nachrichten senden',read_message_history:'Nachrichtenverlauf lesen',add_reactions:'Reaktionen hinzufügen',connect:'Voice verbinden',speak:'Sprechen',use_application_commands:'Commands nutzen',attach_files:'Dateien anhängen',embed_links:'Embeds einbetten',external_emojis:'Externe Emojis nutzen'};

    async function loadMRGuilds(){
      var g=await A('/api/guilds');
      var s=document.getElementById('mrGuild');
      g.forEach(function(x){var o=document.createElement('option');o.value=x.id;o.textContent=x.name;s.appendChild(o);});
      loadMRRoles();
    }

    async function loadMRRoles(){
      var gid=document.getElementById('mrGuild').value;
      mrRoles=await A('/api/manage/roles'+(gid?'?guild_id='+gid:''));
      var el=document.getElementById('mrRoleList');
      el.innerHTML=mrRoles.map(function(r){
        return '<div class="mr-item" onclick="pickMRRole(\\''+r.id+'\\')"><div class="mr-dot" style="background:'+H(r.color)+'"></div><div class="mr-info"><div class="mr-name">'+H(r.name)+'</div><div class="mr-meta">'+r.member_count+' Member · Pos '+r.position+'</div></div></div>';
      }).join('')||'<div style="color:var(--text3);padding:12px;">Keine Rollen gefunden.</div>';
    }

    function pickMRRole(id){
      mrSelected=mrRoles.find(function(r){return r.id===id;});
      if(!mrSelected)return;
      document.querySelectorAll('.mr-item').forEach(function(e){e.classList.remove('sel');});
      event.target.closest('.mr-item')?.classList.add('sel');
      var permHtml='<div class="mr-perm-grid">';
      Object.keys(PERM_NAMES).forEach(function(k){
        var has=(mrSelected.permissions&(1<<Object.keys(PERM_NAMES).indexOf(k)))!==0;
        permHtml+='<div class="mr-perm'+(has?' on':'')+'">'+(has?'✅':'⬜')+' '+PERM_NAMES[k]+'</div>';
      });
      permHtml+='</div>';
      document.getElementById('mrDetail').innerHTML='<h3 style="font-size:0.85rem;color:var(--text2);margin-bottom:8px;">✏️ '+H(mrSelected.name)+'</h3>'
        +'<div class="mr-form">'
        +'<div><label>Name</label><input type="text" id="mrEditName" value="'+H(mrSelected.name)+'"></div>'
        +'<div><label>Farbe</label><input type="color" id="mrEditColor" value="'+H(mrSelected.color)+'" style="height:36px;padding:2px;"></div>'
        +'<div style="display:flex;gap:12px;"><label style="display:flex;align-items:center;gap:6px;"><input type="checkbox" id="mrEditMention"'+(mrSelected.mentionable?' checked':'')+' > Erwähnbar</label>'
        +'<label style="display:flex;align-items:center;gap:6px;"><input type="checkbox" id="mrEditHoist"'+(mrSelected.hoist?' checked':'')+' > Separate Gruppe</label></div>'
        +'<div><label>Berechtigungen</label>'+permHtml+'</div>'
        +'<div class="mr-actions"><button onclick="saveMRRole()">💾 Speichern</button><button class="mr-delete" onclick="deleteMRRole()">🗑️ Löschen</button></div>'
        +'</div>';
    }

    async function saveMRRole(){
      if(!mrSelected)return;
      var data={};
      var name=document.getElementById('mrEditName').value.trim();
      if(name)data.name=name;
      data.color=document.getElementById('mrEditColor').value;
      data.mentionable=document.getElementById('mrEditMention').checked;
      data.hoist=document.getElementById('mrEditHoist').checked;
      try{
        var r=await fetch('/api/manage/roles/'+mrSelected.id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
        var d=await r.json();
        if(d.ok){loadMRRoles();mrSelected=null;document.getElementById('mrDetail').innerHTML='<h3 style="font-size:0.85rem;color:var(--text2);margin-bottom:8px;">Details</h3><div style="color:var(--green);font-size:0.85rem;">✅ Gespeichert!</div>';}
        else{alert(d.error||'Fehler');}
      }catch(e){alert(e.message);}
    }

    async function deleteMRRole(){
      if(!mrSelected||!confirm('Rolle "'+mrSelected.name+'" wirklich löschen?'))return;
      try{
        var r=await fetch('/api/manage/roles/'+mrSelected.id,{method:'DELETE'});
        var d=await r.json();
        if(d.ok){loadMRRoles();mrSelected=null;document.getElementById('mrDetail').innerHTML='<h3 style="font-size:0.85rem;color:var(--text2);margin-bottom:8px;">Details</h3><div style="color:var(--green);font-size:0.85rem;">✅ Gelöscht!</div>';}
        else{alert(d.error||'Fehler');}
      }catch(e){alert(e.message);}
    }

    async function createRole(){
      var gid=document.getElementById('mrGuild').value;
      var name=document.getElementById('mrNewName').value.trim();
      var color=document.getElementById('mrNewColor').value;
      if(!gid||!name){alert('Name erforderlich!');return;}
      try{
        var r=await fetch('/api/manage/roles',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({guild_id:gid,name:name,color:color})});
        var d=await r.json();
        if(d.ok){document.getElementById('mrNewName').value='';loadMRRoles();}
        else{alert(d.error||'Fehler');}
      }catch(e){alert(e.message);}
    }

    loadMRGuilds();
    </script>"""
    return _layout('Rollen-Management', token, body, 'manage-roles')


# ── File Editor API + Page ─────────────────────────────────────────────────────

# Erlaubte Wurzelverzeichnisse für den Editor (Sicherheit)
_EDITOR_ROOTS = {
    'discord_bot': str(BOT_DIR),
    'core': str(BOT_DIR / 'core'),
    'cogs': str(BOT_DIR / 'cogs'),
}
# Dateien die nicht bearbeitet werden dürfen
_EDITOR_BLOCKED = {'.env', '.env.example', 'bot.db', 'dashboard_token.txt', '.pytest_cache'}
# Extensions die als Text gelten
_TEXT_EXTS = {'.py', '.json', '.txt', '.md', '.html', '.css', '.js', '.yml', '.yaml', '.toml', '.cfg', '.ini', '.bat', '.sh', '.env', '.example', '.log'}


def _safe_path(rel_path: str):
    """Gibt den absoluten Pfad zurück, schützt vor Directory-Traversal."""
    clean = rel_path.replace('\\\\', '/').lstrip('/')
    parts = [p for p in clean.split('/') if p and p != '..']
    if not parts:
        return None
    root_key = parts[0]
    if root_key not in _EDITOR_ROOTS:
        return None
    abs_path = Path(_EDITOR_ROOTS[root_key]) / '/'.join(parts[1:])
    abs_path = abs_path.resolve()
    root = Path(_EDITOR_ROOTS[root_key]).resolve()
    if not str(abs_path).startswith(str(root)):
        return None
    return abs_path


def _scan_tree(path: Path, rel_root: str, depth: int = 0):
    """Scannt ein Verzeichnis rekursiv für die Dateibäume."""
    items = []
    if depth > 8:
        return items
    try:
        entries = sorted(path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
    except PermissionError:
        return items
    for entry in entries:
        if entry.name.startswith('.') and entry.name not in ('.env.example',):
            continue
        if entry.name in ('__pycache__', '.pytest_cache', '.git', 'node_modules', 'backups', 'transcripts', 'data'):
            continue
        if entry.is_dir():
            children = _scan_tree(entry, rel_root, depth + 1)
            if children:
                items.append({'name': entry.name, 'type': 'dir', 'children': children})
        else:
            ext = entry.suffix.lower()
            if ext in _TEXT_EXTS or entry.name in ('Dockerfile', 'Makefile', 'docker-compose.yml', 'requirements.txt'):
                rel = str(entry.relative_to(Path(_EDITOR_ROOTS[rel_root]))).replace('\\', '/')
                items.append({'name': entry.name, 'type': 'file', 'path': f'{rel_root}/{rel}', 'ext': ext})
    return items


@dashboard_bp.route('/api/editor/tree')
def api_editor_tree():
    tree = []
    for key, root in _EDITOR_ROOTS.items():
        root_path = Path(root)
        if root_path.exists():
            children = _scan_tree(root_path, key)
            tree.append({'name': key, 'type': 'dir', 'children': children})
    return jsonify(tree)


@dashboard_bp.route('/api/editor/file')
def api_editor_read():
    path = request.args.get('path', '')
    abs_path = _safe_path(path)
    if not abs_path or not abs_path.exists():
        return jsonify(ok=False, error='Datei nicht gefunden'), 404
    if abs_path.name in _EDITOR_BLOCKED:
        return jsonify(ok=False, error='Datei ist gesperrt'), 403
    if abs_path.stat().st_size > 2_000_000:
        return jsonify(ok=False, error='Datei zu groß (>2MB)'), 400
    try:
        content = abs_path.read_text(encoding='utf-8', errors='replace')
        return jsonify(ok=True, content=content, path=path, name=abs_path.name, size=abs_path.stat().st_size)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500


@dashboard_bp.route('/api/editor/file', methods=['PUT'])
def api_editor_save():
    data = request.get_json(force=True)
    path = data.get('path', '')
    content = data.get('content', '')
    abs_path = _safe_path(path)
    if not abs_path:
        return jsonify(ok=False, error='Ungültiger Pfad'), 400
    if abs_path.name in _EDITOR_BLOCKED:
        return jsonify(ok=False, error='Datei ist gesperrt'), 403
    try:
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(content, encoding='utf-8')
        log_audit_event('file_save', {'executor': 'Dashboard', 'target': path})
        return jsonify(ok=True, path=path, size=len(content))
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500


@dashboard_bp.route('/api/editor/file', methods=['DELETE'])
def api_editor_delete():
    path = request.args.get('path', '')
    abs_path = _safe_path(path)
    if not abs_path or not abs_path.exists():
        return jsonify(ok=False, error='Datei nicht gefunden'), 404
    if abs_path.name in _EDITOR_BLOCKED:
        return jsonify(ok=False, error='Datei ist gesperrt'), 403
    try:
        abs_path.unlink()
        log_audit_event('file_delete', {'executor': 'Dashboard', 'target': path})
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500


@dashboard_bp.route('/api/editor/file', methods=['POST'])
def api_editor_create():
    data = request.get_json(force=True)
    path = data.get('path', '')
    abs_path = _safe_path(path)
    if not abs_path:
        return jsonify(ok=False, error='Ungültiger Pfad'), 400
    if abs_path.exists():
        return jsonify(ok=False, error='Datei existiert bereits'), 409
    try:
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text('', encoding='utf-8')
        log_audit_event('file_create', {'executor': 'Dashboard', 'target': path})
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500


@dashboard_bp.route('/editor')
def editor_page():
    token = ''
    body = """<style>
    @import url('https://fonts.googleapis.com/css2?family=Fredoka:wght@400;500;600;700&family=Fira+Code:wght@400;500&display=swap');
    :root{--scratch-blue:#4D97FF;--scratch-green:#4CAF50;--scratch-orange:#FF8C1A;--scratch-purple:#9966FF;
    --scratch-pink:#FF6680;--scratch-yellow:#FFD500;--scratch-red:#FF4D4D;--scratch-teal:#2ECFB0;
    --scratch-dark:#1E1E2E;--scratch-card:#2A2A3D;--scratch-border:#3D3D55;--scratch-surface:#252538;}
    .ed-wrap{display:flex;gap:0;height:calc(100vh - 130px);min-height:500px;overflow:hidden;border-radius:20px;
      border:3px solid var(--scratch-border);background:var(--scratch-dark);box-shadow:0 8px 32px rgba(0,0,0,0.4);}

    /* Sidebar – Dateibrowser */
    .ed-sidebar{width:280px;background:var(--scratch-card);border-right:3px solid var(--scratch-border);
      display:flex;flex-direction:column;flex-shrink:0;}
    .ed-sidebar-head{padding:14px 16px;border-bottom:3px solid var(--scratch-border);font-family:'Fredoka',sans-serif;
      font-weight:700;font-size:1rem;display:flex;justify-content:space-between;align-items:center;
      background:linear-gradient(135deg,var(--scratch-purple),var(--scratch-blue));color:#fff;}
    .ed-sidebar-head button{background:rgba(255,255,255,0.2);color:#fff;border:2px solid rgba(255,255,255,0.3);
      padding:4px 10px;border-radius:12px;font-size:0.72rem;cursor:pointer;font-family:'Fredoka',sans-serif;font-weight:600;}
    .ed-sidebar-head button:hover{background:rgba(255,255,255,0.35);}
    .ed-tree{flex:1;overflow-y:auto;padding:8px 0;}
    .ed-tree::-webkit-scrollbar{width:6px;}
    .ed-tree::-webkit-scrollbar-thumb{background:var(--scratch-border);border-radius:3px;}

    /* Center – Editor */
    .ed-center{flex:1;display:flex;flex-direction:column;overflow:hidden;}

    /* Toolbar – Tabs */
    .ed-toolbar{display:flex;align-items:center;gap:6px;padding:8px 12px;border-bottom:3px solid var(--scratch-border);
      background:var(--scratch-card);min-height:44px;overflow-x:auto;}
    .ed-toolbar::-webkit-scrollbar{height:0;}
    .ed-tab{padding:7px 16px;border-radius:14px;font-size:0.8rem;cursor:pointer;font-family:'Fredoka',sans-serif;font-weight:500;
      background:var(--scratch-surface);color:var(--text2);border:2px solid var(--scratch-border);
      display:flex;align-items:center;gap:6px;transition:all .2s;white-space:nowrap;}
    .ed-tab:hover{border-color:var(--scratch-blue);color:var(--text);transform:translateY(-1px);}
    .ed-tab.active{background:var(--scratch-blue);color:#fff;border-color:var(--scratch-blue);
      box-shadow:0 4px 12px rgba(77,151,255,0.3);}
    .ed-tab .close{opacity:0.4;font-size:0.7rem;margin-left:4px;border-radius:50%;width:18px;height:18px;
      display:flex;align-items:center;justify-content:center;transition:all .15s;}
    .ed-tab .close:hover{opacity:1;background:rgba(255,77,77,0.3);color:var(--scratch-red);}
    .ed-tab .dot{width:8px;height:8px;border-radius:50%;background:var(--scratch-yellow);}

    /* Editor Area */
    .ed-editor{flex:1;overflow:hidden;position:relative;}
    .ed-editor textarea{width:100%;height:100%;background:#1A1A2E;color:#E0E0FF;border:none;padding:16px 20px;
      font-family:'Fira Code','Cascadia Code','Consolas',monospace;font-size:0.88rem;line-height:1.7;resize:none;
      tab-size:4;caret-color:var(--scratch-teal);}
    .ed-editor textarea:focus{outline:none;}
    .ed-editor textarea::selection{background:rgba(77,151,255,0.3);}

    /* Status Bar */
    .ed-status{display:flex;justify-content:space-between;align-items:center;padding:5px 16px;
      background:linear-gradient(90deg,var(--scratch-purple),var(--scratch-blue));
      font-size:0.72rem;color:#fff;font-family:'Fredoka',sans-serif;font-weight:500;}
    .ed-status .pill{background:rgba(255,255,255,0.2);padding:2px 10px;border-radius:10px;}

    /* Empty State */
    .ed-empty{display:flex;align-items:center;justify-content:center;height:100%;color:var(--text3);
      font-family:'Fredoka',sans-serif;font-size:1rem;flex-direction:column;gap:12px;}
    .ed-empty .big{font-size:4rem;animation:bounce 2s infinite;}
    @keyframes bounce{0%,100%{transform:translateY(0);}50%{transform:translateY(-10px);}}

    /* Tree Items */
    .tree-dir{padding:2px 0;}
    .tree-dir-head{display:flex;align-items:center;gap:6px;padding:6px 12px;cursor:pointer;font-size:0.82rem;
      color:var(--text2);font-weight:600;font-family:'Fredoka',sans-serif;border-radius:10px;margin:1px 6px;transition:all .15s;}
    .tree-dir-head:hover{background:rgba(77,151,255,0.1);color:var(--scratch-blue);}
    .tree-dir-head .arrow{transition:transform .2s;font-size:0.6rem;color:var(--scratch-orange);}
    .tree-dir-head.open .arrow{transform:rotate(90deg);}
    .tree-file{display:flex;align-items:center;gap:6px;padding:5px 12px 5px 28px;cursor:pointer;font-size:0.78rem;
      color:var(--text3);transition:all .15s;border-radius:10px;margin:1px 6px;font-family:'Fredoka',sans-serif;}
    .tree-file:hover{background:rgba(77,151,255,0.08);color:var(--text);}
    .tree-file.active{background:rgba(77,151,255,0.15);color:var(--scratch-blue);font-weight:600;
      border-left:3px solid var(--scratch-blue);padding-left:25px;}
    .tree-file .ext{font-size:0.62rem;padding:2px 6px;border-radius:8px;font-weight:600;margin-left:auto;
      font-family:'Fredoka',sans-serif;}
    .ext-py{background:rgba(76,175,80,0.15);color:var(--scratch-green);}
    .ext-json{background:rgba(255,213,0,0.15);color:var(--scratch-yellow);}
    .ext-md{background:rgba(46,207,176,0.15);color:var(--scratch-teal);}
    .ext-html{background:rgba(255,140,26,0.15);color:var(--scratch-orange);}
    .ext-css{background:rgba(153,102,255,0.15);color:var(--scratch-purple);}
    .ext-js{background:rgba(255,213,0,0.15);color:var(--scratch-yellow);}
    .ext-txt{background:rgba(255,255,255,0.05);color:var(--text3);}
    .ext-yml{background:rgba(255,102,128,0.15);color:var(--scratch-pink);}

    /* Scratch-Block Buttons */
    .scratch-btn{font-family:'Fredoka',sans-serif;font-weight:600;border:none;padding:8px 18px;border-radius:14px;
      cursor:pointer;font-size:0.82rem;transition:all .2s;display:inline-flex;align-items:center;gap:6px;
      box-shadow:0 4px 0 rgba(0,0,0,0.2);position:relative;top:0;}
    .scratch-btn:active{top:2px;box-shadow:0 2px 0 rgba(0,0,0,0.2);}
    .scratch-btn-blue{background:var(--scratch-blue);color:#fff;}
    .scratch-btn-blue:hover{background:#5AA0FF;transform:translateY(-1px);}
    .scratch-btn-green{background:var(--scratch-green);color:#fff;}
    .scratch-btn-green:hover{background:#5CBF60;}
    .scratch-btn-red{background:var(--scratch-red);color:#fff;}
    .scratch-btn-red:hover{background:#FF6666;}
    .scratch-btn-orange{background:var(--scratch-orange);color:#fff;}
    .scratch-btn-orange:hover{background:#FFa040;}
    .scratch-btn-purple{background:var(--scratch-purple);color:#fff;}
    .scratch-btn-purple:hover{background:#AA77FF;}
    </style>

    <div class="ed-wrap">
      <div class="ed-sidebar">
        <div class="ed-sidebar-head">
          <span>📂 Dateien</span>
          <button onclick="refreshTree()">🔄 Aktualisieren</button>
        </div>
        <div id="edTree" class="ed-tree"></div>
      </div>
      <div class="ed-center">
        <div id="edToolbar" class="ed-toolbar"></div>
        <div id="edArea" class="ed-editor">
          <div class="ed-empty">
            <div class="big">📝</div>
            <div>Wähle eine Datei aus dem Baum links!</div>
            <div style="font-size:0.75rem;color:var(--text3);">💡 Tipp: Ctrl+S zum Speichern</div>
          </div>
        </div>
        <div id="edStatus" class="ed-status">
          <span id="edStatusLeft" class="pill">🎲 Bereit</span>
          <span id="edStatusRight" class="pill">ScratchAI Editor v2</span>
        </div>
      </div>
    </div>

    <script>
    var edOpen={};
    var edFiles={};
    var edActive=null;
    var edModified={};

    function H(s){return s?s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'):'';}
    function A(u){return fetch(u).then(function(r){return r.json();});}

    function extClass(ext){
      var map={'.py':'ext-py','.json':'ext-json','.md':'ext-md','.html':'ext-html','.css':'ext-css',
        '.js':'ext-js','.txt':'ext-txt','.yml':'ext-yml','.yaml':'ext-yml','.toml':'ext-json',
        '.cfg':'ext-json','.ini':'ext-json','.bat':'ext-txt','.sh':'ext-txt'};
      return map[ext]||'ext-txt';
    }
    function fileIcon(ext){
      var map={'.py':'🐍','.json':'📋','.md':'📖','.html':'🌐','.css':'🎨','.js':'⚡','.txt':'📄',
        '.yml':'⚙️','.yaml':'⚙️','.toml':'⚙️','.ini':'⚙️','.cfg':'⚙️','.bat':'🖥️','.sh':'🖥️'};
      return map[ext]||'📄';
    }
    function fileColor(ext){
      var map={'.py':'var(--scratch-green)','.json':'var(--scratch-yellow)','.md':'var(--scratch-teal)',
        '.html':'var(--scratch-orange)','.css':'var(--scratch-purple)','.js':'var(--scratch-yellow)',
        '.yml':'var(--scratch-pink)','.yaml':'var(--scratch-pink)'};
      return map[ext]||'var(--text3)';
    }

    async function refreshTree(){
      var tree=await A('/api/editor/tree');
      var el=document.getElementById('edTree');
      el.innerHTML='';
      tree.forEach(function(node){el.appendChild(renderDir(node,0));});
    }

    function renderDir(node,depth){
      var div=document.createElement('div');
      div.className='tree-dir';
      var head=document.createElement('div');
      head.className='tree-dir-head'+(edOpen[node.name]?' open':'');
      head.style.paddingLeft=(12+depth*16)+'px';
      head.innerHTML='<span class="arrow">▶</span> 📁 <span>'+H(node.name)+'</span>';
      head.onclick=function(){
        edOpen[node.name]=!edOpen[node.name];
        head.classList.toggle('open');
        body.style.display=edOpen[node.name]?'block':'none';
      };
      div.appendChild(head);
      var body=document.createElement('div');
      body.style.display=edOpen[node.name]?'block':'none';
      if(node.children){
        node.children.forEach(function(child){
          if(child.type==='dir'){body.appendChild(renderDir(child,depth+1));}
          else{body.appendChild(renderFile(child,depth+1));}
        });
      }
      div.appendChild(body);
      return div;
    }

    function renderFile(node,depth){
      var div=document.createElement('div');
      div.className='tree-file'+(edActive===node.path?' active':'');
      div.style.paddingLeft=(28+depth*16)+'px';
      div.innerHTML='<span style="font-size:1rem;">'+fileIcon(node.ext)+'</span> '
        +'<span>'+H(node.name)+'</span>'
        +' <span class="ext '+extClass(node.ext)+'">'+H(node.ext||'?')+'</span>';
      div.dataset.path=node.path;
      div.onclick=function(){openFile(node.path,node.name,node.ext);};
      return div;
    }

    async function openFile(path,name,ext){
      if(edFiles[path]){switchTab(path);return;}
      document.getElementById('edStatusLeft').textContent='⏳ Lade '+name+'...';
      var r=await A('/api/editor/file?path='+encodeURIComponent(path));
      if(!r.ok){alert(r.error||'Fehler beim Laden');document.getElementById('edStatusLeft').textContent='❌ Fehler';return;}
      edFiles[path]={content:r.content,name:name,ext:ext,original:r.content};
      edActive=path;
      renderEditor();
      document.getElementById('edStatusLeft').textContent='📂 '+name+' — '+r.size+' Zeichen';
      refreshTree();
    }

    function switchTab(path){
      saveCurrent();
      edActive=path;
      renderEditor();
      var f=edFiles[path];
      document.getElementById('edStatusLeft').textContent='📂 '+f.name+' — '+(f.content||'').length+' Zeichen';
      refreshTree();
    }

    function closeTab(path,event){
      event.stopPropagation();
      if(edModified[path]&&!confirm('Ungespeicherte Änderungen verwerfen?'))return;
      delete edFiles[path];
      delete edModified[path];
      if(edActive===path){
        var keys=Object.keys(edFiles);
        edActive=keys.length>0?keys[keys.length-1]:null;
      }
      renderEditor();
      refreshTree();
    }

    function saveCurrent(){
      if(!edActive||!edFiles[edActive])return;
      var ta=document.querySelector('#edArea textarea');
      if(ta)edFiles[edActive].content=ta.value;
    }

    async function saveFile(){
      saveCurrent();
      if(!edActive)return;
      var f=edFiles[edActive];
      document.getElementById('edStatusLeft').textContent='💾 Speichert...';
      try{
        var r=await fetch('/api/editor/file',{method:'PUT',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({path:edActive,content:f.content})});
        var d=await r.json();
        if(d.ok){
          f.original=f.content;
          delete edModified[edActive];
          document.getElementById('edStatusLeft').textContent='✅ '+f.name+' gespeichert!';
          renderToolbar();
          flashStatus('green');
        }else{
          document.getElementById('edStatusLeft').textContent='❌ '+(d.error||'Fehler');
          flashStatus('red');
        }
      }catch(e){
        document.getElementById('edStatusLeft').textContent='❌ '+e.message;
        flashStatus('red');
      }
    }

    async function deleteFile(){
      if(!edActive||!confirm('Datei "'+edFiles[edActive].name+'" wirklich löschen?'))return;
      try{
        var r=await fetch('/api/editor/file?path='+encodeURIComponent(edActive),{method:'DELETE'});
        var d=await r.json();
        if(d.ok){
          delete edFiles[edActive];delete edModified[edActive];edActive=null;
          renderEditor();refreshTree();
          document.getElementById('edStatusLeft').textContent='🗑️ Gelöscht!';
          flashStatus('orange');
        }else{alert(d.error);}
      }catch(e){alert(e.message);}
    }

    function flashStatus(color){
      var bar=document.getElementById('edStatus');
      var colors={green:'var(--scratch-green)',red:'var(--scratch-red)',orange:'var(--scratch-orange)'};
      bar.style.background='linear-gradient(90deg,'+(colors[color]||'var(--scratch-purple)')+',var(--scratch-blue))';
      setTimeout(function(){bar.style.background='';},1500);
    }

    function renderToolbar(){
      var el=document.getElementById('edToolbar');
      var html='';
      Object.keys(edFiles).forEach(function(path){
        var f=edFiles[path];
        var mod=edModified[path];
        var active=edActive===path;
        html+='<div class="ed-tab'+(active?' active':'')+'" onclick="switchTab(\\''+path+'\\')" '
          +'style="'+(active?'':'border-color:'+fileColor(f.ext))+'">'
          +fileIcon(f.ext)+' '+H(f.name)
          +(mod?' <span class="dot"></span>':'')
          +' <span class="close" onclick="closeTab(\\''+path+'\\',event)">✕</span></div>';
      });
      if(edActive){
        var f=edFiles[edActive];
        html+='<div style="margin-left:auto;display:flex;gap:6px;">'
          +'<button class="scratch-btn scratch-btn-green" onclick="saveFile()">💾 Speichern</button>'
          +'<button class="scratch-btn scratch-btn-red" onclick="deleteFile()">🗑️ Löschen</button></div>';
      }
      el.innerHTML=html;
    }

    function renderEditor(){
      renderToolbar();
      var area=document.getElementById('edArea');
      if(!edActive||!edFiles[edActive]){
        area.innerHTML='<div class="ed-empty"><div class="big">📝</div>'
          +'<div>Wähle eine Datei aus dem Baum links!</div>'
          +'<div style="font-size:0.75rem;color:var(--text3);">💡 Tipp: Ctrl+S zum Speichern</div></div>';
        return;
      }
      var f=edFiles[edActive];
      area.innerHTML='<textarea id="edTa" spellcheck="false">'+H(f.content)+'</textarea>';
      var ta=document.getElementById('edTa');
      ta.addEventListener('input',function(){
        f.content=ta.value;
        if(f.content!==f.original){edModified[edActive]=true;}else{delete edModified[edActive];}
        renderToolbar();
        var pos=ta.selectionStart;
        var before=ta.value.substring(0,pos);
        var line=before.split('\\n').length;
        var col=pos-before.lastIndexOf('\\n');
        var lines=ta.value.split('\\n').length;
        document.getElementById('edStatusRight').textContent='✏️ Zeile '+line+', Spalte '+col+' — '+lines+' Zeilen';
      });
      ta.addEventListener('keydown',function(e){
        if(e.ctrlKey&&e.key==='s'){e.preventDefault();saveFile();}
        if(e.key==='Tab'){
          e.preventDefault();
          var start=ta.selectionStart,end=ta.selectionEnd;
          ta.value=ta.value.substring(0,start)+'    '+ta.value.substring(end);
          ta.selectionStart=ta.selectionEnd=start+4;
          ta.dispatchEvent(new Event('input'));
        }
      });
      ta.addEventListener('click',function(){
        var pos=ta.selectionStart;
        var before=ta.value.substring(0,pos);
        var line=before.split('\\n').length;
        var col=pos-before.lastIndexOf('\\n');
        document.getElementById('edStatusRight').textContent='✏️ Zeile '+line+', Spalte '+col;
      });
      ta.focus();
    }

    refreshTree();
    </script>"""
    return _layout('Code Editor', token, body, 'editor')


# ── App + Start ────────────────────────────────────────────────────────────────

def _create_app():
    app = Flask(__name__, template_folder='templates')
    app.register_blueprint(dashboard_bp)
    return app

def start_dashboard(bot_instance, port=5682):
    global _bot, _start_time
    _bot = bot_instance
    _start_time = datetime.now(timezone.utc)
    app = _create_app()
    thread = threading.Thread(target=lambda: app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False), daemon=True)
    thread.start()
    logger.info(f'Dashboard gestartet auf Port {port}')


class Dashboard(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        _store_message(message)

    @app_commands.command(name='dashboard', description='Zeigt die URL für das lokale Web-Dashboard')
    async def dashboard_command(self, interaction: discord.Interaction):
        if not OWNER_ID or interaction.user.id != OWNER_ID:
            await interaction.response.send_message('⛔ Nur für den Bot-Owner.', ephemeral=True)
            return
        await interaction.response.send_message(
            embed=discord.Embed(
                title='🌐 Dashboard',
                description='**URL:** `http://127.0.0.1:5682/`\n\n⚠️ *Nur lokal auf diesem PC erreichbar.*',
                color=discord.Color.blue()
            ), ephemeral=True)


async def setup(bot):
    await bot.add_cog(Dashboard(bot))
