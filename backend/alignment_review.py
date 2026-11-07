"""Human semantic judgments for four-column alignment exports."""

import unicodedata

from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from .dictionary import is_han


RED = 'FFCC0000'
BLACK = 'FF000000'


def source_glyph(char: str) -> bool:
    return is_han(char) or unicodedata.category(char) == 'Co' or char == '□'


def comparison_key(value: str) -> str:
    """Lowercase and remove punctuation for comparison, preserving Vietnamese accents."""
    return ' '.join(''.join(
        ' ' if unicodedata.category(char).startswith('P') else char
        for char in unicodedata.normalize('NFC', value).casefold()
    ).split())


def export_text(value: str, side: str, colors: list | None = None):
    """Clean an alignment field at export without changing saved OCR or review marks."""
    output, painted = [], []
    for char, color in zip(value, colors if colors is not None else [None] * len(value)):
        if unicodedata.category(char).startswith('P'):
            continue
        if char.isspace():
            if side == 'target':
                output.append(char)
                painted.append(None)
            continue
        for lowered in (char.lower() if side == 'target' else char):
            output.append(lowered)
            painted.append(color)
    return ''.join(output), painted


def paint(text: str, marks: list[dict], side: str):
    colors = ['match'] * len(text)
    for mark in marks:
        start, end = mark[f'{side}_start'], mark[f'{side}_end']
        colors[start:end] = [mark['kind']] * (end - start)
    return colors


def unmarked_count(text: str, colors: list, side: str) -> int:
    if side == 'source':
        return sum(color is None for char, color in zip(text, colors) if source_glyph(char))
    return sum(color is None for char, color in zip(text, colors) if char.isalpha())


def rich_text(text: str, colors: list):
    if not text:
        return ''
    rendered_color = lambda color: RED if color in ('mismatch', 'unknown') else BLACK
    effective_colors = list(colors)
    following_color = None
    for index in range(len(text) - 1, -1, -1):
        if text[index].isspace():
            effective_colors[index] = following_color
        else:
            following_color = colors[index]
    preceding_color = None
    for index, char in enumerate(text):
        if char.isspace():
            if effective_colors[index] is None:
                effective_colors[index] = preceding_color
        else:
            preceding_color = colors[index]
    result = CellRichText()
    start = 0
    for index in range(1, len(text) + 1):
        if index == len(text) or rendered_color(effective_colors[index]) != rendered_color(effective_colors[start]):
            result.append(TextBlock(InlineFont(color=rendered_color(effective_colors[start])), text[start:index]))
            start = index
    return result


def score(rows: list[dict]):
    total = red = unmarked = 0
    for row in rows:
        source = row['source']
        colors = paint(source, row.get('marks', []), 'source')
        target = row['target']
        unmarked += unmarked_count(target, paint(target, row.get('marks', []), 'target'), 'target')
        for char, color in zip(source, colors):
            if source_glyph(char):
                total += 1
                red += color in ('mismatch', 'unknown')
                unmarked += color is None
    return {'total': total, 'red': red, 'unmarked': unmarked,
            'percent': round(100 * (1 - red / total), 2) if total and not unmarked else None}


def score_boxes(pages: list[dict]):
    total = red = 0
    for page in pages:
        for box in page['boxes']:
            for char in box['transcription']:
                if source_glyph(char):
                    total += 1
                    red += box.get('review_kind') in ('mismatch', 'unknown')
    return {'total': total, 'red': red, 'unmarked': 0,
            'percent': round(100 * (1 - red / total), 2) if total else None}
