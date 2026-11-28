"""SQLite is the checkpoint; PPOCRLabel text files are recoverable projections."""
import json
import os
import re
import sqlite3
import threading
import unicodedata
from .alignment_review import comparison_key, export_text, score_boxes, source_glyph, paint
from .alignment_links import attach_refs, ref_text, replace_ranges, advance_refs, matches_export_frame
from .alignment_output import prepared_rows, write_alignment
from .file_io import replace_file
import csv
from difflib import SequenceMatcher
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path

CATEGORIES = ("ch", "vi", "both", "intro", "ref", "toc", "blank", "misc")
PAIR_TARGET = 2000


def completed_ocr_languages(result):
    completed=result.get('completed_languages',['han'] if 'text_lines' in result else [])
    requested=result.get('requested_languages')
    return [language for language in ('han','vi') if language in completed and (requested is None or language in requested)]


def alignment_word_count(text, field):
    if field == 'source':
        return sum(source_glyph(char) for char in text)
    return sum(bool(re.search(r'\w', word, re.UNICODE)) for word in text.split())


def character_box_groups(boxes, reading_direction):
    """Group character boxes into reading lines/columns in page order."""
    if not boxes:
        return []
    axis = 0 if reading_direction == 1 else 1
    travel = 1 if reading_direction == 1 else 0
    geometry = {id(box): (sum(point[axis] for point in box['points']) / 4,
                         max(point[axis] for point in box['points']) - min(point[axis] for point in box['points']))
                for box in boxes}

    def center(box):
        return geometry[id(box)][0]

    def size(box):
        return geometry[id(box)][1]

    groups = []
    if all(box.get('review_order') is not None for box in boxes):
        for box in sorted(boxes, key=lambda item: item['review_order']):
            previous = groups[-1][-1] if groups else None
            if previous and abs(center(previous) - center(box)) < max(size(previous), size(box)) * .5:
                groups[-1].append(box)
            else:
                groups.append([box])
        return groups

    for box in sorted(boxes, key=center, reverse=reading_direction == 1):
        group = next((items for items in groups
                      if abs(center(items[0]) - center(box)) < max(size(items[0]), size(box)) * .5), None)
        if group is None:
            groups.append([box])
        else:
            group.append(box)
    return [sorted(group, key=lambda box: min(point[travel] for point in box['points'])) for group in groups]


def box_text_lines(boxes, reading_direction, category='ch', image_size=None):
    """Build OCR text from its boxes so text and geometry cannot drift apart."""
    if not boxes:
        return []
    if category == 'vi':
        return [box['transcription'] for box in ordered_boxes(boxes, 'vi', 2, image_size)]
    if image_size and image_size[0] > image_size[1]:
        middle = image_size[0] / 2
        left, right = [], []
        for box in boxes:
            (left if sum(point[0] for point in box['points']) / 4 < middle else right).append(box)
        if left and right:
            return box_text_lines(left, reading_direction, category) + box_text_lines(right, reading_direction, category)
    return [''.join(box['transcription'] for box in group)
            for group in character_box_groups(boxes, reading_direction)]


def source_box_text_lines(boxes, reading_direction, image_size=None, granularity=None):
    if boxes and all(box.get('export_group') for box in boxes):
        return [box['transcription'] for box in nom_export_boxes(boxes, reading_direction, image_size)]
    if granularity == 'phrase':
        return [box['transcription'] for box in ordered_boxes(boxes, 'ch', reading_direction, image_size)]
    return box_text_lines(boxes, reading_direction, 'ch', image_size)


def ordered_boxes(boxes, category, reading_direction=2, image_size=None):
    if boxes and category in ('ch', 'both') and all(box.get('review_order') is not None for box in boxes):
        return sorted(boxes, key=lambda box: box['review_order'])
    # Two-page landscape scans are read left page first, then right page.
    # A single-page landscape scan with content on one side keeps its order.
    if image_size and image_size[0] > image_size[1] and boxes:
        middle=image_size[0]/2
        left=[]; right=[]
        for box in boxes:
            (left if sum(p[0] for p in box['points'])/4 < middle else right).append(box)
        if left and right:
            return ordered_boxes(left,category,reading_direction)+ordered_boxes(right,category,reading_direction)
    if boxes and category in ('ch','both'):
        return [box for group in character_box_groups(boxes, reading_direction) for box in group]
    if category in ("ch", "both") and reading_direction == 1:
        return sorted(boxes, key=lambda b: (-max(p[0] for p in b["points"]), min(p[1] for p in b["points"])))
    return sorted(boxes, key=lambda b: (min(p[1] for p in b["points"]), min(p[0] for p in b["points"])))


def label_groups(page):
    """An image can belong to both language folders; labels stay language-specific."""
    category = page['category']
    if category == 'both':
        return ('ch', 'vi')
    if category in ('intro','ref','toc'):
        languages=page['ocr_languages']
        return (category,) + (('ch',) if 'han' in languages else ()) + (('vi',) if 'vi' in languages else ())
    return (category,)


def label_boxes(page, category):
    size=(page['width'],page['height'])
    if category == 'ch':
        return page['export_boxes']
    if category == 'vi':
        return ordered_boxes(page['vi_boxes'] or (page['boxes'] if page['category']=='vi' else []), 'vi', 2,size)
    return ordered_boxes([*page['boxes'], *page['vi_boxes']], category, page['reading_direction'],size)


def nom_export_boxes(boxes, direction, image_size=None):
    """Combine edit-time glyph boxes into physical Nôm columns or rows for PPOCRLabel."""
    if boxes and all(box.get('export_group') for box in boxes):
        groups={}
        for box in boxes:
            groups.setdefault(box['export_group'],[]).append(box)
        output=[]
        for _,members in sorted(groups.items(),key=lambda item:item[1][0].get('export_order') or 0):
            members.sort(key=lambda box:box.get('export_character_order') or 0)
            x0=min(point[0] for box in members for point in box['points'])
            y0=min(point[1] for box in members for point in box['points'])
            x1=max(point[0] for box in members for point in box['points'])
            y1=max(point[1] for box in members for point in box['points'])
            output.append({'transcription':''.join(box['transcription'] for box in members),
                           'points':[[x0,y0],[x1,y0],[x1,y1],[x0,y1]],
                           'source_ids':[box['id'] for box in members]})
        return output
    ordered=ordered_boxes(boxes,'ch',direction,image_size)
    if not ordered:
        return []
    axis=0 if direction==1 else 1
    travel=1 if direction==1 else 0
    def extent(box, dimension):
        values=[point[dimension] for point in box['points']]
        return min(values),max(values)
    def center(box):
        lo,hi=extent(box,axis)
        return (lo+hi)/2
    def same_line(a,b):
        a0,a1=extent(a,axis); b0,b1=extent(b,axis)
        return abs(center(a)-center(b)) < max(a1-a0,b1-b0)*.5
    def merge(run):
        x0=min(extent(box,0)[0] for box in run)
        y0=min(extent(box,1)[0] for box in run)
        x1=max(extent(box,0)[1] for box in run)
        y1=max(extent(box,1)[1] for box in run)
        return {'transcription':''.join(box['transcription'] for box in run),
                'points':[[x0,y0],[x1,y0],[x1,y1],[x0,y1]],
                'source_ids':[box['id'] for box in run]}
    output=[]; run=[]
    for box in ordered:
        if run:
            previous=run[-1]
            a0,a1=extent(previous,travel); b0,b1=extent(box,travel)
            gap=b0-a1
            span=max(a1-a0,b1-b0)
            if (len(previous['transcription'])>1 or len(box['transcription'])>1 or
                    not previous['transcription'].strip() or not box['transcription'].strip() or
                    not same_line(run[0],box) or gap>span*.75 or
                    previous['transcription'][-1:].isspace() or box['transcription'][:1].isspace()):
                output.append(merge(run)); run=[]
        run.append(box)
    if run:
        output.append(merge(run))
    return output


