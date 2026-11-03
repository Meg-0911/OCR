"""Local line detection and pinned ONNX handwriting recognition on the CPU."""
import hashlib
import importlib.util
import io
import os
import threading
from uuid import uuid4

from dotenv import dotenv_values
from PIL import Image, ImageDraw

from .dictionary import is_han
from .ocr import OCRError
from .setup_vietocr import FILES, REVISION
from .vietnamese_ocr import VietnameseOCR, clean_boxes, image_regions

ENGINE = 'VietOCR chữ viết tay · CPU'
CACHE_KEY = f'vietocr:{REVISION}:rgb-layout-1'


def line_regions(image, han_boxes=None):
    """Locate horizontal lines; colored ink helps separate QN from black Hán/Nôm."""
    import numpy as np

    pixels = np.asarray(image.convert('RGB'), dtype=np.int16)
    r, g, b = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
    red = (r - g > 22) & (r - b > 3) & (g < 205) & (r < 235) & ((b - g > -5) | (r - g > 55))
    # Use color only to locate rows. The recognizer always receives the original RGB pixels.
    colored = int(red.sum()) > max(100, image.width * image.height * .0003)
    if colored:
        mask = red
    else:
        prepared = image.copy()
        painter = ImageDraw.Draw(prepared)
        for box in han_boxes or []:
            if any(is_han(char) for char in box['transcription']):
                painter.polygon([tuple(point) for point in box['points']], fill='white')
        gray = np.asarray(prepared.convert('L'))
        threshold = min(180, max(65, float(np.percentile(gray, 10)) - 25))
        mask = gray < threshold
    counts = mask.sum(axis=1)
    active = np.flatnonzero(counts >= max(4, round(image.width * .006)))
    groups = []
    gap = max(4, round(image.height * .006))
    for y in active:
        if not groups or y - groups[-1][-1] > gap:
            groups.append([int(y)])
        else:
            groups[-1].append(int(y))
    rectangles = []
    padding = max(4, round(image.height * .005))
    for group in groups:
        top, bottom = group[0], group[-1] + 1
        ys, xs = np.where(mask[top:bottom])
        if len(xs) < 40 or bottom - top < 5 or xs.max() - xs.min() < max(25, image.width * .12):
            continue
        # A very tall block has not been separated into lines; never feed it as one line.
        if bottom - top > max(80, image.height * .14):
            continue
        rectangles.append((max(0, int(xs.min()) - padding), max(0, top - padding),
                           min(image.width, int(xs.max()) + padding + 1), min(image.height, bottom + padding)))
    return rectangles, colored


class LineRecognizer:
    def __init__(self, folder, threads):
        import numpy as np
        import onnxruntime as ort

        for filename, expected in FILES.items():
            if filename.endswith(('.onnx', '.txt')) and hashlib.sha256((folder / filename).read_bytes()).hexdigest() != expected:
                raise ValueError(f'Invalid model checksum: {filename}')
        self.np = np
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        self.encoder = ort.InferenceSession(str(folder / 'encoder_fp16.onnx'), sess_options=options, providers=['CPUExecutionProvider'])
        self.decoder = ort.InferenceSession(str(folder / 'decoder_fp16.onnx'), sess_options=options, providers=['CPUExecutionProvider'])
        self.vocab = (folder / 'vocab.txt').read_text(encoding='utf-8').splitlines()

    def predict(self, image):
        np = self.np
        image = image.convert('RGB')
        width = max(32, min(2048, round(32 * image.width / image.height)))
        inputs = (np.asarray(image.resize((width, 32), Image.Resampling.LANCZOS), dtype=np.float32) / 255).transpose(2, 0, 1)[None]
        encoder_input = self.encoder.get_inputs()[0]
        dtype = np.float16 if encoder_input.type == 'tensor(float16)' else np.float32
        memory = self.encoder.run(None, {encoder_input.name: inputs.astype(dtype)})[0]
        tokens, probabilities = [1], []
        ended = False
        for _ in range(128):
            values = {}
            for item in self.decoder.get_inputs():
                values[item.name] = (np.array([tokens], dtype=np.int64).T if 'int64' in item.type else
                                     memory.astype(np.float16 if item.type == 'tensor(float16)' else np.float32))
            logits = self.decoder.run(None, values)[0][0].astype(np.float64)
            token = int(logits.argmax())
            if token == 2:
                ended = True
                break
            scores = np.exp(logits - logits.max())
            probabilities.append(float(scores[token] / scores.sum()))
            tokens.append(token)
        text = ''.join(self.vocab[token] for token in tokens[1:] if 4 <= token < len(self.vocab)).strip()
        # This score is model probability, not a calibrated correctness estimate.
        return text, round(100 * float(np.mean(probabilities)) if probabilities else 0, 2), ended


