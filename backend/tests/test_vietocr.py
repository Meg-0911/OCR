import io

from PIL import Image, ImageDraw
import pytest

from backend.ocr import OCRError
from backend.vietocr import VietOCR, line_regions
from backend.vietnamese_ocr import create_vietnamese_ocr


def two_lines(color):
    picture = Image.new('RGB', (600, 260), 'white')
    pen = ImageDraw.Draw(picture)
    for y in (60, 170):
        for x in range(70, 440, 25):
            pen.rectangle((x, y, x + 12, y + 17), fill=color)
    return picture


def test_find_colored_handwriting_without_including_black_han_row():
    picture = two_lines((160, 80, 90))
    ImageDraw.Draw(picture).rectangle((60, 24, 500, 43), fill='black')
    rectangles, colored = line_regions(picture)
    assert colored and len(rectangles) == 2
    assert all(top > 43 for left, top, right, bottom in rectangles)


def test_black_lines_use_han_mask_but_keep_unmasked_qn():
    picture = two_lines('black')
    mask = [{'transcription': '天地', 'points': [[0, 40], [600, 40], [600, 90], [0, 90]]}]
    rectangles, colored = line_regions(picture, mask)
    assert not colored and len(rectangles) == 1
    assert rectangles[0][1] > 90


def test_recognizer_uses_rgb_crops_and_maps_template_coordinates(tmp_path, monkeypatch):
    provider = VietOCR(tmp_path)
    monkeypatch.setattr(provider, 'status', lambda: {'ready': True})
    seen = []

    class Recognizer:
        def predict(self, picture):
            seen.append(picture)
            return 'Thiên địa huyền hoàng.', 88, True

    provider.model = Recognizer()
    picture = two_lines((160, 80, 90))
    content = io.BytesIO()
    picture.save(content, format='PNG')
    result = provider.recognize(content.getvalue(), regions=[[0, .5, 1, 1]])
    assert len(result['boxes']) == 1
    box = result['boxes'][0]
    assert box['transcription'] == 'Thiên địa huyền hoàng.'
    assert 150 < box['points'][0][1] < 175
    assert all(0 <= x <= 600 and 130 <= y <= 260 for x, y in box['points'])
    assert seen[0].mode == 'RGB'
    assert (160, 80, 90) in seen[0].get_flattened_data()


def test_empty_detection_uses_tesseract_when_available(tmp_path, monkeypatch):
    provider = VietOCR(tmp_path)
    monkeypatch.setattr(provider, 'status', lambda: {'ready': True})
    provider.model = object()
    monkeypatch.setattr(provider.fallback, 'status', lambda: {'ready': True})
    monkeypatch.setattr(provider.fallback, 'recognize', lambda *a, **kw: {'boxes': [], 'text_lines': ['Chữ in'], 'warnings': []})
    content = io.BytesIO()
    Image.new('RGB', (400, 300), 'white').save(content, format='PNG')
    result = provider.recognize(content.getvalue())
    assert result['text_lines'] == ['Chữ in']
    assert any('dự phòng' in warning for warning in result['warnings'])


def test_unfinished_line_is_rejected_instead_of_silently_saving_truncated_text(tmp_path, monkeypatch):
    provider = VietOCR(tmp_path)
    monkeypatch.setattr(provider, 'status', lambda: {'ready': True})

    class Recognizer:
        def predict(self, picture):
            return 'Nội dung chưa đầy đủ', 70, False

    provider.model = Recognizer()
    content = io.BytesIO()
    two_lines((160, 80, 90)).save(content, format='PNG')
    with pytest.raises(OCRError, match='quá dài'):
        provider.recognize(content.getvalue())


def test_long_line_retries_as_two_crops(tmp_path, monkeypatch):
    provider = VietOCR(tmp_path)
    monkeypatch.setattr(provider, 'status', lambda: {'ready': True})
    monkeypatch.setattr('backend.vietocr.line_regions', lambda image, han_boxes: ([(0, 0, 400, 40)], False))
    widths = []

    class Recognizer:
        def predict(self, picture):
            widths.append(picture.width)
            return ('Nội dung bị cắt', 60, False) if picture.width == 400 else ('Nửa dòng', 85, True)

    provider.model = Recognizer()
    content = io.BytesIO()
    Image.new('RGB', (400, 40), 'white').save(content, format='PNG')
    result = provider.recognize(content.getvalue())
    assert result['text_lines'] == ['Nửa dòng Nửa dòng']
    assert widths == [400, 200, 200]


def test_vietocr_is_default_and_reports_missing_setup_without_network(tmp_path, monkeypatch):
    monkeypatch.delenv('VI_OCR_PROVIDER', raising=False)
    provider = create_vietnamese_ocr(tmp_path)
    assert isinstance(provider, VietOCR)
    assert not provider.status()['ready']
    assert not provider.status()['external']
