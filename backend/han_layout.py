"""Image-derived character coordinates for mixed ink Nôm / Quốc ngữ scans."""
import io
from uuid import uuid4

from PIL import Image, ImageFilter
from .ink_colors import PROFILES, ink_mask, profile_colors

PIPELINE_VERSION = 'nom-ink-characters-v2'


def prepare_han_image(image, ink_profile='red_qn'):
    import numpy as np
    picture = image.convert('RGB')
    rgb = np.asarray(picture).astype(np.int16)
    gray = np.asarray(picture.convert('L')).astype(np.int16)
    _, han_color = profile_colors(ink_profile)
    background = np.asarray(picture.convert('L').filter(ImageFilter.GaussianBlur(max(5, picture.height * .0075)))).astype(np.int16)
    mask = (gray < 170) & (background - gray > 25)
    if han_color == 'neutral':
        red_qn = ((rgb[:, :, 0] - rgb[:, :, 1] > 28) &
                  (rgb[:, :, 0] - rgb[:, :, 2] > 10) & (rgb[:, :, 1] < 190))
        colored = int(red_qn.sum()) > max(100, picture.width * picture.height * .0003)
        if colored:
            neutral = (rgb[:, :, 0] - rgb[:, :, 1] < 18) & (rgb[:, :, 0] - rgb[:, :, 2] < 28)
            mask &= neutral
    else:
        han_mask = ink_mask(picture, han_color)
        mask &= han_mask
        colored = int(han_mask.sum()) > max(100, picture.width * picture.height * .0003)
    # Scan edges are not glyphs. This margin is below 1% of the image.
    margin = max(1, round(min(picture.size) * .008))
    mask[:margin] = False; mask[-margin:] = False
    mask[:, :margin] = False; mask[:, -margin:] = False
    if colored:
        pixels = np.full(rgb.shape, 255, dtype=np.uint8)
        pixels[mask] = rgb[mask].astype(np.uint8)
        picture = Image.fromarray(pixels)
    return picture, mask, colored


def character_regions(mask, direction=2):
    """Use ink gaps, never equal divisions of an OCR line, as character bounds."""
    import numpy as np
    working = mask.T if direction == 1 else mask
    height, width = working.shape
    active = np.flatnonzero(working.sum(axis=1) > max(8, width * .008))
    groups = []
    for y in active:
        if not groups or y - groups[-1][-1] > max(4, height * .005):
            groups.append([int(y)])
        else: groups[-1].append(int(y))
    if direction == 1:
        groups.reverse()
    result = []
    for line, group in enumerate(groups):
        top, bottom = group[0], group[-1] + 1
        size = bottom - top
        if size < max(10, height * .008) or size > height * .18:
            continue
        active_x = np.flatnonzero(working[top:bottom].sum(axis=0) > max(2, size * .04))
        parts = []
        for x in active_x:
            if not parts or x - parts[-1][-1] > max(5, size * .28):
                parts.append([int(x)])
            else: parts[-1].append(int(x))
        row = []
        for part in parts:
            left, right = part[0], part[-1] + 1
            yy, xx = np.where(working[top:bottom, left:right])
            if len(xx) < max(50, size * size * .02) or not .15 * size <= right - left <= 2 * size:
                continue
            bounds = (max(0, left - 4), max(0, top + int(yy.min()) - 4), min(width, right + 4), min(height, top + int(yy.max()) + 5))
            if direction == 1:
                bounds = (bounds[1], bounds[0], bounds[3], bounds[2])
            row.append({'bounds': bounds, 'line': line})
        if len(row) >= 2:
            result.extend(row)
    return result


def pack_lines(picture, glyphs):
    """Tight horizontal rows prevent the remote detector joining distant columns."""
    rows = {}
    for glyph in glyphs:
        rows.setdefault(glyph['line'], []).append(glyph)
    width = max(len(row) for row in rows.values()) * 90 + 40
    atlas = Image.new('RGB', (width, len(rows) * 140 + 40), 'white')
    placements = []
    for row_index, row in enumerate(rows.values()):
        start = (width - len(row) * 90) // 2
        for column, glyph in enumerate(row):
            crop = picture.crop(glyph['bounds'])
            crop.thumbnail((78, 84), Image.Resampling.LANCZOS)
            x = start + column * 90 + (90 - crop.width) // 2
            y = 20 + row_index * 140 + (100 - crop.height) // 2
            atlas.paste(crop, (x, y))
            placements.append({**glyph, 'atlas': (x, y, x + crop.width, y + crop.height)})
    return atlas, placements


def map_characters(result, glyphs):
    """Attach text only when an OCR region contains the same number of glyphs."""
    mapped = {}
    for box in result['boxes']:
        xs = [p[0] for p in box['points']]; ys = [p[1] for p in box['points']]
        left, top, right, bottom = min(xs), min(ys), max(xs), max(ys)
        candidates = []
        for index, glyph in enumerate(glyphs):
            a, b, c, d = glyph['atlas']
            if left <= (a + c) / 2 <= right and top <= (b + d) / 2 <= bottom:
                candidates.append(index)
        text = [char for char in box['transcription'] if not char.isspace()]
        if len(candidates) != len(text) or len({glyphs[index]['line'] for index in candidates}) > 1:
            continue
        for index, char in zip(candidates, text):
            mapped.setdefault(index, char)
    boxes, lines = [], {}
    for index, glyph in enumerate(glyphs):
        left, top, right, bottom = glyph['bounds']
        char = mapped.get(index, '□')
        boxes.append({'id': 'han-' + uuid4().hex, 'transcription': char, 'points': [[left, top], [right, top], [right, bottom], [left, bottom]]})
        lines.setdefault(glyph['line'], []).append(char)
    unknown = len(glyphs) - len(mapped)
    warnings = ([f'{unknown} ký tự chưa ghép được với OCR; ô □ cần Gán nhãn.'] if unknown else [])
    return {'boxes': boxes, 'text_lines': [''.join(line) for line in lines.values()], 'warnings': warnings}


def jpeg_bytes(image):
    stream = io.BytesIO(); image.convert('RGB').save(stream, format='JPEG', quality=96)
    return stream.getvalue()
