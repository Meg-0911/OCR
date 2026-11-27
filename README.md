# Nôm Workspace

Nôm Workspace là ứng dụng cục bộ để xây dựng ngữ liệu song song Hán Nôm–Quốc ngữ từ PDF và dữ liệu OCR có sẵn. Ứng dụng hỗ trợ phân loại trang, hiệu chỉnh OCR, liên kết câu với vùng ảnh, xác nhận cặp và xuất dữ liệu.

## Kiến trúc

- Backend: Python 3.13, FastAPI, SQLite và PyMuPDF.
- Frontend: React, TypeScript và Vite tại `http://127.0.0.1:5173`; API sử dụng cổng `8000`.
- OCR Hán Nôm: Kim Hán Nôm khi có token; PP-OCRv5 CPU là phương án dự phòng tùy chọn.
- OCR Quốc ngữ: VietOCR qua ONNX Runtime CPU. Model được cài riêng.
- Tra cứu: từ điển Unicode Unihan trong SQLite cục bộ.
- Duyệt nhanh: đối chiếu Truyện Kiều với `TruyenKieu.txt`; sách khác tra âm Quốc ngữ qua Nôm Na Việt, không dùng Unihan trong luồng này.

SQLite lưu dữ liệu làm việc chính. Các tệp kết quả được tạo từ dữ liệu đã lưu. Bản nháp trên trình duyệt dùng để khôi phục thao tác chưa lưu thành công.

## Khởi động

Hướng dẫn cài đặt đầy đủ nằm trong [USER_GUIDE.md](./USER_GUIDE.md). Sau khi cài dependency, model và dữ liệu:

```powershell
.\.venv\Scripts\python.exe run.py
```

`run.py` chạy frontend từ mã nguồn và backend theo thư mục gốc của dự án. Phiên bản runtime tham chiếu được ghi trong [.python-version](./.python-version) và [.nvmrc](./.nvmrc). Dependency Python được cố định trong [backend/requirements.txt](./backend/requirements.txt); frontend sử dụng `package-lock.json` và cài bằng `npm ci`.

## Dữ liệu đầu vào

```text
backend/data/
├── raw_data/                       PDF nguồn, giữ nguyên tên sách
└── new/
    ├── Alignment/
    │   └── <Tên sách>.xlsx
    └── <Tên sách>/
        ├── Label.txt
        └── images/
            └── <Tên sách>.003.jpg
```

`new/` cung cấp OCR ban đầu cho sách có PDF tương ứng trong `raw_data/`. `Label.txt` cũng có thể nằm trong `images/`. Giữ nguyên kích thước ảnh và thứ tự box trong nhãn. `char_det.txt` là tài liệu tham khảo; importer sử dụng box dòng trong `Label.txt`.

Mỗi sheet XLSX cần các cột:

| Cột | Nội dung |
| --- | --- |
| `Patch ID` | `<Tên sách>.<trang>.<dòng>`. Trang tính từ 1; dòng tính từ 0, trỏ vào phần tử của `Label.txt`. |
| `Label` | Văn bản Hán Nôm của dòng. |
| `Vietnamese` | Văn bản Quốc ngữ tương ứng. |
| `Correctness` | Một bit cho mỗi chữ Nôm: `1` đúng, `0` cần kiểm tra. Lưu dưới dạng Text để giữ số 0 đầu chuỗi. |

Các XLSX có thể bổ sung trang khác nhau của cùng sách. Hai bản ghi cùng `Patch ID` có nội dung khác nhau được báo lỗi nguồn để đối chiếu. `ned_summary.xlsx` và tệp tạm Excel không được nhập.

Quét nguồn chỉ khởi tạo trang chưa có dữ liệu làm việc. Trang đã có OCR, cặp câu, chỉnh sửa hoặc xác nhận được giữ nguyên, kể cả khi XLSX thay đổi hoặc bị gỡ khỏi thư mục. Các bản làm việc từ phiên bản trước tiếp tục sử dụng ID đã lưu.

