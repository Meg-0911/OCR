"""Offline character lookup using Unicode Unihan, with optional local Nôm entries."""
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

VERSION = '17.0.0'
UNIHAN_URL = f'https://www.unicode.org/Public/{VERSION}/ucd/Unihan.zip'
DOCUMENTATION = 'https://www.unicode.org/reports/tr38/'
VARIANT_FIELDS = {
    'kTraditionalVariant':'Phồn thể', 'kSimplifiedVariant':'Giản thể',
    'kSemanticVariant':'Dị thể cùng nghĩa', 'kSpecializedSemanticVariant':'Dị thể nghĩa chuyên biệt',
    'kZVariant':'Dị thể hình chữ', 'kCompatibilityVariant':'Chữ tương thích',
}


def is_han(character):
    return len(character)==1 and (0x3400 <= ord(character) <= 0x4DBF or 0x4E00 <= ord(character) <= 0x9FFF
        or 0xF900 <= ord(character) <= 0xFAFF or 0x20000 <= ord(character) <= 0x3347F)


class Dictionary:
    def __init__(self, folder: Path):
        self.folder = folder
        self.path = folder / f'Unihan-{VERSION}.sqlite3'

    def status(self):
        return {'ready':self.path.is_file(), 'source':f'Unicode Unihan {VERSION}',
                'nom_available':(self.folder/'nom.json').is_file(), 'url':DOCUMENTATION}

    def _local(self):
        path = self.folder / 'nom.json'
        if not path.is_file():
            return []
        try:
            entries = json.loads(path.read_text(encoding='utf-8-sig'))
            if not isinstance(entries, list):
                raise ValueError
            for entry in entries:
                if not isinstance(entry, dict) or not is_han(entry.get('character','')) or not isinstance(entry.get('definitions'),list) or any(not isinstance(text,str) for text in entry['definitions']):
                    raise ValueError
                if any(not isinstance(entry.get(field,[]),list) or any(not isinstance(v,str) for v in entry.get(field,[])) for field in ('readings','variants')):
                    raise ValueError
                if any(entry.get(field) is not None and not isinstance(entry[field],str) for field in ('source','source_url')):
                    raise ValueError
            return entries
        except (ValueError, TypeError):
            raise ValueError('Từ điển nom.json sai định dạng. Xem README để sửa dữ liệu.') from None

    def _unihan(self, character):
        if not self.path.is_file():
            return None
        with closing(sqlite3.connect(f'{self.path.resolve().as_uri()}?mode=ro', uri=True)) as db:
            row = db.execute('SELECT properties FROM entries WHERE character=?', (character,)).fetchone()
        if not row:
            return None
        properties = json.loads(row[0])
        return {
            'character':character, 'codepoint':f'U+{ord(character):04X}', 'source':f'Unicode Unihan {VERSION}',
            'source_url':DOCUMENTATION, 'language':'en',
            'definitions':[properties['kDefinition']] if properties.get('kDefinition') else [],
            'readings':properties.get('kVietnamese','').split(), 'mandarin':properties.get('kMandarin',''),
            'variants':[{'character':chr(int(code,16)), 'kind':kind}
                        for name,kind in VARIANT_FIELDS.items()
                        for code in re.findall(r'U\+([0-9A-F]{4,6})', properties.get(name,''))
                        if int(code,16) <= 0x10FFFF and chr(int(code,16)) != character],
        }

    def lookup(self, character):
        if not is_han(character):
            raise ValueError('Nhập đúng một chữ Hán/Nôm để tra cứu.')
        local = next((e for e in self._local() if e['character']==character), None)
        han = self._unihan(character)
        entry = None
        if local:
            entry = {'character':character, 'codepoint':f'U+{ord(character):04X}',
                     'source':local.get('source') or 'Từ điển Nôm cục bộ',
                     'source_url':local.get('source_url') if (local.get('source_url') or '').startswith(('https://','http://')) else None,
                     'language':'vi', 'definitions':local['definitions'], 'readings':local.get('readings',[]),
                     'mandarin':'', 'variants':[{'character':c, 'kind':'Dị thể trong từ điển Nôm'}
                         for c in local.get('variants',[]) if isinstance(c,str) and is_han(c)]}
        elif han:
            entry = han
        if entry:
            for variant in entry['variants']:
                other = self._unihan(variant['character'])
                variant['definitions'] = other['definitions'] if other else []
                variant['readings'] = other['readings'] if other else []
        return {'query':character, 'found':bool(entry), 'entry':entry,
                'fallback':not bool(local), 'notice':
                'Chỉ hỗ trợ đối chiếu từng chữ. Có mục từ không chứng minh OCR đúng ngữ cảnh; không có mục từ cũng chưa chứng minh chữ sai.'}

    def search(self, query):
        query = query.strip()
        if not query or len(query)>100:
            raise ValueError('Nhập từ khóa từ 1 đến 100 ký tự.')
        if is_han(query):
            result = self.lookup(query)
            return [result['entry']] if result['entry'] else []
        found = [entry['character'] for entry in self._local()
                 if any(query.casefold() in str(r).casefold() for r in entry.get('readings',[]))]
        if self.path.is_file():
            escaped = query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
            with closing(sqlite3.connect(f'{self.path.resolve().as_uri()}?mode=ro', uri=True)) as db:
                found += [row[0] for row in db.execute("SELECT character FROM entries WHERE readings LIKE ? ESCAPE '\\' LIMIT 30", (f'%{escaped}%',))]
        return [self.lookup(char)['entry'] for char in dict.fromkeys(found)][:30]
