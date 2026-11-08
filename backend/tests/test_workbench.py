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


def test_export_box_order_metadata_is_validated_and_persisted(annotated):
    client,_,_,_,page=annotated
    boxes=[
        {'id':'first','transcription':'天','points':[[20,20],[40,20],[40,40],[20,40]],
         'export_group':'group-first','export_order':2,'export_character_order':0},
        {'id':'first-next','transcription':'玄','points':[[42,20],[62,20],[62,40],[42,40]],
         'export_group':'group-first','export_order':2,'export_character_order':1},
        {'id':'second','transcription':'地','points':[[41,20],[61,20],[61,40],[41,40]],
         'export_group':'group-second','export_order':1,'export_character_order':0},
    ]
    response=client.patch(f"/api/pages/{page['id']}",json={'boxes':boxes})
    assert response.status_code==200,response.text
    saved={box['id']:box['export_order'] for box in response.json()['boxes']}
    assert saved=={'first':2,'first-next':2,'second':1}

    boxes[0]['export_order']=1
    invalid=client.patch(f"/api/pages/{page['id']}",json={'boxes':boxes})
    assert invalid.status_code==422

    exported=client.get(f"/api/books/{page['book_id']}/export?format=labels")
    assert exported.status_code==200
    archive=zipfile.ZipFile(io.BytesIO(exported.content))
    label=next(name for name in archive.namelist() if name.endswith('/ch/Label.txt'))
    rows=json.loads(archive.read(label).decode().splitlines()[0].split('\t',1)[1])
    assert [box['transcription'] for box in rows]==['地','天玄']

    updated_boxes=[
        boxes[1],
        boxes[2],
        {'id':'new-glyph','transcription':'人','points':[[70,20],[90,20],[90,40],[70,40]]},
    ]
    updated=client.patch(f"/api/pages/{page['id']}",json={'boxes':updated_boxes})
    assert updated.status_code==200,updated.text
    normalized={box['id']:box for box in updated.json()['boxes']}
    assert normalized['first-next']['export_character_order']==0
    assert normalized['new-glyph']['export_order']==3


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
    assert len(pages) == 2 and all(p['category']=='both' for p in pages)
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


def test_bulk_plan_keeps_ocr_languages_in_sync_with_page_tag(workspace):
    client,store,_=workspace
    book,pages=upload_book(client,'Tags.pdf')
    result=client.put(f"/api/books/{book['id']}/plan",json={'pages':[
        {'page_id':pages[0]['id'],'category':'ch'},
        {'page_id':pages[1]['id'],'category':'vi'},
    ]})
    assert result.status_code==200,result.text
    assert [page['ocr_languages'] for page in result.json()]==[['han'],['vi']]
    with store.db() as db:
        db.execute("UPDATE pages SET ocr_languages='[\"han\", \"vi\"]' WHERE id=?",(pages[1]['id'],))
    assert store.page(pages[1]['id'])['ocr_languages']==['vi']
    assert client.put(f"/api/books/{book['id']}/plan",json={'pages':[
        {'page_id':pages[0]['id'],'category':'both'},
    ]}).json()[0]['ocr_languages']==['han','vi']


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


def test_csv_and_xlsx_exact_schema_and_unicode(annotated):
    client,_,_,book,_ = annotated
    rows = [{'id':'1', 'sentence_id':f"{book['name']}.001.1", 'source':'漢字𠊛', 'target':'=1+1', 'reviewed':True,
             'marks':[{'source_start':0,'source_end':3,'target_start':0,'target_end':4,'kind':'match'}]}]
    assert client.put(f"/api/books/{book['id']}/alignments",json={'rows':rows}).status_code==200
    csv_response=client.get(f"/api/books/{book['id']}/export?format=csv")
    exported=list(csv.reader(io.StringIO(csv_response.content.decode('utf-8-sig'))))
    assert exported[0]==EXPORT_COLUMNS
    assert exported[1]==[f"{book['name']}.001.jpg",f"{book['name']}.001.1",'漢字𠊛','=1+1']
    assert len(exported)==len(rows)+1
    workbook=load_workbook(io.BytesIO(client.get(f"/api/books/{book['id']}/export?format=xlsx").content),rich_text=True)
    sheet=workbook.active
    assert [c.value for c in sheet[1]]==EXPORT_COLUMNS
    assert sheet['D2'].data_type=='s'
    assert str(sheet['C2'].value)=='漢字𠊛'
    assert str(sheet['D2'].value)=='=1+1'
    assert sheet['C2'].value[0].font.color.rgb=='FF000000'


