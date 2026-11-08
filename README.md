# Nôm Workspace

Nôm Workspace là ứng dụng web chạy trên máy cá nhân để xây dựng ngữ liệu song song Hán Nôm–Quốc ngữ từ PDF. Ứng dụng hỗ trợ phân loại trang, nhận dạng và sửa OCR, căn chỉnh văn bản, đánh dấu đối chiếu, và xuất dữ liệu huấn luyện/nghiên cứu.

## Chức năng và kiến trúc

- **Backend:** Python 3.13, FastAPI và SQLite. PyMuPDF đọc/render PDF; dữ liệu sách, trang, box, căn chỉnh và checkpoint được lưu cục bộ.
- **Frontend:** React 19, TypeScript và Vite. Giao diện được build thành `frontend/dist/` và phục vụ cùng backend tại `http://127.0.0.1:8000`.
- **OCR Hán Nôm:** gọi dịch vụ Kim Hán Nôm qua Internet, cần token cá nhân trong `backend/.env`. Ảnh trang được gửi tới dịch vụ này khi chạy OCR Hán Nôm.
- **OCR Quốc ngữ:** VietOCR dùng ONNX Runtime CPU cục bộ; không cần API key. Model được tải riêng bằng script setup và không nằm trong Git.
- **Từ điển:** Unicode Unihan được tải riêng và lưu thành SQLite cục bộ.
- **Kết quả:** CSV/XLSX cho cặp câu và ZIP nhãn PPOCRLabel (`Label.txt`, `fileState.txt`, ảnh trang). Box Hán Nôm lưu để sửa theo từng chữ; khi xuất được nhóm thành box hàng/cột theo hướng đọc.

PDF đầu vào được quét từ `backend/data/raw_data/`. SQLite, ảnh render, checkpoint OCR, model, bản nháp và kết quả xuất nằm trong `backend/data/` và không được commit. Không xóa thư mục dữ liệu khi muốn giữ tiến độ.

## Môi trường đã chạy và đã kiểm tra

Thông tin dưới đây được đo trên máy phát triển của dự án, không phải yêu cầu phần cứng tối thiểu. VietOCR chạy CPU; GPU không được ứng dụng sử dụng.

| Thành phần | Môi trường đã kiểm tra |
|---|---|
| Hệ điều hành | Microsoft Windows 10 Pro 64-bit, build 19045 |
| Python | CPython 3.13.5 64-bit |
| Node.js / npm | Node.js 24.11.1 / npm 11.6.2 |
| CPU | AMD Ryzen 7 PRO 4750U, 8 nhân / 16 luồng |
| RAM | 63.4 GiB khả dụng theo hệ điều hành |
| Đồ họa | AMD Radeon(TM) Graphics tích hợp; không dùng GPU/CUDA cho OCR |

## Dependency và phiên bản

Các dependency Python trực tiếp được pin bằng `==` trong [backend/requirements.txt](./backend/requirements.txt). Frontend pin dependency trực tiếp trong `package.json`, khóa cả cây dependency bắc cầu bằng [frontend/package-lock.json](./frontend/package-lock.json), và cài bằng `npm ci`. Phiên bản Python/Node đã kiểm tra lần lượt ghi ở [.python-version](./.python-version) và [.nvmrc](./.nvmrc).

Các phiên bản Python trực tiếp: FastAPI 0.135.3, Uvicorn 0.44.0, Pydantic 2.12.5, python-multipart 0.0.26, PyMuPDF 2.1, openpyxl 3.1.5, pytest 9.0.2, httpx 0.28.1, python-dotenv 1.2.2, Pillow 12.2.0, NumPy 2.4.4 và ONNX Runtime 1.31.1.

Các dependency trực tiếp frontend: React/React DOM 19.2.0, Vite 7.2.2, TypeScript 5.9.3, `@vitejs/plugin-react` 5.1.1, `lucide-react` 0.468.0, `@fontsource/be-vietnam-pro` 5.3.0 và Prettier 3.6.2. Đừng thay `npm ci` bằng `npm install` khi cài lại dự án, để giữ đúng lockfile.

## Bắt đầu nhanh

Hướng dẫn cài mới từ đầu, setup model/dữ liệu, chạy ứng dụng và làm quy trình sách nằm trong [USER_GUIDE.md](./USER_GUIDE.md).

Sau khi đã tạo `.venv`, cài dependency, build frontend, setup Unihan/VietOCR, thêm PDF và cấu hình `backend/.env`:

```powershell
.\.venv\Scripts\python.exe run.py
```

Mở <http://127.0.0.1:8000>. Chi tiết token OCR, thao tác trên sách, xuất file, sao lưu và xử lý lỗi xem trong User Guide.

## Kiểm tra dự án

```powershell
.\.venv\Scripts\python.exe backend/test.py
npm --prefix frontend run check
npm --prefix frontend run build
```

Một số test tạo PDF/DB tạm trong thư mục test; không gọi OCR dịch vụ bên ngoài.

## Tài liệu và dữ liệu đồ án

- Quy định tham khảo: [docs/Quy_định_đồ_án.pdf](./docs/Quy_định_đồ_án.pdf).
- Bảng đối chiếu được cung cấp: [docs/BichCauKyNgo1_SO_SANH.xlsx](./docs/BichCauKyNgo1_SO_SANH.xlsx).
- PDF trong `backend/data/raw_data/` và dữ liệu làm việc không được Git theo dõi. Khi clone trên máy mới, chép bộ PDF nhóm đã nộp vào thư mục này; giữ nguyên tên để ứng dụng tự nhận diện sách/TXT đối chiếu tương ứng.
