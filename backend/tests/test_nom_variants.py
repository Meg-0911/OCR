import json

import httpx

from backend.nom_dictionary import DETAIL_VERSION, NomDictionary


def test_variants_upgrade_old_cache_and_keep_images_separate(tmp_path, monkeypatch):
    dictionary = NomDictionary(tmp_path)
    folder = tmp_path / 'nomnaviet-details'
    folder.mkdir()
    path = folder / '7d50.json'
    path.write_text(json.dumps({'character': '結', 'meanings': [], 'examples': []}), encoding='utf8')
    requested = []
    def get(url, **kwargs):
        requested.append(url)
        data = {'character': '結', 'nomVariants': ['𡨸', '𡨸', '結'], 'simplifiedForm': '结',
                'traditionalForm': None, 'meanings': [{'source': 'Nôm'}]}
        if url.endswith('/variants'):
            data = {'variants': [{'id': 'one', 'scriptType': 'seal', 'imagePath': 'abc.png'},
                                 {'id': 'bad', 'scriptType': 'seal', 'imagePath': '../bad.png'}]}
        return httpx.Response(200, json={'success': True, 'data': data}, request=httpx.Request('GET', url))
    monkeypatch.setattr(httpx, 'get', get)
    result = dictionary.detail('結')
    assert [(v['character'], v['kind']) for v in result['variants']] == [('𡨸', 'Dị thể Nôm'), ('结', 'Giản thể')]
    assert len(result['historical_forms']) == 1
    assert result['historical_forms'][0]['image_url'] == 'https://api.nomnaviet.com/api/dictionary/glyph/abc.png'
    assert result['cache_version'] == DETAIL_VERSION
    assert len(requested) == 2
    assert dictionary.detail('結') == result
    assert len(requested) == 2


def test_optional_variant_failure_preserves_meaning_and_retries(tmp_path, monkeypatch):
    dictionary = NomDictionary(tmp_path)
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        if url.endswith('/variants'):
            raise httpx.ConnectError('offline')
        return httpx.Response(200, json={'success': True, 'data': {'nomVariants': ['𡨸'],
            'meanings': [{'definition': 'nghĩa đã có'}]}}, request=httpx.Request('GET', url))
    monkeypatch.setattr(httpx, 'get', get)
    result = dictionary.detail('字')
    assert result['variants_notice'] and result['variants'][0]['character'] == '𡨸'
    assert result['meanings'][0]['definition'] == 'nghĩa đã có'
    assert 'cache_version' not in result
    dictionary.detail('字')
    assert len(calls) == 4
    monkeypatch.setattr(httpx, 'get', lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError('offline')))
    offline = dictionary.detail('字')
    assert offline['variants'] == result['variants'] and offline['meanings'] == result['meanings']


def test_no_variants_is_successfully_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(httpx, 'get', lambda url, **k: httpx.Response(200,
        json={'success': True, 'data': {'variants': []} if url.endswith('/variants') else {}},
        request=httpx.Request('GET', url)))
    result = NomDictionary(tmp_path).detail('𤾓')
    assert result['variants'] == result['historical_forms'] == []
    assert 'variants_notice' not in result and result['cache_version'] == DETAIL_VERSION
