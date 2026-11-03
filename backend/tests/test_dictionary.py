import io
import json
import zipfile

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.dictionary import Dictionary, VERSION
from backend.ocr import KHNConfig
from backend.setup_dictionary import build_database


def install_dictionary(folder):
    folder.mkdir(parents=True,exist_ok=True)
    content=io.BytesIO()
    with zipfile.ZipFile(content,'w') as archive:
        archive.writestr('Unihan_Readings.txt', 'U+6F22\tkDefinition\tChinese people\nU+6F22\tkVietnamese\thán\nU+6C49\tkDefinition\tChinese people\nU+2029B\tkVietnamese\tngười\n')
        archive.writestr('Unihan_Variants.txt', 'U+6F22\tkSimplifiedVariant\tU+6C49\nU+6C49\tkTraditionalVariant\tU+6F22\n')
    return build_database(content.getvalue(),folder/f'Unihan-{VERSION}.sqlite3')


def test_installer_lookup_meaning_reading_variants_and_search(tmp_path):
    folder=tmp_path/'backend/data/dictionaries'
    assert install_dictionary(folder)==3
    client=TestClient(create_app(tmp_path,ocr_config=KHNConfig()))
    assert client.get('/api/dictionary/status').json()['ready'] is True
    result=client.get('/api/dictionary/lookup',params={'character':'漢'}).json()
    assert result['entry']['character']=='漢' and result['entry']['definitions']==['Chinese people']
    assert result['entry']['readings']==['hán'] and result['fallback'] is True
    assert result['entry']['variants'][0]['character']=='汉'
    assert client.get('/api/dictionary/search',params={'q':'hán'}).json()[0]['character']=='漢'
    assert client.get('/api/dictionary/search',params={'q':"%' OR 1=1 --"}).json()==[]
    reverse=client.get('/api/dictionary/reverse',params={'q':'hán người'}).json()
    assert [group['syllable'] for group in reverse]==['hán','người']
    assert [entry['character'] for entry in reverse[0]['entries']]==['漢']
    assert [entry['character'] for entry in reverse[1]['entries']]==['𠊛']
    supplementary=client.get('/api/dictionary/lookup',params={'character':'𠊛'}).json()
    assert supplementary['entry']['codepoint']=='U+2029B'
    assert supplementary['entry']['readings']==['người']


def test_nom_overlay_is_preferred_and_missing_entry_is_not_called_a_spelling_error(tmp_path):
    install_dictionary(tmp_path)
    (tmp_path/'nom.json').write_text(json.dumps([{'character':'𠊛','readings':['người'],'definitions':['Con người'],'source':'Tài liệu của nhóm','variants':['人']}],ensure_ascii=False),encoding='utf-8')
    dictionary=Dictionary(tmp_path)
    entry=dictionary.lookup('𠊛')
    assert entry['entry']['language']=='vi' and entry['entry']['definitions']==['Con người']
    assert entry['fallback'] is False
    assert dictionary.lookup('龍')['found'] is False
    assert dictionary.lookup('龍')['notice']


def test_dictionary_without_data_and_invalid_inputs(tmp_path):
    client=TestClient(create_app(tmp_path,ocr_config=KHNConfig()))
    assert client.get('/api/dictionary/status').json()['ready'] is False
    assert client.get('/api/dictionary/lookup',params={'character':'漢'}).json()['found'] is False
    for char in ('','漢字','A','<script>'):
        assert client.get('/api/dictionary/lookup',params={'character':char}).status_code==422
    assert client.get('/api/dictionary/search',params={'q':''}).status_code==422
    assert client.get('/api/dictionary/reverse',params={'q':'!!!'}).status_code==422
    assert client.get('/api/dictionary/reverse',params={'q':'a '*13}).status_code==422


def test_invalid_nom_file_is_reported_without_crashing(tmp_path):
    folder=tmp_path/'backend/data/dictionaries'
    folder.mkdir(parents=True)
    (folder/'nom.json').write_text('[{"character":"漢","definitions":[{}]}]',encoding='utf-8')
    client=TestClient(create_app(tmp_path,ocr_config=KHNConfig()))
    assert client.get('/api/dictionary/lookup',params={'character':'漢'}).status_code==422