def test_incomplete_split_pair_cannot_be_exported(annotated):
    client,_,_,book,_=annotated
    rows=[{'id':'split','sentence_id':f"{book['name']}.001.1",'source':'天地','target':'','reviewed':False}]
    assert client.put(f"/api/books/{book['id']}/alignments",json={'rows':rows}).status_code==200
    assert client.get(f"/api/books/{book['id']}/export?format=csv").status_code==400
    assert client.get(f"/api/books/{book['id']}/export?format=xlsx").status_code==400


def test_xlsx_defaults_to_black_and_rejects_out_of_range_marks(annotated):
    client,_,_,book,_=annotated
    url=f"/api/books/{book['id']}/alignments"
    row={'id':'review','sentence_id':f"{book['name']}.001.1",'source':'一','target':'nhất','reviewed':True}
    assert client.put(url,json={'rows':[row]}).status_code==200
    assert client.get(f"/api/books/{book['id']}/export?format=csv").status_code==200
    workbook=load_workbook(io.BytesIO(client.get(f"/api/books/{book['id']}/export?format=xlsx").content),rich_text=True)
    assert workbook.active['C2'].value[0].font.color.rgb=='FF000000'
    assert workbook.active['D2'].value[0].font.color.rgb=='FF000000'
    row['marks']=[{'source_start':0,'source_end':2,'target_start':0,'target_end':4,'kind':'match'}]
    assert client.put(url,json={'rows':[row]}).status_code==422
    row['marks'][0]['source_end']=1
    assert client.put(url,json={'rows':[row]}).status_code==200
    assert client.get(f"/api/books/{book['id']}/export?format=xlsx").status_code==200


def test_xlsx_uses_per_character_review_from_page_boxes(annotated):
    client,_,_,book,page=annotated
    boxes=[
        {'id':'han-1','transcription':'天','points':[[50,10],[80,10],[80,50],[50,50]]},
        {'id':'han-2','transcription':'玄','points':[[10,10],[40,10],[40,50],[10,50]],'review_kind':'mismatch'},
    ]
    vi_boxes=[
        {'id':'vi-1','transcription':'thiên địa','points':[[10,60],[80,60],[80,90],[10,90]],'review_kind':'unknown'},
    ]
    saved=client.patch(f"/api/pages/{page['id']}",json={
        'category':'ch','source_text':'天地','target_text':'thiên địa','boxes':boxes,'vi_boxes':vi_boxes,
    })
    assert saved.status_code==200
    assert [box.get('review_kind') for box in saved.json()['boxes']]==[None,'mismatch']
    assert [box.get('review_kind') for box in saved.json()['vi_boxes']]==['unknown']
    row={'id':'glyph-colors','sentence_id':f"{book['name']}.001.1",'source':'天地','target':'thiên địa','reviewed':False}
    assert client.put(f"/api/books/{book['id']}/alignments",json={'rows':[row]}).status_code==200
    xlsx_bytes=client.get(f"/api/books/{book['id']}/export?format=xlsx").content
    sheet=load_workbook(io.BytesIO(xlsx_bytes),rich_text=True).active
    assert str(sheet['C2'].value)=='天地'
    assert [block.font.color.rgb for block in sheet['C2'].value]==['FF000000','FFCC0000']
    assert str(sheet['D2'].value)=='thiên địa'
    assert [block.font.color.rgb for block in sheet['D2'].value]==['FF000000','FFCC0000']
    with zipfile.ZipFile(io.BytesIO(xlsx_bytes)) as workbook:
        xml=workbook.read('xl/worksheets/sheet1.xml').decode('utf-8')
        assert 'xml:space="preserve"> địa</t>' in xml
        assert '<t> </t>' not in xml
    summary=client.get(f"/api/books/{book['id']}/results/summary.json").json()
    assert summary['similarity_review']=={'total':2,'red':1,'unmarked':0,'percent':50.0}


