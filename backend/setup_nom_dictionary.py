"""Download the public Nôm reading index used by quick review (no account needed)."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from backend.nom_dictionary import INDEX_URL, SOURCE


def main():
    folder = Path(__file__).resolve().parent / 'data' / 'dictionaries'
    folder.mkdir(parents=True, exist_ok=True)
    response = httpx.get(INDEX_URL, timeout=60, follow_redirects=True)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or len(data) < 1000 or any(
        not isinstance(entries, list) or any(not isinstance(e.get('c'), str) for e in entries)
        for entries in data.values()
    ):
        raise ValueError('Nguồn từ điển thay đổi định dạng; không ghi đè bản cũ.')
    path = folder / 'nomnaviet-readings.json'
    from backend.file_io import replace_file
    temporary = path.with_suffix('.tmp')
    temporary.write_bytes(response.content)
    replace_file(temporary, path)
    (folder / 'nomnaviet-provenance.json').write_text(json.dumps({
        'source': SOURCE, 'url': INDEX_URL, 'downloaded_at': datetime.now(timezone.utc).isoformat(),
        'sha256': hashlib.sha256(response.content).hexdigest(), 'readings': len(data),
        'note': 'Public reading index; summaries may be abbreviated. Follow original entries for context.'
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'{len(data)} readings saved to {path}')


if __name__ == '__main__':
    main()
