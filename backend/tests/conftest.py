"""Keep optional local OCR models out of tests unless explicitly injected."""
import pytest


@pytest.fixture(autouse=True)
def disable_optional_han_fallback(monkeypatch):
    monkeypatch.setenv('HAN_OCR_FALLBACK', 'off')
