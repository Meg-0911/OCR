"""Run from a virtualenv, or use the checkout-local tool packages in this session."""
import sys
from pathlib import Path

local_packages = Path(__file__).parent / 'backend' / '.tools' / 'python'
if sys.prefix == sys.base_prefix and local_packages.exists():
    sys.path.insert(0,str(local_packages))

if __name__ == '__main__':
    import uvicorn
    uvicorn.run('backend.app:create_app',factory=True,host='127.0.0.1',port=8000)
