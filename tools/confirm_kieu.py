"""One-book migration requested by the owner; back up SQLite before confirming."""
import argparse
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from backend.quick_review import KIEU_NAME
from backend.store import Store


def confirm(root, apply=False):
    database = root / 'backend/data/.workspace/workspace.sqlite3'
    with sqlite3.connect(database, timeout=30) as db:
        book = db.execute('SELECT id FROM books WHERE name=?', (KIEU_NAME,)).fetchall()
        if len(book) != 1:
            raise ValueError('Phải có đúng một bản làm việc Truyện Kiều; không sửa sách khác.')
        book_id = book[0][0]
        payload = db.execute('SELECT rows FROM alignments WHERE book_id=?', (book_id,)).fetchone()
        rows = json.loads(payload[0]) if payload else []
        pending = sum(not row.get('reviewed') for row in rows)
        pages = db.execute("SELECT count(*) FROM pages WHERE book_id=? AND status!='done'", (book_id,)).fetchone()[0]
        report = {'book_id': book_id, 'pairs': len(rows), 'pairs_to_confirm': pending, 'pages_to_confirm': pages}
        if not apply or not (pending or pages):
            return report
        folder = database.parent / 'backups'
        folder.mkdir(exist_ok=True)
        backup = folder / ('before-kieu-confirm-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '.sqlite3')
        with sqlite3.connect(backup) as target:
            db.backup(target)
        db.execute('BEGIN IMMEDIATE')
        # Re-read inside the write transaction in case another editor just saved.
        rows = json.loads(db.execute('SELECT rows FROM alignments WHERE book_id=?', (book_id,)).fetchone()[0])
        for row in rows:
            row['reviewed'] = True
        db.execute('UPDATE alignments SET rows=? WHERE book_id=?', (json.dumps(rows, ensure_ascii=False), book_id))
        db.execute("UPDATE pages SET status='done',version=version+1 WHERE book_id=? AND status!='done'", (book_id,))
        db.commit()
        report['backup'] = str(backup)
    # Publish only this book, without running Store's global startup migrations.
    store = Store.__new__(Store)
    store.root, store.data, store.local = root, root / 'backend/data', database.parent
    store.db_path, store.lock = database, threading.RLock()
    store.sync_labels(book_id)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    options = parser.parse_args()
    print(json.dumps(confirm(Path(__file__).resolve().parents[1], options.apply), ensure_ascii=False, indent=2))
