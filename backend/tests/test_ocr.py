import json

import httpx
import pymupdf
import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.ocr import KHNConfig, KimHanNomOCR, OCRError, normalize_result
from backend.han_ocr import HanFallbackConfig, PPOCRv5

TOKEN = 'test-secret-never-return'
POINTS = [[10, 10], [100, 10], [100, 50], [10, 50]]


def success(data):
    return httpx.Response(200, json={'is_success':True, 'code':'000000', 'message':None, 'data':data})


def client_with_page(tmp_path, handler, token=TOKEN, fallback=None):
    client = TestClient(create_app(tmp_path, ocr_config=KHNConfig(token=token), ocr_transport=httpx.MockTransport(handler), han_fallback_provider=fallback))
    with pymupdf.open() as document:
        document.new_page(width=200, height=200)
        book = client.post('/api/books/upload', files={'file':('OCR.pdf', document.tobytes(), 'application/pdf')}).json()
    page = client.get(f"/api/books/{book['id']}/pages").json()[0]
    page = client.put(f"/api/pages/{page['id']}", json={
        'boxes':[], 'done':False, 'category':'ch', 'version':page['version'],
    }).json()
    return client, page


def test_env_loading_and_secret_stays_private(tmp_path, monkeypatch):
    monkeypatch.delenv('KHN_token', raising=False)
    env = tmp_path / '.env'
    env.write_text('KHN_token="Bearer local-secret"\nKHN_TIMEOUT_SECONDS=45\n', encoding='utf-8')
    config = KHNConfig.from_env(env)
    assert config.token == 'local-secret' and config.timeout == 45
    assert 'local-secret' not in repr(config)
    monkeypatch.setenv('KHN_token', 'environment-secret')
    assert KHNConfig.from_env(env).token == 'environment-secret'


@pytest.mark.parametrize('setting', ['KHN_TIMEOUT_SECONDS=nan', 'KHN_TIMEOUT_SECONDS=-1', 'KHN_BASE_URL=http://example.com', 'KHN_USER_AGENT=python-requests/2'])
def test_invalid_configuration_is_rejected(tmp_path, setting):
    env = tmp_path / '.env'
    env.write_text(setting, encoding='utf-8')
    with pytest.raises(ValueError):
        KHNConfig.from_env(env)


def test_ocr_upload_recognize_preview_save_and_horizontal_label_order(tmp_path):
    calls = []
    def handler(request):
        calls.append(request)
        assert request.headers['authorization'] == f'Bearer {TOKEN}'
        assert not request.headers['user-agent'].startswith('python-requests')
        if request.url.path.endswith('/image-upload'):
            assert 'multipart/form-data' in request.headers['content-type']
            assert b'name="image_file"' in request.content and b'\xff\xd8' in request.content
            return success({'file_name':'temp.jpg'})
        assert json.loads(request.content) == {
            'file_name':'temp.jpg', 'ocr_id':1, 'lang_type':1,
            'reading_direction':2, 'epitaph':0, 'tag':None, 'font_type':0,
        }
        return success({'result_ocr_text':['天地', '玄黃'], 'result_bbox':[POINTS, [[120, 10], [190, 10], [190, 50], [120, 50]]]})
    client, page = client_with_page(tmp_path, handler)
    url = f"/api/pages/{page['id']}"
    response = client.post(url + '/ocr', json={'version':page['version'], 'ocr_id':4, 'lang_type':1, 'reading_direction':2})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['text_lines'] == ['\u5929\u5730\u7384\u9ec3'] and len(result['boxes']) == 2
    assert len(calls) == 2 and TOKEN not in response.text
    saved = client.get(f"/api/books/{page['book_id']}/pages").json()[0]
    assert saved == page  # Recognition is a preview, never an automatic edit.
    files = list((tmp_path / 'backend/data/.workspace/ocr' / page['id']).glob('*.json'))
    assert len(files) == 1 and TOKEN not in files[0].read_text(encoding='utf-8')
    assert client.put(url, json={
        'version':page['version'], 'category':'ch', 'done':False,
        'boxes':result['boxes'], 'reading_direction':result['reading_direction'],
    }).status_code == 200
    label = tmp_path / 'backend/data/.workspace/books' / page['book_id'] / 'ch/Label.txt'
    boxes = json.loads(label.read_text(encoding='utf-8').split('\t', 1)[1])
    assert [b['transcription'] for b in boxes] == ['天地', '玄黃']
    restarted = TestClient(create_app(tmp_path, ocr_config=KHNConfig()))
    assert restarted.get(f"/api/books/{page['book_id']}/pages").json()[0]['reading_direction'] == 2
    assert TOKEN not in client.get('/api/workspace').text
    assert client.get('/api/health').json()['ocr'] == 'configured'


