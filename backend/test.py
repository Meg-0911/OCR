"""Use the checkout-local dependencies when no virtual environment is active."""
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
if sys.prefix == sys.base_prefix and (root / 'backend/.tools/python').exists():
    sys.path.insert(0, str(root / 'backend/.tools/python'))
import pytest

raise SystemExit(pytest.main([str(root / 'backend/tests'), *sys.argv[1:]]))
