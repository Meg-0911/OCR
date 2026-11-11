import csv
import json
import threading
import os

import httpx
import pymupdf
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.ocr import KHNConfig

VI_BOX={'id':'manual-vi','transcription':'Thiên địa',
        'points':[[40,150],[140,150],[140,180],[40,180]]}
HAN_BOX={'id':'manual-han','transcription':'天地',
         'points':[[10,20],[90,20],[90,60],[10,60]]}


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
        {'page_id':p['id'],'category':'both','ocr_skip':p['number'] in skip} for p in pages]})
    assert response.status_code==200,response.text
    return response.json()


def finish(app,job):
    app.state.ocr_jobs.futures[job['id']].result(timeout=20)
    result=app.state.ocr_jobs.get(job['id'])
    assert result['status']=='completed',result


def test_resume_rechecks_old_completed_checkpoints_but_never_confirmed_pages(tmp_path):
    app,client,book,pages,calls,vi,_=workspace(tmp_path,count=2)
    job=start(client,book,pages);finish(app,job)
    store=app.state.store
    with store.db() as db:
        for page in pages:
            cached=store.latest_ocr(page['id'])
            cached['language_settings']['han']['pipeline_version']='old-pipeline'
            cached['language_settings']['vi']['han_mask']['pipeline_version']='old-pipeline'
            db.execute('UPDATE ocr_results SET result=? WHERE id=?',(json.dumps(cached),cached['result_id']))
        db.execute("UPDATE pages SET status='done' WHERE id=?",(pages[0]['id'],))
        db.execute("UPDATE ocr_jobs SET status='paused' WHERE id=?",(job['id'],))
    resumed=client.post(f"/api/ocr-jobs/{job['id']}/resume").json()
    finish(app,resumed)
    assert len(calls)==3 and vi.calls==3
    assert store.page(pages[0]['id'])['status']=='done'
    app.state.ocr_jobs.close()


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


def test_uploaded_txt_is_reference_and_does_not_replace_ocr_or_geometry(tmp_path):
    app,client,book,pages,calls,vi,transport=workspace(tmp_path,count=2,txt='Legacy companion must not be used')
    url=f"/api/books/{book['id']}/text-sources"
    assert client.get(url).json()=={}
    assert client.get(f"/api/books/{book['id']}/reference").json() is None
    han={'filename':'arbitrary-nom.txt','text':'天地\n玄黃'}
    target={'filename':'arbitrary-translation.txt','text':'TXT reference text'}
    assert client.put(url+'/han',json=han).status_code==200
    assert client.put(url+'/vi',json=target).status_code==200
    job=start(client,book,pages);finish(app,job)
    saved=client.get(f"/api/books/{book['id']}/pages").json()
    assert all(p['target_text']=='Thiên địa\nHuyền hoàng' and len(p['boxes'])==2 and p['status']=='pending' for p in saved)
    assert len(calls)==2 and vi.calls==2
    app.state.ocr_jobs.close()
    with TestClient(create_app(tmp_path,ocr_config=KHNConfig(token='test-only'),ocr_transport=transport,vi_provider=vi)) as restarted:
        assert restarted.get(url).json()=={'han':han,'vi':target}
        assert restarted.get(f"/api/books/{book['id']}/reference").json()==target
        again=start(restarted,book,saved);finish(restarted.app,again)
        assert len(calls)==2 and vi.calls==2


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
    assert client.get(f"/api/books/{book['id']}/pages").json()[0]['category']=='both'
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


