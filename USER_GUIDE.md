# Hướng dẫn sử dụng

## Duyệt nhanh bằng thẻ

1. Cài nguồn Nôm một lần: `.\.venv\Scripts\python.exe -m backend.setup_nom_dictionary`, sau đó khởi động lại ứng dụng.
2. Chọn **Duyệt nhanh** ở thanh trái, chọn sách và **Quét đối chiếu**. Truyện Kiều dùng `TruyenKieu.txt`; các sách còn lại lấy Quốc ngữ hiện có để tra Nôm Na Việt.
3. Mỗi thẻ hiện chỗ chưa khớp. Bấm chữ gợi ý để chọn, sửa Quốc ngữ nếu cần, rồi bấm **Đúng · đen**, **Đỏ**, **Thiếu từ điển**, hoặc **Để sau**. Phím tắt lần lượt: `1/→`, `2/←`, `3`, `Space`. Khi đang gõ, phím tắt tạm ngừng.
   Nếu nguồn có dị thể, mục **Dị thể** hiện các chữ có mã Unicode để chọn thay (ghi rõ Nôm, phồn thể, giản thể). Mục **Dạng chữ tư liệu** hiện ảnh dạng chữ cổ để đối chiếu, bấm ảnh để phóng lớn. Dữ liệu lấy từ Nôm Na Việt và lưu cục bộ; lỗi tải dị thể không làm mất nghĩa đã tra được.
4. Hai ảnh Nôm và Quốc ngữ lấy từ đúng trang liên kết của cặp, có ghi số trang riêng (Quốc ngữ có thể ở trang sau). Khung xanh là box dòng đã lưu; khung cam là vị trí đang xét, nét đứt nếu ước lượng trong box dòng. Chọn **Chỗ đang xét / Cả dòng / Cả trang** và **1× / 2×** để dò. Nếu chưa có trang Quốc ngữ liên kết, giao diện báo rõ để bạn chọn trong căn chỉnh đầy đủ.
5. Dòng lệch số chữ hiện nguyên dòng. Chọn chữ Nôm trong dãy nút để chỉ vị trí cần thay, nhập âm muốn tra rồi chọn chữ gợi ý. Dùng **Xem ngữ cảnh** để chuyển sang căn chỉnh đầy đủ.
6. Bấm **Quay lại** ngay trên nhóm nút duyệt để hoàn tác lần bấm gần nhất (kể cả **Để sau**) và mở lại đúng thẻ đó. Có thể bấm nhiều lần để lùi tiếp; nút mờ khi hết lịch sử. Bật **Xem cả để sau** để xem các thẻ đã hoãn. Mọi quyết định lưu ngay trong SQLite; tệp xuất cập nhật theo đợt sau khoảng 12 giây nghỉ thao tác. Không cần giữ màn hình này mở để quét, nhưng backend cần chạy. Sau lần quét bị ngắt do tắt máy, bấm quét lại; các quyết định đã lưu không mất.

