"""SQLite is the checkpoint; PPOCRLabel text files are recoverable projections."""
import json
import os
import sqlite3
import threading
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

CATEGORIES = ("ch", "vi", "intro", "ref", "toc", "blank", "misc")
PAIR_TARGET = 2000
DEMO_SOURCE = ["天地玄黃宇宙洪荒", "日月盈昃辰宿列張", "寒來暑往秋收冬藏", "閏餘成歲律呂調陽", "雲騰致雨露結為霜", "金生麗水玉出崑岡"]
DEMO_TARGET = ["Thiên địa huyền hoàng, vũ trụ hồng hoang.", "Nhật nguyệt doanh trắc, thần tú liệt trương.", "Hàn lai thử vãng, thu thâu đông tàng.", "Nhuận dư thành tuế, luật lữ điều dương.", "Vân đằng trí vũ, lộ kết vi sương.", "Kim sinh lệ thủy, ngọc xuất Côn Cương."]


def ordered_boxes(boxes, category):
    if category == "ch":
        return sorted(boxes, key=lambda b: (-max(p[0] for p in b["points"]), min(p[1] for p in b["points"])))
    return sorted(boxes, key=lambda b: (min(p[1] for p in b["points"]), min(p[0] for p in b["points"])))


class Store:
    def __init__(self, root: Path):
        self.root = root
        self.data = root / "data"
        self.local = self.data / ".workspace"
        self.local.mkdir(parents=True, exist_ok=True)
        for directory in ("raw_data", "processed_images", "output_alignment"):
            (self.data / directory).mkdir(exist_ok=True)
        self.db_path = self.local / "workspace.sqlite3"
        self.lock = threading.RLock()
        with self.db() as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS books (
              id TEXT PRIMARY KEY, name TEXT NOT NULL, filename TEXT NOT NULL,
              source TEXT, demo INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS pages (
              id TEXT PRIMARY KEY, book_id TEXT NOT NULL REFERENCES books(id),
              number INTEGER NOT NULL, category TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
              width INTEGER NOT NULL DEFAULT 800, height INTEGER NOT NULL DEFAULT 1100,
              boxes TEXT NOT NULL DEFAULT '[]', version INTEGER NOT NULL DEFAULT 0,
              UNIQUE(book_id,number,category));
            CREATE TABLE IF NOT EXISTS alignments (
              book_id TEXT PRIMARY KEY REFERENCES books(id), rows TEXT NOT NULL DEFAULT '[]');
            """)
        self.seed()
        # Repair interrupted text-file writes from the committed SQLite checkpoint.
        for book in self.books():
            self.sync_labels(book["id"])

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def seed(self):
        with self.db() as db:
            if db.execute("SELECT 1 FROM books WHERE id='demo'").fetchone():
                return
            db.execute("INSERT INTO books VALUES (?,?,?,?,?,?)", ("demo", "Thiên tự văn", "Thiên tự văn.pdf", None, 1, datetime.now(timezone.utc).isoformat()))
            for number in range(1, 13):
                category = "ch" if number % 2 else "vi"
                boxes = []
                for i, text in enumerate(DEMO_SOURCE if category == "ch" else DEMO_TARGET):
                    x, y, w, h = (648 - i * 94, 185, 60, 660) if category == "ch" else (92, 220 + i * 105, 616, 70)
                    boxes.append({"id": f"box-{i+1}", "transcription": text, "points": [[x,y],[x+w,y],[x+w,y+h],[x,y+h]]})
                db.execute("INSERT INTO pages (id,book_id,number,category,status,boxes) VALUES (?,?,?,?,?,?)", (f"demo-{number}", "demo", number, category, "done" if number <= 3 else "pending", json.dumps(boxes, ensure_ascii=False)))
            rows = [{"id":str(uuid4()), "sentence_id": f"Thiên tự văn.001.{i+1}", "source": source, "target": DEMO_TARGET[i], "reviewed": False} for i, source in enumerate(DEMO_SOURCE)]
            db.execute("INSERT INTO alignments VALUES (?,?)", ("demo", json.dumps(rows, ensure_ascii=False)))

    def books(self):
        with self.db() as db:
            return [dict(row) | {"demo":bool(row["demo"])} for row in db.execute("""
            SELECT b.id,b.name,b.filename,b.demo,b.created_at,COUNT(p.id) AS pages,
            SUM(CASE WHEN p.status='done' THEN 1 ELSE 0 END) AS done
            FROM books b LEFT JOIN pages p ON b.id=p.book_id GROUP BY b.id ORDER BY b.demo,b.created_at DESC
            """)]

    def book(self, book_id):
        with self.db() as db:
            row = db.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
            return dict(row) if row else None

    def pair_stats(self):
        """Count saved, complete, distinct pairs across real books only."""
        with self.db() as db:
            alignments = db.execute("""
                SELECT a.rows FROM alignments a JOIN books b ON b.id=a.book_id
                WHERE b.demo=0
            """).fetchall()
        pairs = {}
        incomplete = duplicates = 0
        for alignment in alignments:
            for row in json.loads(alignment['rows']):
                source = ''.join(unicodedata.normalize('NFC', row['source']).split())
                target = ' '.join(unicodedata.normalize('NFC', row['target']).split()).casefold()
                if not source or not target:
                    incomplete += 1
                    continue
                key = (source, target)
                if key in pairs:
                    duplicates += 1
                pairs[key] = pairs.get(key, False) or bool(row.get('reviewed', False))
        count = len(pairs)
        return {
            'target': PAIR_TARGET,
            'pairs': count,
            'reviewed_pairs': sum(pairs.values()),
            'remaining': max(0, PAIR_TARGET - count),
            'duplicate_pairs': duplicates,
            'incomplete_pairs': incomplete,
        }

    @staticmethod
    def page_dict(row):
        page = dict(row)
        page["boxes"] = json.loads(page["boxes"])
        page["image_url"] = f"/api/pages/{page['id']}/image"
        return page

    def pages(self, book_id):
        with self.db() as db:
            return [self.page_dict(row) for row in db.execute("SELECT * FROM pages WHERE book_id=? ORDER BY number,category", (book_id,))]

    def page(self, page_id):
        with self.db() as db:
            row = db.execute("SELECT * FROM pages WHERE id=?", (page_id,)).fetchone()
            return self.page_dict(row) if row else None

    def book_dir(self, book_id):
        return self.local / "books" / book_id

    def sync_labels(self, book_id):
        with self.lock:
            book = self.book(book_id)
            if not book:
                return
            pages = self.pages(book_id)
            for category in CATEGORIES:
                folder = self.book_dir(book_id) / category
                folder.mkdir(parents=True, exist_ok=True)
                if category in ("blank", "misc"):
                    continue
                labels, states = [], []
                for page in pages:
                    if page["category"] != category:
                        continue
                    name = f"{category}/{book['name']}.{page['number']:03d}.jpg"
                    boxes = [{"transcription":b["transcription"], "points":b["points"]} for b in ordered_boxes(page["boxes"], category)]
                    labels.append(name + "\t" + json.dumps(boxes, ensure_ascii=False))
                    states.append(name + "\t" + str(int(page["status"] == "done")))
                for filename, lines in (("Label.txt", labels), ("fileState.txt", states)):
                    target = folder / filename
                    tmp = target.with_suffix(".tmp")
                    tmp.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
                    os.replace(tmp, target)
