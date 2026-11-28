"""Nôm Na Việt's public reading index; never fall back to Unihan here."""
import json
import re
import unicodedata
from functools import cached_property
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import httpx

INDEX_URL = 'https://nomnaviet.com/data/nom-dict.json'
SOURCE = 'Nôm Na Việt'
DETAIL_VERSION = 2


def key(text):
    return unicodedata.normalize('NFC', text).strip().casefold()


class NomDictionary:
    def __init__(self, folder: Path):
        self.folder = folder
        self.path = folder / 'nomnaviet-readings.json'

    @cached_property
    def index(self):
        if not self.path.is_file():
            return {}
        data = json.loads(self.path.read_text(encoding='utf-8'))
        return {key(reading): entries for reading, entries in data.items()}

    @cached_property
    def reverse(self):
        result = {}
        for reading, entries in self.index.items():
            for entry in entries:
                result.setdefault(entry['c'], set()).add(reading)
        return result

    def matches(self, character, reading):
        return key(reading) in self.reverse.get(character, ())

    def search(self, query):
        query = key(query)
        readings = self.reverse.get(query, ())
        entries = ([{'c': query, 'm': ', '.join(sorted(readings)), 'w': 100}]
                   if readings else self.index.get(query, []))
        return {'ready': bool(self.index), 'source': SOURCE, 'query': query,
                'url': 'https://nomnaviet.com/en/search?q=' + quote(query),
                'entries': [{'character': e['c'], 'summary': e.get('m', ''),
                             'readings': sorted(self.reverse.get(e['c'], ())),
                             'url': 'https://nomnaviet.com/en/character/' + quote(e['c'])}
                            for e in sorted(entries, key=lambda e: -e.get('w', 0))]}

    def detail(self, character):
        if not 1 <= len(character) <= 4:
            raise ValueError('Chọn một chữ để tra cứu.')
        folder = self.folder / 'nomnaviet-details'
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / ('-'.join(f'{ord(c):x}' for c in character) + '.json')
        cached = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else None
        if cached and cached.get('cache_version') == DETAIL_VERSION:
            return cached
        url = 'https://api.nomnaviet.com/api/dictionary/character/' + quote(character, safe='')
        def fetch(endpoint):
            response = httpx.get(endpoint, timeout=20)
            response.raise_for_status()
            payload = response.json()
            if not payload.get('success') or not isinstance(payload.get('data'), dict):
                raise ValueError('Nguồn từ điển chưa trả về mục từ hợp lệ.')
            return payload['data']
        try:
            data = fetch(url)
        except (httpx.HTTPError, ValueError):
            if cached:
                return {**cached, 'variants': cached.get('variants', []), 'historical_forms': cached.get('historical_forms', []),
                        'variants_notice': 'Đang dùng nghĩa đã lưu; chưa tải được dữ liệu dị thể. Thử tra lại khi có mạng.'}
            raise
        result = {'character': character, 'source': SOURCE,
                  'readings': data.get('readings', []), 'meanings': data.get('meanings', []),
                  'examples': data.get('examples', [])[:8], 'variants': [], 'historical_forms': []}
        seen = set()
        for field, label in (('nomVariants', 'Dị thể Nôm'), ('traditionalForm', 'Phồn thể'), ('simplifiedForm', 'Giản thể')):
            values = data.get(field) or []
            if isinstance(values, str):
                values = [values]
            if not isinstance(values, list):
                continue
            for value in values:
                if not isinstance(value, str) or not value.strip() or value == character or (value, label) in seen:
                    continue
                seen.add((value, label))
                result['variants'].append({'character': value, 'kind': label, 'source': SOURCE,
                                           'readings': sorted(self.reverse.get(value, ()))})
        try:
            forms = fetch(url + '/variants').get('variants')
            if not isinstance(forms, list):
                raise ValueError('Dữ liệu dạng chữ không hợp lệ.')
            for form in forms:
                if not isinstance(form, dict):
                    continue
                filename = form.get('imagePath', '')
                if not isinstance(filename, str) or not re.fullmatch(r'[a-zA-Z0-9_-]+\.(?:png|jpe?g|webp)', filename):
                    continue
                result['historical_forms'].append({'id': str(form.get('id') or filename),
                    'script_type': str(form.get('scriptType') or 'other'), 'source': SOURCE,
                    'image_url': 'https://api.nomnaviet.com/api/dictionary/glyph/' + filename})
            result['cache_version'] = DETAIL_VERSION
        except (httpx.HTTPError, ValueError):
            # Keep useful meanings/Unicode variants; retry the optional images next lookup.
            result['variants_notice'] = 'Chưa tải được ảnh dạng chữ cổ. Các dị thể có mã chữ bên trên vẫn dùng được.'
        from .file_io import replace_file
        temporary = path.with_suffix('.' + uuid4().hex + '.tmp')
        temporary.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
        replace_file(temporary, path)
        return result
