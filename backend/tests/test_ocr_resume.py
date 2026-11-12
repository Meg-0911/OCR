import json
import threading

import httpx
import pymupdf
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.ocr import KHNConfig


def response(data):
    return httpx.Response(200,json={'is_success':True,'code':'000000','data':data})


def write_book(root):
    folder=root/'backend/data/raw_data'
    folder.mkdir(parents=True)
    with pymupdf.open() as document:
        for _ in range(3):
            document.new_page(width=200,height=300)
        document.save(folder/'Book.pdf')


def ocr_response():
    return response({'result_ocr_text':['天地'], 'result_bbox':[[[10,10],[100,10],[100,40],[10,40]]]})


def test_saved_ocr_is_restored_without_resending_after_restart(tmp_path):
    write_book(tmp_path)
    calls=[]
    def handler(request):
        calls.append(request.url.path)
        return response({'file_name':'image.jpg'}) if request.url.path.endswith('image-upload') else ocr_response()
    with TestClient(create_app(tmp_path,ocr_config=KHNConfig(token='secret'),ocr_transport=httpx.MockTransport(handler))) as client:
        book=client.get('/api/workspace').json()['books'][0]
        page=client.get(f"/api/books/{book['id']}/pages").json()[0]
        page=client.put(f"/api/pages/{page['id']}",json={'version':0,'boxes':[],'category':'ch'}).json()
        url=f"/api/pages/{page['id']}/ocr"
        first=client.post(url,json={'version':page['version']}).json()
        second=client.post(url,json={'version':page['version']}).json()
        assert second['cached'] and second['result_id']==first['result_id'] and len(calls)==2
        edited=client.put(f"/api/pages/{page['id']}",json={'version':page['version'],'category':'ch','boxes':first['boxes']}).json()
        after_edit=client.post(url,json={'version':edited['version']}).json()
        assert after_edit['cached'] and after_edit['result_id']==first['result_id'] and len(calls)==2
        page=edited
    with TestClient(create_app(tmp_path,ocr_config=KHNConfig())) as restarted:
        restored=restarted.get(url).json()
        assert restored['boxes']==first['boxes']
        assert restarted.post(url,json={'version':page['version']}).json()['cached']
        assert len(calls)==2


