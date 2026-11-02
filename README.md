# Nôm · Hán Nôm – Quốc ngữ

Ứng dụng local để nhập sách PDF, hiệu đính OCR và căn chỉnh ngữ liệu song ngữ.

```text
frontend/    React + TypeScript, cấu hình npm và bản build
backend/     API Python, lưu tiến trình, xuất dữ liệu và kiểm thử
docs/        Yêu cầu gốc, đối chiếu yêu cầu và hướng dẫn sử dụng
data/        Sách nguồn và toàn bộ dữ liệu phát sinh — không commit
run.py       Chạy ứng dụng
```

## Cài và chạy

Python 3.13, Node.js ≥22.12. Chạy các lệnh từ thư mục gốc:

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
npm --prefix frontend ci
npm --prefix frontend run build
.venv\Scripts\python.exe run.py
```

Mở **http://127.0.0.1:8000**. Trong workspace đã chuẩn bị hiện tại, có thể chạy ngay `py run.py`.

Để phát triển frontend, chạy thêm `npm --prefix frontend run dev`.

## Kiểm thử

```powershell
.venv\Scripts\python.exe backend/test.py
npm --prefix frontend run build
```

Hướng dẫn chi tiết: [docs/USER_GUIDE.md](docs/USER_GUIDE.md). Phạm vi triển khai: [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md).

Giao diện đã hỗ trợ sửa vùng chữ/văn bản, checkpoint SQLite, căn chỉnh thủ công và xuất CSV/XLSX/PPOCRLabel. OCR thực tế, từ điển và đánh giá ≥95% còn chờ tích hợp. Bộ mẫu được ghi rõ là minh họa.

Bộ đếm theo dõi mục tiêu **2.000 cặp Nôm – Quốc ngữ** trên toàn bộ sách thật: chỉ tính cặp đã lưu, đủ hai vế và không trùng văn bản. Giao diện báo số còn thiếu và có nút bổ sung tài liệu. Nút nhỏ ở góc trái thanh trên dùng để thu/mở sidebar và nhớ lựa chọn trên trình duyệt.

Giữ toàn bộ sách, ảnh, nhãn và file xuất trong `data/`; không đưa dữ liệu lên Git hoặc dịch vụ công khai.