def test_xlsx_applies_page_colors_to_the_single_quoc_ngu_column_on_each_page(annotated):
    client,_,_,book,page=annotated
    pages=client.get(f"/api/books/{book['id']}/pages").json()
    second=pages[1]
    first_boxes=[
        {'id':'first-a','transcription':'天','points':[[50,10],[80,10],[80,50],[50,50]]},
        {'id':'first-b','transcription':'地','points':[[10,10],[40,10],[40,50],[10,50]],'review_kind':'mismatch'},
    ]
    second_boxes=[
        {'id':'second-a','transcription':'安','points':[[50,10],[80,10],[80,50],[50,50]]},
        {'id':'second-b','transcription':'和','points':[[10,10],[40,10],[40,50],[10,50]],'review_kind':'mismatch'},
    ]
    assert client.patch(f"/api/pages/{page['id']}",json={
        'category':'both','source_text':'天地','target_text':'thiên địa','boxes':first_boxes,
        'vi_boxes':[{'id':'first-vi','transcription':'thiên địa','points':[[10,60],[80,60],[80,90],[10,90]]}],
    }).status_code==200
    assert client.patch(f"/api/pages/{second['id']}",json={
        'category':'both','source_text':'安和','target_text':'an hòa','boxes':second_boxes,
        'vi_boxes':[{'id':'second-vi','transcription':'an hòa','points':[[10,60],[80,60],[80,90],[10,90]]}],
    }).status_code==200
    rows=[
        {'id':'first-page','sentence_id':f"{book['name']}.001.1",'source':'天地','target':'thiên địa','reviewed':False},
        {'id':'second-page','sentence_id':f"{book['name']}.002.1",'source':'安和','target':'an hòa','reviewed':False},
    ]
    assert client.put(f"/api/books/{book['id']}/alignments",json={'rows':rows}).status_code==200
    sheet=load_workbook(
        io.BytesIO(client.get(f"/api/books/{book['id']}/export?format=xlsx").content),
        rich_text=True,
    ).active
    assert sheet.max_column==4
    assert str(sheet['D2'].value)=='thiên địa'
    assert [block.font.color.rgb for block in sheet['D2'].value]==['FF000000','FFCC0000']
    assert str(sheet['D3'].value)=='an hòa'
    assert [block.font.color.rgb for block in sheet['D3'].value]==['FF000000','FFCC0000']


def test_exports_clean_both_scripts_and_keep_xlsx_colors_aligned(annotated):
    client,_,_,book,_=annotated
    row={'id':'clean','sentence_id':f"{book['name']}.001.1",'source':'一，二。','target':'NHẤT, NHỊ!',
         'marks':[
             {'source_start':0,'source_end':4,'target_start':0,'target_end':10,'kind':'match'},
             {'source_start':2,'source_end':3,'target_start':6,'target_end':9,'kind':'mismatch'},
         ]}
    assert client.put(f"/api/books/{book['id']}/alignments",json={'rows':[row]}).status_code==200
    csv_response=client.get(f"/api/books/{book['id']}/export?format=csv")
    assert list(csv.reader(io.StringIO(csv_response.content.decode('utf-8-sig'))))[1][2:]==['一二','nhất nhị']
    snapshot=client.get(f"/api/books/{book['id']}/results/pairs.csv")
    assert list(csv.reader(io.StringIO(snapshot.content.decode('utf-8-sig'))))[1][2:]==['一二','nhất nhị']
    response=client.get(f"/api/books/{book['id']}/export?format=xlsx")
    sheet=load_workbook(io.BytesIO(response.content),rich_text=True).active
    assert str(sheet['C2'].value)=='一二'
    assert str(sheet['D2'].value)=='nhất nhị'
    assert [block.font.color.rgb for block in sheet['C2'].value]==['FF000000','FFCC0000']


def test_exports_preserve_leading_and_trailing_quoc_ngu_spaces(annotated):
    client,_,_,book,_=annotated
    target='  THIÊN,   ĐỊA!  '
    row={'id':'spaces','sentence_id':f"{book['name']}.001.1",'source':'天地','target':target,'reviewed':False}
    assert client.put(f"/api/books/{book['id']}/alignments",json={'rows':[row]}).status_code==200
    csv_rows=list(csv.reader(io.StringIO(
        client.get(f"/api/books/{book['id']}/export?format=csv").content.decode('utf-8-sig')
    )))
    assert csv_rows[1][3]=='  thiên   địa  '
    xlsx_bytes=client.get(f"/api/books/{book['id']}/export?format=xlsx").content
    xlsx=load_workbook(io.BytesIO(xlsx_bytes),rich_text=True)
    assert str(xlsx.active['D2'].value)=='  thiên   địa  '
    with zipfile.ZipFile(io.BytesIO(xlsx_bytes)) as workbook:
        xml=workbook.read('xl/worksheets/sheet1.xml').decode('utf-8')
        assert 'xml:space="preserve">  thiên   địa  </t>' in xml


def test_correcting_placeholder_updates_saved_pairs_after_split_and_merge(workspace):
    client,_,_=workspace
    book,pages=upload_book(client,'Corrections.pdf')
    page=client.patch(f"/api/pages/{pages[0]['id']}",json={'category':'ch','source_text':'□天□'}).json()
    rows=[
        {'id':'one','sentence_id':'Corrections.001.1','source':'□天','target':'A','reviewed':True},
        {'id':'two','sentence_id':'Corrections.001.2','source':'□','target':'B','reviewed':True},
    ]
    assert client.put(f"/api/books/{book['id']}/alignments",json={'rows':rows}).status_code==200
    page=client.patch(f"/api/pages/{page['id']}",json={'source_text':'地天□'}).json()
    saved=client.get(f"/api/books/{book['id']}/alignments").json()
    assert [row['source'] for row in saved]==['地天','□']
    assert [row['reviewed'] for row in saved]==[False,True]
    merged=[{**saved[0],'source':'地天□','target':'AB'}]
    assert client.put(f"/api/books/{book['id']}/alignments",json={'rows':merged}).status_code==200
    client.patch(f"/api/pages/{page['id']}",json={'source_text':'地天玄'})
    assert [row['source'] for row in client.get(f"/api/books/{book['id']}/alignments").json()]==['地天玄']


