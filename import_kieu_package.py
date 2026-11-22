#!/usr/bin/env python3
"""
Script tự động giải nén và nạp dữ liệu OCR cuốn Truyện Kiều vào dự án Nôm Workspace.
Sử dụng:
    python import_kieu_package.py [đường_dẫn_file_zip]
Nếu không truyền tham số, script tự tìm file 'truyen_kieu_ocr_handoff.zip' trong thư mục hiện tại.
"""

import os
import sys
import zipfile
import sqlite3

def main():
    print("=" * 60)
    print("  NÔM WORKSPACE — TỰ ĐỘNG NẠP DỮ LIỆU OCR TRUYỆN KIỀU")
    print("=" * 60)

    # 1. Xác định thư mục gốc dự án (chứa backend và frontend)
    repo_root = os.path.dirname(os.path.abspath(__file__))
    if not os.path.isdir(os.path.join(repo_root, "backend")):
        # Nếu chạy từ thư mục khác
        cwd = os.getcwd()
        if os.path.isdir(os.path.join(cwd, "backend")):
            repo_root = cwd
        else:
            print(f"[ERROR] Không tìm thấy thư mục 'backend' tại: {repo_root}")
            print("Vui lòng đặt script này tại thư mục gốc của dự án OCR rồi chạy lại.")
            sys.exit(1)

    print(f"[INFO] Thư mục dự án: {repo_root}")

    # 2. Tìm file ZIP gói dữ liệu
    zip_path = None
    if len(sys.argv) > 1:
        custom_path = sys.argv[1]
        if os.path.isfile(custom_path):
            zip_path = custom_path
        else:
            print(f"[ERROR] Không tìm thấy file zip được chỉ định: {custom_path}")
            sys.exit(1)
    else:
        candidates = [
            os.path.join(repo_root, "truyen_kieu_ocr_handoff.zip"),
            os.path.join(repo_root, "kieu_ocr_handoff.zip"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                zip_path = c
                break

        if not zip_path:
            # Dò tìm file zip bất kỳ có chữ kieu trong tên
            for f in os.listdir(repo_root):
                if f.lower().endswith(".zip") and "kieu" in f.lower():
                    zip_path = os.path.join(repo_root, f)
                    break

    if not zip_path:
        print("[ERROR] Không tìm thấy file 'truyen_kieu_ocr_handoff.zip' trong thư mục dự án.")
        print("Vui lòng chép file ZIP vào thư mục gốc dự án hoặc chạy:")
        print("    python import_kieu_package.py <đường_dẫn_file_zip>")
        sys.exit(1)

    print(f"[INFO] Đã tìm thấy gói dữ liệu: {os.path.basename(zip_path)} ({os.path.getsize(zip_path) / 1024 / 1024:.2f} MB)")

    # 3. Giải nén vào thư mục dự án
    print("[INFO] Đang giải nén dữ liệu vào đúng các thư mục backend/data/...")
    extracted_count = 0
    with zipfile.ZipFile(zip_path, 'r') as zf:
        members = zf.infolist()
        total_files = len(members)
        for i, member in enumerate(members, 1):
            zf.extract(member, path=repo_root)
            extracted_count += 1
            if i % 500 == 0 or i == total_files:
                print(f"  Đã giải nén: {i}/{total_files} files...")

    # 4. Kiểm tra tính toàn vẹn
    print("\n[INFO] Đang kiểm tra tính toàn vẹn dữ liệu sau khi nạp...")
    db_path = os.path.join(repo_root, "backend", "data", ".workspace", "workspace.sqlite3")
    pdf_path = os.path.join(repo_root, "backend", "data", "raw_data", "TruyenKieuBanDuyMinhThi1872AnChiPhienAmChuGiaiVaThaoLuan_NguyenDu.pdf")
    book_id = "74868a599b314d249b4c9188f1d38870"
    proc_img_dir = os.path.join(repo_root, "backend", "data", "processed_images", book_id)

    errors = []
    if not os.path.isfile(pdf_path):
        errors.append(f"Thiếu file PDF: {pdf_path}")
    if not os.path.isfile(db_path):
        errors.append(f"Thiếu SQLite DB: {db_path}")
    if not os.path.isdir(proc_img_dir):
        errors.append(f"Thiếu thư mục ảnh: {proc_img_dir}")

    if errors:
        print("[ERROR] Quá trình nạp gặp vấn đề:")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)

    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        book = cur.execute("SELECT id, name FROM books WHERE id=?", (book_id,)).fetchone()
        if not book:
            print(f"[WARNING] Chưa thấy bản ghi sách {book_id} trong database.")
        else:
            pages_with_boxes = cur.execute(
                "SELECT count(*) FROM pages WHERE book_id=? AND ((boxes is not null and length(boxes) > 2) OR (vi_boxes is not null and length(vi_boxes) > 2))",
                (book_id,)
            ).fetchone()[0]
            alignments = cur.execute("SELECT count(*) FROM alignments WHERE book_id=?", (book_id,)).fetchone()[0]
            print(f"  + Cuốn sách: {book[1]}")
            print(f"  + Số trang đã có bounding box OCR: {pages_with_boxes}/598 trang")
            print(f"  + Cặp căn chỉnh song ngữ đã sẵn sàng trong DB: {'Đã có' if alignments > 0 else 'Chưa có'}")
        con.close()
    except Exception as ex:
        print(f"[WARNING] Không thể truy vấn SQLite: {ex}")

    img_count = len(os.listdir(proc_img_dir)) if os.path.exists(proc_img_dir) else 0
    print(f"  + Số lượng ảnh trang render sẵn: {img_count} files")

    print("\n" + "=" * 60)
    print("  [THÀNH CÔNG] Dữ liệu đã được nạp chính xác vào hệ thống!")
    print("  Bạn có thể khởi động ngay giao diện bằng lệnh:")
    print("      .\\.venv\\Scripts\\python.exe run.py   (Windows)")
    print("  hoặc:")
    print("      python run.py                       (Linux/Ubuntu)")
    print("  Sau đó mở http://127.0.0.1:5173 và làm tiếp từ trang 250.")
    print("=" * 60)

if __name__ == "__main__":
    main()
