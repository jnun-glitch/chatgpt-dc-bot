"""Pillow-Generierung von Willkommens- und Rank-Cards."""
import asyncio
import io
import urllib.request

try:
    from PIL import Image, ImageDraw, ImageFont
    PILLOW_AVAILABLE = True
except Exception:
    PILLOW_AVAILABLE = False


def _round_corner(img, radius):
    mask = Image.new('L', img.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, img.size[0] - 1, img.size[1] - 1), radius=radius, fill=255)
    out = Image.new('RGBA', img.size, (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def _load_avatar(url, size):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'ScratchAI-Bot/1.0'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = resp.read()
        av = Image.open(io.BytesIO(data)).convert('RGBA').resize((size, size), Image.LANCZOS)
        return _round_corner(av, size // 2)
    except Exception:
        return None


def _font(size, bold=False):
    variants = [
        'segoeui.ttf' if not bold else 'segoeuib.ttf',
        'arial.ttf' if not bold else 'arialbd.ttf',
        'DejaVuSans.ttf' if not bold else 'DejaVuSans-Bold.ttf',
    ]
    for name in variants:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _progress_bar(draw, x, y, w, h, frac, color, bg=(38, 40, 52)):
    draw.rounded_rectangle((x, y, x + w, y + h), radius=h // 2, fill=bg)
    fw = max(h, int(w * min(max(frac, 0.0), 1.0)))
    if fw > 0:
        draw.rounded_rectangle((x, y, x + fw, y + h), radius=h // 2, fill=color)


def make_welcome_card(member, member_count, guild_name):
    """Generiert eine Willkommens-Karte als PNG-Bytes."""
    if not PILLOW_AVAILABLE:
        return None
    try:
        W, H = 1000, 350
        bg = Image.new('RGBA', (W, H), (44, 47, 62, 255))
        draw = ImageDraw.Draw(bg)
        # Verlauf-Effekt (horizontale Streifen)
        for i in range(H):
            t = i / H
            r = int(44 + (75 - 44) * t)
            g = int(47 + (102 - 47) * t)
            b = int(62 + (179 - 62) * t)
            draw.line((0, i, W, i), fill=(r, g, b, 255))

        avatar = _load_avatar(member.display_avatar.url, 180)
        if avatar:
            bg.paste(avatar, (60, (H - 180) // 2), avatar)
        else:
            draw.ellipse((60, (H - 180) // 2, 240, (H - 180) // 2 + 180), fill=(30, 32, 44))

        title_font = _font(52, bold=True)
        sub_font = _font(28)
        small_font = _font(22)

        name = member.display_name if member.display_name else member.name
        if len(name) > 26:
            name = name[:24] + '…'
        draw.text((290, 70), f'Willkommen {name}!', font=title_font, fill=(255, 255, 255))
        draw.text((292, 160), f'Herzlich willkommen im **{guild_name}** Discord!',
                  font=sub_font, fill=(220, 225, 240))
        draw.text((292, 215), f'Du bist Mitglied #{member_count} 💜', font=small_font, fill=(190, 200, 230))

        buf = io.BytesIO()
        bg.convert('RGB').save(buf, format='PNG')
        buf.seek(0)
        return buf
    except Exception:
        return None


def make_rank_card(member, level, xp, xp_needed, rank, member_count):
    """Generiert eine Rank-Card (Level, XP-Fortschritt, Platzierung) als PNG-Bytes."""
    if not PILLOW_AVAILABLE:
        return None
    try:
        W, H = 1000, 350
        bg = Image.new('RGBA', (W, H), (32, 34, 46, 255))
        draw = ImageDraw.Draw(bg)
        for i in range(H):
            t = i / H
            r = int(32 + (70 - 32) * t)
            g = int(34 + (102 - 34) * t)
            b = int(46 + (179 - 46) * t)
            draw.line((0, i, W, i), fill=(r, g, b, 255))

        avatar = _load_avatar(member.display_avatar.url, 160)
        if avatar:
            bg.paste(avatar, (70, (H - 160) // 2), avatar)
        else:
            draw.ellipse((70, (H - 160) // 2, 230, (H - 160) // 2 + 160), fill=(30, 32, 44))

        title_font = _font(44, bold=True)
        level_font = _font(32, bold=True)
        small_font = _font(24)

        name = member.display_name if member.display_name else member.name
        if len(name) > 24:
            name = name[:22] + '…'
        draw.text((290, 50), f'{name}', font=title_font, fill=(255, 255, 255))
        draw.text((292, 120), f'Level {level}  •  #{rank} von {member_count}',
                  font=level_font, fill=(140, 220, 255))

        _progress_bar(draw, 290, 195, W - 380, 34, xp / xp_needed if xp_needed else 0, (108, 99, 255))
        draw.text((290, 245), f'{xp} / {xp_needed} XP', font=small_font, fill=(200, 208, 230))

        buf = io.BytesIO()
        bg.convert('RGB').save(buf, format='PNG')
        buf.seek(0)
        return buf
    except Exception:
        return None


async def make_welcome_card_async(member, member_count, guild_name):
    """Blockierende Bildgenerierung (Avatar-Download + Pillow) aus dem Event-Loop auslagern."""
    return await asyncio.to_thread(make_welcome_card, member, member_count, guild_name)


async def make_rank_card_async(member, level, xp, xp_needed, rank, member_count):
    """Blockierende Bildgenerierung (Avatar-Download + Pillow) aus dem Event-Loop auslagern."""
    return await asyncio.to_thread(make_rank_card, member, level, xp, xp_needed, rank, member_count)