def test_book_job_continues_after_page_failure_and_retries_only_failed_page(tmp_path):
    write_book(tmp_path)
    count=0
    def handler(request):
        nonlocal count
        if request.url.path.endswith('image-upload'):
            return response({'file_name':'image.jpg'})
        count+=1
        return httpx.Response(429) if count==2 else ocr_response()
    app=create_app(tmp_path,ocr_config=KHNConfig(token='secret'),ocr_transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        book=client.get('/api/workspace').json()['books'][0]
        job=client.post(f"/api/books/{book['id']}/ocr-job",json={'include_unclassified':True}).json()
        app.state.ocr_jobs.futures[job['id']].result(timeout=10)
        failed=client.get(f"/api/books/{book['id']}/ocr-job").json()
        assert failed['status']=='failed' and failed['completed']==2 and failed['processed']==3
        assert [item['status'] for item in failed['pages']]==['succeeded','failed','succeeded']
    resumed_calls=[]
    def resumed_handler(request):
        if request.url.path.endswith('image-upload'):
            return response({'file_name':'image.jpg'})
        resumed_calls.append(1)
        return ocr_response()
    app=create_app(tmp_path,ocr_config=KHNConfig(token='secret'),ocr_transport=httpx.MockTransport(resumed_handler))
    with TestClient(app) as client:
        assert client.get(f"/api/books/{book['id']}/ocr-job").json()['status']=='failed'
        assert not resumed_calls  # Never restart paid/external work automatically.
        assert client.post(f"/api/ocr-jobs/{job['id']}/resume").status_code==200
        app.state.ocr_jobs.futures[job['id']].result(timeout=10)
        completed=client.get(f"/api/books/{book['id']}/ocr-job").json()
        assert completed['status']=='completed' and completed['completed']==3
        assert len(resumed_calls)==1
        pages=client.get(f"/api/books/{book['id']}/pages").json()
        assert all(p['boxes'] and p['status']=='pending' for p in pages)
        assert all(client.get(f"/api/pages/{p['id']}/ocr").json()['text_lines']==['天地'] for p in pages)


def test_book_job_continues_when_primary_and_fallback_both_fail(tmp_path):
    write_book(tmp_path)
    calls=[]

    class EmptyFallback:
        ready=True

        def status(self):
            return {'ready':True, 'provider':'ppocrv5_cpu', 'device':'cpu', 'setup':''}

        def recognize(self, image, **kwargs):
            return {'result_ocr_text':[], 'result_bbox':[], 'provider':'ppocrv5_cpu'}

    def handler(request):
        if request.url.path.endswith('image-upload'):
            return response({'file_name':'image.jpg'})
        calls.append(1)
        return httpx.Response(502) if len(calls)==2 else ocr_response()

    app=create_app(tmp_path,ocr_config=KHNConfig(token='secret'),
                   ocr_transport=httpx.MockTransport(handler),han_fallback_provider=EmptyFallback())
    with TestClient(app) as client:
        book=client.get('/api/workspace').json()['books'][0]
        job=client.post(f"/api/books/{book['id']}/ocr-job",json={'include_unclassified':True}).json()
        app.state.ocr_jobs.futures[job['id']].result(timeout=10)
        finished=client.get(f"/api/books/{book['id']}/ocr-job").json()
        assert len(calls)==3
        assert finished['processed']==3 and finished['completed']==2
        assert [item['status'] for item in finished['pages']]==['succeeded','failed','succeeded']
        assert finished['pages'][1]['error']
        assert finished['status']=='failed'


def test_pause_waits_for_inflight_page_and_new_jobs_are_serialized(tmp_path):
    write_book(tmp_path)
    entered,release=threading.Event(),threading.Event()
    calls=[]
    def handler(request):
        if request.url.path.endswith('image-upload'):
            return response({'file_name':'image.jpg'})
        calls.append(1)
        if len(calls)==1:
            entered.set()
            assert release.wait(5)
        return ocr_response()
    app=create_app(tmp_path,ocr_config=KHNConfig(token='secret'),ocr_transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        book=client.get('/api/workspace').json()['books'][0]
        job=client.post(f"/api/books/{book['id']}/ocr-job",json={'include_unclassified':True}).json()
        assert entered.wait(3)
        assert client.post(f"/api/books/{book['id']}/ocr-job",json={}).status_code==409
        assert client.post(f"/api/ocr-jobs/{job['id']}/pause").json()['status']=='pausing'
        release.set()
        app.state.ocr_jobs.futures[job['id']].result(timeout=10)
        assert client.get(f"/api/books/{book['id']}/ocr-job").json()['status']=='paused'
        assert len(calls)==1
        client.post(f"/api/ocr-jobs/{job['id']}/resume")
        app.state.ocr_jobs.futures[job['id']].result(timeout=10)
        assert len(calls)==3


def test_restart_pauses_incomplete_job_without_any_network_call(tmp_path):
    write_book(tmp_path)
    app=create_app(tmp_path,ocr_config=KHNConfig())
    book=app.state.store.books()[0]
    page=app.state.store.pages(book['id'])[0]
    with app.state.store.db() as db:
        db.execute('INSERT INTO ocr_jobs VALUES (?,?,?,?,?,?)',('crash',book['id'],'running','{}',None,'2026'))
        db.execute('INSERT INTO ocr_job_pages VALUES (?,?,?,NULL)',('crash',page['id'],'running'))
    app.state.ocr_jobs.close()
    with TestClient(create_app(tmp_path,ocr_config=KHNConfig())) as client:
        job=client.get(f"/api/books/{book['id']}/ocr-job").json()
        assert job['status']=='paused' and job['pages'][0]['status']=='pending'


def test_batch_skips_existing_edits_and_ocr_results(tmp_path):
    write_book(tmp_path)
    calls=[]
    def handler(request):
        if request.url.path.endswith('image-upload'):
            return response({'file_name':'image.jpg'})
        calls.append(1)
        return ocr_response()
    app=create_app(tmp_path,ocr_config=KHNConfig(token='secret'),ocr_transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        book=client.get('/api/workspace').json()['books'][0]
        pages=client.get(f"/api/books/{book['id']}/pages").json()
        first=client.put(f"/api/pages/{pages[0]['id']}",json={'version':0,'category':'ch','boxes':[]}).json()
        original=client.post(f"/api/pages/{first['id']}/ocr",json={'version':first['version']}).json()
        edited=client.put(f"/api/pages/{pages[1]['id']}",json={'version':0,'category':'ch','boxes':[{'id':'manual','transcription':'Đã sửa','points':[[1,1],[20,1],[20,20],[1,20]]}]}).json()
        job=client.post(f"/api/books/{book['id']}/ocr-job",json={'include_unclassified':True}).json()
        app.state.ocr_jobs.futures[job['id']].result(timeout=10)
        completed=client.get(f"/api/books/{book['id']}/ocr-job").json()
        assert len(calls)==2  # One manual OCR, one new page in the batch.
        assert [p['status'] for p in completed['pages']]==['skipped','skipped','succeeded']
        assert client.get(f"/api/pages/{first['id']}/ocr").json()['result_id']==original['result_id']
        assert client.get(f"/api/books/{book['id']}/pages").json()[1]==edited


def test_explicit_force_keeps_previous_result_history(tmp_path):
    write_book(tmp_path)
    def handler(request):
        return response({'file_name':'image.jpg'}) if request.url.path.endswith('image-upload') else ocr_response()
    app=create_app(tmp_path,ocr_config=KHNConfig(token='secret'),ocr_transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        book=client.get('/api/workspace').json()['books'][0]
        page=client.get(f"/api/books/{book['id']}/pages").json()[0]
        page=client.put(f"/api/pages/{page['id']}",json={'version':0,'category':'ch','boxes':[]}).json()
        url=f"/api/pages/{page['id']}/ocr"
        first=client.post(url,json={'version':page['version']}).json()
        second=client.post(url,json={'version':page['version'],'force':True}).json()
        assert first['result_id']!=second['result_id']
        with app.state.store.db() as db:
            assert db.execute('SELECT COUNT(*) FROM ocr_results WHERE page_id=?',(page['id'],)).fetchone()[0]==2
        assert client.get(url).json()['result_id']==second['result_id']