def test_page_rerun_reuses_saved_ocr_id_instead_of_normalizing_it(tmp_path):
    calls = []
    def handler(request):
        if request.url.path.endswith('/image-upload'):
            return success({'file_name':'temp.jpg'})
        calls.append(json.loads(request.content))
        return success({'result_ocr_text':['天地'], 'result_bbox':[POINTS]})

    client, page = client_with_page(tmp_path, handler)
    app = client.app
    url = f"/api/pages/{page['id']}/ocr"
    initial = client.post(url, json={'version':page['version']}).json()
    initial['settings']['ocr_id'] = 4
    with app.state.store.db() as db:
        db.execute('UPDATE ocr_results SET result=?,settings=? WHERE id=?', (
            json.dumps(initial,ensure_ascii=False),
            json.dumps(initial['settings']),
            initial['result_id'],
        ))

    rerun = client.post(url, json={
        'version':page['version'],'force':True,'reuse_saved_settings':True,'ocr_id':1,
    })

    assert rerun.status_code == 200, rerun.text
    assert calls == [
        {'file_name':'temp.jpg','ocr_id':1,'lang_type':2,'reading_direction':2,'epitaph':0,'tag':None,'font_type':0},
        {'file_name':'temp.jpg','ocr_id':4,'lang_type':2,'reading_direction':2,'epitaph':0,'tag':None,'font_type':0},
    ]


def test_text_only_does_not_invent_boxes():
    result = normalize_result({'result_ocr_text':['天地'], 'result_bbox':[]}, 200, 200)
    assert result['boxes'] == [] and result['text_lines'] == ['天地'] and result['warnings']


@pytest.mark.parametrize('points', [
    [[0, 0]] * 4, [[-1, 0], [10, 0], [10, 10], [0, 10]],
    [[0, 0], [999, 0], [999, 10], [0, 10]],
    [[0, 0], [10, 10], [10, 0], [0, 10]],
    [[0, 0], [10, 0], [float('nan'), 10], [0, 10]],
    [1, 2, 3, 4], None,
])
def test_invalid_provider_regions_are_not_applied(points):
    result = normalize_result({'result_ocr_text':['天地'], 'result_bbox':[points]}, 200, 200)
    assert result['boxes'] == [] and result['warnings']


@pytest.mark.parametrize('ocr_id',[1,2])
def test_han_box_ocr_reuses_model_id_from_page_ocr(tmp_path,ocr_id):
    requests=[]
    def handler(request):
        if request.url.path.endswith('/image-upload'):
            return success({'file_name':'box.jpg'})
        requests.append(json.loads(request.content))
        return success({'result_ocr_text':['漢'],'result_bbox':[]})

    client,page=client_with_page(tmp_path,handler)
    initial=client.post(f"/api/pages/{page['id']}/ocr",json={
        'version':page['version'],'ocr_id':ocr_id,'reading_direction':2,
    })
    assert initial.status_code==200,initial.text
    response=client.post(f"/api/pages/{page['id']}/ocr-region",json={
        'box':{'id':'box-1','transcription':'字','points':POINTS},
        'language':'han','reading_direction':2,
    })

    assert response.status_code==200,response.text
    assert response.json()['text']=='漢'
    assert [request['ocr_id'] for request in requests]==[ocr_id,ocr_id]