def test_label_archive_and_alignment_validation(annotated):
    client,_,_,book,_ = annotated
    response=client.get(f"/api/books/{book['id']}/export?format=labels")
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert f"{book['name']}/ref/Label.txt" in archive.namelist()
        assert f"{book['name']}/ch/fileState.txt" in archive.namelist()
        assert f"{book['name']}/ch/{book['name']}.001.jpg" in archive.namelist()
    rows=[{'id':'1', 'sentence_id':f"{book['name']}.001.1", 'source':'字', 'target':'Chữ', 'reviewed':False}]
    assert client.put(f"/api/books/{book['id']}/alignments",json={'rows':[rows[0],rows[0]]}).status_code==422
    rows[0]['sentence_id']=f"{book['name']}.999.1"
    assert client.put(f"/api/books/{book['id']}/alignments",json={'rows':rows}).status_code==422
    book,_=upload_book(client)
    assert client.get(f"/api/books/{book['id']}/export?format=csv").status_code==400


def test_bilingual_labels_contain_real_images_and_only_their_language(workspace):
    client,_,_=workspace
    book,pages=upload_book(client,'Mixed Book.pdf')
    han={'id':'han','transcription':'天，地。','points':[[10,10],[30,10],[30,40],[10,40]]}
    vi={'id':'vi','transcription':'Thiên, Địa!','points':[[40,10],[100,10],[100,40],[40,40]]}
    response=client.put(f"/api/pages/{pages[0]['id']}",json={
        'version':pages[0]['version'],'category':'both','boxes':[han],'vi_boxes':[vi],
        'source_text':'天地','target_text':'Thiên địa','done':True})
    assert response.status_code==200,response.text
    response=client.put(f"/api/pages/{pages[1]['id']}",json={
        'version':pages[1]['version'],'category':'blank','boxes':[],'done':True})
    assert response.status_code==200,response.text
    row={'id':'one','sentence_id':'Mixed Book.001.1','source':'天地','target':'Thiên địa','reviewed':True}
    assert client.put(f"/api/books/{book['id']}/alignments",json={'rows':[row]}).status_code==200
    response=client.get(f"/api/books/{book['id']}/export?format=labels")
    assert response.status_code==200,response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names=set(archive.namelist())
        for category in ('ch','vi'):
            image=f'Mixed Book/{category}/Mixed Book.001.jpg'
            assert image in names and archive.read(image).startswith(b'\xff\xd8')
        assert 'Mixed Book/blank/Mixed Book.002.jpg' in names
        han_labels=archive.read('Mixed Book/ch/Label.txt').decode('utf-8')
        vi_labels=archive.read('Mixed Book/vi/Label.txt').decode('utf-8')
        assert '天地' in han_labels and 'Thiên' not in han_labels and '，' not in han_labels
        assert 'thiên địa' in vi_labels and '天地' not in vi_labels and '!' not in vi_labels


def test_translated_intro_is_in_special_and_both_language_folders(workspace):
    client,_,_=workspace
    book,pages=upload_book(client,'Intro Book.pdf')
    han={'id':'han','transcription':'序','points':[[10,10],[30,10],[30,40],[10,40]]}
    vi={'id':'vi','transcription':'Lời tựa','points':[[40,10],[100,10],[100,40],[40,40]]}
    response=client.put(f"/api/pages/{pages[0]['id']}",json={
        'version':pages[0]['version'],'category':'intro','boxes':[han],'vi_boxes':[vi],
        'source_text':'序','target_text':'Lời tựa','done':True})
    assert response.status_code==200,response.text
    row={'id':'intro','sentence_id':'Intro Book.001.1','source':'序','target':'Lời tựa','reviewed':True}
    assert client.put(f"/api/books/{book['id']}/alignments",json={'rows':[row]}).status_code==200
    with zipfile.ZipFile(io.BytesIO(client.get(f"/api/books/{book['id']}/export?format=labels").content)) as archive:
        for category in ('intro','ch','vi'):
            assert f'Intro Book/{category}/Intro Book.001.jpg' in archive.namelist()
        assert 'Lời tựa' not in archive.read('Intro Book/ch/Label.txt').decode('utf-8')
        assert 'lời tựa' in archive.read('Intro Book/intro/Label.txt').decode('utf-8')


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
        ('天， 地。', 'thie\u0302n đi\u0323a!', True),
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
