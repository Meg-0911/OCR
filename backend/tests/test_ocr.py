import json

import httpx
import pymupdf
import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.ocr import KHNConfig, KimHanNomOCR, OCRError, normalize_result

TOKEN = 'test-secret-never-return'
POINTS = [[10, 10], [100, 10], [100, 50], [10, 50]]


def success(data):
    return httpx.Response(200, json={'is_success':True, 'code':'000000', 'message':None, 'data':data})


def client_with_page(tmp_path, handler, token=TOKEN):
    client = TestClient(create_app(tmp_path, ocr_config=KHNConfig(token=token), ocr_transport=httpx.MockTransport(handler)))
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
            'file_name':'temp.jpg', 'ocr_id':4, 'lang_type':1,
            'reading_direction':2, 'epitaph':0, 'tag':None,
        }
        return success({'result_ocr_text':['天地', '玄黃'], 'result_bbox':[POINTS, [[120, 10], [190, 10], [190, 50], [120, 50]]]})
    client, page = client_with_page(tmp_path, handler)
    url = f"/api/pages/{page['id']}"
    response = client.post(url + '/ocr', json={'version':page['version'], 'ocr_id':4, 'lang_type':1, 'reading_direction':2})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['text_lines'] == ['天地', '玄黃'] and len(result['boxes']) == 2
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
        assert client.post(url + '/ocr', json={'version':updated['version']}).status_code == 422
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


@pytest.mark.parametrize('error,expected', [(httpx.ReadTimeout('timeout'), 504), (httpx.ConnectError('offline'), 502)])
def test_network_failure_mapping(error, expected):
    def handler(request):
        raise error
    provider = KimHanNomOCR(KHNConfig(token=TOKEN), httpx.MockTransport(handler))
    with pytest.raises(OCRError) as raised:
        provider.recognize(b'jpeg')
    assert raised.value.status_code == expected


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