def test_missing_token_unclassified_and_stale_requests_do_not_call_provider(tmp_path):
    def handler(request):
        pytest.fail('Provider must not be called')
    client, page = client_with_page(tmp_path, handler, token='')
    url = f"/api/pages/{page['id']}"
    assert client.post(url + '/ocr', json={'version':page['version']}).status_code == 503
    assert client.post('/api/pages/missing/ocr', json={'version':0}).status_code == 404
    assert client.post(url + '/ocr', json={'version':page['version'] + 1}).status_code == 409
    assert client.post(url + '/ocr', json={'version':page['version'], 'ocr_id':99}).status_code == 422
    for category in ('vi', 'misc', 'blank'):
        updated = client.put(url, json={'version':page['version'], 'category':category, 'boxes':[], 'done':False}).json()
        assert client.post(url + '/ocr', json={'version':updated['version']}).status_code == (422 if category=='blank' else 503)
        page = updated


@pytest.mark.parametrize('status,payload,expected', [
    (401, {}, 502), (403, {}, 502), (429, {}, 429), (500, {}, 502),
    (200, {'is_success':False, 'code':'123', 'message':{'text':TOKEN}}, 502),
    (200, {'is_success':True, 'code':'000000', 'data':None}, 502),
    (200, {'is_success':True, 'code':'000000', 'data':{}}, 502),
])
def test_upstream_errors_are_sanitized(tmp_path, status, payload, expected):
    client, page = client_with_page(tmp_path, lambda request: httpx.Response(status, json=payload))
    response = client.post(f"/api/pages/{page['id']}/ocr", json={'version':page['version']})
    assert response.status_code == expected and TOKEN not in response.text
    assert client.get(f"/api/books/{page['book_id']}/pages").json()[0] == page


@pytest.mark.parametrize('error,expected,message', [
    (httpx.ReadTimeout('timeout'), 504, 'xử lý quá thời gian'),
    (httpx.ConnectError('offline'), 502, 'chứng chỉ HTTPS'),
])
def test_network_failure_mapping(error, expected, message):
    def handler(request):
        raise error
    provider = KimHanNomOCR(KHNConfig(token=TOKEN), httpx.MockTransport(handler))
    with pytest.raises(OCRError) as raised:
        provider.recognize(b'jpeg')
    assert raised.value.status_code == expected and message in str(raised.value)


def test_malformed_json_is_handled():
    provider = KimHanNomOCR(KHNConfig(token=TOKEN), httpx.MockTransport(lambda request: httpx.Response(200, text='<html>proxy error</html>')))
    with pytest.raises(OCRError, match='JSON'):
        provider.recognize(b'jpeg')


def test_concurrent_edit_during_ocr_keeps_result_and_returns_conflict(tmp_path):
    def handler(request):
        if request.url.path.endswith('/image-upload'):
            return success({'file_name':'temp.jpg'})
        assert client.put(f"/api/pages/{page['id']}", json={'version':page['version'], 'category':'ch', 'boxes':[], 'done':False}).status_code == 200
        return success({'result_ocr_text':['天地'], 'result_bbox':[POINTS]})
    client, page = client_with_page(tmp_path, handler)
    response = client.post(f"/api/pages/{page['id']}/ocr", json={'version':page['version']})
    assert response.status_code == 409
    assert len(list((tmp_path / 'backend/data/.workspace/ocr' / page['id']).glob('*.json'))) == 1


def test_invalid_ocr_response_is_archived_without_changing_page(tmp_path):
    def handler(request):
        if request.url.path.endswith('/image-upload'):
            return success({'file_name':'temp.jpg'})
        return success({'result_ocr_text':{'invalid':'shape'}, 'result_bbox':[]})
    client, page = client_with_page(tmp_path, handler)
    response = client.post(f"/api/pages/{page['id']}/ocr", json={'version':page['version']})
    assert response.status_code == 502
    assert len(list((tmp_path / 'backend/data/.workspace/ocr' / page['id']).glob('*.json'))) == 1
    assert client.get(f"/api/books/{page['book_id']}/pages").json()[0] == page


class FakeHanFallback:
    ready = True

    def __init__(self):
        self.calls = []

    def status(self):
        return {'provider':'ppocrv5_cpu', 'ready':True, 'device':'cpu', 'setup':'test'}

    def recognize(self, image, **kwargs):
        self.calls.append((image, kwargs))
        return {'result_ocr_text':['天地'], 'result_bbox':[[[1,1],[40,1],[40,20],[1,20]]],
                'provider':'ppocrv5_cpu'}


