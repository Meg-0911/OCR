# User Guide

## 1. Chuẩn bị máy

### Cấu hình đề nghị

- Windows 10/11 +.
- Python 3.13.5 64-bit và Node.js 24.11.1; phiên bản tham chiếu nằm trong `.python-version` và `.nvmrc`.
- Tối thiểu 8 GB RAM; khuyến nghị 16 GB trở lên khi xử lý PDF lớn/nhiều trang.

## 2. Lấy mã nguồn và dữ liệu nhóm

Mở PowerShell hoặc Terminal tại thư mục clone dự án. Cấu trúc cần giữ:

```text
backend/data/raw_data/       PDF nguồn và TXT đối chiếu (đưa vào thủ công)
backend/data/new/            XLSX dóng hàng, ảnh và nhãn mới (bổ sung theo từng đợt)
backend/.env                 token OCR cá nhân (tạo từ .env.example)
backend/data/                SQLite, ảnh, model, checkpoint và kết quả (tự sinh/local)
```

**Dữ liệu:** Lấy PDF/TXT từ gói dữ liệu, rồi chép vào `backend/data/raw_data/`.

Sau khi khởi động, ứng dụng dò PDF trong `backend/data/raw_data/` tự động. Có thể thêm PDF khác sau này rồi bấm đồng bộ nguồn hoặc khởi động lại backend.
Với dữ liệu OCR sẵn, tạo thư mục new theo đúng cấu trúc bên dưới.

## 3. Cài đặt trên Windows

### 3.1 Cài runtime

1. Cài Python 3.13.5 x64 và Node.js 24.11.1 x64. Xác nhận trong PowerShell:

   ```powershell
   py -3.13 --version
   node --version
   npm --version
   ```

   Phiên bản tham chiếu là `Python 3.13.5`, `v24.11.1` và npm 11.x. Nếu Windows không nhận lệnh `py`, cài lại Python và chọn Python Launcher; nếu không nhận `node`, cài Node.js LTS và mở terminal mới.

2. Tạo virtualenv và cài Python packages đã pin:

   ```powershell
   py -3.13 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
   ```

3. Cài frontend đúng lockfile để chạy từ mã nguồn:

   ```powershell
   npm --prefix frontend ci
   ```

### 3.2 Cài từ điển và model VietOCR

Chạy tại thư mục gốc repo:

```powershell
.\.venv\Scripts\python.exe backend/setup_dictionary.py
.\.venv\Scripts\python.exe backend/setup_vietocr.py
```

Tesseract chỉ là phương án OCR dự phòng. Trên Windows, script `backend/setup_vietnamese_ocr.py` cần 7-Zip; không cần chạy nếu VietOCR đã hoạt động.

### 3.3 Cấu hình OCR Hán Nôm

Tạo file cấu hình từ mẫu nếu chưa có:

```powershell
Copy-Item backend/.env.example backend/.env
```

Nếu dùng Kim Hán Nôm, mở `backend/.env` và điền token cookie `token` của tài khoản vào `KHN_token`. Nếu chỉ dùng PP-OCRv5 CPU, có thể để trống token.

### 3.3.1 Cài PP-OCRv5 CPU dự phòng

