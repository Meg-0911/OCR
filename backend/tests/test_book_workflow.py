import csv
import json
import threading
import os

import httpx
import pymupdf
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.ocr import KHNConfig


class LocalVI:
    def __init__(self,block=False):
        self.calls=0
        self.entered=threading.Event()
        self.release=threading.Event()
        if not block:self.release.set()

    def status(self):
        return {'ready':True,'engine':'local-test','setup':''}

    def recognize(self,image,**settings):
        self.calls+=1;self.entered.set()
        assert self.release.wait(15)
        return {'boxes':[],'text_lines':['Thiên địa','Huyền hoàng'],'warnings':[]}


def workspace(tmp_path,count=4,vi=None,txt=None):
    raw=tmp_path/'backend/data/raw_data';raw.mkdir(parents=True)
    with pymupdf.open() as doc:
        for _ in range(count):doc.new_page(width=200,height=300)
        doc.save(raw/'Book.pdf')
    if txt:(raw/'Book_Dịch.txt').write_text(txt,encoding='utf-8')
    calls=[]
    def handler(request):
        if request.url.path.endswith('image-upload'):
            data={'file_name':'page.jpg'}
        else:
            calls.append(1)
            data={'result_ocr_text':['天地','玄黃'],'result_bbox':[[[10,50],[100,50],[100,70],[10,70]],[[10,100],[100,100],[100,120],[10,120]]]}
        return httpx.Response(200,json={'is_success':True,'code':'000000','data':data})
    transport=httpx.MockTransport(handler)
    vi=vi or LocalVI()
    app=create_app(tmp_path,ocr_config=KHNConfig(token='test-only'),ocr_transport=transport,vi_provider=vi)
    client=TestClient(app)
    book=client.get('/api/workspace').json()['books'][0]
    pages=client.get(f"/api/books/{book['id']}/pages").json()
    return app,client,book,pages,calls,vi,transport


def start(client,book,pages,skip=()):
    response=client.post(f"/api/books/{book['id']}/workflow",json={'reading_direction':2,'plan':[
        {'page_id':p['id'],'category':'ch','ocr_skip':p['number'] in skip} for p in pages]})
    assert response.status_code==200,response.text
    return response.json()


def finish(app,job):
    app.state.ocr_jobs.futures[job['id']].result(timeout=20)
    result=app.state.ocr_jobs.get(job['id'])
    assert result['status']=='completed',result


def test_save_plan_starts_whole_book_and_never_calls_ocr_for_excluded_pages(tmp_path):
    app,client,book,pages,calls,vi,_=workspace(tmp_path)
    job=start(client,book,pages,skip=(2,4));finish(app,job)
    assert len(calls)==2 and vi.calls==2
    saved=client.get(f"/api/books/{book['id']}/pages").json()
    assert [p['number'] for p in saved if p['target_text']]==[1,3]
    assert all(p['ocr_skip'] for p in saved if p['number'] in (2,4))
    app.state.ocr_jobs.close()


def test_partial_language_streams_and_editing_while_ocr_does_not_fail_or_overwrite(tmp_path):
    app,client,book,pages,calls,vi,_=workspace(tmp_path,count=1,vi=LocalVI(block=True))
    job=start(client,book,pages)
    try:
        assert vi.entered.wait(10)
        current=client.get(f"/api/books/{book['id']}/pages").json()[0]
        assert current['source_text']=='天地\n玄黃' and current['target_text']==''
        edited=client.patch(f"/api/pages/{pages[0]['id']}",json={'source_text':'Nôm đã sửa','target_text':'Quốc ngữ đang tự nhập'}).json()
        assert edited['source_text']=='Nôm đã sửa'
    finally:vi.release.set()
    finish(app,job)
    saved=client.get(f"/api/books/{book['id']}/pages").json()[0]
    assert saved['source_text']=='Nôm đã sửa' and saved['target_text']=='Quốc ngữ đang tự nhập'
    app.state.ocr_jobs.close()


def test_excluding_queued_page_during_ocr_is_respected(tmp_path):
    app,client,book,pages,calls,vi,_=workspace(tmp_path,count=2,vi=LocalVI(block=True))
    job=start(client,book,pages)
    try:
        assert vi.entered.wait(10)
        assert client.put(f"/api/books/{book['id']}/plan",json={'pages':[{'page_id':pages[1]['id'],'category':'ref','ocr_skip':True}]}).status_code==200
    finally:vi.release.set()
    finish(app,job)
    assert len(calls)==1 and vi.calls==1
    assert app.state.ocr_jobs.get(job['id'])['pages'][1]['status']=='skipped'
    app.state.ocr_jobs.close()


def test_txt_is_extracted_by_nom_line_count_and_cursor_survives_restart(tmp_path):
    txt='******* Page 01 *******\nMột\nHai\nBa\nBốn\nNăm\nSáu\n******* Page 04 *******\nBảy\nTám\n'
    app,client,book,pages,calls,vi,transport=workspace(tmp_path,txt=txt)
    job=start(client,book,pages,skip=(2,));finish(app,job)
    saved=client.get(f"/api/books/{book['id']}/pages").json()
    assert [p['target_text'] for p in saved]==['Một\nHai','','Ba\nBốn','Bảy\nTám']
    assert not vi.calls and len(calls)==3
    assert saved[0]['target_origin'].startswith('txt-draft:')
    app.state.ocr_jobs.close()
    with TestClient(create_app(tmp_path,ocr_config=KHNConfig(token='test-only'),ocr_transport=transport,vi_provider=vi)) as restarted:
        again=start(restarted,book,saved,skip=(2,))
        # No new OCR or TXT consumption: every filled language is durable.
        resumed=restarted.app.state.ocr_jobs
        resumed.futures[again['id']].result(timeout=20)
        assert len(calls)==3 and not vi.calls
        assert restarted.get(f"/api/books/{book['id']}/pages").json()[2]['target_text']=='Ba\nBốn'


