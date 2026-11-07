# Nôm Workspace

Ứng dụng chạy tại máy để gắn nhãn trang PDF, OCR Hán Nôm và Quốc ngữ, sửa box, dóng hàng và xuất kết quả theo [quy định đồ án](docs/Quy_định_đồ_án.pdf). PDF của người dùng nằm trong `backend/data/raw_data/`.

## Cài đặt và chạy

Đã chạy trên Windows 10 64-bit với Python 3.13.5, Node.js ≥22.12 và VietOCR/ONNX Runtime CPU. Cài Microsoft Visual C++ Redistributable x64 nếu ONNX Runtime báo thiếu DLL. Phiên bản thư viện được khóa trong `backend/requirements.txt` và `frontend/package-lock.json`.

Mở PowerShell tại thư mục dự án:

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
npm --prefix frontend ci
npm --prefix frontend run build
.venv\Scripts\python.exe backend/setup_dictionary.py
.venv\Scripts\python.exe backend/setup_vietocr.py
if (-not (Test-Path backend/.env)) { Copy-Item backend/.env.example backend/.env }
```

Trong `backend/.env`, điền `KHN_token` bằng cookie `token` của tài khoản Kim Hán Nôm. Backend gửi ảnh Hán Nôm tới dịch vụ đó khi OCR. Không đưa token vào frontend hoặc Git. VietOCR chạy local với `VI_OCR_PROVIDER=vietocr`; có thể cài Tesseract dự phòng bằng `backend/setup_vietnamese_ocr.py`. Các lệnh setup mô hình cần Internet. Trên Linux dùng `.venv/bin/python` thay cho `.venv\Scripts\python.exe`.

Đặt PDF gốc vào `backend/data/raw_data/`, giữ nguyên tên và nội dung sau khi nhập. Trước khi OCR hàng loạt, kiểm tên sách, quyển, khoảng trang và phạm vi tương ứng của bản Hán Nôm và Quốc ngữ. Khôi phục phiên làm việc bằng cả PDF và `backend/data/.workspace/`, không chỉ PDF.

```powershell
.venv\Scripts\python.exe run.py
```

Mở <http://127.0.0.1:8000>, vào **Cài đặt** kiểm trạng thái token, VietOCR, từ điển và font. Trạng thái `ocr: configured` chỉ cho biết token đã được nhập; nếu OCR báo 401/403 thì cập nhật token và khởi động lại.

## Quy trình trên từng sách

1. **Thêm nội dung:** có thể tải TXT UTF-8 Hán Nôm hoặc Quốc ngữ làm bản đối chiếu. TXT không thay box OCR và không tự chia trang nếu không có dấu trang rõ ràng.
2. **Gắn nhãn trang:** xem từng ảnh, chọn Hán Nôm (`ch`), Quốc ngữ (`vi`), cả hai, hoặc tag giới thiệu (`intro`), chú thích (`ref`), mục lục (`toc`), trắng (`blank`), khác (`misc`). Ảnh có cả hai chữ phải bật cả hai ngôn ngữ; trang chỉ có một loại chữ phải tắt ngôn ngữ kia. Trang mới mặc định “cả hai” để thao tác nhanh; chỉnh tag ở trang chỉ có một loại chữ. Chọn chiều đọc và vùng nội dung; với bố cục khác nhau, cắt lại từng trang. Chỉ bỏ qua OCR khi không có chữ cần xử lý.
3. **OCR:** chạy toàn sách hoặc từng trang. OCR Hán Nôm dùng Kim Hán Nôm; Quốc ngữ dùng VietOCR tại máy. Có thể tạm dừng và tiếp tục nhờ checkpoint trong `backend/data/.workspace/ocr/`. Đổi ngôn ngữ, chiều đọc hoặc vùng quét thì OCR lại trang liên quan.
4. **Gán nhãn:** so với ảnh gốc ở mức phóng đại đủ đọc. Giao diện giữ box Hán Nôm **từng chữ** để sửa và dò lỗi. Sửa chữ `□`, kéo góc box, vẽ thêm box bằng nút **Vẽ box chữ** hoặc Alt+kéo; **OCR lại box** khi cần. Lưu trang sau khi sửa để cập nhật cả cặp căn chỉnh đã tách/gộp còn chứa `□`. Box Quốc ngữ nên ôm một hàng hoặc đoạn. Xóa số trang, tiêu đề, chân trang, chú thích ngoài nội dung chính, bảng và tranh. Đọc lại trước khi bấm hoàn thành.
5. **Căn chỉnh:** ghép câu bị đứt qua trang rồi tách đơn vị nhỏ nhất đủ nghĩa. Cho phép 1–1, 1–n, n–1, n–m; kiểm tên riêng, địa danh, thời gian, con số và ranh giới. Màu đánh dấu theo box ở bước Gán nhãn hiển thị trực tiếp trong hai ô căn chỉnh; có thể sửa chữ ngay tại đó. Đặt con trỏ trong **một ô** rồi bấm **Tách**; cặp mới để trống vế còn lại để sửa hoặc ghép tiếp. Lưu trước khi xuất. `sentence_id` có dạng `<Tên sách>.<số trang ít nhất 3 chữ số>.<số câu>`.

Ảnh chụp hai trang phải đọc **trang trái trước, trang phải sau**, rồi theo chiều chữ trong từng trang. Ứng dụng dùng nửa ảnh ngang để suy đoán thứ tự; cần kiểm thủ công nếu ảnh ngang chỉ chứa một trang hoặc box nằm sát gáy. Bố cục và màu mực thay đổi theo sách, vì vậy hãy rà lại cả vùng Nôm lẫn Quốc ngữ sau OCR, nhất là trang chữ đỏ hoặc xanh.

## File kết quả và kiểm tra

Trong **Xuất dữ liệu**, tải CSV, XLSX và ZIP nhãn PPOCRLabel. Ứng dụng lưu chúng tại `backend/data/output_alignment/<book_id>/`. ZIP nhãn chứa ảnh JPEG và `Label.txt`/`fileState.txt` ở từng thư mục nhóm. Ảnh song ngữ có trong cả `ch` và `vi`; `Label.txt` của mỗi nhóm chỉ chứa box của ngôn ngữ tương ứng. Trang `intro/ref/toc` có chữ cũng được sao vào thư mục ngôn ngữ tương ứng.

Khi xuất, box Hán Nôm từng chữ được gộp thành **box cột** nếu viết dọc hoặc **box hàng** nếu viết ngang; khoảng trắng rõ giữa chữ tách thành box riêng. Box Quốc ngữ giữ theo hàng/đoạn. Xem `Label.txt` bằng PPOCRLabel với ảnh cùng thư mục; mỗi dòng có đường dẫn ảnh, dấu TAB và JSON các box bốn điểm. `fileState.txt` ghi `1` cho trang đã hoàn thành, `0` cho trang chưa xong. Kiểm ít nhất một trang ở mỗi loại chữ và trang song ngữ.

Đối chiếu ảnh ở bước **Gán nhãn**: từng box chữ Hán Nôm mặc định đen; chọn box rồi bấm **Đen**, **Đỏ** (khác nghĩa) hoặc **Thiếu từ điển**. Màu áp dụng cho từ Quốc ngữ cùng thứ tự (box Hán/Nôm thứ n ↔ từ Quốc ngữ thứ n). Có thể dùng `Alt+1`, `Alt+2`, `Alt+3` để đánh dấu box đang chọn. CSV/XLSX có một cột `ChuQN_txt`; khi xuất, các bản nháp màu trên mọi trang được lưu trước, và XLSX giữ khoảng trắng giữa các đoạn màu khác nhau.

## Sao lưu và xử lý lỗi

- Trước khi sao lưu, tạm dừng OCR, chờ trang đang chạy xong, lưu nháp và dừng server; sao lưu toàn bộ `backend/data/`. SQLite có WAL, vì vậy không chép riêng `workspace.sqlite3` khi server đang chạy.
- `backend/data/output_alignment/<book_id>/summary.json`, `pages.json`, `alignments.json`, `pairs.csv`, `events.jsonl` là snapshot và nhật ký để phục hồi/kiểm tra.
- Nếu ONNX báo `DLL load failed`, kiểm Python 64-bit và Visual C++ Redistributable x64. Nếu VietOCR chưa sẵn sàng, chạy lại `backend/setup_vietocr.py`. Nếu trang không tìm được chữ, kiểm tag ngôn ngữ, vùng đọc và ảnh ở độ phân giải cao trước khi vẽ box thủ công.
- Kiểm thử: `.venv\Scripts\python.exe backend/test.py`, `npm --prefix frontend run check`, `npm --prefix frontend run build`.