Trong virtualenv của backend, cài thêm hai gói tùy chọn:

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-han-fallback.txt
```

Giữ `HAN_OCR_FALLBACK=ppocrv5` trong `backend/.env` (mặc định nếu không khai báo). `HAN_OCR_THREADS=4` giới hạn luồng CPU.
OCR dự phòng là model chữ Hán tổng quát, cần kiểm tra độ đúng trên sách thực tế. Đặt `HAN_OCR_FALLBACK=off` nếu muốn tắt.

### 3.4 Khởi động

Đảm bảo PDF sách đã ở `backend/data/raw_data/`, sau đó chạy:

```powershell
.\.venv\Scripts\python.exe run.py
```

Mở <http://127.0.0.1:5173>. Lệnh trên chạy cả giao diện từ `frontend/src/` và API ở cổng `8000`, cùng dùng gốc dự án chứa `run.py`.

## 4. Làm việc trên một bộ sách

1. **Kiểm tra nguồn:** trong ứng dụng, chọn sách đã dò từ `raw_data/` hoặc tải PDF. Tải TXT UTF-8 Hán Nôm/Quốc ngữ làm bản tham chiếu nếu có.
2. **Lập kế hoạch trang:** mỗi trang có một nhãn `ch` (Hán Nôm), `vi` (Quốc ngữ), `both` (cả hai), `intro`, `ref`, `toc`, `blank` hoặc `misc`; chọn vùng nội dung. Chọn **Chiều đọc Hán/Nôm mặc định cho cả sách** là dọc hoặc ngang, rồi dùng **Chiều đọc riêng của trang** khi trang Hán/Nôm cần khác mặc định. Trang chỉ có Quốc ngữ luôn đọc ngang từ trái sang phải. Đây là thiết lập OCR, không phải nhãn xuất chuẩn. Trang trắng/không cần xử lý có thể bỏ qua OCR. Ảnh hai trang cần kiểm tra thứ tự trang trái trước, trang phải sau.
   - **Gắn nhãn nhiều trang:** giữ Ctrl và nhấp các ảnh trang muốn chọn, hoặc bấm **Chọn tất cả** (Ctrl+A) để chọn toàn bộ sách.
3. **Chạy OCR:** chọn OCR từng trang hoặc theo phạm vi. OCR Hán Nôm dùng Kim Hán Nôm hoặc PP-OCRv5 CPU dự phòng đã cài; OCR Quốc ngữ dùng model VietOCR đã tải. Nếu cả hai cách OCR Hán Nôm đều thất bại ở một trang, tác vụ ghi lỗi cho trang đó và tiếp tục các trang sau. Khi chạy hết phạm vi, bấm **Tiếp tục OCR** để thử lại các trang lỗi; các trang đã thành công được giữ nguyên. Có thể tạm dừng/tiếp tục tác vụ; checkpoint nằm trong `backend/data/.workspace/ocr/`.
4. **Gán nhãn OCR:** so box và chữ với ảnh, sửa ký tự chưa chắc (`□`), kéo/đổi kích thước box, vẽ hoặc xóa box. Ô **Chia theo cụm** nằm ngay dưới **Lưu & hoàn thành**: tick nếu mỗi box OCR chứa một cụm chữ, bỏ tick nếu mỗi box chứa một chữ. Bấm **Lưu & hoàn thành** để ghi cách chia và xác nhận trang.
5. **Căn chỉnh song ngữ:** cặp được tự tạo và lưu ngay khi có OCR, không cần xác nhận trang trước. Dữ liệu OCR sẵn dùng trực tiếp cặp `Label`–`Vietnamese` theo `Patch ID` trong XLSX. Với raw_data, chế độ **Theo cụm** giữ mỗi box OCR Hán Nôm thành một dòng; chế độ **Theo chữ** ghép chữ trong cùng dòng/cột đọc. Hệ thống ghép hai vế theo thứ tự, giữ riêng dòng Nôm chưa có Quốc ngữ để bổ sung sau.
   - **Câu nằm lệch trang:** ở bước **Gắn nhãn trang**, chọn trang rồi đánh dấu các trang liên kết trong ô **Trang liên kết**. Có thể tìm theo số trang và sửa liên kết sau khi OCR; trạng thái duyệt, box và checkpoint OCR được giữ nguyên. Ở **Căn chỉnh song ngữ**, ứng dụng tự ghép các trang liên kết theo thứ tự dòng. Kéo một dòng Quốc ngữ sang dòng Hán Nôm cần ghép, hoặc chọn dòng rồi bấm **Gắn vào dòng** để sửa.
   - **ID và tệp kết quả:** `sentence_id` và `img_id` luôn dùng số trang Hán Nôm, ví dụ `Tên sách.007.1` và `Tên sách.007.jpg`. ID giữ nguyên khi sửa/đổi thứ tự, cụm mới nhận ID mới. `alignments.json` lưu thêm ID trang và số dòng của hai vế để truy vết. `pairs.csv`, CSV và XLSX vẫn dùng bốn cột `img_id`, `sentence_id`, `SinoNom_Char`, `ChuQN_txt`; `pages.json` lưu danh sách `linked_page_ids`.
6. **Xuất:** trong **Xuất dữ liệu**, bấm **Tải kết quả (.ZIP)**. ZIP chỉ gồm CSV/XLSX và nhãn OCR của các cặp **đã xác nhận và đủ hai vế**; không cần hoàn thành toàn bộ sách. Các cặp chưa xác nhận hoặc thiếu vế vẫn được giữ trong ứng dụng để sửa tiếp. `manifest.json` trong ZIP ghi số cặp đã xuất và chưa xuất của từng cuốn.

## 6. Dữ liệu, đầu ra và sao lưu

- PDF/TXT nguồn: `backend/data/raw_data/`.
- DB và trạng thái đã lưu: `backend/data/.workspace/` (SQLite `workspace.sqlite3`, các trang sách, ảnh bản mới trong `book-assets/` và checkpoint). Bản nháp chưa lưu nằm trên trình duyệt.
- Ảnh đã xử lý: `backend/data/processed_images/`.
- Kết quả xuất: `backend/data/output_alignment/<book_id>/`.
- Model/tài nguyên setup: `backend/.tools/`.

## 7. Kiểm thử và phát triển

```powershell
.\.venv\Scripts\python.exe backend/test.py
npm --prefix frontend run check
npm --prefix frontend run check:alignment
```

## 8. Xử lý sự cố

- **Sách không xuất hiện:** với PDF, kiểm tra `backend/data/raw_data/`; với dữ liệu mới, kiểm tra XLSX, ảnh và `Label.txt` trong `backend/data/new/` theo README. Quét thư mục và xem lỗi nguồn trên tổng quan, hoặc khởi động lại.
- **401/403 từ OCR Hán Nôm:** token hết hạn/sai hoặc tài khoản thiếu quyền. Cập nhật `KHN_token` trong `backend/.env`, sau đó khởi động lại backend.
- **VietOCR chưa sẵn sàng:** chạy lại `backend/setup_vietocr.py`, xem thông báo lỗi trong Cài đặt. Cần mạng để tải model lần đầu.
- **ONNX báo `DLL load failed` trên Windows:** xác nhận Python 64-bit và cài Microsoft Visual C++ Redistributable x64.
- **Thiếu từ điển:** chạy `backend/setup_dictionary.py`, rồi khởi động lại backend.
- **Giao diện không khởi động/thiếu Vite:** chạy `npm --prefix frontend ci`, rồi chạy lại `run.py`; không xóa `package-lock.json`. Kiểm tra cổng `5173` và `8000` không bị một phiên ứng dụng khác chiếm.
- **Không thấy box/nhận dạng kém:** kiểm tag ngôn ngữ, hướng đọc, vùng ảnh, độ phân giải và chất lượng ảnh; có thể vẽ box thủ công rồi lưu.
