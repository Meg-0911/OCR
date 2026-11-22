@echo off
chcp 65001 >nul
echo ============================================================
echo   NÔM WORKSPACE - TỰ ĐỘNG NẠP DỮ LIỆU OCR TRUYỆN KIỀU
echo ============================================================

if exist ".\.venv\Scripts\python.exe" (
    ".\.venv\Scripts\python.exe" import_kieu_package.py %*
) else (
    python import_kieu_package.py %*
)

pause
