import os
import shutil
import zipfile
import sqlite3
import json
import time

start_time = time.time()
book_id = '74868a599b314d249b4c9188f1d38870'
zip_filename = r'd:\OCR\truyen_kieu_ocr_handoff.zip'
staging_dir = r'd:\OCR\tmp\handoff_staging'

print("1. Checkpointing SQLite database to ensure clean state...")
db_path = r'backend/data/.workspace/workspace.sqlite3'
con = sqlite3.connect(db_path)
con.execute("PRAGMA wal_checkpoint(FULL)")
con.close()

# Prepare staging dir
if os.path.exists(staging_dir):
    shutil.rmtree(staging_dir)
os.makedirs(staging_dir, exist_ok=True)

print("2. Creating handoff copy of SQLite with ALL pairs unconfirmed (reviewed=False)...")
staging_db_dir = os.path.join(staging_dir, "backend", "data", ".workspace")
os.makedirs(staging_db_dir, exist_ok=True)
staging_db_path = os.path.join(staging_db_dir, "workspace.sqlite3")
shutil.copy2(db_path, staging_db_path)

# Update staging DB: set reviewed=False for all alignment rows of Truyen Kieu
con_stage = sqlite3.connect(staging_db_path)
cur_stage = con_stage.cursor()
row = cur_stage.execute("SELECT rows FROM alignments WHERE book_id=?", (book_id,)).fetchone()
if row:
    rows = json.loads(row[0])
    original_reviewed = sum(bool(r.get('reviewed')) for r in rows)
    for r in rows:
        r['reviewed'] = False
    cur_stage.execute("UPDATE alignments SET rows=? WHERE book_id=?", (json.dumps(rows, ensure_ascii=False), book_id))
    con_stage.commit()
    print(f"  Reset {original_reviewed} previously reviewed pairs to False (total rows: {len(rows)}).")
con_stage.execute("VACUUM")
con_stage.close()

# Verify staging DB
con_verify = sqlite3.connect(staging_db_path)
v_row = con_verify.execute("SELECT rows FROM alignments WHERE book_id=?", (book_id,)).fetchone()
v_rows = json.loads(v_row[0])
assert sum(bool(r.get('reviewed')) for r in v_rows) == 0, "Verification failed: reviewed count is not 0"
con_verify.close()
print("  Staging DB verified: 0 reviewed pairs.")

# 3. Handle output_alignment alignments.json & summary.json
staging_out_dir = os.path.join(staging_dir, "backend", "data", "output_alignment", book_id)
os.makedirs(staging_out_dir, exist_ok=True)
orig_align_json = f'backend/data/output_alignment/{book_id}/alignments.json'
if os.path.exists(orig_align_json):
    with open(orig_align_json, 'r', encoding='utf-8') as f:
        align_data = json.load(f)
    for r in align_data:
        if isinstance(r, dict):
            r['reviewed'] = False
    with open(os.path.join(staging_out_dir, 'alignments.json'), 'w', encoding='utf-8') as f:
        json.dump(align_data, f, ensure_ascii=False, indent=2)

orig_sum_json = f'backend/data/output_alignment/{book_id}/summary.json'
if os.path.exists(orig_sum_json):
    with open(orig_sum_json, 'r', encoding='utf-8') as f:
        sum_data = json.load(f)
    sum_data['pairs'] = 0
    sum_data['reviewed_pairs'] = 0
    sum_data['remaining'] = sum_data.get('target', 2000)
    with open(os.path.join(staging_out_dir, 'summary.json'), 'w', encoding='utf-8') as f:
        json.dump(sum_data, f, ensure_ascii=False, indent=2)

print("4. Preparing file list for package...")
# List of all matched page_ids for ocr cache
con_orig = sqlite3.connect(db_path)
cur_orig = con_orig.cursor()
page_ids = set(r[0] for r in cur_orig.execute('SELECT id FROM pages WHERE book_id=?', (book_id,)).fetchall())
con_orig.close()

# Map of (archive_rel_path -> physical_path)
files_map = {}

# 1. PDF
pdf_path = r'backend/data/raw_data/TruyenKieuBanDuyMinhThi1872AnChiPhienAmChuGiaiVaThaoLuan_NguyenDu.pdf'
if os.path.exists(pdf_path):
    files_map['backend/data/raw_data/TruyenKieuBanDuyMinhThi1872AnChiPhienAmChuGiaiVaThaoLuan_NguyenDu.pdf'] = pdf_path

# 2. SQLite (from staging, unconfirmed)
files_map['backend/data/.workspace/workspace.sqlite3'] = staging_db_path

# 3. processed_images
proc_dir = f'backend/data/processed_images/{book_id}'
if os.path.exists(proc_dir):
    for root, _, files in os.walk(proc_dir):
        for f in files:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, r'd:\OCR').replace('\\', '/')
            files_map[rel] = full

# 4. workspace/books/<book_id>
books_dir = f'backend/data/.workspace/books/{book_id}'
if os.path.exists(books_dir):
    for root, _, files in os.walk(books_dir):
        for f in files:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, r'd:\OCR').replace('\\', '/')
            files_map[rel] = full

# 5. workspace/ocr
ocr_base = r'backend/data/.workspace/ocr'
if os.path.exists(ocr_base):
    for pid in page_ids:
        pdir = os.path.join(ocr_base, pid)
        if os.path.exists(pdir):
            for root, _, files in os.walk(pdir):
                for f in files:
                    full = os.path.join(root, f)
                    rel = os.path.relpath(full, r'd:\OCR').replace('\\', '/')
                    files_map[rel] = full

# 6. workspace/ocr-images/<book_id>
ocr_img_dir = f'backend/data/.workspace/ocr-images/{book_id}'
if os.path.exists(ocr_img_dir):
    for root, _, files in os.walk(ocr_img_dir):
        for f in files:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, r'd:\OCR').replace('\\', '/')
            files_map[rel] = full

# 7. output_alignment/<book_id>
output_dir = f'backend/data/output_alignment/{book_id}'
if os.path.exists(output_dir):
    for root, _, files in os.walk(output_dir):
        for f in files:
            if f.endswith('_labels.zip'):
                continue
            full = os.path.join(root, f)
            rel = os.path.relpath(full, r'd:\OCR').replace('\\', '/')
            if rel not in files_map:
                files_map[rel] = full

# Override alignments.json and summary.json with staged versions
staged_align = os.path.join(staging_out_dir, 'alignments.json')
if os.path.exists(staged_align):
    files_map[f'backend/data/output_alignment/{book_id}/alignments.json'] = staged_align
staged_sum = os.path.join(staging_out_dir, 'summary.json')
if os.path.exists(staged_sum):
    files_map[f'backend/data/output_alignment/{book_id}/summary.json'] = staged_sum

print(f"Total files to package: {len(files_map)}")

print(f"5. Creating ZIP package: {zip_filename}...")
if os.path.exists(zip_filename):
    os.remove(zip_filename)

with zipfile.ZipFile(zip_filename, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
    for i, (arcname, filepath) in enumerate(files_map.items(), 1):
        zf.write(filepath, arcname=arcname)
        if i % 500 == 0 or i == len(files_map):
            print(f"  Packaged {i}/{len(files_map)} files...")

# Clean staging
shutil.rmtree(staging_dir, ignore_errors=True)

zip_size_mb = os.path.getsize(zip_filename) / 1024 / 1024
elapsed = time.time() - start_time
print(f"Done in {elapsed:.1f}s! ZIP size: {zip_size_mb:.2f} MB")
