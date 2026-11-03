"""Kim Hán Nôm web API adapter (see docs/how to use api/)."""
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import httpx
from dotenv import dotenv_values

API_URL = 'https://kimhannom.fit.hcmus.edu.vn'
API_PATH = '/api/web/clc-sinonom'


class OCRError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class KHNConfig:
    token: str = field(default='', repr=False)
    base_url: str = API_URL
    timeout: float = 180
    user_agent: str = 'NomWorkspace/0.1'

    @classmethod
    def from_env(cls, env_file: Path):
        # Read without changing process-wide environment; process values take priority.
        values = {key.upper(): value for key, value in dotenv_values(env_file, interpolate=False).items()}
        values.update({key.upper(): value for key, value in os.environ.items()})
        token = (values.get('KHN_TOKEN') or '').strip()
        if token.lower().startswith('bearer '):
            token = token[7:].strip()
        try:
            timeout = float(values.get('KHN_TIMEOUT_SECONDS', '180'))
            if not math.isfinite(timeout) or timeout <= 0:
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError('KHN_TIMEOUT_SECONDS phải là số dương hữu hạn.') from None
        base_url = (values.get('KHN_BASE_URL') or API_URL).rstrip('/')
        url = httpx.URL(base_url)
        if url.scheme != 'https' or not url.host or url.userinfo or url.query or url.fragment:
            raise ValueError('KHN_BASE_URL phải là URL HTTPS, không kèm thông tin đăng nhập/query.')
        agent = values.get('KHN_USER_AGENT') or 'NomWorkspace/0.1'
        if agent.lower().startswith('python-requests'):
            raise ValueError('KHN_USER_AGENT không được bắt đầu bằng python-requests.')
        return cls(token=token, base_url=base_url, timeout=timeout, user_agent=agent)

    @property
    def ready(self):
        return bool(self.token)


class KimHanNomOCR:
    def __init__(self, config: KHNConfig, transport: httpx.BaseTransport | None = None):
        self.config = config
        self.transport = transport

    def _post(self, client, endpoint, **kwargs):
        try:
            response = client.post(f'{API_PATH}/{endpoint}', **kwargs)
        except httpx.TimeoutException:
            raise OCRError('Kim Hán Nôm xử lý quá thời gian. Hãy thử lại từng trang.', 504) from None
        except httpx.RequestError:
            raise OCRError('Không kết nối được Kim Hán Nôm. Kiểm tra mạng và KHN_BASE_URL.') from None
        if response.status_code in (401, 403):
            raise OCRError('Kim Hán Nôm từ chối xác thực. Cập nhật KHN_token trong backend/.env rồi khởi động lại.', 502)
        if response.status_code == 429:
            raise OCRError('Kim Hán Nôm đang giới hạn lượt gọi. Hãy đợi rồi thử lại.', 429)
        if not response.is_success:
            raise OCRError(f'Kim Hán Nôm trả lỗi HTTP {response.status_code}.')
        try:
            body = response.json()
        except (ValueError, UnicodeError):
            raise OCRError('Kim Hán Nôm trả dữ liệu không phải JSON hợp lệ.') from None
        if not isinstance(body, dict) or body.get('is_success') is not True or body.get('code') != '000000':
            # Do not echo upstream messages: they can contain headers/tokens or HTML.
            raise OCRError('Kim Hán Nôm báo yêu cầu thất bại. Kiểm tra token, quyền mô hình và tham số OCR.')
        if not isinstance(body.get('data'), dict):
            raise OCRError('Kim Hán Nôm trả thiếu trường data.')
        return body['data']

    def recognize(self, image: bytes, *, ocr_id=1, lang_type=2, reading_direction=1, epitaph=0, tag=None):
        if not self.config.ready:
            raise OCRError('Thiếu KHN_token trong backend/.env. Thêm token rồi khởi động lại.', 503)
        with httpx.Client(
            base_url=self.config.base_url, timeout=self.config.timeout,
            headers={'Authorization':f'Bearer {self.config.token}', 'User-Agent':self.config.user_agent},
            transport=self.transport, follow_redirects=False,
        ) as client:
            upload = self._post(client, 'image-upload', files={'image_file':('page.jpg', image, 'image/jpeg')})
            name = upload.get('file_name')
            if not isinstance(name, str) or not name.strip():
                raise OCRError('Kim Hán Nôm không trả file_name sau khi tải ảnh.')
            return self._post(client, 'image-ocr', json={
                'file_name':name, 'ocr_id':ocr_id, 'lang_type':lang_type,
                'reading_direction':reading_direction, 'epitaph':epitaph, 'tag':tag,
            })


def normalize_result(data: dict, width: int, height: int):
    """Keep real image coordinates only. Never invent regions for text-only output."""
    texts = data.get('result_ocr_text', [])
    if isinstance(texts, str):
        texts = texts.splitlines()
    if not isinstance(texts, list) or any(not isinstance(t, str) for t in texts):
        raise OCRError('Kim Hán Nôm trả result_ocr_text không hợp lệ.')
    regions = data.get('result_bbox')
    if regions is None:
        regions = []
    if not isinstance(regions, list):
        raise OCRError('Kim Hán Nôm trả result_bbox không hợp lệ.')
    boxes, skipped = [], 0
    for index, region in enumerate(regions):
        text = texts[index] if index < len(texts) else ''
        points = region
        if isinstance(region, dict):
            points = region.get('points')
            text = region.get('transcription', text)
        elif isinstance(region, list) and len(region) == 2 and isinstance(region[1], (list, tuple)):
            points = region[0]
            if region[1] and isinstance(region[1][0], str):
                text = region[1][0]
        if not isinstance(text, str) or len(text) > 30000 or not isinstance(points, (list, tuple)) or len(points) != 4:
            skipped += 1
            continue
        try:
            if any(len(p) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in p) for p in points):
                raise ValueError
            polygon = [[float(x), float(y)] for x,y in points]
            if any(not math.isfinite(x) or not math.isfinite(y) or not 0 <= x <= width or not 0 <= y <= height for x,y in polygon):
                raise ValueError
            turns = []
            for i in range(4):
                a,b,c = polygon[i], polygon[(i+1)%4], polygon[(i+2)%4]
                turns.append((b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0]))
            if not (all(t > 0 for t in turns) or all(t < 0 for t in turns)):
                raise ValueError
        except (TypeError, ValueError):
            skipped += 1
            continue
        boxes.append({'id':uuid4().hex, 'transcription':text, 'points':polygon})
    warnings = []
    if skipped:
        warnings.append(f'{skipped} vùng không đúng định dạng/tọa độ ảnh; xem JSON gốc để kiểm tra.')
    if texts and not boxes:
        warnings.append('API chỉ trả văn bản hoặc không có box hợp lệ. Vẽ/chọn vùng trên ảnh rồi gán văn bản; không tự tạo tọa độ.')
    if boxes and len(texts) != len(regions):
        warnings.append('Số dòng văn bản và số box khác nhau. Cần kiểm tra từng vùng trước khi lưu.')
    if not texts and not boxes:
        warnings.append('API không tìm thấy chữ. Thử kiểu văn bản khác hoặc kiểm tra ảnh nguồn.')
    return {'boxes':boxes, 'text_lines':texts, 'warnings':warnings}