def test_shared_crop_page_override_and_skips_are_used_by_ocr(tmp_path):
    app,client,book,pages,calls,vi,_=workspace(tmp_path,count=3)
    base=f"/api/books/{book['id']}"
    assert all(p['category']=='both' and p['ocr_languages']==['han','vi'] and p['status']=='pending' for p in pages)
    assert client.put(base+'/layout',json={'source_regions':[[.5,.5,1,1]],'target_regions':[]}).status_code==200
    own=[[0,0,.5,.5]]
    first=client.patch(f"/api/pages/{pages[0]['id']}",json={'source_regions':own}).json()
    assert first['source_regions']==own
    assert client.patch(f"/api/pages/{pages[2]['id']}",json={'ocr_skip':True}).status_code==200
    job=client.post(base+'/workflow',json={}).json();finish(app,job)
    saved=client.get(base+'/pages').json()
    assert len(calls)==2 and vi.calls==2 and saved[2]['boxes']==[]
    assert saved[0]['boxes'][0]['points'][0]==[10,50]
    assert saved[1]['boxes'][0]['points'][0]==[160,275]
    confirmed=client.put(f"/api/pages/{saved[0]['id']}",json={'version':saved[0]['version'],'category':'both','boxes':saved[0]['boxes'],'vi_boxes':[VI_BOX],'done':True}).json()
    assert confirmed['status']=='done' and 'boxes' not in confirmed['edited_fields']
    assert client.patch(f"/api/pages/{first['id']}",json={'source_regions':[[0,0,2,1]]}).status_code==422
    reset=client.patch(f"/api/pages/{first['id']}",json={'source_regions':None}).json()
    assert reset['source_regions'] is None
    # Re-cropping refreshes automatic geometry while keeping the other page cached.
    job=client.post(base+'/workflow',json={}).json();finish(app,job)
    assert len(calls)==3
    assert client.get(base+'/pages').json()[0]['boxes'][0]['points'][0]==[160,275]
    app.state.ocr_jobs.close()


def test_language_tags_are_independent_of_special_page_category(tmp_path):
    app,client,book,pages,calls,vi,_=workspace(tmp_path,count=1)
    url=f"/api/pages/{pages[0]['id']}"
    page=client.patch(url,json={'category':'intro','ocr_languages':['vi']}).json()
    assert page['category']=='intro' and page['ocr_languages']==['vi']
    job=client.post(f"/api/books/{book['id']}/workflow",json={}).json();finish(app,job)
    assert not calls and vi.calls==1
    assert client.patch(url,json={'ocr_languages':[]}).status_code==422
    page=client.patch(url,json={'ocr_languages':['han','vi']}).json()
    assert page['category']=='intro'
    job=client.post(f"/api/books/{book['id']}/workflow",json={}).json();finish(app,job)
    assert len(calls)==1
    app.state.ocr_jobs.close()


def test_autosave_needs_confirmation_and_edits_invalidate_confirmation(tmp_path):
    app,client,book,pages,_,_,_=workspace(tmp_path,count=2)
    url=f"/api/pages/{pages[0]['id']}"
    draft=client.patch(url,json={'source_text':'天地'}).json()
    assert draft['status']=='pending' and client.get('/api/workspace').json()['books'][0]['done']==0
    saved=client.put(url,json={'version':draft['version'],'category':'ch','source_text':'天地','boxes':[HAN_BOX],'done':True}).json()
    assert saved['status']=='done'
    changed=client.patch(url,json={'source_text':'天地玄黃'}).json()
    assert changed['status']=='pending'
    skipped=client.patch(f"/api/pages/{pages[1]['id']}",json={'ocr_skip':True}).json()
    confirmed=client.put(f"/api/pages/{skipped['id']}",json={'version':skipped['version'],'category':'both','done':True})
    assert confirmed.status_code==200 and confirmed.json()['status']=='done'
    app.state.ocr_jobs.close()


def test_cannot_confirm_page_while_ocr_is_still_running(tmp_path):
    app,client,book,pages,_,vi,_=workspace(tmp_path,count=1,vi=LocalVI(block=True))
    job=start(client,book,pages)
    try:
        assert vi.entered.wait(10)
        page=client.get(f"/api/books/{book['id']}/pages").json()[0]
        response=client.put(f"/api/pages/{page['id']}",json={'version':page['version'],'category':'both','boxes':page['boxes'],'done':True})
        assert response.status_code==409
    finally:vi.release.set()
    finish(app,job)
    page=client.get(f"/api/books/{book['id']}/pages").json()[0]
    assert page['status']=='pending'
    assert client.put(f"/api/pages/{page['id']}",json={'version':page['version'],'category':'both','boxes':page['boxes'],'vi_boxes':[VI_BOX],'done':True}).json()['status']=='done'
    app.state.ocr_jobs.close()