## Lưu và liên kết dữ liệu

- ID cặp và `sentence_id` giữ nguyên khi sửa nội dung hoặc đổi thứ tự. Cặp mới nhận ID mới.
- Liên kết OCR sử dụng ID box và phạm vi chữ. Dữ liệu cũ được bổ sung liên kết khi xác định được vị trí phù hợp; trường hợp mơ hồ giữ nguyên nội dung đã lưu.
- Cặp đã xác nhận giữ trạng thái khi sửa chữ, box hoặc màu. Người dùng có thể chủ động bỏ xác nhận.
- Hai phiên sửa các trường khác nhau của bảng căn chỉnh có thể lưu kết hợp. Hai thay đổi khác nhau trên cùng trường cần đối chiếu; bản nháp được giữ để khôi phục.
- Tách/gộp cặp cần kiểm tra vùng ảnh tương ứng. Xuất ZIP yêu cầu box Nôm khớp với từng cặp được chọn.

## Kết quả

CSV/XLSX sử dụng đúng bốn cột: `img_id`, `sentence_id`, `SinoNom_Char`, `ChuQN_txt`. Tên ảnh có dạng `<Tên sách>.<trang ít nhất 3 số>.jpg`; ID câu có dạng `<Tên sách>.<trang>.<câu từ 1>`.

Văn bản xuất loại số, dấu câu và ký tự điều khiển; Nôm không chứa khoảng trắng, Quốc ngữ viết thường và có một khoảng trắng giữa các từ. Màu XLSX đi theo ký tự sau khi làm sạch. Nội dung OCR đang chỉnh sửa được giữ để đối chiếu.

ZIP tải từ giao diện chứa dữ liệu từng sách:

```text
<Tên sách>/
├── <Tên sách>.pdf
├── <Tên sách>.csv
├── <Tên sách>.xlsx
├── ch/                            Ảnh, Label.txt, fileState.txt
├── vi/                            Khi có box Quốc ngữ thực
├── intro/
├── ref/
├── toc/
├── blank/
└── misc/
```

Bảng căn chỉnh và nhãn trong ZIP lấy các cặp đã xác nhận, đủ hai vế sau làm sạch. Ảnh giữ theo phân loại trang của sách. `fileState.txt` chỉ ghi hoàn thành khi nhãn xuất bao phủ đủ nội dung OCR của trang. Sách `new` thiếu box Quốc ngữ vẫn có vế Quốc ngữ trong CSV/XLSX và không tạo nhãn Quốc ngữ giả.

Quy cách dữ liệu tham chiếu: [đặc tả định dạng](./docs/Quy_định_đồ_án.pdf). ZIP của ứng dụng là gói dữ liệu sách; báo cáo và gói mã nguồn cấp dự án được chuẩn bị riêng khi bàn giao.

Tại `backend/data/output_alignment/<book_id>/`, `<Tên sách>.csv` và `<Tên sách>.xlsx` tự cập nhật các cặp đã xác nhận sau khi lưu. `pairs.csv`, `pages.json`, `alignments.json` và `summary.json` là bản lưu làm việc, có thể chứa cặp chưa xác nhận. API xuất riêng toàn bộ bảng sử dụng thư mục `working/`. ZIP được dựng từ bản chụp cố định tại thời điểm tải; thay đổi tiếp theo được đưa vào lần tải kế tiếp.

## Kiểm thử

```powershell
.\.venv\Scripts\python.exe backend/test.py
npm --prefix frontend run check
npm --prefix frontend run check:alignment
npm --prefix frontend run check:quick-review
node --experimental-strip-types frontend/scripts/check-linked-alignment.mjs
node --experimental-strip-types frontend/scripts/check-result-pipeline.mjs
```

Các kiểm thử backend tạo PDF và SQLite trong thư mục tạm, sử dụng OCR giả lập và không gọi dịch vụ OCR bên ngoài. Dữ liệu nguồn, cơ sở dữ liệu làm việc và model cục bộ không được Git theo dõi.