class Store:
    def __init__(self, root: Path):
        self.root = root
        self.data = root / "backend" / "data"
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
            CREATE TABLE IF NOT EXISTS ocr_results (
              id TEXT PRIMARY KEY, page_id TEXT NOT NULL REFERENCES pages(id),
              version INTEGER NOT NULL, settings TEXT NOT NULL, result TEXT NOT NULL,
              created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS ocr_results_page ON ocr_results(page_id,created_at);
            CREATE TABLE IF NOT EXISTS ocr_jobs (
              id TEXT PRIMARY KEY, book_id TEXT NOT NULL REFERENCES books(id),
              status TEXT NOT NULL, settings TEXT NOT NULL, error TEXT,
              created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS ocr_job_pages (
              job_id TEXT NOT NULL REFERENCES ocr_jobs(id), page_id TEXT NOT NULL REFERENCES pages(id),
              status TEXT NOT NULL DEFAULT 'pending', error TEXT,
              PRIMARY KEY(job_id,page_id));
            CREATE TABLE IF NOT EXISTS book_layouts (
              book_id TEXT PRIMARY KEY REFERENCES books(id), profile TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS ui_sessions (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reference_allocations (
              page_id TEXT PRIMARY KEY REFERENCES pages(id), allocation TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS book_text_sources (
              book_id TEXT NOT NULL REFERENCES books(id), language TEXT NOT NULL,
              filename TEXT NOT NULL, text TEXT NOT NULL,
              PRIMARY KEY(book_id,language));
            CREATE TABLE IF NOT EXISTS page_links (
              book_id TEXT NOT NULL REFERENCES books(id),
              page_a TEXT NOT NULL REFERENCES pages(id),
              page_b TEXT NOT NULL REFERENCES pages(id),
              PRIMARY KEY(book_id,page_a,page_b), CHECK(page_a < page_b));
            CREATE INDEX IF NOT EXISTS page_links_b ON page_links(book_id,page_b);
            CREATE TABLE IF NOT EXISTS new_data_books (
              book_id TEXT PRIMARY KEY REFERENCES books(id), fingerprint TEXT NOT NULL,
              revision TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS new_data_pages (
              page_id TEXT PRIMARY KEY REFERENCES pages(id), image_path TEXT NOT NULL,
              fingerprint TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS new_data_rows (
              page_id TEXT NOT NULL REFERENCES pages(id), patch_id TEXT NOT NULL,
              row_id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(page_id,patch_id));
            CREATE TABLE IF NOT EXISTS alignment_versions (
              book_id TEXT PRIMARY KEY REFERENCES books(id) ON DELETE CASCADE, version INTEGER NOT NULL DEFAULT 0);
            CREATE TRIGGER IF NOT EXISTS alignment_insert_version AFTER INSERT ON alignments BEGIN
              INSERT INTO alignment_versions VALUES (NEW.book_id,1) ON CONFLICT(book_id) DO UPDATE SET version=version+1;
            END;
            CREATE TRIGGER IF NOT EXISTS alignment_update_version AFTER UPDATE ON alignments BEGIN
              INSERT INTO alignment_versions VALUES (NEW.book_id,1) ON CONFLICT(book_id) DO UPDATE SET version=version+1;
            END;
            CREATE TRIGGER IF NOT EXISTS alignment_delete_version AFTER DELETE ON alignments BEGIN
              INSERT INTO alignment_versions VALUES (OLD.book_id,1) ON CONFLICT(book_id) DO UPDATE SET version=version+1;
            END;
            """)
            if 'reading_direction' not in {row['name'] for row in db.execute('PRAGMA table_info(pages)')}:
                db.execute('ALTER TABLE pages ADD COLUMN reading_direction INTEGER NOT NULL DEFAULT 2')
            columns={row['name'] for row in db.execute('PRAGMA table_info(pages)')}
            if 'reading_direction_override' not in columns:
                db.execute('ALTER TABLE pages ADD COLUMN reading_direction_override INTEGER DEFAULT NULL')
            for column,default in (('source_text',"''"),('target_text',"''"),('vi_boxes',"'[]'"),('export_boxes',"'null'")):
                if column not in columns:
                    db.execute(f'ALTER TABLE pages ADD COLUMN {column} TEXT NOT NULL DEFAULT {default}')
            if 'ocr_skip' not in columns:
                db.execute('ALTER TABLE pages ADD COLUMN ocr_skip INTEGER NOT NULL DEFAULT 0')
            if 'target_origin' not in columns:
                db.execute("ALTER TABLE pages ADD COLUMN target_origin TEXT NOT NULL DEFAULT ''")
            if 'edited_fields' not in columns:
                db.execute("ALTER TABLE pages ADD COLUMN edited_fields TEXT NOT NULL DEFAULT '[]'")
            for column in ('source_regions','target_regions'):
                if column not in columns:
                    db.execute(f'ALTER TABLE pages ADD COLUMN {column} TEXT DEFAULT NULL')
            if 'ocr_languages' not in columns:
                db.execute("ALTER TABLE pages ADD COLUMN ocr_languages TEXT DEFAULT NULL")
            if 'ocr_granularity' not in columns:
                db.execute('ALTER TABLE pages ADD COLUMN ocr_granularity TEXT DEFAULT NULL')
                # Pages confirmed before this field existed keep their completed state.
                for old in db.execute("SELECT id,boxes FROM pages WHERE status='done'").fetchall():
                    old_boxes = json.loads(old['boxes'])
                    if old_boxes:
                        granularity = 'character' if all(len(box['transcription'].strip()) == 1 for box in old_boxes) else 'phrase'
                        db.execute('UPDATE pages SET ocr_granularity=? WHERE id=?', (granularity, old['id']))
            db.execute("UPDATE pages SET reading_direction_override=NULL,reading_direction=2 WHERE category='vi' AND (reading_direction_override IS NOT NULL OR reading_direction!=2)")
            if 'source_regions' not in columns:
                db.execute("UPDATE pages SET category='both' WHERE category='misc' AND NOT EXISTS (SELECT 1 FROM pages other WHERE other.book_id=pages.book_id AND other.number=pages.number AND other.category='both')")
            # Remove only the legacy seeded records; real books and edits stay intact.
            db.execute('DELETE FROM alignments WHERE book_id IN (SELECT id FROM books WHERE demo=1)')
            db.execute('DELETE FROM pages WHERE book_id IN (SELECT id FROM books WHERE demo=1)')
            db.execute('DELETE FROM books WHERE demo=1')
        self.repair_box_texts()
        # Repair interrupted text-file writes from the committed SQLite checkpoint.
        for book in self.books():
            for page in self.pages(book['id']):
                self.restore_ocr_geometry(page)
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

    def books(self):
        with self.db() as db:
            books = [dict(row) for row in db.execute("""
            SELECT b.id,b.name,b.filename,b.created_at,COUNT(p.id) AS pages,
            COALESCE(n.revision,'') AS input_revision,
            COALESCE(v.version,0) AS alignment_version,
            COALESCE(SUM(p.version),0) AS content_version,
            (SELECT id FROM pages WHERE book_id=b.id ORDER BY number,category LIMIT 1) AS first_page_id,
            SUM(CASE WHEN p.status='done' AND p.ocr_skip=0 AND p.category!='blank' THEN 1 ELSE 0 END) AS done,
            SUM(CASE WHEN p.ocr_skip=1 OR p.category='blank' THEN 1 ELSE 0 END) AS excluded
            FROM books b LEFT JOIN pages p ON b.id=p.book_id
            LEFT JOIN new_data_books n ON n.book_id=b.id
            LEFT JOIN alignment_versions v ON v.book_id=b.id
            WHERE b.demo=0 AND b.source IS NOT NULL GROUP BY b.id ORDER BY b.name COLLATE NOCASE
            """)]
        return [book for book in books if (self.data / 'raw_data' / book['filename']).is_file()]

    def book(self, book_id):
        with self.db() as db:
            row = db.execute("""SELECT b.*,COALESCE(n.revision,'') AS input_revision,COALESCE(v.version,0) AS alignment_version FROM books b
                LEFT JOIN new_data_books n ON n.book_id=b.id LEFT JOIN alignment_versions v ON v.book_id=b.id WHERE b.id=?""", (book_id,)).fetchone()
            return dict(row) if row else None

    def pair_stats(self, book_id=None):
        with self.lock:
            books = self.books()
            if book_id is not None:
                books = [book for book in books if book['id'] == book_id]
            rows = [(book['id'], row) for book in books for row in self.statistics_rows(book)]
            return self.count_pairs(rows)

    def statistics_rows(self, book):
        """Cache only derived counters; every saved page/alignment revision invalidates them."""
        with self.db() as db:
            pages = tuple(tuple(row) for row in db.execute('''SELECT id,version,category,status,ocr_skip,
                reading_direction,reading_direction_override,ocr_granularity FROM pages WHERE book_id=? ORDER BY id''', (book['id'],)))
            layout = db.execute('SELECT profile FROM book_layouts WHERE book_id=?', (book['id'],)).fetchone()
        key = (book['input_revision'], book['alignment_version'], pages, layout['profile'] if layout else None)
        if not hasattr(self, '_statistics_cache'):
            self._statistics_cache = {}
        cached = self._statistics_cache.get(book['id'])
        if cached and cached[0] == key:
            return cached[1]
        fields = ('id','sentence_id','source','target','source_page_id','source_line_index',
                  'reviewed','countable','duplicate_of','review_state')
        rows = [{field: row[field] for field in fields if field in row}
                for row in self.describe_alignments(book['id'])]
        self._statistics_cache[book['id']] = (key, rows)
        return rows

    def alignment_rows(self, book_id):
        with self.db() as db:
            saved = db.execute('SELECT rows FROM alignments WHERE book_id=?', (book_id,)).fetchone()
        return json.loads(saved['rows']) if saved else []

    def describe_alignments(self, book_id, rows=None):
        with self.lock:
            return self._describe_alignments(book_id, rows)

    def _describe_alignments(self, book_id, rows=None):
        rows = self.alignment_rows(book_id) if rows is None else rows
        if not rows:
            return []
        pages = self.pages(book_id, include_export_boxes=False)
        rows = attach_refs(rows, pages)
        base = self.source_box_colors(book_id, rows, pages=pages)
        eligible_ids = {page['id'] for page in pages if not page['ocr_skip'] and page['category'] not in ('blank','misc') and 'han' in page['ocr_languages']}
        eligible_numbers = {page['number'] for page in pages if page['id'] in eligible_ids}
        with self.db() as db:
            active_ids = {item['row_id'] for item in db.execute('SELECT r.row_id FROM new_data_rows r JOIN pages p ON p.id=r.page_id WHERE p.book_id=?', (book_id,))}
        output = []
        version = self.book(book_id)['alignment_version']
        for row in rows:
            colors = {}
            for side in ('source', 'target'):
                values = base.get(row['id'], {}).get(side, [])
                colors[side] = [kind or 'match' for kind in values] if len(values) == len(row[side]) else ['match'] * len(row[side])
                for mark in row.get('marks', []):
                    colors[side][mark[f'{side}_start']:mark[f'{side}_end']] = [mark['kind']] * (mark[f'{side}_end']-mark[f'{side}_start'])
            complete = all(export_text(row[side], side)[0] for side in ('source', 'target'))
            eligible = (row['source_page_id'] in eligible_ids if row.get('source_page_id') else int(row['sentence_id'].rsplit('.',2)[1]) in eligible_numbers)
            errors = '□' in row['source'] or any(kind in ('mismatch', 'unknown') for values in colors.values() for kind in values)
            counted = bool(eligible and complete and row.get('reviewed'))
            output.append({**row, 'alignment_version': version, 'review_colors': colors, 'has_errors': errors, 'countable': counted,
                           'review_state': 'excluded' if not eligible else 'incomplete' if not complete else 'accepted' if row.get('reviewed') else 'needs_review' if errors else 'clean'})
        groups = {}
        for row in output:
            if all(comparison_key(row[side]).strip() for side in ('source', 'target')):
                groups.setdefault(self.pair_identity(book_id, row), []).append(row)
        for group in groups.values():
            chosen = next((row for row in group if row['id'] in active_ids), None) or next((row for row in group if row['countable']), group[0])
            for row in group:
                if row is not chosen:
                    row.update(countable=False, duplicate_of=chosen['id'], review_state='duplicate')
        return output

    @staticmethod
    def pair_identity(book_id, row):
        page = row['sentence_id'].rsplit('.', 2)[-2]
        position = row.get('source_line_index')
        identity = ('line', position) if position is not None else ('phrase', row['id']) if row.get('source_page_id') else (
            'text', comparison_key(row['source']).replace(' ', ''), comparison_key(row['target']))
        return book_id, page, identity

    @staticmethod
    def count_pairs(rows):
        unique = {}
        incomplete = duplicates = excluded = 0
        for book_id, row in rows:
            if row.get('review_state') == 'excluded':
                excluded += 1
                continue
            source, target = export_text(row['source'], 'source')[0], export_text(row['target'], 'target')[0]
            if not source or not target:
                incomplete += 1
                continue
            key = Store.pair_identity(book_id, row)
            duplicates += int(key in unique)
            previous = unique.setdefault(key, {'counted': False, 'reviewed': False})
            previous['counted'] |= bool(row['countable'])
            previous['reviewed'] |= bool(row.get('reviewed') and not row.get('duplicate_of'))
        count = sum(row['counted'] for row in unique.values())
        return {'target': PAIR_TARGET, 'pairs': count, 'saved_pairs': len(unique),
                'reviewed_pairs': sum(row['reviewed'] for row in unique.values()),
                'pending_error_pairs': sum(not row['counted'] for row in unique.values()),
                'remaining': max(0, PAIR_TARGET-count), 'duplicate_pairs': duplicates, 'incomplete_pairs': incomplete, 'excluded_pairs': excluded}

    @staticmethod
    def page_dict(row, inherited_reading_direction=None, linked_page_ids=None, include_export_boxes=True):
        page = dict(row)
        page['ocr_languages']=(['han'] if page['category']=='ch' else ['vi'] if page['category']=='vi' else ['han','vi']) if page['category'] in ('ch','vi','both') else (json.loads(page['ocr_languages']) if page['ocr_languages'] is not None else ['han','vi'])
        if page['ocr_languages'] == ['vi'] and page['category'] not in ('blank','misc'):
            page['reading_direction'] = 2
            page['reading_direction_override'] = None
        elif page.get('reading_direction_override') in (1, 2):
            page['reading_direction'] = page['reading_direction_override']
        elif inherited_reading_direction in (1, 2):
            page['reading_direction'] = inherited_reading_direction
        page["boxes"] = ordered_boxes(json.loads(page["boxes"]), page['category'], page['reading_direction'],(page['width'],page['height']))
        page['vi_boxes']=ordered_boxes(json.loads(page['vi_boxes']),'vi',2,(page['width'],page['height']))
        export_boxes=json.loads(page['export_boxes']) if include_export_boxes else []
        if export_boxes is None:
            export_boxes=[]
            for index,box in enumerate(nom_export_boxes(page['boxes'],page['reading_direction'],(page['width'],page['height']))):
                source_ids=box.pop('source_ids',[])
                source_boxes=[source for source in page['boxes'] if source['id'] in source_ids]
                groups={source.get('export_group') for source in source_boxes}
                group=next(iter(groups)) if len(groups)==1 else None
                if not group:
                    group=f"{page['id']}-export-{index+1}"
                alignment_ids={source.get('alignment_id') for source in source_boxes}
                export_boxes.append({
                    **box,
                    'id':group,
                    'export_group':group,
                    'export_order':index+1,
                    'export_character_order':0,
                    **({'alignment_id':next(iter(alignment_ids))} if len(alignment_ids)==1 and None not in alignment_ids else {}),
                })
        else:
            export_boxes.sort(key=lambda box: box.get('export_order') or 0)
        page['export_boxes']=export_boxes
        page['ocr_skip']=bool(page['ocr_skip'])
        page['edited_fields']=json.loads(page['edited_fields'])
        page['review_state'] = ('skipped' if page['ocr_skip'] or page['category'] == 'blank' else
                                'done' if page['status'] == 'done' else 'in_progress' if page['edited_fields'] else 'unchecked')
        for key in ('source_regions','target_regions'):
            page[key]=json.loads(page[key]) if page[key] is not None else None
        page['linked_page_ids']=linked_page_ids or []
        page["image_url"] = f"/api/pages/{page['id']}/image" + (f"?v={page['input_revision']}" if page.get('input_revision') else '')
        return page

    @staticmethod
    def links_for_book(db, book_id):
        links={}
        for row in db.execute('SELECT page_a,page_b FROM page_links WHERE book_id=?',(book_id,)):
            links.setdefault(row['page_a'],[]).append(row['page_b'])
            links.setdefault(row['page_b'],[]).append(row['page_a'])
        return links

    def pages(self, book_id, include_export_boxes=True):
        with self.db() as db:
            layout=db.execute('SELECT profile FROM book_layouts WHERE book_id=?',(book_id,)).fetchone()
            direction=json.loads(layout['profile']).get('reading_direction',2) if layout else 2
            links=self.links_for_book(db,book_id)
            pages = [self.page_dict(row,direction,links.get(row['id']),include_export_boxes) for row in db.execute("""SELECT p.*,COALESCE(n.revision,'') AS input_revision FROM pages p
                LEFT JOIN new_data_books n ON n.book_id=p.book_id WHERE p.book_id=? ORDER BY p.number,p.category""", (book_id,))]
            saved = db.execute('SELECT rows FROM alignments WHERE book_id=?', (book_id,)).fetchone()
        return self.review_states(pages, json.loads(saved['rows']) if saved else [])

    @staticmethod
    def review_states(pages, rows):
        checked = {row.get(key) for row in rows if row.get('reviewed') for key in ('source_page_id', 'target_page_id')}
        rows_by_page = {}
        for row in rows:
            rows_by_page.setdefault(row.get('source_page_id'), []).append(row)
        for page in pages:
            if page['review_state'] == 'unchecked' and page['id'] in checked:
                page['review_state'] = 'in_progress'
            page['review_rows'] = attach_refs(rows_by_page.get(page['id'], []), [page])
        return pages

    def source_box_colors(self, book_id, rows, pages=None):
        """Map per-box review colors onto both sides of saved alignment text."""
        book = self.book(book_id)
        if not book:
            return {}
        output = {}
        rows_by_prefix = {}
        for row in rows:
            rows_by_prefix.setdefault(row['sentence_id'].rsplit('.', 1)[0] + '.', []).append(row)
        for page in (self.pages(book_id, include_export_boxes=False) if pages is None else pages):
            if 'han' not in page['ocr_languages'] or not page['boxes']:
                continue
            prefix = f"{book['name']}.{page['number']:03d}."
            page_rows = [row for row in rows_by_prefix.get(prefix, [])
                         if not row.get('source_page_id') or row['source_page_id'] == page['id']]
            if not page_rows:
                continue
            from .auto_alignment import source_groups
            groups = None
            boxes_by_alignment = {}
            for box in page['boxes']:
                if box.get('alignment_id'):
                    boxes_by_alignment.setdefault(box['alignment_id'], []).append(box)
            def glyph_reviews(boxes):
                values = []
                for box in boxes:
                    for index, char in enumerate(box['transcription']):
                        if source_glyph(char):
                            kind = box.get('review_kind') or 'match'
                            for mark in box.get('review_marks', []):
                                if mark['start'] <= index < mark['end']:
                                    kind = mark['kind']
                            values.append(kind)
                return values
            stream = glyph_reviews(page['boxes'])
            boxes_by_id = {box['id']: box for box in page['boxes']}
            text = None
            cursor = 0
            for row in sorted(page_rows, key=lambda row: int(row['sentence_id'].rsplit('.', 1)[1])):
                assigned = boxes_by_alignment.get(row['id'], [])
                line = row.get('source_line_index')
                if not assigned and isinstance(line, int) and line >= 0:
                    if groups is None:
                        groups = source_groups(page)
                    if line < len(groups) and ''.join(box['transcription'] for box in groups[line]).strip() == row['source'].strip():
                        assigned = groups[line]
                size = sum(source_glyph(char) for char in row['source'])
                refs = row.get('source_refs', [])
                if refs and ref_text(refs, page['boxes']) == row['source']:
                    glyphs = []
                    for ref in refs:
                        box = boxes_by_id[ref['box_id']]
                        for index in range(ref['start'], ref['end']):
                            if source_glyph(box['transcription'][index]):
                                kind = box.get('review_kind') or 'match'
                                for mark in box.get('review_marks', []):
                                    if mark['start'] <= index < mark['end']:
                                        kind = mark['kind']
                                glyphs.append(kind)
                elif assigned:
                    glyphs = glyph_reviews(assigned)
                elif row.get('source_page_id'):
                    if text is None:
                        text = ''.join(char for box in page['boxes'] for char in box['transcription'] if source_glyph(char))
                    wanted = ''.join(char for char in row['source'] if source_glyph(char))
                    start = text.find(wanted) if wanted else -1
                    glyphs = stream[start:start+size] if start >= 0 and text.find(wanted, start+1) < 0 else ['unknown'] * size
                else:
                    glyphs = stream[cursor:cursor+size]
                cursor += size
                index = 0
                colors = []
                for char in row['source']:
                    if source_glyph(char):
                        colors.append(glyphs[index] if index < len(glyphs) else None)
                        index += 1
                    else:
                        colors.append(None)
                output.setdefault(row['id'], {})['source'] = colors
            for row in page_rows:
                glyph_colors = [color or 'match' for char, color in zip(row['source'], output[row['id']]['source'])
                                if source_glyph(char)]
                word_index = 0
                colors = ['match'] * len(row['target'])
                for match in re.finditer(r'\S+', row['target']):
                    if not any(
                        unicodedata.category(char).startswith(('L', 'N'))
                        for char in match.group()
                    ):
                        continue
                    if word_index < len(glyph_colors):
                        kind = glyph_colors[word_index]
                        colors[match.start():match.end()] = [kind] * (match.end() - match.start())
                    word_index += 1
                output.setdefault(row['id'], {})['target'] = colors
        return output

    def page(self, page_id):
        with self.db() as db:
            row = db.execute("""SELECT p.*,COALESCE(n.revision,'') AS input_revision FROM pages p
                LEFT JOIN new_data_books n ON n.book_id=p.book_id WHERE p.id=?""", (page_id,)).fetchone()
            if not row:
                return None
            layout=db.execute('SELECT profile FROM book_layouts WHERE book_id=?',(row['book_id'],)).fetchone()
            direction=json.loads(layout['profile']).get('reading_direction',2) if layout else 2
            links=self.links_for_book(db,row['book_id'])
            saved = db.execute('SELECT rows FROM alignments WHERE book_id=?', (row['book_id'],)).fetchone()
            return self.review_states([self.page_dict(row,direction,links.get(page_id))], json.loads(saved['rows']) if saved else [])[0]

    def book_dir(self, book_id):
        return self.local / "books" / book_id

    def latest_ocr(self, page_id):
        with self.db() as db:
            imported = db.execute('''SELECT p.*,n.revision FROM pages p JOIN new_data_books n ON n.book_id=p.book_id
                WHERE p.id=? AND p.target_origin='new_data' ''', (page_id,)).fetchone()
            if imported:
                completed = ['han'] + (['vi'] if imported['target_text'].strip() else [])
                return {'page_id': page_id, 'version': imported['version'],
                        'result_id': f"new-{imported['revision']}-{page_id}", 'cached': True,
                        'boxes': json.loads(imported['boxes']), 'vi_boxes': [],
                        'text_lines': imported['source_text'].splitlines(),
                        'vi_text_lines': imported['target_text'].splitlines(),
                        'reading_direction': imported['reading_direction'], 'settings': {}, 'warnings': [],
                        'target_origin': 'new_data', 'completed_languages': completed, 'requested_languages': completed}
            row = db.execute('SELECT result FROM ocr_results WHERE page_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1', (page_id,)).fetchone()
        return json.loads(row['result']) if row else None

    def restore_ocr_geometry(self,page):
        """Repair older text-only projections, never a deliberate edit or confirmation."""
        if page['status']=='done' or page['ocr_skip']:
            return
        result=self.latest_ocr(page['id'])
        if not result:
            return
        changes={}
        for key,text_key,lines_key in (('boxes','source_text','text_lines'),('vi_boxes','target_text','vi_text_lines')):
            if not page[key] and not {key,text_key}.intersection(page['edited_fields']) and result.get(key) and page[text_key].strip() and page[text_key]=='\n'.join(result.get(lines_key,[])):
                changes[key]=json.dumps(result[key],ensure_ascii=False)
        if changes:
            with self.db() as db:
                db.execute('UPDATE pages SET '+','.join(key+'=?' for key in changes)+',version=version+1 WHERE id=?',(*changes.values(),page['id']))

    def save_ocr(self, result, settings, created_at):
        with self.db() as db:
            db.execute('''INSERT INTO ocr_results VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                settings=excluded.settings,result=excluded.result,created_at=excluded.created_at''', (
                result['result_id'], result['page_id'], result['version'],
                json.dumps(settings, sort_keys=True), json.dumps(result, ensure_ascii=False), created_at,
            ))
        page = self.page(result['page_id'])
        if page:
            self.auto_align_ocr(page['book_id'])

    def auto_align_ocr(self, book_id):
        """Save pairs as OCR arrives, independently of optional human confirmation."""
        from .auto_alignment import boxes_for_rows, index_pages, page_rows

        with self.lock:
            book = self.book(book_id)
            pages = self.pages(book_id)
            for page in pages:
                result = self.latest_ocr(page['id'])
                if result and page['status'] != 'done' and page['target_origin'] != 'new_data':
                    for box_key, text_key, result_key in (
                        ('boxes', 'source_text', 'text_lines'), ('vi_boxes', 'target_text', 'vi_text_lines'),
                    ):
                        if not {box_key, text_key}.intersection(page['edited_fields']):
                            if result.get(box_key):
                                page[box_key] = result[box_key]
                            if result.get(result_key):
                                page[text_key] = '\n'.join(result[result_key])
                if not page['ocr_granularity']:
                    page['ocr_granularity'] = ('phrase' if any(len(box['transcription'].strip()) > 1
                        for box in page['boxes']) else 'character')
            indexes = index_pages(pages)
            with self.db() as db:
                saved = db.execute('SELECT rows FROM alignments WHERE book_id=?', (book_id,)).fetchone()
                reference = db.execute("SELECT text FROM book_text_sources WHERE book_id=? AND language='vi'", (book_id,)).fetchone()
            rows = json.loads(saved['rows']) if saved else []
            reference = reference['text'] if reference else ''
            sources = [page for page in pages if not page['ocr_skip'] and page['category'] not in ('blank', 'misc')
                       and 'han' in page['ocr_languages'] and page['target_origin'] != 'new_data'
                       and (page['source_text'].strip() or page['boxes'])]
            if reference and not (re.search(r'^\s*\*+\s*Page\s+\d+\s*\*+\s*$', reference, re.I | re.M)
                                  or '\f' in reference or len(sources) == 1):
                reference = ''
            changed = False
            for page in sources:
                prefix = f"{book['name']}.{page['number']:03d}."
                existing = [row for row in rows if row['sentence_id'].startswith(prefix)]
                fresh = page_rows(page, pages, book['name'], reference, indexes)
                if not existing:
                    rows.extend(fresh)
                    existing = fresh
                    changed |= bool(fresh)
                else:
                    # A second language may finish after the first checkpoint.
                    for row in existing:
                        index = row.get('source_line_index')
                        if (not row['target'].strip() and not row.get('reviewed') and not row.get('marks')
                                and isinstance(index, int) and index < len(fresh)
                                and row['source'] == fresh[index]['source'] and fresh[index]['target'].strip()):
                            row.update({key: fresh[index].get(key) for key in
                                        ('target', 'target_page_id', 'target_line_index')})
                            changed = True
                if not page['export_boxes']:
                    generated = boxes_for_rows(page, existing)
                    if generated:
                        with self.db() as db:
                            db.execute('UPDATE pages SET export_boxes=? WHERE id=?',
                                       (json.dumps(generated, ensure_ascii=False), page['id']))
                        changed = True
            if changed:
                rows.sort(key=lambda row: tuple(map(int, row['sentence_id'].rsplit('.', 2)[1:])))
                with self.db() as db:
                    db.execute('INSERT INTO alignments VALUES (?,?) ON CONFLICT(book_id) DO UPDATE SET rows=excluded.rows',
                               (book_id, json.dumps(rows, ensure_ascii=False)))
                self.sync_labels(book_id)
            return changed

    def book_layout(self,book_id):
        with self.db() as db:
            row=db.execute('SELECT profile FROM book_layouts WHERE book_id=?',(book_id,)).fetchone()
        return json.loads(row['profile']) if row else {'source_regions':[],'target_regions':[]}

    def session(self,key):
        with self.db() as db:
            row=db.execute('SELECT value FROM ui_sessions WHERE key=?',(key,)).fetchone()
        return json.loads(row['value']) if row else {}

    def save_session(self,key,value):
        with self.db() as db:
            db.execute('INSERT INTO ui_sessions VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                       (key,json.dumps(value,ensure_ascii=False)))

    def save_ocr_alignment_changes(self, page, rows, removed, replacements):
        """Keep derived sentence boxes attached to the OCR groups that survived."""
        exports = []
        replaced = set()
        for box in page['export_boxes']:
            row_id = box.get('alignment_id')
            if row_id in removed:
                continue
            if row_id in replacements:
                if row_id in replaced:
                    continue
                replaced.add(row_id)
                source, members = replacements[row_id]
                xs = [point[0] for member in members for point in member['points']]
                ys = [point[1] for member in members for point in member['points']]
                box = {**box, 'transcription': source,
                       'points': [[min(xs),min(ys)],[max(xs),min(ys)],[max(xs),max(ys)],[min(xs),max(ys)]],
                       'export_character_order': 0}
            exports.append(box)
        orders = {}
        for box in exports:
            group = box.get('export_group') or box['id']
            orders.setdefault(group, len(orders) + 1)
            box['export_order'] = orders[group]
        with self.db() as db:
            db.execute('UPDATE alignments SET rows=? WHERE book_id=?',
                       (json.dumps(rows, ensure_ascii=False), page['book_id']))
            changes = {'export_boxes': json.dumps(exports, ensure_ascii=False)}
            if page['target_origin'] == 'new_data':
                local = [row for row in rows if row.get('source_page_id') == page['id']]
                changes.update(source_text='\n'.join(row['source'] for row in local),
                               target_text='\n'.join(row['target'] for row in local))
            db.execute('UPDATE pages SET '+','.join(key+'=?' for key in changes)+',version=version+1 WHERE id=?',
                       (*changes.values(), page['id']))

    def sync_deleted_source_boxes(self, previous, current):
        """A deleted OCR group removes its pair; surviving groups keep their IDs/targets."""
        old_ids = {box['id'] for box in previous['boxes']}
        new_ids = {box['id'] for box in current['boxes']}
        if not new_ids < old_ids:
            return False  # Replacing/rerunning OCR is not a box deletion.
        from .auto_alignment import source_groups, joined
        before = source_groups(previous)
        after = source_groups(current)
        positions = {box['id']: index for index, group in enumerate(after) for box in group}
        surviving = {box['id']: box for box in current['boxes']}
        rows = self.alignment_rows(previous['book_id'])
        removed, replacements = set(), {}
        changed = False
        for row in rows:
            assigned = [box for box in previous['boxes'] if box.get('alignment_id') == row['id']]
            index = row.get('source_line_index')
            if not assigned and row.get('source_page_id') == previous['id'] and isinstance(index, int) and 0 <= index < len(before):
                candidate = before[index]
                if joined(row['source']) == joined(''.join(box['transcription'] for box in candidate)):
                    assigned = candidate
            if not assigned:
                continue  # Manual split/merged pairs need their explicit geometry.
            members = [surviving[box['id']] for box in assigned if box['id'] in surviving]
            if not members:
                removed.add(row['id'])
                changed = True
                continue
            next_index = min(positions[box['id']] for box in members)
            if row.get('source_line_index') != next_index:
                row['source_line_index'] = next_index
                changed = True
            if len(members) != len(assigned):
                row.update(source=''.join(box['transcription'] for box in members), marks=[])
                replacements[row['id']] = (row['source'], members)
                changed = True
        if changed:
            self.save_ocr_alignment_changes(current, [row for row in rows if row['id'] not in removed], removed, replacements)
        return changed

    def reconcile_deleted_source_boxes(self, book_id):
        """Repair deletions saved before OCR and sentence boxes were synchronized."""
        from .auto_alignment import source_groups, joined, page_rows
        book = self.book(book_id)
        with self.db() as db:
            versions = tuple(tuple(row) for row in db.execute('SELECT id,version FROM pages WHERE book_id=? ORDER BY id', (book_id,)))
        key = (book['input_revision'], book['alignment_version'], versions)
        if not hasattr(self, '_deleted_boxes_cache'):
            self._deleted_boxes_cache = {}
        if self._deleted_boxes_cache.get(book_id) == key:
            return False
        rows = self.alignment_rows(book_id)
        by_page = {}
        for row in rows:
            if isinstance(row.get('source_line_index'), int):
                by_page.setdefault(row.get('source_page_id'), []).append(row)
        with self.db() as db:
            candidates = [raw['id'] for raw in db.execute(
                'SELECT id,edited_fields,ocr_granularity,json_array_length(boxes) AS box_count FROM pages WHERE book_id=?', (book_id,))
                if 'boxes' in json.loads(raw['edited_fields']) and by_page.get(raw['id'])
                and (raw['ocr_granularity'] != 'phrase' or len(by_page[raw['id']]) > raw['box_count'])]
        changed = False
        for page_id in candidates:
            page = self.page(page_id)
            local = by_page.get(page['id'], [])
            groups = source_groups(page)
            if len(local) <= len(groups):
                continue
            exports = {box.get('alignment_id'): box for box in page['export_boxes']}
            anchored = {box.get('alignment_id') for box in page['boxes'] if box.get('alignment_id')}
            removed = set()
            # Old preparation could leave a raw OCR row without an export box,
            # even though every current phrase already had its own saved row.
            # Require an exact, unique cover before treating that row as obsolete.
            group_texts = [joined(''.join(b['transcription'] for b in group)) for group in groups]
            group_matches = {row['id']: [i for i, text in enumerate(group_texts)
                                         if text and joined(row['source']) == text] for row in local}
            covered = [indexes[0] for indexes in group_matches.values() if len(indexes) == 1]
            orphans = [row for row in local if not group_matches[row['id']]]
            complete_cover = (sorted(covered) == list(range(len(groups)))
                              and len(covered) + len(orphans) == len(local))
            # Bulk confirmation used to protect even empty rows from deleted OCR
            # noise. Only retire these when the original OCR proves the deletion
            # and every surviving phrase already has its own saved pair.
            if complete_cover:
                result = self.latest_ocr(page['id']) or {}
                live_ids = {box['id'] for box in page['boxes']}
                deleted_boxes = [box for box in result.get('boxes', []) if box['id'] not in live_ids]
                for row in orphans:
                    exported = exports.get(row['id'])
                    if (row.get('page_linked') and not row['target'].strip()
                            and not row.get('marks') and not row.get('source_refs')
                            and not row.get('target_refs') and exported
                            and not any(joined(row['source']) in text for text in group_texts)
                            and any(box['transcription'] == row['source'] == exported['transcription']
                                    and matches_export_frame(box['points'], exported['points']) for box in deleted_boxes)):
                        removed.add(row['id'])
            obsolete_defaults = (
                page['ocr_granularity'] == 'phrase' and bool(orphans)
                and sorted(covered) == list(range(len(groups)))
                and len(covered) + len(orphans) == len(local)
                and all(not row.get('reviewed') and not row.get('marks')
                        and row['id'] not in exports and row['id'] not in anchored for row in orphans)
            )
            fresh = page_rows(page, self.pages(book_id), book['name']) if obsolete_defaults else []
            # Reflow only untouched default assignments; manual target ordering survives.
            reflow = bool(fresh) and all(
                not row.get('reviewed') and not row.get('marks') and (
                    (not row['target'] and row.get('target_line_index') is None)
                    or (isinstance(row.get('source_line_index'), int)
                        and row['source_line_index'] < len(fresh)
                        and all(row.get(key) == fresh[row['source_line_index']].get(key)
                                for key in ('target', 'target_page_id', 'target_line_index')))
                ) for row in local)
            if obsolete_defaults:
                removed.update(row['id'] for row in orphans)
            for row in local:
                box = exports.get(row['id'])
                if not box or row['id'] in anchored:
                    continue
                if not row['source'].strip() and not row['target'].strip() and row['source_line_index'] >= len(groups):
                    removed.add(row['id'])
                    continue
                if row.get('reviewed') or row.get('source_refs'):
                    continue
                if page['target_origin'] == 'new_data':
                    removed.add(row['id'])
                    continue
                xs, ys = zip(*box['points'])
                present = any(
                    min(xs)-1 <= sum(point[0] for point in member['points'])/4 <= max(xs)+1 and
                    min(ys)-1 <= sum(point[1] for point in member['points'])/4 <= max(ys)+1
                    for group in groups for member in group)
                if not present and joined(row['source']):
                    # A saved sentence may occupy only half of a larger OCR
                    # column. Its centre can lie outside the sentence rectangle.
                    # Keep it when text and overlapping geometry both survive.
                    area = max(0, max(xs)-min(xs)) * max(0, max(ys)-min(ys))
                    for group, text in zip(groups, group_texts):
                        if joined(row['source']) not in text or not area:
                            continue
                        gx = [point[0] for member in group for point in member['points']]
                        gy = [point[1] for member in group for point in member['points']]
                        overlap = max(0, min(max(xs), max(gx))-max(min(xs), min(gx))) * max(
                            0, min(max(ys), max(gy))-max(min(ys), min(gy)))
                        if overlap / area >= 0.5:
                            present = True
                            break
                if not present and not any(joined(row['source']) and joined(row['source']) == joined(''.join(b['transcription'] for b in group)) for group in groups):
                    removed.add(row['id'])
            if not removed:
                continue
            rows = [row for row in rows if row['id'] not in removed]
            for row in rows:
                if row.get('source_page_id') != page['id'] or row.get('source_line_index') is None:
                    continue
                matches = [index for index, group in enumerate(groups)
                           if joined(row['source']) == joined(''.join(box['transcription'] for box in group))]
                if len(matches) == 1:
                    row['source_line_index'] = matches[0]
                    if reflow:
                        current = fresh[matches[0]]
                        for field in ('target', 'target_page_id', 'target_line_index'):
                            row[field] = current.get(field)
                        row.update(reviewed=False, marks=[])
            self.save_ocr_alignment_changes(page, rows, removed, {})
            changed = True
        with self.db() as db:
            versions = tuple(tuple(row) for row in db.execute('SELECT id,version FROM pages WHERE book_id=? ORDER BY id', (book_id,)))
        self._deleted_boxes_cache[book_id] = (book['input_revision'], self.book(book_id)['alignment_version'], versions)
        return changed

    def apply_ocr_texts(self,result):
        """Fill empty fields after each language, never replace an edit made during OCR."""
        with self.lock:
            page=self.page(result['page_id'])
            if not page or page['status']=='done' or page['ocr_skip'] or page['category']=='blank':
                return
            completed=completed_ocr_languages(result)
            changes={}
            for language,key in (('han','boxes'),('vi','vi_boxes')):
                if language in completed and key not in page['edited_fields'] and page[key]!=result.get(key,[]) and result.get(key):
                    changes[key]=json.dumps(result[key],ensure_ascii=False)
            if 'han' in completed:
                source_boxes = page['boxes'] if 'boxes' in page['edited_fields'] else result.get('boxes', [])
                if source_boxes:
                    changes['source_text']='\n'.join(box_text_lines(
                        source_boxes,page['reading_direction'],'ch',(page['width'],page['height']),
                    ))
                elif 'source_text' not in page['edited_fields']:
                    changes['source_text']='\n'.join(result.get('text_lines',[]))
            if 'vi' in completed:
                target_boxes = page['vi_boxes'] if 'vi_boxes' in page['edited_fields'] else result.get('vi_boxes', [])
                if target_boxes:
                    changes['target_text']='\n'.join(box_text_lines(
                        target_boxes,2,'vi',(page['width'],page['height']),
                    ))
                elif 'target_text' not in page['edited_fields']:
                    changes['target_text']='\n'.join(result.get('vi_text_lines',[]))
                if result.get('target_origin'):
                    changes['target_origin']=result['target_origin']
            changes={key:value for key,value in changes.items() if (not isinstance(value,str) or value.strip()) and value!=(json.dumps(page[key],ensure_ascii=False) if key in ('boxes','vi_boxes') else page[key])}
            if changes:
                if 'boxes' in changes:
                    changes['ocr_granularity'] = None
                with self.db() as db:
                    db.execute('UPDATE pages SET '+','.join(key+'=?' for key in changes)+",status='pending',version=version+1 WHERE id=?",
                               (*changes.values(),page['id']))
                self.sync_alignment_page_text(page,page['source_text'],page['target_text'],
                                              changes.get('source_text',page['source_text']),
                                              changes.get('target_text',page['target_text']))
                self.sync_labels(page['book_id'])

    def repair_box_texts(self):
        """Migrate saved Vietnamese box corrections whose page text stayed at raw OCR."""
        repairs = []
        with self.lock, self.db() as db:
            for row in list(db.execute('SELECT id,book_id,number,width,height,source_text,target_text,vi_boxes,edited_fields FROM pages')):
                edited = json.loads(row['edited_fields'])
                if 'target_text' in edited and 'vi_boxes' not in edited:
                    continue
                boxes = json.loads(row['vi_boxes'])
                if not boxes:
                    continue
                corrected = '\n'.join(box_text_lines(
                    boxes,2,'vi',(row['width'],row['height'])))
                if corrected == row['target_text']:
                    continue
                db.execute('UPDATE pages SET target_text=?,version=version+1 WHERE id=?',
                           (corrected,row['id']))
                repairs.append((dict(row),corrected))
        for page, corrected in repairs:
            self.sync_alignment_page_text(page,page['source_text'],page['target_text'],
                                          page['source_text'],corrected)
        return len(repairs)

    def propagate_placeholder_edits(self, book_id, page_number, old_text, new_text):
        """Keep saved alignment rows in sync when corrected Nôm boxes replace □."""
        if old_text == new_text or '□' not in old_text:
            return
        replacements={}
        for operation,start,end,new_start,new_end in SequenceMatcher(None,old_text,new_text,autojunk=False).get_opcodes():
            if operation != 'replace':
                continue
            old=old_text[start:end]
            new=new_text[new_start:new_end]
            if not old or not all(char=='□' or char.isspace() for char in old) or new.count('□')>=old.count('□'):
                continue
            rank=old_text[:start].count('□')
            replacements[rank]=new.replace('\r','').replace('\n','')
            for next_rank in range(rank+1,rank+old.count('□')):
                replacements[next_rank]=''
        if not replacements:
            return
        book=self.book(book_id)
        prefix=f"{book['name']}.{page_number:03d}."
        with self.db() as db:
            saved=db.execute('SELECT rows FROM alignments WHERE book_id=?',(book_id,)).fetchone()
            if not saved:
                return
            rows=json.loads(saved['rows'])
            indices=[index for index,row in enumerate(rows) if row['sentence_id'].startswith(prefix)]
            if sum(rows[index]['source'].count('□') for index in indices)!=old_text.count('□'):
                return
            rank=0; changed=False
            for index in indices:
                row=rows[index]
                source=[]
                for char in row['source']:
                    if char=='□':
                        source.append(replacements.get(rank,char))
                        changed |= rank in replacements
                        rank+=1
                    else:
                        source.append(char)
                if ''.join(source)!=row['source']:
                    row['source']=''.join(source)
                    row['marks']=[]
            if changed:
                db.execute('UPDATE alignments SET rows=? WHERE book_id=?',(json.dumps(rows,ensure_ascii=False),book_id))

    def sync_alignment_page_text(self, page, old_source, old_target, new_source, new_target):
        """Refresh pairs that still contain the OCR line they were created from."""
        if old_source == new_source and old_target == new_target:
            return False
        book = self.book(page['book_id'])
        prefix = f"{book['name']}.{page['number']:03d}."
        def lines(text):
            return [line.strip() for line in text.split('\n')]
        changes = (
            ('source', 'source_page_id', 'source_line_index', lines(old_source), lines(new_source), old_source != new_source),
            ('target', 'target_page_id', 'target_line_index', lines(old_target), lines(new_target), old_target != new_target),
        )
        # Inserting/removing an OCR line must not replace every subsequent
        # sentence by its new neighbour while retaining the old translation.
        line_maps = {}
        for field, _, _, old_lines, new_lines, _ in changes:
            mapping = {}
            for operation, start, end, new_start, new_end in SequenceMatcher(
                    None, old_lines, new_lines, autojunk=False).get_opcodes():
                if operation == 'equal' or (operation == 'replace' and end-start == new_end-new_start):
                    mapping.update((index, new_start + index-start) for index in range(start, end))
            line_maps[field] = mapping
        imported = page.get('target_origin') == 'new_data'
        previous_boxes = {box.get('alignment_id'): box for box in page.get('boxes', [])} if imported else {}
        current_boxes = {box.get('alignment_id'): box for box in self.page(page['id'])['boxes']} if imported and old_source != new_source else {}
        current_page = None
        if page.get('boxes') is not None and not imported:
            current_page = self.page(page['id'])
        with self.db() as db:
            saved = db.execute('SELECT rows FROM alignments WHERE book_id=?', (page['book_id'],)).fetchone()
            if not saved:
                return False
            rows = json.loads(saved['rows'])
            if current_page:
                rows = attach_refs(rows, [page])
            local_indices = {row['id']: index for index, row in enumerate(
                row for row in rows if row['sentence_id'].startswith(prefix))} if imported else {}
            changed = False
            for row in rows:
                for field, page_key, index_key, old_lines, new_lines, text_changed in changes:
                    if not text_changed:
                        continue
                    explicit_page = row.get(page_key)
                    if explicit_page and explicit_page != page['id']:
                        continue
                    if not explicit_page and not row['sentence_id'].startswith(prefix):
                        continue
                    refs = row.get(field + '_refs', [])
                    if refs and current_page:
                        boxes_key = 'boxes' if field == 'source' else 'vi_boxes'
                        before = page[boxes_key]
                        after = current_page[boxes_key]
                        indexed = {box['id']: box for box in after}
                        offsets = {}
                        for box in before:
                            if box['id'] not in indexed:
                                continue
                            offsets[box['id']] = [(start, end, indexed[box['id']]['transcription'][new_start:new_end])
                                for operation, start, end, new_start, new_end in SequenceMatcher(
                                    None, box['transcription'], indexed[box['id']]['transcription'], autojunk=False).get_opcodes()
                                if operation != 'equal']
                        advanced = advance_refs(refs, offsets)
                        replacement = ref_text(advanced, after) if advanced else None
                        if ref_text(refs, before) == row[field] and replacement is not None:
                            if row[field] != replacement:
                                row[field] = replacement
                                row['marks'] = []
                                changed = True
                            if advanced != refs:
                                row[field + '_refs'] = advanced
                                changed = True
                        continue
                    index = row.get(index_key)
                    if imported:
                        index = local_indices.get(row['id'])
                        if field == 'source':
                            previous_box = previous_boxes.get(row['id'])
                            current_box = current_boxes.get(row['id'])
                            if previous_box and current_box and row['source'] == previous_box['transcription']:
                                row['source'] = current_box['transcription']
                                if previous_box['transcription'] != current_box['transcription']:
                                    row['marks'] = []
                                    changed = True
                                continue
                    if index is None:
                        matching = [i for i, line in enumerate(old_lines) if line == row[field].strip()]
                        if len(matching) != 1:
                            continue
                        index = matching[0]
                    if index >= len(old_lines) or row[field].strip() != old_lines[index]:
                        continue
                    new_index = index if imported else line_maps[field].get(index)
                    if new_index is None:
                        continue  # Deleted/ambiguous lines are handled by box reconciliation.
                    if explicit_page and row.get(index_key) != new_index:
                        row[index_key] = new_index
                        changed = True
                    replacement = new_lines[new_index] if new_index < len(new_lines) else ''
                    if row[field] == replacement:
                        continue
                    row[field] = replacement
                    row['marks'] = []
                    changed = True
            if changed:
                db.execute('UPDATE alignments SET rows=? WHERE book_id=?',
                           (json.dumps(rows, ensure_ascii=False), page['book_id']))
            return changed

    def sync_new_data_edits(self, book_id):
        """Keep phrase OCR, sentence text and export labels on the same saved text."""
        with self.lock, self.db() as db:
            saved = db.execute('SELECT rows FROM alignments WHERE book_id=?', (book_id,)).fetchone()
            if not saved:
                return
            rows = json.loads(saved['rows'])
            book = self.book(book_id)
            if not book['input_revision']:
                return
            for raw in db.execute("SELECT * FROM pages WHERE book_id=? AND target_origin='new_data'", (book_id,)).fetchall():
                prefix = f"{book['name']}.{raw['number']:03d}."
                page_rows = [row for row in rows if row['sentence_id'].startswith(prefix)]
                old_boxes = {box.get('alignment_id'): box for box in json.loads(raw['boxes'])}
                old_exports = {box.get('alignment_id'): box for box in json.loads(raw['export_boxes'])}
                boxes, exports = [], []
                for index, row in enumerate(page_rows):
                    previous = old_boxes.get(row['id']) or old_exports.get(row['id'])
                    if not previous:
                        continue  # A manually split/new row still needs real geometry.
                    box = dict(previous)
                    refs = row.get('source_refs', [])
                    partial = bool(refs and ref_text(refs, [previous]) == row['source'] and
                                   row['source'] != previous['transcription'])
                    if box['transcription'] != row['source'] and not partial:
                        box.update(transcription=row['source'], review_kind='unknown', review_marks=[])
                    if row.get('marks'):
                        box['review_marks'] = [{'start': mark['source_start'], 'end': mark['source_end'], 'kind': mark['kind']}
                                               for mark in row['marks']]
                    box.update(review_order=len(boxes)+1, export_order=len(boxes)+1)
                    boxes.append(box)
                    exported = {**old_exports.get(row['id'], box), 'transcription': box['transcription'] if partial else row['source'],
                                'export_order': len(exports)+1,
                                'review_kind': box.get('review_kind', 'match'), 'review_marks': box.get('review_marks', [])}
                    exports.append(exported)
                changes = {'source_text': '\n'.join(box['transcription'] for box in boxes) if any(row.get('source_refs') for row in page_rows) else '\n'.join(row['source'] for row in page_rows),
                           'target_text': '\n'.join(row['target'] for row in page_rows),
                           'boxes': json.dumps(boxes, ensure_ascii=False),
                           'export_boxes': json.dumps(exports, ensure_ascii=False)}
                if any(changes[key] != raw[key] for key in changes):
                    edited = set(json.loads(raw['edited_fields']))
                    modified = {key for key in ('source_text', 'target_text') if changes[key] != raw[key]}
                    if boxes != json.loads(raw['boxes']):
                        modified.add('boxes')
                    if modified:
                        changes.update(edited_fields=json.dumps(sorted(edited | modified)))
                    db.execute('UPDATE pages SET '+','.join(key+'=?' for key in changes)+',version=version+1 WHERE id=?',
                               (*changes.values(), raw['id']))
                    folder = self.data / 'output_alignment' / book_id
                    for name in (f"{book['name']}_labels.zip",):
                        (folder / name).unlink(missing_ok=True)
                    (self.data / 'output_alignment' / 'tat-ca-ket-qua.zip').unlink(missing_ok=True)

    def sync_alignment_edits(self, book_id, previous, rows):
        """Update only OCR ranges whose identity and old text both match."""
        pages = self.pages(book_id)
        previous = attach_refs(previous, pages)
        old = {row['id']: row for row in previous}
        for page in pages:
            updates = {}
            for side, boxes_key, text_key in (('source', 'boxes', 'source_text'), ('target', 'vi_boxes', 'target_text')):
                edits = []
                for row in rows:
                    original = old.get(row['id'])
                    if not original or original[side] == row[side]:
                        continue
                    if original.get(side + '_page_id') != page['id']:
                        continue
                    if row.get(side + '_page_id') != original.get(side + '_page_id'):
                        continue
                    refs = original.get(side + '_refs', [])
                    # Split/merged/reassigned pairs describe ranges, not an OCR replacement.
                    if row.get(side + '_refs', []) != refs:
                        continue
                    if row.get(side + '_line_index') != original.get(side + '_line_index'):
                        continue
                    edits.append((refs, original[side], row[side]))
                boxes, offsets = replace_ranges(page[boxes_key], edits)
                if not offsets:
                    continue
                updates[boxes_key] = json.dumps(boxes, ensure_ascii=False)
                updates[text_key] = '\n'.join(source_box_text_lines(boxes, page['reading_direction'],
                    (page['width'], page['height']), page['ocr_granularity']) if side == 'source' else
                    box_text_lines(boxes, 2, 'vi', (page['width'], page['height'])))
                for row in rows:
                    if row.get(side + '_page_id') == page['id'] and row.get(side + '_refs'):
                        row[side + '_refs'] = advance_refs(row[side + '_refs'], offsets)
            if updates:
                updates['edited_fields'] = json.dumps(sorted(set(page['edited_fields']) | set(updates)))
                with self.db() as db:
                    db.execute('UPDATE pages SET '+','.join(key+'=?' for key in updates)+',version=version+1 WHERE id=?',
                               (*updates.values(), page['id']))
        with self.db() as db:
            db.execute('UPDATE alignments SET rows=? WHERE book_id=?', (json.dumps(rows, ensure_ascii=False), book_id))

    def reconcile_alignment_ocr(self, book_id):
        """Repair older pairs left at the original OCR after a saved box correction."""
        book = self.book(book_id)
        with self.db() as db:
            page_versions = tuple(tuple(row) for row in db.execute(
                'SELECT id,version FROM pages WHERE book_id=? ORDER BY id', (book_id,)))
            key = (book['input_revision'], book['alignment_version'], page_versions)
            if not hasattr(self, '_reconciliation_cache'):
                self._reconciliation_cache = {}
            if self._reconciliation_cache.get(book_id) == key:
                return False
            saved = db.execute('SELECT rows FROM alignments WHERE book_id=?', (book_id,)).fetchone()
            if not saved:
                return False
            rows = json.loads(saved['rows'])
            prefix = f"{book['name']}."
            numbers = {int(match.group(1)) for row in rows
                       if (match := re.fullmatch(re.escape(prefix) + r'(\d{3,})\.[1-9]\d*', row['sentence_id']))}
            ids = {page_id for row in rows for page_id in
                   (row.get('source_page_id'), row.get('target_page_id')) if page_id}
            pages = [dict(row) for row in db.execute(
                '''SELECT p.id,p.book_id,p.number,p.source_text,p.target_text,p.edited_fields,
                   (SELECT r.result FROM ocr_results r WHERE r.page_id=p.id
                    ORDER BY r.created_at DESC,r.rowid DESC LIMIT 1) AS ocr_result
                   FROM pages p WHERE p.book_id=?''',
                (book_id,))]
        changed = False
        for page in pages:
            if page['number'] not in numbers and page['id'] not in ids:
                continue
            edited = json.loads(page['edited_fields'])
            if not set(edited) & {'boxes', 'vi_boxes', 'source_text', 'target_text'}:
                continue
            if not page['ocr_result']:
                continue
            result = json.loads(page['ocr_result'])
            original_source = '\n'.join(result.get('text_lines', []))
            original_target = '\n'.join(result.get('vi_text_lines', []))
            changed |= self.sync_alignment_page_text(
                page, original_source or page['source_text'], original_target or page['target_text'],
                page['source_text'], page['target_text'])
        self._reconciliation_cache[book_id] = (book['input_revision'], self.book(book_id)['alignment_version'], page_versions)
        return changed

    def sync_results(self,book_id,event=None, *, checkpoint=True):
        """Write recoverable working snapshots and the current confirmed output."""
        with self.lock:
            if checkpoint:
                self.sync_new_data_edits(book_id)
            book=self.book(book_id)
            if not book:
                return
            folder=self.data/'output_alignment'/book_id
            folder.mkdir(parents=True,exist_ok=True)
            pages=self.pages(book_id)
            with self.db() as db:
                alignment=db.execute('SELECT rows FROM alignments WHERE book_id=?',(book_id,)).fetchone()
                job=db.execute('SELECT id,status,error,created_at FROM ocr_jobs WHERE book_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1',(book_id,)).fetchone()
                progress=[dict(row) for row in db.execute('SELECT page_id,status,error FROM ocr_job_pages WHERE job_id=?',(job['id'],))] if job else []
                languages={row['page_id']:completed_ocr_languages(json.loads(row['result'])) for row in db.execute(
                    'SELECT r.page_id,r.result FROM ocr_results r JOIN pages p ON p.id=r.page_id WHERE p.book_id=? ORDER BY r.created_at,r.rowid',(book_id,))}
                languages.update({row['id']: ['han'] + (['vi'] if row['target_text'].strip() else []) for row in db.execute(
                    "SELECT id,target_text FROM pages WHERE book_id=? AND target_origin='new_data'", (book_id,))})
            rows=json.loads(alignment['rows']) if alignment else []
            described = self.describe_alignments(book_id, rows)
            statistics = self.count_pairs([(book_id, row) for row in described])
            now=datetime.now(timezone.utc).isoformat()
            summary={'book_id':book_id,'book':book['name'],'updated_at':now,'pages':len(pages),
                     'excluded_pages':sum(p['ocr_skip'] or p['category']=='blank' for p in pages),
                     'reviewed_pages':sum(p['review_state']=='done' for p in pages),
                     'ocr_pages':sum(bool(languages.get(p['id'])) for p in pages),
                     **{key: statistics[key] for key in ('pairs','saved_pairs','reviewed_pairs','pending_error_pairs','duplicate_pairs','incomplete_pairs','excluded_pairs')},
                     'similarity_review':score_boxes(pages),
                     'job':dict(job) if job else None,'job_pages':progress}
            def write_json(path,value):
                tmp=path.with_suffix(path.suffix+'.tmp')
                tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
                replace_file(tmp,path)
            write_json(folder/'summary.json',summary)
            write_json(folder/'pages.json',[{key:p[key] for key in ('id','number','category','ocr_skip','status','ocr_granularity','source_text','target_text','target_origin','version','linked_page_ids')} |
                                           {'completed_languages':languages.get(p['id'],[])} for p in pages])
            write_json(folder/'alignments.json',described)
            csv_path=folder/'pairs.csv'; tmp=csv_path.with_suffix('.csv.tmp')
            with tmp.open('w',encoding='utf-8-sig',newline='') as stream:
                writer=csv.writer(stream); writer.writerow(['img_id','sentence_id','SinoNom_Char','ChuQN_txt'])
                writer.writerows([[r['sentence_id'].rsplit('.',1)[0]+'.jpg',r['sentence_id'],
                                   export_text(r['source'], 'source')[0], export_text(r['target'], 'target')[0]]
                                  for r in described if not r.get('duplicate_of') and r['review_state'] != 'excluded'])
            replace_file(tmp,csv_path)
            write_json(self.data/'output_alignment'/'summary.json',{'updated_at':now,**self.pair_stats()})
            prepared = prepared_rows(described, reviewed_only=True)
            signature = [(row['id'], row['sentence_id'], source, sc, target, tc)
                         for row, source, sc, target, tc in prepared]
            if not hasattr(self, '_output_signatures'):
                self._output_signatures = {}
            if self._output_signatures.get(book_id) != signature or any(
                    not (folder / f"{book['name']}.{extension}").exists() for extension in ('csv', 'xlsx')):
                for extension in ('csv', 'xlsx'):
                    write_alignment(folder / f"{book['name']}.{extension}", prepared)
                self._output_signatures[book_id] = signature
            # ZIPs are assembled on demand from this saved revision, never served from an old cache.
            (folder / f"{book['name']}_labels.zip").unlink(missing_ok=True)
            (self.data / 'output_alignment' / 'tat-ca-ket-qua.zip').unlink(missing_ok=True)

    def prepare_label_checkpoint(self, book_id):
        """Finish checkpoint updates before returning a page version to an editor."""
        with self.lock:
            self.sync_new_data_edits(book_id)
            book = self.book(book_id)
            if not book:
                return None, []
            pages = self.pages(book_id)
            if not book['input_revision']:
                rows = {row['id']: row for row in self.alignment_rows(book_id)}
                for page in pages:
                    exports = []
                    for box in page['export_boxes']:
                        alignment_id = box.get('alignment_id')
                        row = rows.get(alignment_id)
                        exports.append({**box, 'transcription': row['source']} if row else box)
                    if exports != page['export_boxes']:
                        with self.db() as db:
                            db.execute('UPDATE pages SET export_boxes=?,version=version+1 WHERE id=?',
                                       (json.dumps(exports, ensure_ascii=False), page['id']))
                        page['export_boxes'] = exports
                        page['version'] += 1
            return book, pages

    def sync_labels(self, book_id, *, checkpoint=True):
        with self.lock:
            book, pages = self.prepare_label_checkpoint(book_id) if checkpoint else (self.book(book_id), self.pages(book_id))
            if not book:
                return
            text_path=self.book_dir(book_id)/'page_texts.json'
            text_path.parent.mkdir(parents=True,exist_ok=True)
            temporary=text_path.with_suffix('.tmp')
            temporary.write_text(json.dumps([{'page_id':p['id'],'number':p['number'],'category':p['category'],
                'source_text':p['source_text'],'target_text':p['target_text'],'vi_boxes':p['vi_boxes'],
                'status':p['status']} for p in pages],ensure_ascii=False,indent=2),encoding='utf-8')
            replace_file(temporary,text_path)
            for category in CATEGORIES:
                folder = self.book_dir(book_id) / category
                folder.mkdir(parents=True, exist_ok=True)
                if category in ("blank", "misc"):
                    continue
                labels, states = [], []
                for page in pages:
                    if category not in label_groups(page):
                        continue
                    name = f"{category}/{book['name']}.{page['number']:03d}.jpg"
                    vi_box_ids = {id(box) for box in page['vi_boxes']}
                    boxes = []
                    for box in label_boxes(page, category):
                        side = 'target' if category == 'vi' or (category in ('intro', 'ref', 'toc') and id(box) in vi_box_ids) else 'source'
                        transcription = export_text(box['transcription'], side)[0]
                        if transcription:
                            boxes.append({'transcription': transcription, 'points': box['points']})
                    labels.append(name + "\t" + json.dumps(boxes, ensure_ascii=False))
                    states.append(name + "\t" + str(int(page['review_state'] == 'done')))
                for filename, lines in (("Label.txt", labels), ("fileState.txt", states)):
                    target = folder / filename
                    tmp = target.with_suffix(".tmp")
                    tmp.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
                    replace_file(tmp, target)
            self.sync_results(book_id, checkpoint=False)