TXT chỉ là bản tham khảo, khác bản chưa chắc OCR sai. Chỉ lỗi thừa đúng một `t` cuối từ từ trang 250 của Truyện Kiều được tự sửa khi bỏ `t` khớp mẫu. Các trang trước đó không áp dụng. Từ điển mới dùng bảng âm Nôm cục bộ và tải thêm nghĩa/ví dụ có nguồn khi có mạng; không dùng Unihan thay thế nếu thiếu từ. Xem [quy tắc và dữ liệu lưu](README.md#đối-chiếu-bán-tự-động).

## 1. Môi trường

- Windows 10/11, Python 3.13.5 64-bit và Node.js 24.11.1.
- Tối thiểu 8 GB RAM; khuyến nghị 16 GB khi xử lý sách nhiều trang.
- Kết nối mạng để cài dependency, tải model/từ điển và sử dụng Kim Hán Nôm. VietOCR và từ điển chạy cục bộ sau khi cài đặt.

Phiên bản runtime tham chiếu nằm trong `.python-version` và `.nvmrc`.

## 2. Cài đặt

Mở PowerShell tại thư mục gốc dự án:

```powershell
py -3.13 --version
node --version
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
npm --prefix frontend ci
.\.venv\Scripts\python.exe backend/setup_dictionary.py
.\.venv\Scripts\python.exe backend/setup_vietocr.py
```

Nếu dùng dịch vụ Kim Hán Nôm, tạo `backend/.env` từ `backend/.env.example` khi chưa có file cấu hình. Điền cookie `token` của tài khoản vào `KHN_token`. Token được lưu riêng trên mỗi máy.

PP-OCRv5 CPU là phương án OCR Hán Nôm dự phòng tùy chọn:

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-han-fallback.txt
```

`HAN_OCR_FALLBACK=ppocrv5` bật phương án dự phòng; `HAN_OCR_FALLBACK=off` tắt. `HAN_OCR_THREADS=4` đặt số luồng CPU. Tesseract là phương án Quốc ngữ dự phòng khác; script `backend/setup_vietnamese_ocr.py` trên Windows cần 7-Zip.

## 3. Chuẩn bị dữ liệu và khởi động

```text
backend/data/raw_data/       PDF nguồn, TXT tham chiếu nếu có
backend/data/new/            XLSX căn chỉnh, ảnh và Label.txt có sẵn
backend/data/.workspace/     SQLite, ảnh nhập và checkpoint làm việc
backend/data/output_alignment/  Tệp kết quả tự sinh
```

Chép PDF vào `raw_data/`, giữ nguyên tên tài liệu. Với OCR có sẵn, chuẩn bị `new/` theo [README](./README.md#dữ-liệu-đầu-vào). Trang ảnh tính từ trang đầu PDF; chỉ số dòng trong `Patch ID` tính từ 0 theo mảng box của `Label.txt`.

```powershell
.\.venv\Scripts\python.exe run.py
```

Mở `http://127.0.0.1:5173`. `run.py` khởi động frontend và backend cùng nhau. Khi thêm dữ liệu, sử dụng thao tác đồng bộ nguồn trong ứng dụng.

Quét lại `new/` giữ các trang đã có dữ liệu làm việc. Thay XLSX nguồn không thay các cặp đã sửa trên web. Một `Patch ID` xuất hiện với hai nội dung khác nhau trong các file nguồn cần được đối chiếu trước khi nhập; dữ liệu đã lưu vẫn được giữ.

## 4. Xử lý sách

1. **Phân loại trang:** chọn `ch`, `vi`, `both`, `intro`, `ref`, `toc`, `blank` hoặc `misc`. Đặt chiều đọc Nôm và vùng OCR. Quốc ngữ đọc ngang. Ảnh hai trang đọc trang trái trước, trang phải sau.
2. **OCR:** sách đã nhập từ `new/` có thể chuyển trực tiếp sang kiểm tra. Với PDF chưa có OCR, chạy theo trang hoặc phạm vi. Tác vụ hỗ trợ tạm dừng, tiếp tục và thử lại trang lỗi.
3. **Hiệu chỉnh:** đối chiếu chữ với ảnh, sửa nội dung và vùng box. Chọn theo chữ hoặc theo cụm phù hợp với OCR. Lưu và hoàn thành trang sau khi kiểm tra.
4. **Căn chỉnh:** kiểm tra hai vế và trang đối chiếu. Dùng trang liên kết khi Nôm và Quốc ngữ nằm khác trang. Kéo/gắn dòng để sửa cách ghép. ID cặp giữ nguyên khi chỉnh sửa và đổi thứ tự.
5. **Tách/gộp:** kiểm tra cả hai vế sau thao tác. Box OCR có thể chứa nhiều cặp; vùng chữ được liên kết theo từng đoạn. Vẽ/gán box Nôm cho cặp mới trước khi xuất. Nếu một box Quốc ngữ chứa nhiều cặp, xác nhận đủ các phần hoặc tách box thực trên ảnh.
6. **Xác nhận:** xác nhận từng cặp hoặc các cặp trên trang. Cặp đã xác nhận vẫn giữ dấu khi sửa nội dung, box hoặc màu. Thao tác bỏ xác nhận đưa cặp trở lại danh sách cần kiểm tra.

Trạng thái hoàn thành trang và xác nhận cặp là hai trạng thái riêng. Dữ liệu một cặp có thể gồm số chữ Nôm và số từ Quốc ngữ khác nhau; người dùng kiểm tra quan hệ nội dung của hai vế.

## 5. Lưu và xuất

Chỉnh sửa được lưu tự động; `Ctrl+S` lưu ngay. Theo dõi trạng thái lưu trước khi đóng trình duyệt. Khi hai phiên chỉnh sửa bảng căn chỉnh, hệ thống kết hợp các thay đổi độc lập. Nếu cùng một trường có hai nội dung khác nhau, thông báo xung đột xuất hiện và bản nháp được giữ để khôi phục; đối chiếu trước khi lưu tiếp. Chỉnh sửa trang OCR sử dụng kiểm tra phiên bản để tránh ghi đè dữ liệu mới.

Trong **Xuất dữ liệu**, chọn **Tải kết quả (.ZIP)**. Ứng dụng chờ các lần lưu đang chạy rồi đóng gói từ dữ liệu đã lưu. Gói chứa:

- PDF nguồn và ảnh theo phân loại trang của từng sách.
- CSV/XLSX của các cặp đã xác nhận, đủ hai vế sau làm sạch.
- `Label.txt` và `fileState.txt` theo PPOCRLabel cho nhãn được chọn. Trang chỉ hoàn thành khi nhãn xuất bao phủ đủ OCR của trang.
- Nhãn Quốc ngữ khi có box thực. Với `new/` chỉ có văn bản Quốc ngữ, vế dịch vẫn nằm trong bảng căn chỉnh; không tạo nhãn hoặc ảnh Quốc ngữ giả.

Số, dấu câu và ký tự điều khiển được bỏ khi xuất. Nôm không có khoảng trắng; Quốc ngữ viết thường, bỏ khoảng trắng dư. Xem phần xem trước của từng cặp để đối chiếu nội dung xuất. CSV có UTF-8 BOM; XLSX giữ màu đen/đỏ theo đánh dấu.

Nếu xuất bị chặn vì thiếu box hoặc sai liên kết, mở cặp được nêu trong thông báo, kiểm tra ID trang và vùng ảnh, rồi lưu lại. Cặp thiếu liên kết không bị âm thầm bỏ khỏi kết quả.

Các file `<Tên sách>.csv` và `<Tên sách>.xlsx` trong `output_alignment/<book_id>/` tự cập nhật sau khi lưu. Các file JSON và `pairs.csv` dùng theo dõi dữ liệu làm việc, bao gồm cặp chưa xác nhận. ZIP tải xuống là một bản chụp; tải lại để nhận chỉnh sửa mới.

Cấu trúc dữ liệu từng sách được mô tả trong [README](./README.md#kết-quả). Báo cáo và gói mã nguồn cấp dự án được chuẩn bị riêng khi bàn giao.

## 6. Sao lưu và chuyển máy

1. Chờ lưu hoàn tất, sau đó dừng ứng dụng.
2. Sao lưu toàn bộ `backend/data/.workspace/` cùng `raw_data/` và `new/`. Giữ nguyên cấu trúc đường dẫn và tên sách.
3. Khi chuyển máy, khôi phục bộ dữ liệu làm việc cùng nhau, cài dependency/model và cấu hình token riêng.
4. Mở sách, kiểm tra số cặp, dấu xác nhận và một số trang đại diện trước khi tiếp tục.

Các thành viên đang dùng bản cũ nên giữ nguyên bản sao dữ liệu làm việc trước khi cập nhật mã nguồn. CSV/XLSX xuất là sản phẩm dữ liệu; bộ làm việc đầy đủ cần SQLite, ảnh và các liên kết đã lưu.

## 7. Kiểm thử

```powershell
.\.venv\Scripts\python.exe backend/test.py
npm --prefix frontend run check
npm --prefix frontend run check:alignment
node --experimental-strip-types frontend/scripts/check-linked-alignment.mjs
node --experimental-strip-types frontend/scripts/check-result-pipeline.mjs
```

Khi Vite đang chạy, kiểm tra component qua runtime phát triển:

```powershell
npm --prefix frontend run check:review-runtime
```

## 8. Xử lý sự cố

- **Sách không xuất hiện:** kiểm tra PDF tương ứng trong `raw_data/` và lỗi đồng bộ nguồn. `new/` chỉ được nhập khi tìm được đúng sách nguồn.
- **Không có box Quốc ngữ ở sách nhập sẵn:** XLSX có thể chỉ cung cấp văn bản. Đây là dữ liệu không có tọa độ; nhãn Quốc ngữ được bỏ qua khi xuất.
- **Xung đột lưu:** kiểm tra phiên đang mở và bản nháp khôi phục. Giữ nội dung cần đối chiếu trước khi đóng trình duyệt.
- **Kim Hán Nôm trả 401/403:** kiểm tra token và quyền tài khoản, cập nhật `backend/.env`, sau đó khởi động lại.
- **VietOCR chưa sẵn sàng:** chạy lại `backend/setup_vietocr.py`. Nếu ONNX báo `DLL load failed`, kiểm tra Python 64-bit và Microsoft Visual C++ Redistributable x64.
- **Thiếu từ điển:** chạy `backend/setup_dictionary.py` rồi khởi động lại.
- **Frontend không chạy:** chạy `npm --prefix frontend ci`, kiểm tra cổng `5173` và `8000`, rồi khởi động lại bằng `run.py`.
