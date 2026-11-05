import io
import json
import zipfile
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.app import create_app
from backend.colab_exchange import export_bundle, import_bundle, SCHEMA
from backend.store import Store


@pytest.fixture
def exchange(tmp_path):
    store = Store(tmp_path)
    with store.db() as db:
        db.execute('INSERT INTO books VALUES (?,?,?,?,?,?)', ('book', 'Book', 'Book.pdf', None, 0, 'now'))
        for i in (1, 2):
            db.execute('INSERT INTO pages (id,book_id,number,category,width,height,boxes) VALUES (?,?,?,?,?,?,?)',
                       (str(i), 'book', i, 'both', 200, 300,
                        json.dumps([{'id': 'han', 'transcription': '天', 'points': [[1,1],[10,1],[10,20],[1,20]]}])))
    image = tmp_path / 'page.jpg'
    Image.new('RGB', (400, 600), 'white').save(image)
    bundle = export_bundle(store, 'book', lambda p: image, lambda p: {
        'mode': 'vi', 'target_regions': [[0,0,1,1]], 'ink_profile': 'blue_qn_red_han',
    })
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        manifest = json.loads(archive.read('manifest.json'))
    return store, manifest


def test_export_bundle_includes_ink_profile_for_colab_worker(exchange):
    _, manifest = exchange
    assert all(page['settings']['ink_profile'] == 'blue_qn_red_han' for page in manifest['pages'])


def results(manifest):
    payload = {'schema': SCHEMA, 'bundle_id': manifest['bundle_id'], 'pages': []}
    for entry in manifest['pages']:
        payload['pages'].append({'page_id': entry['page_id'], 'sha256': entry['sha256'], 'boxes': [
            {'transcription': 'Thiên địa', 'points': [[20,40],[200,40],[200,80],[20,80]]}]})
    return payload


def pack(payload):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('results.json', json.dumps(payload))
    return stream.getvalue()


def test_roundtrip_scales_coordinates_and_keeps_han_pending(exchange):
    store, manifest = exchange
    before = store.page('1')['boxes']
    report = import_bundle(store, 'book', pack(results(manifest)))
    page = store.page('1')
    assert report['imported'] == 2
    assert page['boxes'] == before
    assert page['vi_boxes'][0]['points'] == [[10,20],[100,20],[100,40],[10,40]]
    assert page['status'] == 'pending' and page['version'] == 1
    assert page['target_text'] == 'Thiên địa'
    assert store.latest_ocr('1')['vi_boxes'] == page['vi_boxes']
    labels = (store.book_dir('book') / 'vi/Label.txt').read_text(encoding='utf-8')
    assert 'Thiên địa' in labels and '天' not in labels
    with pytest.raises(ValueError, match='thay đổi'):
        import_bundle(store, 'book', pack(results(manifest)))


def test_modified_second_page_rejects_entire_import(exchange):
    store, manifest = exchange
    with store.db() as db:
        db.execute("UPDATE pages SET version=version+1,target_text='Manual edit' WHERE id='2'")
    with pytest.raises(ValueError, match='thay đổi'):
        import_bundle(store, 'book', pack(results(manifest)))
    assert store.page('1')['target_text'] == ''
    assert store.latest_ocr('1') is None


@pytest.mark.parametrize('mutation', ['hash', 'bounds', 'duplicate', 'empty', 'nonfinite'])
def test_reject_bad_results_before_writing(exchange, mutation):
    store, manifest = exchange
    payload = results(manifest)
    record = payload['pages'][0]
    if mutation == 'hash':
        record['sha256'] = 'wrong'
    elif mutation == 'bounds':
        record['boxes'][0]['points'][0][0] = 9999
    elif mutation == 'nonfinite':
        record['boxes'][0]['points'][0][0] = float('nan')
    elif mutation == 'empty':
        record['boxes'] = []
    else:
        payload['pages'].append(record)
    with pytest.raises(ValueError):
        import_bundle(store, 'book', pack(payload))
    assert store.page('1')['version'] == 0


def test_export_skips_done_skip_and_han_only(exchange):
    store, _ = exchange
    with store.db() as db:
        db.execute("UPDATE pages SET status='done' WHERE id='1'")
        db.execute("UPDATE pages SET ocr_languages='[\"han\"]' WHERE id='2'")
    with pytest.raises(ValueError, match='Không có trang'):
        export_bundle(store, 'book', lambda p: None, lambda p: {})


def test_routes_render_bundle_and_import_vietnamese(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        with pymupdf.open() as doc:
            doc.new_page(width=200, height=300)
            uploaded = client.post('/api/books/upload', files={'file': ('Book.pdf', doc.tobytes(), 'application/pdf')})
        assert uploaded.status_code == 201
        book = uploaded.json()
        page = client.get(f"/api/books/{book['id']}/pages").json()[0]
        response = client.patch('/api/pages/' + page['id'], json={'category': 'vi'})
        assert response.status_code == 200
        layout=client.get(f"/api/books/{book['id']}/layout").json()
        layout['ink_profile']='blue_qn_red_han'
        assert client.put(f"/api/books/{book['id']}/layout",json=layout).status_code==200
        exported = client.get(f"/api/books/{book['id']}/colab-bundle")
        assert exported.status_code == 200, exported.text
        with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
            manifest = json.loads(archive.read('manifest.json'))
        assert manifest['pages'][0]['settings']['ink_profile']=='blue_qn_red_han'
        source=client.get('/api/colab/source')
        assert source.status_code==200
        with zipfile.ZipFile(io.BytesIO(source.content)) as archive:
            assert 'backend/ink_colors.py' in archive.namelist()
            assert not any(name.endswith('.env') for name in archive.namelist())
        response = client.post(f"/api/books/{book['id']}/colab-results", files={'file': ('results.zip', pack(results(manifest)), 'application/zip')})
        assert response.status_code == 200, response.text
        updated = app.state.store.page(page['id'])
        assert updated['target_text'] == 'Thiên địa'


def test_cuda_sessions_require_cuda_not_silent_fallback(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    from backend import vietocr
    for filename in ('encoder_fp16.onnx', 'decoder_fp16.onnx', 'vocab.txt'):
        (tmp_path / filename).write_text('test')
    monkeypatch.setattr(vietocr, 'FILES', {})
    class Options:
        pass
    fake = SimpleNamespace(SessionOptions=Options, get_available_providers=lambda: ['CPUExecutionProvider'])
    monkeypatch.setitem(sys.modules, 'onnxruntime', fake)
    with pytest.raises(RuntimeError, match='CUDAExecutionProvider unavailable'):
        vietocr.LineRecognizer(tmp_path, 1, 'cuda')
    fake.get_available_providers = lambda: ['CUDAExecutionProvider', 'CPUExecutionProvider']
    fake.InferenceSession = lambda *a, **k: SimpleNamespace(get_providers=lambda: ['CPUExecutionProvider'])
    with pytest.raises(RuntimeError, match='refusing silent CPU fallback'):
        vietocr.LineRecognizer(tmp_path, 1, 'cuda')