## Đối chiếu bán tự động

Cài bảng tra Nôm một lần bằng `.\.venv\Scripts\python.exe -m backend.setup_nom_dictionary`, rồi khởi động lại ứng dụng. Mở **Duyệt nhanh**, chọn sách và bấm **Quét đối chiếu**. Bảng âm công khai của [Nôm Na Việt](https://nomnaviet.com/en/search) được lưu cục bộ; nghĩa và ví dụ tải theo chữ từ nguồn, có bộ nhớ đệm. Không chuyển sang Unihan khi thiếu mục từ. Metadata nguồn, ngày tải và SHA-256 nằm cạnh bảng âm trong `backend/data/dictionaries/`.

- Truyện Kiều: ghép theo nội dung hai vế; chỉ nhận dòng tham khảo có điểm khớp và khoảng cách với ứng viên kế tiếp đủ rõ. Dòng mơ hồ đưa lên thẻ cả dòng. TXT là bản tham khảo có dị bản, không phải bản chuẩn để ghi đè.
- Đủ số chữ: mỗi thẻ chứa một vị trí chưa khớp; vế đã khớp không lặp lại mẫu. Khác số chữ hoặc thiếu nguồn: hiện cả dòng, cho sửa trực tiếp và tra từng chữ. Dòng thiếu một vế cần bổ sung hoặc sửa trong căn chỉnh đầy đủ trước khi gán màu.
- Tự chuyển đen khi Quốc ngữ khớp và Nôm trùng nguồn hoặc có âm tương ứng trong bảng Nôm. Với sách khác, lấy Quốc ngữ hiện tại làm âm đối chiếu. Đây là đối chiếu âm/chữ, không phải mô hình hiểu toàn bộ ngữ nghĩa.
- Chỉ cuốn Truyện Kiều đã định danh, từ trang ảnh 250: xóa một `t` cuối từ khi kết quả khớp đúng từ ở cùng vị trí trong mẫu. Không sửa gần đúng khác, không xóa `t` của từ vốn đúng, không sửa trang 1–249.
- Chọn chữ rồi bấm màu để lưu: **1 / →** đen, **2 / ←** đỏ, **3** thiếu từ điển (xuất đỏ), **Space** để sau. Phím tắt không hoạt động khi đang gõ. Có ngữ cảnh, ảnh gốc và hoàn tác. Ở thẻ cả dòng, chọn vị trí Nôm trước khi chọn chữ thay thế.

Hàng đợi và lịch sử nằm trong SQLite. Quét chạy nền; có thể rời màn hình nhưng backend phải còn chạy. Nếu tắt máy giữa lượt quét, mở lại và bấm quét; quyết định đã lưu được giữ. Quyết định người dùng được ưu tiên ở lần quét tiếp theo khi dòng chưa bị sửa. Thẻ cũ bị từ chối khi có sửa đổi từ màn hình khác. SQLite và OCR liên kết được lưu ngay; CSV/XLSX/nhãn cập nhật sau khoảng 12 giây không có quyết định mới. Lỗi xuất hiển thị riêng và không làm mất quyết định; khởi động lại cũng dựng lại tệp xuất từ SQLite.

Luồng này không chạy OCR hoặc dựng lại box, không tự xác nhận toàn bộ cặp của sách khác. Script một lần `python -m tools.confirm_kieu --apply` chỉ xác nhận trang/cặp đúng bản Truyện Kiều Duy Minh Thị và sao lưu SQLite trước khi sửa. Bỏ `--apply` để xem số lượng. TXT gốc nằm ở `backend/data/.workspace/backups/TruyenKieu.original.txt`; bản hiện tại là bảng tab gồm thứ tự thực, số dòng gốc, Nôm, Quốc ngữ và ghi chú. Các số gốc lặp/nhảy và hai chỗ `NAME?` không được suy đoán lại.
