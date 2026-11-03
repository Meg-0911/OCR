from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.ocr import KHNConfig
from backend.store import Store


def write_pdf(path):
    with pymupdf.open() as document:
        document.new_page(width=200, height=300).insert_text((20, 40), 'Source page')
        document.save(path)


@pytest.mark.parametrize('count', [0, 5, 15])
def test_startup_indexes_all_pdfs_without_count_limit_or_copies(tmp_path, count):
    folder = tmp_path / 'backend/data/raw_data'
    folder.mkdir(parents=True)
    for index in range(count):
        write_pdf(folder / f'Sách {index}.PDF')
    (folder / 'unrelated.txt').write_text('Quốc ngữ', encoding='utf-8')
    client = TestClient(create_app(tmp_path, ocr_config=KHNConfig()))
    workspace = client.get('/api/workspace').json()
    assert len(workspace['books']) == count
    assert workspace['source_errors'] == []
    assert workspace['source_folder'] == 'backend/data/raw_data/'
    assert all(book['pages'] == 1 for book in workspace['books'])
    assert all('demo' not in book for book in workspace['books'])
    assert len(list(folder.iterdir())) == count + 1
    assert len(client.get('/api/sources').json()) == count
    before = workspace['books']
    after = client.post('/api/sources/sync').json()['books']
    assert before == after


def test_reference_is_attached_to_matching_pdf_and_never_separate_book(tmp_path):
    folder = tmp_path / 'backend/data/raw_data'
    folder.mkdir(parents=True)
    filename = 'Tiên Phả Dịch Lục, Nôm, 2 volumes_Y.pdf'
    write_pdf(folder / filename)
    write_pdf(folder / 'Sách khác.pdf')
    text = '******* Page 06 *******\nGiời Nam chung tú mới kỳ,\nBốn người bất tử lại vì nữ Tiên.'
    reference = folder / 'Tiên Phả Dịch Lục_Dịch.txt'
    reference.write_text(text, encoding='utf-8-sig')
    client = TestClient(create_app(tmp_path, ocr_config=KHNConfig()))
    books = client.get('/api/workspace').json()['books']
    assert len(books) == 2
    book = next(book for book in books if book['filename'] == filename)
    assert book['reference_file'] is None
    assert client.get(f"/api/books/{book['id']}/reference").json() is None
    assert client.put(f"/api/books/{book['id']}/text-sources/vi",json={'filename':reference.name,'text':text}).status_code==200
    assert client.get(f"/api/books/{book['id']}/reference").json() == {'filename':reference.name, 'text':text}
    assert client.get(f"/api/books/{book['id']}/alignments").json() == []
    assert client.get('/api/workspace').json()['pair_stats']['pairs'] == 0
    other = next(book for book in books if book['filename'] != filename)
    assert other['reference_file'] is None
    assert client.get(f"/api/books/{other['id']}/reference").json() is None
    assert reference.read_text(encoding='utf-8-sig') == text


def test_refresh_adds_sources_without_resetting_edits_and_reports_bad_pdfs(tmp_path):
    folder = tmp_path / 'backend/data/raw_data'
    folder.mkdir(parents=True)
    write_pdf(folder / 'First.pdf')
    client = TestClient(create_app(tmp_path, ocr_config=KHNConfig()))
    first = client.get('/api/workspace').json()['books'][0]
    page = client.get(f"/api/books/{first['id']}/pages").json()[0]
    updated = client.put(f"/api/pages/{page['id']}", json={'version':0, 'boxes':[], 'category':'ch', 'done':False}).json()
    write_pdf(folder / 'Second.pdf')
    (folder / 'Broken.pdf').write_bytes(b'not a PDF')
    workspace = client.post('/api/sources/sync').json()
    assert len(workspace['books']) == 2
    assert workspace['source_errors'][0]['filename'] == 'Broken.pdf'
    assert client.get(f"/api/books/{first['id']}/pages").json()[0] == updated
    restarted = TestClient(create_app(tmp_path, ocr_config=KHNConfig()))
    assert len(restarted.get('/api/workspace').json()['books']) == 2
    assert restarted.get(f"/api/books/{first['id']}/pages").json()[0] == updated


def test_ambiguous_reference_is_not_guessed(tmp_path):
    folder = tmp_path / 'backend/data/raw_data'
    folder.mkdir(parents=True)
    write_pdf(folder / 'Tên sách, tập 1.pdf')
    write_pdf(folder / 'Tên sách, tập 2.pdf')
    (folder / 'Tên sách_Dịch.txt').write_text('Quốc ngữ', encoding='utf-8')
    client = TestClient(create_app(tmp_path, ocr_config=KHNConfig()))
    assert all(book['reference_file'] is None for book in client.get('/api/workspace').json()['books'])


def test_legacy_seeded_records_removed_without_touching_real_books(tmp_path):
    folder = tmp_path / 'backend/data/raw_data'
    folder.mkdir(parents=True)
    write_pdf(folder / 'Real.pdf')
    app = create_app(tmp_path, ocr_config=KHNConfig())
    real = app.state.store.books()[0]
    with app.state.store.db() as db:
        db.execute("INSERT INTO books VALUES ('legacy', 'Legacy', 'Legacy.pdf', NULL, 1, '2026')")
        db.execute("INSERT INTO pages (id,book_id,number,category) VALUES ('legacy-page','legacy',1,'ch')")
        db.execute("INSERT INTO alignments VALUES ('legacy','[]')")
    resumed = Store(tmp_path)
    assert resumed.books() == [real]
    assert resumed.page('legacy-page') is None
