import json
import io
import zipfile
import httpx
import pymupdf
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.ocr import KHNConfig, OCRError
from backend.vietnamese_ocr import create_vietnamese_ocr, parse_tsv, clean_boxes


def success(data):
    return httpx.Response(200,json={'is_success':True,'code':'000000','data':data})


class LocalVI:
    def __init__(self,fail=False):
        self.calls=0
        self.fail=fail
        self.regions=[]
    def status(self):
        return {'ready':True,'engine':'test-vie','setup':''}
    def recognize(self,image,**settings):
        self.calls+=1
        self.regions.append(settings.get('regions'))
        if self.fail:
            raise OCRError('Tạm lỗi Quốc ngữ',502)
        return {'boxes':[], 'text_lines':['Thiên địa huyền hoàng.'],'warnings':[]}


def setup(tmp_path,vi=None):
    folder=tmp_path/'backend/data/raw_data'; folder.mkdir(parents=True)
    with pymupdf.open() as document:
        document.new_page(width=200,height=300)
        document.save(folder/'Bilingual.pdf')
    calls=[]
    def handler(request):
        if request.url.path.endswith('/image-upload'):
            return success({'file_name':'page.jpg'})
        calls.append(1)
        return success({'result_ocr_text':['天地玄黃'],'result_bbox':[[[10,10],[30,10],[30,30],[10,30]]]})
    app=create_app(tmp_path,ocr_config=KHNConfig(token='test-secret'),ocr_transport=httpx.MockTransport(handler),vi_provider=vi or LocalVI())
    client=TestClient(app)
    book=client.get('/api/workspace').json()['books'][0]
    page=client.get(f"/api/books/{book['id']}/pages").json()[0]
    return app,client,book,page,calls


def test_text_only_bilingual_page_can_be_saved_completed_and_restored(tmp_path):
    app,client,book,page,_=setup(tmp_path)
    url=f"/api/pages/{page['id']}"
    result=client.put(url,json={'version':0,'category':'ch','done':True,'source_text':'天地','target_text':'Thiên địa'}).json()
    assert result['status']=='done' and result['boxes']==[] and result['vi_boxes']==[]
    assert result['source_text']=='天地' and result['target_text']=='Thiên địa'
    with zipfile.ZipFile(io.BytesIO(client.get(f"/api/books/{book['id']}/export?format=labels").content)) as archive:
        exported=json.loads(archive.read(f"{book['name']}/page_texts.json"))
        assert exported[0]['source_text']=='天地' and exported[0]['target_text']=='Thiên địa'
    # Older clients omitting the new text fields never erase saved text.
    result=client.put(url,json={'version':result['version'],'category':'ch','boxes':[]}).json()
    assert result['source_text']=='天地' and result['target_text']=='Thiên địa'
    app.state.ocr_jobs.close()
    with TestClient(create_app(tmp_path,ocr_config=KHNConfig())) as restarted:
        page=restarted.get(f"/api/books/{book['id']}/pages").json()[0]
        assert page['source_text']=='天地' and page['target_text']=='Thiên địa'
        text_file=tmp_path/'backend/data/.workspace/books'/book['id']/'page_texts.json'
        assert json.loads(text_file.read_text(encoding='utf-8'))[0]['target_text']=='Thiên địa'


def test_bilingual_ocr_works_on_one_unclassified_page_and_no_vi_boxes_required(tmp_path):
    app,client,_,page,calls=setup(tmp_path)
    result=client.post(f"/api/pages/{page['id']}/ocr",json={'version':0,'mode':'bilingual'}).json()
    assert result['completed_languages']==['han','vi']
    assert result['text_lines']==['天地玄黃'] and result['vi_text_lines']==['Thiên địa huyền hoàng.']
    assert result['vi_boxes']==[] and len(calls)==1
    app.state.ocr_jobs.close()


def test_partial_language_checkpoint_does_not_resend_han_when_vi_retries(tmp_path):
    vi=LocalVI(fail=True)
    app,client,_,page,calls=setup(tmp_path,vi)
    url=f"/api/pages/{page['id']}/ocr"
    assert client.post(url,json={'version':0,'mode':'bilingual'}).status_code==502
    partial=client.get(url).json()
    assert partial['completed_languages']==['han'] and len(calls)==1
    vi.fail=False
    completed=client.post(url,json={'version':0,'mode':'bilingual'}).json()
    assert completed['completed_languages']==['han','vi'] and len(calls)==1 and vi.calls==2
    app.state.ocr_jobs.close()


