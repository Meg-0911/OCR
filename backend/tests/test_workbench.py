import csv
import io
import json
import zipfile
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from backend.app import EXPORT_COLUMNS, create_app
from backend.store import CATEGORIES, Store


@pytest.fixture
def workspace(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        yield client, app.state.store, tmp_path


def page_payload(page, **changes):
    return {'boxes':page['boxes'], 'category':page['category'], 'done':False, 'version':page['version']} | changes


def upload_book(client, name='Book with spaces.pdf'):
    pdf = pymupdf.open()
    pdf.new_page(width=400, height=600).insert_text((50,50),'Test page one')
    pdf.new_page(width=400, height=600).insert_text((50,50),'Test page two')
    response = client.post('/api/books/upload', files={'file':(name,pdf.tobytes(),'application/pdf')})
    pdf.close()
    assert response.status_code == 201, response.text
    book = response.json()
    return book, client.get(f"/api/books/{book['id']}/pages").json()


def labelled_book(client):
    book, pages = upload_book(client, 'Sách kiểm thử.pdf')
    boxes = [{'id':str(i), 'transcription':f'字{i}', 'points':[[480-i*70,80],[520-i*70,80],[520-i*70,480],[480-i*70,480]]} for i in range(6)]
    page = client.put(f"/api/pages/{pages[0]['id']}", json=page_payload(pages[0], category='ch', boxes=boxes)).json()
    return book, page


@pytest.fixture
def annotated(workspace):
    client,store,root = workspace
    book,page = labelled_book(client)
    return client,store,root,book,page


def test_empty_workspace_and_real_pdf_folders_include_ref(workspace):
    client,store,_ = workspace
    data = client.get('/api/workspace').json()
    assert data['ocr_ready'] is False
    assert data['books'] == []
    book,pages = upload_book(client)
    for category in CATEGORIES:
        assert (store.book_dir(book['id'])/category).is_dir()
    assert client.get(pages[0]['image_url']).headers['content-type'] == 'image/jpeg'


def test_save_resume_and_ppocrlabel_contract(annotated):
    client,store,root,book,page = annotated
    page['boxes'][0]['transcription'] = '漢字𠊛'
    response = client.put(f"/api/pages/{page['id']}",json=page_payload(page, done=True))
    assert response.status_code == 200
    reloaded = Store(root)
    assert reloaded.page(page['id'])['status'] == 'done'
    assert reloaded.page(page['id'])['boxes'][0]['transcription'] == '漢字𠊛'
    label_path = store.book_dir(book['id'])/'ch'/'Label.txt'
    entries = {line.split('\t',1)[0]:json.loads(line.split('\t',1)[1]) for line in label_path.read_text(encoding='utf-8').splitlines()}
    boxes = entries['ch/Sách kiểm thử.001.jpg']
    assert all(set(box)=={'transcription','points'} and len(box['points'])==4 for box in boxes)
    assert boxes[0]['points'][0][0] > boxes[-1]['points'][0][0]
    assert 'ch/Sách kiểm thử.001.jpg\t1' in (label_path.parent/'fileState.txt').read_text(encoding='utf-8')
    label_path.write_text('interrupted write',encoding='utf-8')
    Store(root)
    assert label_path.read_text(encoding='utf-8').startswith('ch/')


def test_stale_page_cannot_overwrite_newer_edits(annotated):
    client,_,_,_,page = annotated
    assert client.put(f"/api/pages/{page['id']}",json=page_payload(page)).status_code == 200
    assert client.put(f"/api/pages/{page['id']}",json=page_payload(page)).status_code == 409


@pytest.mark.parametrize('points', [
    [[0,0],[30,0],[30,30]],
    [[0,0],[30,0],[30,30],[0,30],[0,0]],
    [[-1,0],[30,0],[30,30],[0,30]],
    [[0,0],[900,0],[900,30],[0,30]],
    [[0,0],[30,30],[30,0],[0,30]],
    [[0,0],[0,0],[0,0],[0,0]],
])
def test_invalid_boxes_are_rejected(annotated,points):
    client,_,_,_,page = annotated
    payload = page_payload(page,boxes=[{'id':'invalid','transcription':'text','points':points}])
    assert client.put(f"/api/pages/{page['id']}",json=payload).status_code == 422


def test_cannot_complete_empty_transcription(annotated):
    client,_,_,_,page = annotated
    page['boxes'][0]['transcription'] = '  '
    assert client.put(f"/api/pages/{page['id']}",json=page_payload(page,done=True)).status_code == 422


def test_pdf_import_render_classification_and_bilingual_copy(workspace):
    client,store,root = workspace
    book,pages = upload_book(client, 'Sách thử nghiệm.pdf')
    assert book['name'] == 'Sách thử nghiệm'
    assert len(pages) == 2 and all(p['category']=='misc' for p in pages)
    page = pages[0]
    image = client.get(page['image_url'])
    assert image.status_code==200 and image.headers['content-type']=='image/jpeg'
    assert image.content.startswith(b'\xff\xd8')
    response = client.put(f"/api/pages/{page['id']}",json=page_payload(page,category='ch'))
    assert response.status_code == 200
    result = client.post(f"/api/pages/{page['id']}/duplicate")
    assert result.status_code == 200
    duplicate = result.json()
    assert duplicate['category']=='vi' and duplicate['boxes']==[]
    assert client.get(duplicate['image_url']).content == image.content
    assert client.post(f"/api/pages/{page['id']}/duplicate").status_code == 409
    for category in ('ch','vi'):
        assert (store.book_dir(book['id'])/category/'Sách thử nghiệm.001.jpg').is_file()
    assert not (store.book_dir(book['id'])/'misc'/'Sách thử nghiệm.001.jpg').exists()
    assert len(list((root/'backend/data/raw_data').glob('*.pdf')))==1


def test_bad_pdf_and_path_traversal_are_rejected(workspace):
    client,_,root = workspace
    assert client.post('/api/books/upload',files={'file':('broken.pdf',b'not a pdf','application/pdf')}).status_code == 400
    assert client.post('/api/books/import',json={'filename':'../secret.pdf'}).status_code == 400
    assert client.post('/api/books/import',json={'filename':'..\\secret.pdf'}).status_code == 400
    assert client.post('/api/books/import',json={'filename':'absent.pdf'}).status_code == 404
    assert not list((root/'backend/data/.workspace').glob('upload-*'))


def test_sources_are_local_and_import_keeps_name(workspace):
    client,_,root = workspace
    folder = root/'backend/data/raw_data'
    pdf=pymupdf.open()
    pdf.new_page()
    pdf.save(folder/'Original Name.PDF')
    pdf.close()
    sources=client.get('/api/sources').json()
    assert sources[0]['name']=='Original Name.PDF'
    response=client.post('/api/books/import',json={'filename':sources[0]['name']})
    assert response.status_code==201
    assert response.json()['name']=='Original Name'
    assert client.post('/api/books/import',json={'filename':sources[0]['name']}).status_code==409


def test_csv_and_xlsx_exact_schema_unicode_and_unverified_color(annotated):
    client,_,_,book,_ = annotated
    rows = [{'id':'1', 'sentence_id':f"{book['name']}.001.1", 'source':'漢字𠊛', 'target':'=1+1', 'reviewed':True}]
    assert client.put(f"/api/books/{book['id']}/alignments",json={'rows':rows}).status_code==200
    csv_response=client.get(f"/api/books/{book['id']}/export?format=csv")
    exported=list(csv.reader(io.StringIO(csv_response.content.decode('utf-8-sig'))))
    assert exported[0]==EXPORT_COLUMNS
    assert exported[1]==[f"{book['name']}.001.jpg",f"{book['name']}.001.1",'漢字𠊛','=1+1']
    assert len(exported)==len(rows)+1
    workbook=load_workbook(io.BytesIO(client.get(f"/api/books/{book['id']}/export?format=xlsx").content))
    sheet=workbook.active
    assert [c.value for c in sheet[1]]==EXPORT_COLUMNS
    assert sheet['C2'].value=='漢字𠊛'
    assert sheet['D2'].data_type=='s'
    assert sheet['C2'].font.color.rgb=='00C43838'
    assert sheet['D2'].font.color.rgb=='00C43838'


def test_label_archive_and_alignment_validation(annotated):
    client,_,_,book,_ = annotated
    response=client.get(f"/api/books/{book['id']}/export?format=labels")
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert f"{book['name']}/ref/Label.txt" in archive.namelist()
        assert f"{book['name']}/ch/fileState.txt" in archive.namelist()
        assert all(not name.endswith('.jpg') for name in archive.namelist())
    rows=[{'id':'1', 'sentence_id':f"{book['name']}.001.1", 'source':'字', 'target':'Chữ', 'reviewed':False}]
    assert client.put(f"/api/books/{book['id']}/alignments",json={'rows':[rows[0],rows[0]]}).status_code==422
    rows[0]['sentence_id']=f"{book['name']}.999.1"
    assert client.put(f"/api/books/{book['id']}/alignments",json={'rows':rows}).status_code==422
    book,_=upload_book(client)
    assert client.get(f"/api/books/{book['id']}/export?format=csv").status_code==400


def test_unknown_resources_are_404(workspace):
    client,_,_ = workspace
    assert client.get('/api/books/missing/pages').status_code==404
    assert client.get('/api/pages/missing/image').status_code==404
    assert client.get('/api/books/missing/export').status_code==404


def save_counted_pairs(client, name, pairs):
    book, pages = upload_book(client, name)
    page = pages[0]
    assert client.put(f"/api/pages/{page['id']}", json=page_payload(page, category='ch')).status_code == 200
    rows = [
        {'id':str(i), 'sentence_id':f"{book['name']}.001.{i}",
         'source':source, 'target':target, 'reviewed':reviewed}
        for i,(source,target,reviewed) in enumerate(pairs, start=1)
    ]
    response = client.put(f"/api/books/{book['id']}/alignments", json={'rows':rows})
    assert response.status_code == 200, response.text
    return book


def test_pair_counter_excludes_incomplete_and_duplicates_and_resumes(workspace):
    client, _, root = workspace
    stats = client.get('/api/workspace').json()['pair_stats']
    assert stats == {
        'target':2000, 'pairs':0, 'reviewed_pairs':0, 'remaining':2000,
        'duplicate_pairs':0, 'incomplete_pairs':0,
    }
    first = save_counted_pairs(client, 'Stats One.pdf', [
        ('天地', 'Thiên địa', False),
        ('天 地', 'thie\u0302n đi\u0323a', True),
        ('', 'Nội dung', True),
        ('玄黃', ' \t\n', False),
    ])
    second = save_counted_pairs(client, 'Stats Two.pdf', [
        ('天地', 'THIÊN   ĐỊA', False),
        ('宇宙', 'Vũ trụ', False),
    ])
    stats = client.get('/api/workspace').json()['pair_stats']
    assert stats == {
        'target':2000, 'pairs':2, 'reviewed_pairs':1, 'remaining':1998,
        'duplicate_pairs':2, 'incomplete_pairs':2,
    }
    assert Store(root).pair_stats() == stats
    assert client.put(f"/api/books/{second['id']}/alignments", json={'rows':[]}).status_code == 200
    assert client.get('/api/workspace').json()['pair_stats']['pairs'] == 1
    assert client.put(f"/api/books/{first['id']}/alignments", json={'rows':[]}).status_code == 200
    assert client.get('/api/workspace').json()['pair_stats']['remaining'] == 2000


@pytest.mark.parametrize('count,remaining', [(1999,1), (2000,0), (2001,0)])
def test_pair_counter_target_boundaries(workspace, count, remaining):
    client, _, _ = workspace
    save_counted_pairs(client, 'Target.pdf', [
        (f'句{i}', f'Câu {i}', False) for i in range(count)
    ])
    stats = client.get('/api/workspace').json()['pair_stats']
    assert stats['pairs'] == count
    assert stats['remaining'] == remaining
    assert stats['target'] == 2000
