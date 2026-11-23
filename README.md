# Nôm Workspace

Nôm Workspace là ứng dụng web chạy trên máy cá nhân để xây dựng ngữ liệu song song Hán Nôm–Quốc ngữ từ PDF. Ứng dụng hỗ trợ phân loại trang, nhận dạng và sửa OCR, căn chỉnh văn bản, đánh dấu đối chiếu, và xuất dữ liệu huấn luyện/nghiên cứu.

## Chức năng và kiến trúc

- **Backend:** Python 3.13, FastAPI và SQLite. PyMuPDF đọc/render PDF; dữ liệu sách, trang, box, căn chỉnh và checkpoint được lưu cục bộ.
- **Frontend:** React 19, TypeScript và Vite. `run.py` chạy trực tiếp giao diện từ `frontend/src/` tại `http://127.0.0.1:5173`, proxy API về backend cổng `8000`. Không dùng `frontend/dist/` khi chạy ứng dụng.
- **OCR Hán Nôm:** ưu tiên dịch vụ Kim Hán Nôm qua Internet; khi dịch vụ lỗi hoặc không trả chữ, dùng PP-OCRv5 chạy CPU cục bộ nếu đã cài. Bộ dò vùng mobile kết hợp model nhận chữ server để ưu tiên độ đúng. Ảnh chỉ gửi tới Kim Hán Nôm khi có token và dịch vụ được gọi.
- **OCR Quốc ngữ:** VietOCR dùng ONNX Runtime CPU cục bộ;
- **Từ điển:** Unicode Unihan được tải riêng và lưu thành SQLite cục bộ.
- **Kết quả:** CSV/XLSX cho cặp câu và ZIP nhãn PPOCRLabel (`Label.txt`, `fileState.txt`, ảnh trang). Box Hán Nôm lưu để sửa theo từng chữ; khi xuất được nhóm thành box hàng/cột theo hướng đọc.

PDF đầu vào được quét từ `backend/data/raw_data/`. SQLite, ảnh render, checkpoint OCR, model VietOCR, bản nháp và kết quả xuất nằm trong `backend/data/`. PP-OCRv5 lưu model trong cache của PaddleX trên máy.

## Thêm dữ liệu mới theo từng đợt

`backend/data/raw_data/` là danh sách sách. backend/data/new/ là dữ liệu đã có OCR.

```text
backend/data/new/
├── Alignment/
│   ├── <Tên sách>.xlsx
│   ├── <Tên sách>.dot-2.xlsx          # các file hiện có cùng tạo thành bản mới của cuốn
│   └── ned_summary.xlsx              # thống kê lỗi, không nhập thành cặp câu
└── <Tên sách>/
    └── images/
        ├── <Tên sách>.003.jpg
        ├── <Tên sách>.004.jpg
        ├── Label.txt                 # nhãn dòng theo thứ tự có sẵn
        └── char_det.txt              # tọa độ từng chữ, nếu có
```

`Label.txt` và `char_det.txt` cũng có thể nằm ngay trong `<Tên sách>/`, như gói dữ liệu hiện có. Giữ nguyên kích thước ảnh để khớp tọa độ nhãn. Mỗi dòng TXT có dạng `<đường dẫn ảnh><TAB><mảng JSON>`, ví dụ `images/<Tên sách>.003.jpg<TAB>[{"transcription":"","points":[[10,10],[110,10],[110,40],[10,40]]}]`. Bản mới luôn dùng **box dòng theo cụm** từ `Label.txt`, chữ lấy từ XLSX. `char_det.txt` và các bản dự đoán có thể giữ để chia sẻ/tham khảo, không được dùng để tách ngược bản mới thành box từng chữ.

Mỗi sheet XLSX cần các cột sau; thứ tự cột tùy ý, có thể giữ các cột phụ:

