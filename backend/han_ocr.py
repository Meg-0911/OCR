"""CPU-only PP-OCRv5 fallback for the Kim Han Nom OCR adapter."""
import importlib.util
import io
import os
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from dotenv import dotenv_values
from PIL import Image

from .ocr import OCRError, normalize_result


@dataclass(frozen=True)
class HanFallbackConfig:
    enabled: bool = True
    threads: int = 4

    @classmethod
    def from_env(cls, env_file: Path):
        values = {key.upper(): value for key, value in dotenv_values(env_file, interpolate=False).items()}
        values.update({key.upper(): value for key, value in os.environ.items()})
        provider = (values.get('HAN_OCR_FALLBACK') or 'ppocrv5').strip().lower()
        if provider not in ('ppocrv5', 'off'):
            raise ValueError('HAN_OCR_FALLBACK phải là ppocrv5 hoặc off.')
        try:
            threads = int(values.get('HAN_OCR_THREADS') or '4')
            if not 1 <= threads <= 32:
                raise ValueError
        except ValueError:
            raise ValueError('HAN_OCR_THREADS phải là số nguyên từ 1 đến 32.') from None
        return cls(provider == 'ppocrv5', threads)


class PPOCRv5:
    def __init__(self, config: HanFallbackConfig):
        self.config = config
        self._engine = None
        self._lock = threading.RLock()

    @property
    def ready(self):
        return self.config.enabled and importlib.util.find_spec('paddleocr') is not None and importlib.util.find_spec('paddle') is not None

    def status(self):
        return {'provider': 'ppocrv5_cpu', 'ready': self.ready, 'device': 'cpu',
                'setup': 'python -m pip install -r backend/requirements-han-fallback.txt'}

    def recognize(self, image: bytes, **_kwargs):
        if not self.ready:
            raise OCRError('Chưa cài PP-OCRv5 CPU. Cài backend/requirements-han-fallback.txt rồi khởi động lại.', 503)
        with self._lock:
            try:
                if self._engine is None:
                    from paddleocr import PaddleOCR
                    self._engine = PaddleOCR(
                        text_detection_model_name='PP-OCRv5_mobile_det',
                        text_recognition_model_name='PP-OCRv5_server_rec',
                        device='cpu', cpu_threads=self.config.threads,
                        use_doc_orientation_classify=False,
                        use_doc_unwarping=False,
                        use_textline_orientation=False,
                    )
                picture = np.asarray(Image.open(io.BytesIO(image)).convert('RGB'))
                predictions = self._engine.predict(picture)
            except Exception as error:
                raise OCRError('PP-OCRv5 CPU không chạy được. Kiểm tra cài đặt PaddleOCR và model.') from error
        texts, polygons = [], []
        for prediction in predictions:
            data = prediction.json
            if not isinstance(data, dict):
                raise OCRError('PP-OCRv5 trả dữ liệu không hợp lệ.')
            data = data.get('res', data)
            if not isinstance(data, dict):
                raise OCRError('PP-OCRv5 trả dữ liệu không hợp lệ.')
            rec_texts, rec_polys = data.get('rec_texts'), data.get('rec_polys')
            if not isinstance(rec_texts, list) or not isinstance(rec_polys, list) or len(rec_texts) != len(rec_polys):
                raise OCRError('PP-OCRv5 trả chữ và box không khớp.')
            for text, polygon in zip(rec_texts, rec_polys):
                if not isinstance(text, str) or not isinstance(polygon, list):
                    raise OCRError('PP-OCRv5 trả chữ hoặc box không hợp lệ.')
                if text.strip():
                    texts.append(text)
                    polygons.append(polygon)
        return {'result_ocr_text': texts, 'result_bbox': polygons, 'provider': 'ppocrv5_cpu'}


class HanOCRWithFallback:
    """Present the same recognize interface as KimHanNomOCR to every caller."""
    def __init__(self, primary, fallback):
        self.primary = primary
        self.fallback = fallback

    @property
    def ready(self):
        return self.primary.config.ready or self.fallback.ready

    def recognize(self, image: bytes, **kwargs):
        primary_error = None
        raw = None
        if self.primary.config.ready:
            try:
                raw = self.primary.recognize(image, **kwargs)
                with Image.open(io.BytesIO(image)) as picture:
                    result = normalize_result(raw, *picture.size)
                if any(line.strip() for line in result['text_lines']) or any(box['transcription'].strip() for box in result['boxes']):
                    return raw
                primary_error = OCRError('Kim Hán Nôm không tìm thấy chữ.')
            except OCRError as error:
                primary_error = error
        else:
            primary_error = OCRError('Thiếu KHN_token và PP-OCRv5 CPU chưa sẵn sàng. Cài backend/requirements-han-fallback.txt hoặc cấu hình token.', 503)
        if not self.fallback.ready:
            if raw is not None:
                return raw  # Preserve the original checkpoint/validation path without a backup.
            raise primary_error
        raw = self.fallback.recognize(image, **kwargs)
        with Image.open(io.BytesIO(image)) as picture:
            result = normalize_result(raw, *picture.size)
        if not (any(line.strip() for line in result['text_lines']) or any(box['transcription'].strip() for box in result['boxes'])):
            raise OCRError('Cả Kim Hán Nôm và PP-OCRv5 đều không đọc được chữ trong ảnh.')
        return raw