def test_saved_reading_direction_is_used_by_whole_book_workflow(tmp_path):
    app,client,book,pages,calls,vi,transport=workspace(tmp_path,count=2)
    base=f"/api/books/{book['id']}"
    layout={'source_regions':[[.1,.1,.9,.9]],'target_regions':[],'reading_direction':2}
    assert client.put(base+'/layout',json=layout).json()==layout
    job=client.post(base+'/workflow',json={}).json();finish(app,job)
    for page in client.get(base+'/pages').json():
        result=client.get(f"/api/pages/{page['id']}/ocr").json()
        assert result['settings']['reading_direction']==2 and result['settings']['ocr_id']==1
        assert page['reading_direction']==2
    assert len(calls)==2 and vi.calls==2
    app.state.ocr_jobs.close()
    with TestClient(create_app(tmp_path,ocr_config=KHNConfig(token='test-only'),ocr_transport=transport,vi_provider=vi)) as reopened:
        assert reopened.get(base+'/layout').json()==layout


def test_horizontal_default_and_vertical_page_override(tmp_path):
    app,client,book,pages,_,_,_=workspace(tmp_path,count=2)
    first=client.patch(f"/api/pages/{pages[0]['id']}",json={'reading_direction_override':1})
    assert first.status_code==200
    assert first.json()['reading_direction_override']==1
    job=client.post(f"/api/books/{book['id']}/workflow",json={}).json()
    finish(app,job)
    results=[client.get(f"/api/pages/{page['id']}/ocr").json() for page in pages]
    assert [result['settings']['reading_direction'] for result in results]==[1,2]
    current=client.get(f"/api/books/{book['id']}/pages").json()[0]
    confirmed=client.put(f"/api/pages/{current['id']}",json={
        'version':current['version'],'category':'ch','done':True,'boxes':current['boxes'],
    })
    assert confirmed.status_code==200
    assert confirmed.json()['reading_direction']==1
    client.put(f"/api/books/{book['id']}/layout",json={
        'source_regions':[],'target_regions':[],'reading_direction':1,
    })
    inherited=client.get(f"/api/books/{book['id']}/pages").json()[0]
    assert inherited['status']=='done' and inherited['version']==confirmed.json()['version']
    client.put(f"/api/books/{book['id']}/layout",json={
        'source_regions':[],'target_regions':[],'reading_direction':2,
    })
    reset=client.patch(f"/api/pages/{pages[0]['id']}",json={'reading_direction_override':None})
    assert reset.status_code==200
    assert reset.json()['reading_direction_override'] is None
    assert reset.json()['reading_direction']==2
    app.state.ocr_jobs.close()


def test_confirmed_pages_stay_complete_and_are_excluded_from_new_ocr_jobs(tmp_path):
    app,client,book,pages,calls,vi,transport=workspace(tmp_path,count=2)
    base=f"/api/books/{book['id']}"
    job=start(client,book,pages);finish(app,job)
    saved=client.get(base+'/pages').json()
    first=saved[0]
    complete=client.put(f"/api/pages/{first['id']}",json={'version':first['version'],'category':'both','boxes':first['boxes'],'vi_boxes':[VI_BOX],'done':True}).json()
    assert complete['status']=='done'
    state={'view':'review','page_id':first['id'],'workflow_step':4}
    assert client.put(base+'/session',json=state).status_code==200
    assert client.get('/api/workspace').json()['books'][0]['done']==1
    # Even different OCR settings only queue the unfinished page.
    next_job=client.post(base+'/workflow',json={'reading_direction':1}).json();finish(app,next_job)
    assert [p['page_id'] for p in next_job['pages']]==[saved[1]['id']]
    assert len(calls)==3
    still_complete=client.get(base+'/pages').json()[0]
    assert still_complete['status']=='done' and still_complete['version']==complete['version']
    result=client.get(f"/api/pages/{first['id']}/ocr").json()
    app.state.store.apply_ocr_texts({**result,'text_lines':['late OCR must not overwrite confirmation']})
    assert client.get(base+'/pages').json()[0]==still_complete
    app.state.ocr_jobs.close()
    with TestClient(create_app(tmp_path,ocr_config=KHNConfig(token='test-only'),ocr_transport=transport,vi_provider=vi)) as reopened:
        assert reopened.get(base+'/session').json()['workflow_step']==4
        remaining=[p for p in reopened.get(base+'/pages').json() if p['status']!='done']
        assert [p['id'] for p in remaining]==[saved[1]['id']]
        last=remaining[0]
        assert reopened.put(f"/api/pages/{last['id']}",json={'version':last['version'],'category':'both','boxes':last['boxes'],'vi_boxes':[VI_BOX],'done':True}).json()['status']=='done'
        summary=reopened.get('/api/workspace').json()['books'][0]
        assert summary['done']==summary['pages']==2
        assert reopened.post(base+'/workflow',json={}).status_code==409
        assert len(calls)==3