| Cột | Cách dùng |
| --- | --- |
| `Patch ID` | `<Tên sách>.<trang>.<dòng>`, ví dụ `Tên sách.003.000`. Trang khớp tên ảnh; dòng đếm từ **0**, trỏ vào vị trí box trong mảng của `Label.txt`. |
| `Vietnamese` | Vế Quốc ngữ đã dóng hàng với dòng Nôm. |
| `Label` | Chữ Nôm sau voting và hậu chỉnh sửa, được ưu tiên hơn OCR cũ và dự đoán trong `char_det.txt`. |
| `Correctness` | Một bit cho mỗi chữ Nôm: `1` chấp nhận, `0` đánh dấu lỗi để kiểm tra. Nên lưu dưới dạng **Text** để giữ số `0` đầu chuỗi. Với ô dạng số, ứng dụng bổ sung `0` bên trái theo số chữ; chuỗi dài phải dùng Text vì Excel có thể làm mất độ chính xác số. |

Dữ liệu `new` ghép câu theo chính `Patch ID` và cặp `Label`–`Vietnamese` trong XLSX; nguồn cũ ghép từ dòng OCR đã nhận. Số chữ Nôm và số từ Quốc ngữ **không bắt buộc bằng nhau**, kể cả khi lưu OCR, lưu cặp hoặc xuất. Output: CSV/XLSX có bốn cột `img_id`, `sentence_id`, `SinoNom_Char`, `ChuQN_txt`; `sentence_id` bắt đầu từ **1**, giữ nguyên khi sửa hoặc đổi thứ tự; ZIP vẫn chứa ảnh, `Label.txt`, `fileState.txt`. Các bit lỗi thể hiện qua dấu kiểm tra và màu chữ khi xuất XLSX.

## Dependency và phiên bản

Các dependency Python trực tiếp được pin bằng `==` trong [backend/requirements.txt](./backend/requirements.txt). Frontend pin dependency trực tiếp trong `package.json`, khóa cả cây dependency bắc cầu bằng [frontend/package-lock.json](./frontend/package-lock.json), và cài bằng `npm ci`. Phiên bản Python/Node đã kiểm tra lần lượt ghi ở [.python-version](./.python-version) và [.nvmrc](./.nvmrc).

Các phiên bản Python trực tiếp: FastAPI 0.135.3, Uvicorn 0.44.0, Pydantic 2.12.5, python-multipart 0.0.26, PyMuPDF 2.1, openpyxl 3.1.5, pytest 9.0.2, httpx 0.28.1, python-dotenv 1.2.2, Pillow 12.2.0, NumPy 2.3.5 và ONNX Runtime 1.31.1. PP-OCRv5 CPU là dependency tùy chọn được pin riêng trong [backend/requirements-han-fallback.txt](./backend/requirements-han-fallback.txt).

Các dependency trực tiếp frontend: React/React DOM 19.2.0, Vite 7.2.2, TypeScript 5.9.3, `@vitejs/plugin-react` 5.1.1, `lucide-react` 0.468.0, `@fontsource/be-vietnam-pro` 5.3.0 và Prettier 3.6.2. Đừng thay `npm ci` bằng `npm install` khi cài lại dự án, để giữ đúng lockfile.

## Bắt đầu nhanh

Hướng dẫn cài mới từ đầu, setup model/dữ liệu, chạy ứng dụng và làm quy trình sách nằm trong [USER_GUIDE.md](./USER_GUIDE.md).

Sau khi đã tạo `.venv`, cài dependency (`npm --prefix frontend ci` cho frontend), setup Unihan/VietOCR, thêm PDF và cấu hình `backend/.env`:

```powershell
.\.venv\Scripts\python.exe run.py
```

Mở <http://127.0.0.1:5173>. `run.py` dùng thư mục chứa chính nó làm gốc dự án, kể cả khi gọi từ thư mục khác; khởi động/tắt cả frontend và backend cùng nhau. Cổng `8000` dành cho API và chuyển hướng về giao diện. Chi tiết token OCR, thao tác trên sách, xuất file, sao lưu và xử lý lỗi xem trong User Guide.

## Kiểm tra dự án

```powershell
.\.venv\Scripts\python.exe backend/test.py
npm --prefix frontend run check
npm --prefix frontend run check:alignment
```

Một số test tạo PDF/DB tạm trong thư mục test; không gọi OCR dịch vụ bên ngoài.

## Tài liệu và dữ liệu đồ án

- Quy định tham khảo: [docs/Quy_định_đồ_án.pdf](./docs/Quy_định_đồ_án.pdf).
- PDF trong `backend/data/raw_data/` và dữ liệu làm việc không được Git theo dõi.