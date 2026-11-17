"""Run from a virtualenv, or use the checkout-local tool packages in this session."""
import sys
import os
import shutil
import subprocess
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
local_packages = ROOT / 'backend' / '.tools' / 'python'
if sys.prefix == sys.base_prefix and local_packages.exists():
    sys.path.insert(0,str(local_packages))

def main():
    import uvicorn
    node = shutil.which('node')
    vite = ROOT / 'frontend/node_modules/vite/bin/vite.js'
    if not node or not vite.is_file():
        raise SystemExit('Cài Node.js và chạy npm --prefix frontend ci trước khi khởi động.')
    os.environ['CORPUS_ROOT'] = str(ROOT)
    print('Đang nạp dữ liệu và khởi tạo API…', flush=True)
    config = uvicorn.Config('backend.app:create_app', factory=True, host='127.0.0.1', port=8000)
    # Loading the factory scans/migrates the workspace and can take a while.
    # Complete it before exposing Vite's API proxy to the browser.
    config.load()
    ui = subprocess.Popen([node, str(vite), '--host', '127.0.0.1', '--port', '5173', '--strictPort'],
                          cwd=ROOT / 'frontend', creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    server = uvicorn.Server(config)
    def monitor_ui():
        ui.wait()
        server.should_exit = True
    threading.Thread(target=monitor_ui, daemon=True).start()
    try:
        print('Mở http://127.0.0.1:5173', flush=True)
        server.run()
    finally:
        if ui.poll() is None:
            ui.terminate()
        try:
            ui.wait(timeout=10)
        except subprocess.TimeoutExpired:
            ui.kill()
            ui.wait()


if __name__ == '__main__':
    main()
