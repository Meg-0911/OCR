"""Download the public Unicode Unihan data and build an offline lookup database."""
import argparse
import hashlib
import io
import json
import os
import sqlite3
import sys
import zipfile
from contextlib import closing
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
if sys.prefix == sys.base_prefix and (root/'backend/.tools/python').exists():
    sys.path.insert(0,str(root/'backend/.tools/python'))

import httpx
from backend.dictionary import VERSION, UNIHAN_URL, VARIANT_FIELDS


def build_database(content, destination):
    entries = {}
    fields = {'kDefinition','kVietnamese','kMandarin', *VARIANT_FIELDS}
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        for name in archive.namelist():
            if not name.startswith('Unihan') or not name.endswith('.txt'):
                continue
            for line in archive.read(name).decode('utf-8-sig').splitlines():
                if not line or line.startswith('#'):
                    continue
                code,field,value = line.split('\t',2)
                if field in fields:
                    entries.setdefault(chr(int(code[2:],16)),{})[field] = value
    if not entries:
        raise ValueError('Không có dữ liệu từ điển trong Unihan.zip.')
    temporary = destination.with_name(destination.name + '.tmp')
    temporary.unlink(missing_ok=True)
    with closing(sqlite3.connect(temporary)) as db, db:
        db.execute('CREATE TABLE entries (character TEXT PRIMARY KEY,readings TEXT NOT NULL,properties TEXT NOT NULL)')
        db.executemany('INSERT INTO entries VALUES (?,?,?)', ((char,props.get('kVietnamese',''),json.dumps(props,ensure_ascii=False)) for char,props in entries.items()))
    os.replace(temporary,destination)
    return len(entries)


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zip', type=Path, help='Use an already downloaded Unihan.zip, without network')
    args = parser.parse_args()
    folder = root/'backend/data/dictionaries'
    folder.mkdir(parents=True,exist_ok=True)
    with httpx.Client(timeout=90,follow_redirects=True) as client:
        content = args.zip.read_bytes() if args.zip else client.get(UNIHAN_URL).raise_for_status().content
        license_text = client.get('https://www.unicode.org/license.txt').raise_for_status().text if not args.zip else None
    if license_text:
        (folder/'UNICODE-LICENSE.txt').write_text(license_text,encoding='utf-8')
    count = build_database(content,folder/f'Unihan-{VERSION}.sqlite3')
    (folder/'unihan-source.json').write_text(json.dumps({'version':VERSION,'url':UNIHAN_URL,'sha256':hashlib.sha256(content).hexdigest(),'entries':count},indent=2),encoding='utf-8')
    print(f'Installed Unicode Unihan {VERSION}: {count} character entries. No API key required.')


if __name__=='__main__':
    main()