def test_pause_and_restart_resume_only_unfinished_pages(tmp_path):
    app,client,book,pages,calls,vi,transport=workspace(tmp_path,count=2,vi=LocalVI(block=True))
    job=start(client,book,pages)
    try:
        assert vi.entered.wait(10)
        assert client.post(f"/api/ocr-jobs/{job['id']}/pause").status_code==200
    finally:vi.release.set()
    app.state.ocr_jobs.futures[job['id']].result(timeout=20)
    assert app.state.ocr_jobs.get(job['id'])['status']=='paused'
    app.state.ocr_jobs.close()
    with TestClient(create_app(tmp_path,ocr_config=KHNConfig(token='test-only'),ocr_transport=transport,vi_provider=vi)) as reopened:
        assert reopened.post(f"/api/ocr-jobs/{job['id']}/resume").status_code==200
        reopened.app.state.ocr_jobs.futures[job['id']].result(timeout=20)
        assert len(calls)==2 and vi.calls==2


def test_session_and_pair_result_files_are_updated_without_manual_export(tmp_path):
    app,client,book,pages,_,_,_=workspace(tmp_path,count=1)
    id=book['id'];page=pages[0]
    assert client.put(f'/api/books/{id}/plan',json={'pages':[{'page_id':page['id'],'category':'ch'}]}).status_code==200
    state={'page_id':page['id'],'view':'alignment','alignment_page':page['id']}
    assert client.put(f'/api/books/{id}/session',json=state).status_code==200
    rows=[{'id':'one','sentence_id':book['name']+'.001.1','source':'天地','target':'Thiên địa','reviewed':True}]
    assert client.put(f'/api/books/{id}/alignments',json={'rows':rows}).status_code==200
    folder=tmp_path/'backend/data/output_alignment'/id
    summary=json.loads((folder/'summary.json').read_text(encoding='utf-8'))
    assert summary['pairs']==1 and summary['reviewed_pairs']==1
    assert len(list(csv.reader((folder/'pairs.csv').read_text(encoding='utf-8-sig').splitlines())))==2
    assert 'save_alignments' in (folder/'events.jsonl').read_text(encoding='utf-8')
    app.state.ocr_jobs.close()
    with TestClient(create_app(tmp_path)) as reopened:
        assert reopened.get('/api/workspace').json()['resume']['page_id']==page['id']
        assert reopened.get(f'/api/books/{id}/session').json()['view']=='alignment'


def test_invalid_plan_is_atomic_and_autosave_does_not_erase_other_language(tmp_path):
    app,client,book,pages,_,_,_=workspace(tmp_path,count=1)
    id=pages[0]['id']
    assert client.patch(f'/api/pages/{id}',json={'source_text':'天地'}).status_code==200
    saved=client.patch(f'/api/pages/{id}',json={'target_text':'Thiên địa'}).json()
    assert saved['source_text']=='天地'
    response=client.put(f"/api/books/{book['id']}/plan",json={'pages':[{'page_id':id,'category':'ch'},{'page_id':'foreign','category':'blank'}]})
    assert response.status_code==422
    assert client.get(f"/api/books/{book['id']}/pages").json()[0]['category']=='misc'
    app.state.ocr_jobs.close()


def test_intentionally_cleared_edit_stays_empty_when_other_language_finishes(tmp_path):
    app,client,book,pages,_,vi,_=workspace(tmp_path,count=1,vi=LocalVI(block=True))
    job=start(client,book,pages)
    try:
        assert vi.entered.wait(10)
        assert client.patch(f"/api/pages/{pages[0]['id']}",json={'source_text':''}).status_code==200
    finally:vi.release.set()
    finish(app,job)
    saved=client.get(f"/api/books/{book['id']}/pages").json()[0]
    assert saved['source_text']=='' and saved['target_text']=='Thiên địa\nHuyền hoàng'
    app.state.ocr_jobs.close()


def test_transient_windows_snapshot_lock_does_not_break_job(tmp_path,monkeypatch):
    if os.name!='nt':
        return
    app,client,book,pages,_,_,_=workspace(tmp_path,count=1)
    original=os.replace
    locked=[]
    def temporarily_locked(source,target):
        if str(target).endswith('summary.json') and len(locked)<2:
            locked.append(1)
            raise PermissionError('Transient snapshot reader')
        return original(source,target)
    monkeypatch.setattr('backend.store.os.replace',temporarily_locked)
    job=start(client,book,pages);finish(app,job)
    assert len(locked)==2
    summary=json.loads((tmp_path/'backend/data/output_alignment'/book['id']/'summary.json').read_text(encoding='utf-8'))
    assert summary['job']['status']=='completed'
    app.state.ocr_jobs.close()