class VietOCR:
    def __init__(self, root):
        self.folder = root / 'backend/.tools/vietocr'
        values = {**dotenv_values(root / 'backend/.env'), **os.environ}
        try:
            self.threads = max(1, min(8, int(values.get('VI_OCR_THREADS') or 4)))
        except ValueError:
            self.threads = 4
        self.fallback = VietnameseOCR(root)
        self.lock = threading.Lock()
        self.model = None

    def status(self):
        ready = all((self.folder / name).is_file() for name in ('encoder_fp16.onnx', 'decoder_fp16.onnx', 'vocab.txt'))
        ready = ready and all(importlib.util.find_spec(name) is not None for name in ('numpy', 'onnxruntime'))
        return {'ready': bool(ready), 'engine': ENGINE, 'cache_key': CACHE_KEY, 'external': False,
                'setup': 'py backend/setup_vietocr.py', 'device': 'CPU',
                'fallback_ready': self.fallback.status()['ready']}

    def recognize(self, image, *, regions=None, han_boxes=None, psm=11):
        if not self.status()['ready']:
            raise OCRError('Chưa cài VietOCR. Cài backend/requirements.txt, chạy py backend/setup_vietocr.py rồi khởi động lại backend.', 503)
        original = Image.open(io.BytesIO(image)).convert('RGB')
        boxes, warnings = [], ['Quốc ngữ do VietOCR đọc tự động; kiểm tra từ, dấu và thứ tự dòng trước khi hoàn thành.']
        try:
            with self.lock:
                if self.model is None:
                    self.model = LineRecognizer(self.folder, self.threads)
                for crop, x, y in image_regions(original, regions):
                    local_han = [{**box, 'points': [[a - x, b - y] for a, b in box['points']]} for box in han_boxes or []]
                    rectangles, colored = line_regions(crop, local_han)
                    if len(rectangles) > 200:
                        raise OCRError('Có quá nhiều vùng dòng trên trang. Giới hạn vùng Quốc ngữ bằng mẫu cho quyển rồi thử lại.', 422)
                    for left, top, right, bottom in rectangles:
                        text, probability, ended = self.model.predict(crop.crop((left, top, right, bottom)))
                        if sum(char.isalpha() for char in text) < 2:
                            continue
                        if not ended:
                            # Never mark a silently truncated line as completed.
                            raise OCRError('Một dòng Quốc ngữ quá dài hoặc chưa tách đúng. Thu hẹp vùng mẫu rồi thử lại; phần Nôm đã lưu.', 422)
                        boxes.append({'id': 'vi-' + uuid4().hex, 'transcription': text,
                                      'points': [[left+x, top+y], [right+x, top+y], [right+x, bottom+y], [left+x, bottom+y]],
                                      'confidence': probability})
        except OCRError:
            raise
        except Exception:
            raise OCRError('Không chạy được VietOCR local. Cài lại backend/requirements.txt và chạy py backend/setup_vietocr.py; checkpoint Nôm vẫn được giữ.', 503) from None
        boxes = clean_boxes(boxes, original.width, original.height)
        # Overlapping user templates must not duplicate the same recognized line.
        unique = {}
        for box in boxes:
            key = (box['transcription'], tuple(tuple(p) for p in box['points']))
            unique.setdefault(key, box)
        boxes = sorted(unique.values(), key=lambda box: (box['points'][0][1], box['points'][0][0]))
        if not boxes and self.fallback.status()['ready']:
            result = self.fallback.recognize(image, regions=regions, han_boxes=han_boxes, psm=psm)
            result['warnings'] = warnings + ['VietOCR không tìm được dòng; đã thử Tesseract dự phòng.'] + result.get('warnings', [])
            return result
        if not boxes:
            warnings.append('Chưa tìm được dòng Quốc ngữ. Chọn vùng mẫu chứa các dòng Quốc ngữ hoặc hiệu đính thủ công.')
        return {'boxes': boxes, 'text_lines': [box['transcription'] for box in boxes], 'warnings': warnings}
