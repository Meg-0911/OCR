"""SQLite is the checkpoint; PPOCRLabel text files are recoverable projections."""
import json
import os
import re
import sqlite3
import threading
import unicodedata
from .alignment_review import comparison_key, export_text, score_boxes, source_glyph
import csv
import time
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


def replace_file(temporary,target):
    # Windows readers/antivirus can briefly hold a newly written snapshot open.
    for attempt in range(6):
        try:
            os.replace(temporary,target)
            return
        except PermissionError:
            if os.name!='nt' or attempt==5:
                raise
            time.sleep(.02*2**attempt)


def character_box_groups(boxes, reading_direction):
    """Group character boxes into reading lines/columns in page order."""
    if not boxes:
        return []
    axis = 0 if reading_direction == 1 else 1
    travel = 1 if reading_direction == 1 else 0

    def center(box):
        return sum(point[axis] for point in box['points']) / 4

    def size(box):
        return max(point[axis] for point in box['points']) - min(point[axis] for point in box['points'])

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
            return [dict(row) for row in db.execute("""
            SELECT b.id,b.name,b.filename,b.created_at,COUNT(p.id) AS pages,
            (SELECT id FROM pages WHERE book_id=b.id ORDER BY number,category LIMIT 1) AS first_page_id,
            SUM(CASE WHEN p.status='done' AND p.ocr_skip=0 AND p.category!='blank' THEN 1 ELSE 0 END) AS done,
            SUM(CASE WHEN p.ocr_skip=1 OR p.category='blank' THEN 1 ELSE 0 END) AS excluded
            FROM books b LEFT JOIN pages p ON b.id=p.book_id GROUP BY b.id ORDER BY b.name COLLATE NOCASE
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
                source = comparison_key(row['source']).replace(' ', '')
                target = comparison_key(row['target'])
                if not source or not target:
                    incomplete += 1
                    continue
                key = (source, target)
                if key in pairs:
                    duplicates += 1
                pairs[key] = pairs.get(key, False) or bool(row.get('reviewed', False))
        count = sum(pairs.values())
        return {
            'target': PAIR_TARGET,
            'pairs': count,
            'reviewed_pairs': count,
            'remaining': max(0, PAIR_TARGET - count),
            'duplicate_pairs': duplicates,
            'incomplete_pairs': incomplete,
        }

    @staticmethod
    def page_dict(row, inherited_reading_direction=None, linked_page_ids=None):
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
        if page['vi_boxes']:
            page['target_text']='\n'.join(box_text_lines(
                page['vi_boxes'],2,'vi',(page['width'],page['height'])))
        export_boxes=json.loads(page['export_boxes'])
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
        for key in ('source_regions','target_regions'):
            page[key]=json.loads(page[key]) if page[key] is not None else None
        page['linked_page_ids']=linked_page_ids or []
        page["image_url"] = f"/api/pages/{page['id']}/image"
        return page

    @staticmethod
    def links_for_book(db, book_id):
        links={}
        for row in db.execute('SELECT page_a,page_b FROM page_links WHERE book_id=?',(book_id,)):
            links.setdefault(row['page_a'],[]).append(row['page_b'])
            links.setdefault(row['page_b'],[]).append(row['page_a'])
        return links

    def pages(self, book_id):
        with self.db() as db:
            layout=db.execute('SELECT profile FROM book_layouts WHERE book_id=?',(book_id,)).fetchone()
            direction=json.loads(layout['profile']).get('reading_direction',2) if layout else 2
            links=self.links_for_book(db,book_id)
            return [self.page_dict(row,direction,links.get(row['id'])) for row in db.execute("SELECT * FROM pages WHERE book_id=? ORDER BY number,category", (book_id,))]

    def source_box_colors(self, book_id, rows):
        """Map per-box review colors onto both sides of saved alignment text."""
        book = self.book(book_id)
        if not book:
            return {}
        output = {}
        for page in self.pages(book_id):
            if 'han' not in page['ocr_languages'] or not page['boxes']:
                continue
            prefix = f"{book['name']}.{page['number']:03d}."
            page_rows = [row for row in rows if row['sentence_id'].startswith(prefix)]
            if not page_rows:
                continue
            stream = ''.join(row['source'] for row in page_rows)
            stream_colors = [None] * len(stream)
            box_glyph_colors = []
            for box in page['boxes']:
                for character_index, char in enumerate(box['transcription']):
                    if not source_glyph(char):
                        continue
                    kind = box.get('review_kind') or 'match'
                    for mark in box.get('review_marks', []):
                        if mark['start'] <= character_index < mark['end']:
                            kind = mark['kind']
                    box_glyph_colors.append(kind)
            glyph_index = 0
            for index, char in enumerate(stream):
                if not source_glyph(char):
                    continue
                if glyph_index < len(box_glyph_colors):
                    stream_colors[index] = box_glyph_colors[glyph_index]
                glyph_index += 1
            offset = 0
            for row in page_rows:
                end = offset + len(row['source'])
                output.setdefault(row['id'], {})['source'] = stream_colors[offset:end]
                offset = end
            word_index = 0
            for row in page_rows:
                colors = ['match'] * len(row['target'])
                for match in re.finditer(r'\S+', row['target']):
                    if not any(
                        unicodedata.category(char).startswith(('L', 'N'))
                        for char in match.group()
                    ):
                        continue
                    if word_index < len(page['boxes']):
                        kind = page['boxes'][word_index].get('review_kind') or 'match'
                        colors[match.start():match.end()] = [kind] * (match.end() - match.start())
                    word_index += 1
                output.setdefault(row['id'], {})['target'] = colors
        return output

    def page(self, page_id):
        with self.db() as db:
            row = db.execute("SELECT * FROM pages WHERE id=?", (page_id,)).fetchone()
            if not row:
                return None
            layout=db.execute('SELECT profile FROM book_layouts WHERE book_id=?',(row['book_id'],)).fetchone()
            direction=json.loads(layout['profile']).get('reading_direction',2) if layout else 2
            links=self.links_for_book(db,row['book_id'])
            return self.page_dict(row,direction,links.get(page_id))

    def book_dir(self, book_id):
        return self.local / "books" / book_id

    def latest_ocr(self, page_id):
        with self.db() as db:
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
            for row in list(db.execute('SELECT id,book_id,number,width,height,source_text,target_text,vi_boxes FROM pages')):
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
            return [line.strip() for line in text.splitlines() if line.strip()]
        changes = (
            ('source', 'source_page_id', 'source_line_index', lines(old_source), lines(new_source), old_source != new_source),
            ('target', 'target_page_id', 'target_line_index', lines(old_target), lines(new_target), old_target != new_target),
        )
        with self.db() as db:
            saved = db.execute('SELECT rows FROM alignments WHERE book_id=?', (page['book_id'],)).fetchone()
            if not saved:
                return False
            rows = json.loads(saved['rows'])
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
                    index = row.get(index_key)
                    if index is None:
                        matching = [i for i, line in enumerate(old_lines) if line == row[field].strip()]
                        if len(matching) != 1:
                            continue
                        index = matching[0]
                    if index >= len(old_lines) or row[field].strip() != old_lines[index]:
                        continue
                    replacement = new_lines[index] if index < len(new_lines) else ''
                    if row[field] == replacement:
                        continue
                    word_count_changed = alignment_word_count(replacement, field) != alignment_word_count(row[field], field)
                    row[field] = replacement
                    row['marks'] = []
                    if word_count_changed:
                        row['reviewed'] = False
                    changed = True
            if changed:
                db.execute('UPDATE alignments SET rows=? WHERE book_id=?',
                           (json.dumps(rows, ensure_ascii=False), page['book_id']))
            return changed

    def reconcile_alignment_ocr(self, book_id):
        """Repair older pairs left at the original OCR after a saved box correction."""
        book = self.book(book_id)
        with self.db() as db:
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
        return changed

    def sync_results(self,book_id,event=None):
        """Recoverable result snapshots and a small operational audit, separate from OCR history."""
        with self.lock:
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
            rows=json.loads(alignment['rows']) if alignment else []
            seen={}; incomplete=duplicates=0
            for row in rows:
                key=(comparison_key(row['source']).replace(' ', ''),comparison_key(row['target']))
                if not all(key):
                    incomplete+=1
                    continue
                duplicates+=int(key in seen)
                seen[key]=seen.get(key,False) or bool(row.get('reviewed'))
            now=datetime.now(timezone.utc).isoformat()
            summary={'book_id':book_id,'book':book['name'],'updated_at':now,'pages':len(pages),
                     'excluded_pages':sum(p['ocr_skip'] or p['category']=='blank' for p in pages),
                     'reviewed_pages':sum(p['status']=='done' for p in pages),
                     'ocr_pages':sum(bool(languages.get(p['id'])) for p in pages),
                     'pairs':len(seen),'reviewed_pairs':sum(seen.values()),'duplicate_pairs':duplicates,'incomplete_pairs':incomplete,
                     'similarity_review':score_boxes(pages),
                     'job':dict(job) if job else None,'job_pages':progress}
            def write_json(path,value):
                tmp=path.with_suffix(path.suffix+'.tmp')
                tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
                replace_file(tmp,path)
            write_json(folder/'summary.json',summary)
            write_json(folder/'pages.json',[{key:p[key] for key in ('id','number','category','ocr_skip','status','ocr_granularity','source_text','target_text','target_origin','version','linked_page_ids')} |
                                           {'completed_languages':languages.get(p['id'],[])} for p in pages])
            write_json(folder/'alignments.json',rows)
            csv_path=folder/'pairs.csv'; tmp=csv_path.with_suffix('.csv.tmp')
            with tmp.open('w',encoding='utf-8-sig',newline='') as stream:
                writer=csv.writer(stream); writer.writerow(['img_id','sentence_id','SinoNom_Char','ChuQN_txt'])
                writer.writerows([[r['sentence_id'].rsplit('.',1)[0]+'.jpg',r['sentence_id'],
                                   export_text(r['source'], 'source')[0], export_text(r['target'], 'target')[0]]
                                  for r in rows])
            replace_file(tmp,csv_path)
            write_json(self.data/'output_alignment'/'summary.json',{'updated_at':now,**self.pair_stats()})
            if event:
                with (folder/'events.jsonl').open('a',encoding='utf-8') as stream:
                    stream.write(json.dumps({'time':now,'event':event,'pairs':len(seen),'reviewed_pages':summary['reviewed_pages']},ensure_ascii=False)+'\n')

    def sync_labels(self, book_id):
        with self.lock:
            book = self.book(book_id)
            if not book:
                return
            pages = self.pages(book_id)
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
                    states.append(name + "\t" + str(int(page["status"] == "done")))
                for filename, lines in (("Label.txt", labels), ("fileState.txt", states)):
                    target = folder / filename
                    tmp = target.with_suffix(".tmp")
                    tmp.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
                    replace_file(tmp, target)
            self.sync_results(book_id)
