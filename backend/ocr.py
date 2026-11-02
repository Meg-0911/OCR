"""Integration boundary for the forthcoming Kim Han Nom API instructions."""
from typing import Protocol


class OCRProvider(Protocol):
    def recognize(self, image: bytes, language: str) -> list[dict]: ...


class UnconfiguredOCR:
    def recognize(self, image: bytes, language: str) -> list[dict]:
        raise NotImplementedError("Chưa cấu hình OCR. Cần tài liệu API trước khi nhận dạng.")