@pytest.mark.parametrize('primary_response', [
    httpx.Response(502),
    success({'result_ocr_text':[], 'result_bbox':[]}),
    success({'result_ocr_text':{'bad':'shape'}, 'result_bbox':[]}),
])
def test_han_fallback_keeps_page_boxes_and_checkpoint(tmp_path, primary_response):
    fallback = FakeHanFallback()
    def handler(request):
        return success({'file_name':'image.jpg'}) if request.url.path.endswith('image-upload') else primary_response
    client, page = client_with_page(tmp_path, handler, fallback=fallback)
    response = client.post(f"/api/pages/{page['id']}/ocr", json={'version':page['version']})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['text_lines'] == ['天地'] and len(result['boxes']) == 1
    assert any('PP-OCRv5 CPU' in warning for warning in result['warnings'])
    assert len(fallback.calls) == 1
    archive = next((tmp_path / 'backend/data/.workspace/ocr' / page['id']).glob('*.json'))
    assert json.loads(archive.read_text(encoding='utf-8'))['response']['provider'] == 'ppocrv5_cpu'


def test_han_fallback_without_token_and_region_ocr(tmp_path):
    fallback = FakeHanFallback()
    def handler(_request):
        pytest.fail('Kim Han Nom must not be called without a token')
    client, page = client_with_page(tmp_path, handler, token='', fallback=fallback)
    assert client.get('/api/workspace').json()['ocr_ready'] is True
    assert client.post(f"/api/pages/{page['id']}/ocr", json={'version':page['version']}).status_code == 200
    region = client.post(f"/api/pages/{page['id']}/ocr-region", json={
        'language':'han', 'reading_direction':2,
        'box':{'id':'selected', 'transcription':'', 'points':[[10,10],[100,10],[100,50],[10,50]]},
    })
    assert region.status_code == 200, region.text
    assert region.json()['text'] == '天地'
    assert len(fallback.calls) == 2


def test_han_fallback_without_token_runs_book_job(tmp_path):
    fallback = FakeHanFallback()
    client, page = client_with_page(tmp_path, lambda _request: pytest.fail('Kim Han Nom must not be called'),
                                    token='', fallback=fallback)
    with client:
        response = client.post(f"/api/books/{page['book_id']}/ocr-job", json={'include_unclassified':True})
        assert response.status_code == 200, response.text
        job = response.json()
        client.app.state.ocr_jobs.futures[job['id']].result(timeout=15)
        assert client.get(f"/api/books/{page['book_id']}/ocr-job").json()['status'] == 'completed'
        assert len(fallback.calls) == 1


def test_primary_han_result_does_not_call_fallback(tmp_path):
    fallback = FakeHanFallback()
    def handler(request):
        return success({'file_name':'image.jpg'}) if request.url.path.endswith('image-upload') else success({
            'result_ocr_text':['漢字'], 'result_bbox':[POINTS]})
    client, page = client_with_page(tmp_path, handler, fallback=fallback)
    response = client.post(f"/api/pages/{page['id']}/ocr", json={'version':page['version']})
    assert response.status_code == 200 and response.json()['text_lines'] == ['漢字']
    assert fallback.calls == []


def test_ppocrv5_cpu_adapter_maps_polygons_to_existing_contract(monkeypatch):
    from PIL import Image
    from io import BytesIO
    monkeypatch.setattr(PPOCRv5, 'ready', property(lambda self: True))
    provider = PPOCRv5(HanFallbackConfig())
    class Engine:
        def predict(self, image):
            assert image.shape == (60, 100, 3)
            return [type('Prediction', (), {'json': {'res': {
                'rec_texts':['天地', ''],
                'rec_polys':[[[1,1],[40,1],[40,20],[1,20]], [[45,1],[70,1],[70,20],[45,20]]],
            }}})()]
    provider._engine = Engine()
    buffer = BytesIO()
    Image.new('RGB', (100, 60), 'white').save(buffer, format='JPEG')
    raw = provider.recognize(buffer.getvalue())
    assert raw['provider'] == 'ppocrv5_cpu'
    assert normalize_result(raw, 100, 60)['text_lines'] == ['天地']