def test_book_template_crops_han_maps_coordinates_and_applies_text_without_boxes(tmp_path):
    vi=LocalVI()
    app,client,book,page,calls=setup(tmp_path,vi)
    layout={'source_regions':[[.5,.5,1,1]],'target_regions':[[0,.25,1,.5]]}
    assert client.put(f"/api/books/{book['id']}/layout",json=layout).status_code==200
    assert client.get(f"/api/books/{book['id']}/layout").json()==layout
    job=client.post(f"/api/books/{book['id']}/ocr-job",json={'mode':'bilingual','include_unclassified':True}).json()
    app.state.ocr_jobs.futures[job['id']].result(timeout=10)
    finished=client.get(f"/api/books/{book['id']}/ocr-job").json()
    assert finished['status']=='completed',finished
    page=client.get(f"/api/books/{book['id']}/pages").json()[0]
    assert page['source_text']=='天地玄黃' and page['target_text']=='Thiên địa huyền hoàng.'
    assert page['boxes']==[] and page['status']=='pending'
    result=client.get(f"/api/pages/{page['id']}/ocr").json()
    assert result['boxes'][0]['points'][0]==[160,235]
    assert vi.regions==[[[0,.25,1,.5]]]
    invalid=client.put(f"/api/books/{book['id']}/layout",json={'source_regions':[[0,0,1.1,1]]})
    assert invalid.status_code==422
    app.state.ocr_jobs.close()


def test_old_han_only_result_does_not_skip_needed_vietnamese_in_new_job(tmp_path):
    vi=LocalVI()
    app,client,book,page,calls=setup(tmp_path,vi)
    page=client.put(f"/api/pages/{page['id']}",json={'version':0,'category':'ch','boxes':[]}).json()
    assert client.post(f"/api/pages/{page['id']}/ocr",json={'version':page['version'],'mode':'han'}).status_code==200
    job=client.post(f"/api/books/{book['id']}/ocr-job",json={'mode':'bilingual'}).json()
    app.state.ocr_jobs.futures[job['id']].result(timeout=10)
    assert len(calls)==1 and vi.calls==1
    assert client.get(f"/api/books/{book['id']}/ocr-job").json()['status']=='completed'
    app.state.ocr_jobs.close()


def test_vietnamese_only_does_not_require_khn_token(tmp_path):
    app,client,book,page,calls=setup(tmp_path)
    app.state.ocr_jobs.close()
    with TestClient(create_app(tmp_path,ocr_config=KHNConfig(),vi_provider=LocalVI())) as local:
        response=local.post(f"/api/pages/{page['id']}/ocr",json={'version':0,'mode':'vi'})
        assert response.status_code==200 and response.json()['completed_languages']==['vi']
    assert not calls




def test_page_header_is_not_counted_as_vietnamese_body():
    boxes=[{'transcription':'Part 1, page 3','points':[[0,0],[10,0],[10,10],[0,10]]},
           {'transcription':'Image ID: 123','points':[[0,20],[10,20],[10,30],[0,30]]},
           {'transcription':'Thiên địa','points':[[0,40],[30,40],[30,50],[0,50]]}]
    assert [b['transcription'] for b in clean_boxes(boxes,100,100)]==['Thiên địa']


def test_empty_vi_result_is_not_marked_complete_and_han_checkpoint_survives(tmp_path):
    class EmptyVI(LocalVI):
        def recognize(self,image,**settings):
            return {'boxes':[],'text_lines':[],'warnings':['Không đọc được chữ viết tay.']}
    app,client,_,page,calls=setup(tmp_path,EmptyVI())
    url=f"/api/pages/{page['id']}/ocr"
    response=client.post(url,json={'version':0,'mode':'bilingual'})
    assert response.status_code==502
    partial=client.get(url).json()
    assert partial['completed_languages']==['han'] and partial['vi_text_lines']==[]
    assert partial['text_lines']==['天地玄黃'] and len(calls)==1
    app.state.ocr_jobs.close()


def test_previously_reviewed_han_only_page_can_add_vi_without_overwriting_edits(tmp_path):
    app,client,book,page,calls=setup(tmp_path)
    page=client.put(f"/api/pages/{page['id']}",json={'version':0,'category':'ch','source_text':'Nôm đã hiệu đính','target_text':'','done':True}).json()
    job=client.post(f"/api/books/{book['id']}/ocr-job",json={'mode':'bilingual'}).json()
    app.state.ocr_jobs.futures[job['id']].result(timeout=10)
    updated=client.get(f"/api/books/{book['id']}/pages").json()[0]
    assert updated['source_text']=='Nôm đã hiệu đính' and updated['target_text']=='Thiên địa huyền hoàng.'
    assert updated['status']=='pending' and not calls
    app.state.ocr_jobs.close()


def test_legacy_cloud_setting_uses_only_local_provider(tmp_path,monkeypatch):
    monkeypatch.setenv('VI_OCR_PROVIDER','google_vision')
    provider=create_vietnamese_ocr(tmp_path)
    assert provider.__class__.__name__=='VietnameseOCR'
    assert not provider.status().get('external',False)


def test_changing_vi_model_keeps_han_checkpoint_and_rereads_only_vi(tmp_path):
    vi=LocalVI()
    app,client,_,page,calls=setup(tmp_path,vi)
    url=f"/api/pages/{page['id']}/ocr"
    payload={'version':0,'mode':'bilingual'}
    assert client.post(url,json=payload).status_code==200
    vi.status=lambda:{'ready':True,'engine':'test-vie','cache_key':'new-handwriting-model','setup':''}
    result=client.post(url,json=payload).json()
    assert result['completed_languages']==['han','vi']
    assert len(calls)==1 and vi.calls==2
    assert result['settings']['vi_engine']=='new-handwriting-model'
    app.state.ocr_jobs.close()