def test_pause_between_languages_keeps_han_checkpoint_and_resumes_vi_only(tmp_path):
    app,client,book,pages,calls,vi,_=workspace(tmp_path,count=1)
    entered,release=threading.Event(),threading.Event()
    # Block only the first remote recognition while the user requests pause.
    def handler(request):
        if request.url.path.endswith('image-upload'):
            data={'file_name':'page.jpg'}
        else:
            calls.append(1);entered.set();assert release.wait(10)
            data={'result_ocr_text':['天地'],'result_bbox':[[[10,50],[100,50],[100,70],[10,70]]]}
        return httpx.Response(200,json={'is_success':True,'code':'000000','data':data})
    app.state.ocr_jobs.close()

    app=create_app(tmp_path,ocr_config=KHNConfig(token='test-only'),ocr_transport=httpx.MockTransport(handler),vi_provider=vi)
    client=TestClient(app)
    job=start(client,book,pages)
    try:
        assert entered.wait(10)
        assert client.post(f"/api/ocr-jobs/{job['id']}/pause").json()['status']=='pausing'
    finally:release.set()
    app.state.ocr_jobs.futures[job['id']].result(timeout=20)
    assert app.state.ocr_jobs.get(job['id'])['status']=='paused'
    assert len(calls)==1 and vi.calls==0
    current=client.get(f"/api/books/{book['id']}/pages").json()[0]
    assert current['source_text']=='天地' and current['target_text']=='' and current['status']=='pending'
    assert client.post(f"/api/ocr-jobs/{job['id']}/resume").status_code==200
    finish(app,job)
    assert len(calls)==1 and vi.calls==1
    app.state.ocr_jobs.close()



def test_shared_reading_area_uses_tags_without_language_region_selection(tmp_path):
    app,client,book,pages,calls,vi,_=workspace(tmp_path,count=3)
    base=f"/api/books/{book['id']}"
    common=[[.2,.2,.9,.9]]
    private=[[0,0,.5,.5]]
    assert client.put(base+'/layout',json={'source_regions':common,'target_regions':common}).status_code==200
    # A page cropped separately is an exception to the shared PDF template.
    assert client.patch(f"/api/pages/{pages[0]['id']}",json={'source_regions':private}).status_code==200
    assert client.patch(f"/api/pages/{pages[1]['id']}",json={'ocr_skip':True}).status_code==200
    options={'shared_reading_area':True,'reading_direction':2}
    job=client.post(base+'/workflow',json=options).json();finish(app,job)
    assert len(calls)==2 and vi.calls==2
    for page,expected in ((pages[0],private),(pages[2],common)):
        result=client.get(f"/api/pages/{page['id']}/ocr").json()
        assert result['settings']['source_regions']==result['settings']['target_regions']==expected
    # Identical shared regions and overrides still hit the durable checkpoints.
    again=client.post(base+'/workflow',json=options).json();finish(app,again)
    assert len(calls)==2 and vi.calls==2
    # Language tags decide the engine; there is no second region-language choice.
    assert client.patch(f"/api/pages/{pages[2]['id']}",json={'ocr_languages':['vi']}).status_code==200
    result=client.post(base+'/workflow',json=options).json();finish(app,result)
    assert len(calls)==2 and vi.calls==3
    app.state.ocr_jobs.close()
