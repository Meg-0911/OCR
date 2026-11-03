"""Local source discovery and companion Quốc ngữ text matching."""
import re
import unicodedata
from pathlib import Path


def source_files(folder: Path, suffix: str):
    return sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == suffix
                   and p.resolve().parent == folder.resolve()), key=lambda p: p.name.casefold())


def title_key(path: Path):
    title = unicodedata.normalize('NFC', path.stem).casefold().split(',')[0]
    title = re.sub(r'(?:[_\s-]+(?:dịch|quốc ngữ|y))+$', '', title)
    return ' '.join(re.findall(r'[^\W_]+', title, re.UNICODE))


def companion_text(pdf: Path):
    """Require an unambiguous shared title; never match by arbitrary substring."""
    matches = [p for p in source_files(pdf.parent, '.txt') if title_key(p) == title_key(pdf)]
    pdf_matches = [p for p in source_files(pdf.parent, '.pdf') if title_key(p) == title_key(pdf)]
    return matches[0] if len(matches) == 1 and len(pdf_matches) == 1 else None
