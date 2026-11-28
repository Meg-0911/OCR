"""Lossless readable TSV: positional IDs, original numbering, both scripts, warnings."""
import csv
import io
import shutil
from pathlib import Path

from backend.quick_review import read_reference


def main():
    path = Path(__file__).resolve().parents[1] / 'TruyenKieu.txt'
    rows = read_reference(path)
    if path.read_text(encoding='utf-8-sig').startswith('Thứ tự\t'):
        print('Already cleaned')
        return
    backup = path.parent / 'backend/data/.workspace/backups/TruyenKieu.original.txt'
    backup.parent.mkdir(parents=True, exist_ok=True)
    if not backup.exists():
        shutil.copy2(path, backup)
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
    writer.writerow(['Thứ tự', 'Số dòng gốc', 'Chữ Nôm', 'Quốc ngữ', 'Ghi chú'])
    for row in rows:
        writer.writerow([row['position'], row['label'], row['source'], row['target'], row['note']])
    path.write_text(stream.getvalue(), encoding='utf-8')
    assert read_reference(path) == rows
    print(f'{len(rows)} lines; original kept at {backup}')


if __name__ == '__main__':
    main()
