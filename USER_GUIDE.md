# User Guide — Nôm Workspace

Hướng dẫn cài và chạy dự án trên một máy mới, nạp dữ liệu PDF của nhóm, làm OCR/căn chỉnh và lấy kết quả. Người dùng thao tác trong trình duyệt; dữ liệu sách và bản nháp được lưu trên máy đang chạy backend.

## 1. Chuẩn bị máy

### Cấu hình đề nghị

- Windows 10/11 64-bit hoặc Ubuntu 24.04 LTS trở lên (x86-64).
- Python 3.13.5 64-bit và Node.js 24.11.1; phiên bản tham chiếu nằm trong `.python-version` và `.nvmrc`.
- Tối thiểu 8 GB RAM; khuyến nghị 16 GB trở lên khi xử lý PDF lớn/nhiều trang. GPU không bắt buộc.
- Kết nối Internet khi cài dependency/model, tải Unihan và gọi OCR Hán Nôm.
- Microsoft Visual C++ Redistributable x64 trên Windows nếu ONNX Runtime báo thiếu DLL.

## 2. Lấy mã nguồn và dữ liệu nhóm

Mở PowerShell hoặc Terminal tại thư mục clone dự án. Cấu trúc cần giữ:

```text
backend/data/raw_data/       PDF nguồn và TXT đối chiếu (đưa vào thủ công)
backend/.env                 token OCR cá nhân (tạo từ .env.example)
backend/data/                SQLite, ảnh, model, checkpoint và kết quả (tự sinh/local)
```

**Dữ liệu:** Lấy PDF/TXT từ gói dữ liệu, rồi chép vào `backend/data/raw_data/`. Không cần đổi tên PDF; TXT đối chiếu nên cùng thư mục và cùng tên gốc để ứng dụng nhận diện.

Sau khi khởi động, ứng dụng dò PDF trong `backend/data/raw_data/` tự động. Có thể thêm PDF khác sau này rồi bấm đồng bộ nguồn hoặc khởi động lại backend.

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

3. Cài frontend đúng lockfile và build giao diện:

   ```powershell
   npm --prefix frontend ci
   npm --prefix frontend run build
   ```

### 3.2 Cài từ điển và model VietOCR

Chạy tại thư mục gốc repo:

```powershell
.\.venv\Scripts\python.exe backend/setup_dictionary.py
.\.venv\Scripts\python.exe backend/setup_vietocr.py
```

Hai lệnh cần Internet. Script từ điển tải Unicode Unihan và tạo DB cục bộ. Script VietOCR tải các model ONNX tại revision cố định, kiểm SHA-256 rồi lưu vào `backend/.tools/vietocr/`; model không được commit. OCR Quốc ngữ mặc định chạy local bằng ONNX Runtime CPU.

Tesseract chỉ là phương án OCR dự phòng. Trên Windows, script `backend/setup_vietnamese_ocr.py` cần 7-Zip; không cần chạy nếu VietOCR đã hoạt động.

### 3.3 Cấu hình OCR Hán Nôm

Tạo file cấu hình từ mẫu nếu chưa có:

```powershell
Copy-Item backend/.env.example backend/.env
```

Nếu dùng Kim Hán Nôm, mở `backend/.env` và điền token cookie `token` của tài khoản vào `KHN_token`. Không gửi file `.env` lên Git, email công khai hoặc ảnh chụp màn hình. `KHN_BASE_URL` mặc định dùng HTTPS chính thức. Token cần có quyền truy cập dịch vụ OCR. Nếu chỉ dùng PP-OCRv5 CPU, có thể để trống token.

OCR Hán Nôm gửi ảnh lên dịch vụ Kim Hán Nôm. Chỉ chạy OCR với dữ liệu mà nhóm được phép đưa tới dịch vụ đó. OCR Quốc ngữ VietOCR xử lý local.

### 3.3.1 Cài PP-OCRv5 CPU dự phòng

Trong virtualenv của backend, cài thêm hai gói tùy chọn (cần Internet lúc cài và lúc tải model lần đầu):

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-han-fallback.txt
```

Giữ `HAN_OCR_FALLBACK=ppocrv5` trong `backend/.env` (mặc định nếu không khai báo). `HAN_OCR_THREADS=4` giới hạn luồng CPU. Khởi động lại backend; model dò vùng mobile và model nhận chữ server sẽ được tải vào cache PaddleX của tài khoản hệ điều hành trong lần OCR dự phòng đầu tiên. Khi Kim Hán Nôm trả lỗi, dữ liệu không hợp lệ hoặc không tìm được chữ, ứng dụng tự chạy PP-OCRv5 trên CPU cho cùng ảnh/vùng. Nếu không có token, có thể chỉ dùng PP-OCRv5. Kết quả vẫn vào cùng trang OCR, box và checkpoint; khi fallback được dùng sẽ có cảnh báo để rà chữ Nôm. OCR dự phòng là model chữ Hán tổng quát, cần kiểm tra độ đúng trên sách thực tế. Đặt `HAN_OCR_FALLBACK=off` nếu muốn tắt.

### 3.4 Khởi động

Đảm bảo PDF của nhóm đã ở `backend/data/raw_data/`, sau đó chạy:

```powershell
.\.venv\Scripts\python.exe run.py
```

Mở <http://127.0.0.1:8000>. Backend chỉ lắng nghe `127.0.0.1`; để tắt, quay lại cửa sổ PowerShell và nhấn `Ctrl+C`.

## 4. Cài đặt tham khảo trên Ubuntu

Các bước này là hướng dẫn cài mới, không phải cấu hình đã benchmark. Cài các thư viện hệ thống và công cụ phiên bản đã pin:

```bash
sudo apt update
sudo apt install -y build-essential curl git libffi-dev libssl-dev zlib1g-dev \
  libbz2-dev libreadline-dev libsqlite3-dev liblzma-dev libncursesw5-dev \
  libgdbm-dev libnss3-dev libexpat1-dev tk-dev xz-utils \
  tesseract-ocr tesseract-ocr-vie
```

Cài Python build bằng `pyenv` và Node bằng `nvm`. Các lệnh cài manager dưới đây tải mã cài đặt từ dự án chính thức; mở terminal mới sau khi chạy:

```bash
curl -fsSL https://pyenv.run | bash
echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.bashrc
echo '[[ -d $PYENV_ROOT/bin ]] && export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.bashrc
echo 'eval "$(pyenv init - bash)"' >> ~/.bashrc
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
source ~/.bashrc
pyenv install 3.13.5
pyenv local 3.13.5
nvm install 24.11.1
nvm use 24.11.1
python --version
node --version
```

Sau đó từ thư mục gốc repo:

```bash
python -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
npm --prefix frontend ci
npm --prefix frontend run build
.venv/bin/python backend/setup_dictionary.py
.venv/bin/python backend/setup_vietocr.py
cp backend/.env.example backend/.env
```

Điền `KHN_token` trong `backend/.env`, chép dữ liệu nhóm vào `backend/data/raw_data/`, rồi chạy:

```bash
.venv/bin/python run.py
```

Mở <http://127.0.0.1:8000>. Với Tesseract dự phòng, dùng gói `tesseract-ocr`/`tesseract-ocr-vie` vừa cài; script tải Tesseract riêng trong repo là quy trình Windows.

## 5. Làm việc trên một bộ sách

1. **Kiểm tra nguồn:** trong ứng dụng, chọn sách đã dò từ `raw_data/` hoặc tải PDF. Tải TXT UTF-8 Hán Nôm/Quốc ngữ làm bản tham chiếu nếu có. TXT không tự tạo bounding box; chỉ dấu trang rõ ràng mới được dùng để phân trang tham chiếu.
2. **Lập kế hoạch trang:** mỗi trang có một nhãn `ch` (Hán Nôm), `vi` (Quốc ngữ), `both` (cả hai), `intro`, `ref`, `toc`, `blank` hoặc `misc`; chọn vùng nội dung. Chọn **Chiều đọc Hán/Nôm mặc định cho cả sách** là dọc hoặc ngang, rồi dùng **Chiều đọc riêng của trang** khi trang Hán/Nôm cần khác mặc định. Trang chỉ có Quốc ngữ luôn đọc ngang từ trái sang phải. Đây là thiết lập OCR, không phải nhãn xuất chuẩn. Trang trắng/không cần xử lý có thể bỏ qua OCR. Ảnh hai trang cần kiểm tra thứ tự trang trái trước, trang phải sau.
   - **Gắn nhãn nhiều trang:** giữ Ctrl và nhấp các ảnh trang muốn chọn, hoặc bấm **Chọn tất cả** (Ctrl+A) để chọn toàn bộ sách. Bấm **Hán/Nôm**, **Quốc ngữ** hoặc **Cả hai** để gắn nhãn ngay cho nhóm đã chọn; các nhãn khác nằm trong danh sách bên cạnh. Bấm **Bỏ chọn** để hủy vùng chọn.
3. **Chạy OCR:** chọn OCR từng trang hoặc theo phạm vi. OCR Hán Nôm dùng Kim Hán Nôm hoặc PP-OCRv5 CPU dự phòng đã cài; OCR Quốc ngữ dùng model VietOCR đã tải. Có thể tạm dừng/tiếp tục tác vụ; checkpoint nằm trong `backend/data/.workspace/ocr/`.
4. **Gán nhãn OCR:** so box và chữ với ảnh, sửa ký tự chưa chắc (`□`), kéo/đổi kích thước box, vẽ hoặc xóa box. Box Hán Nôm được giữ từng chữ để rà soát. Lưu nháp/trang sau khi sửa.
5. **Căn chỉnh song ngữ:** chọn trang để xem box nhãn xuất trên ảnh. Nếu trang chưa có cặp câu, bấm **Tạo box từ OCR** để tự gom các box chữ OCR theo dòng/cột đọc của trang; thao tác này thay thế các box nhãn xuất hiện có sau khi xác nhận. Khi đã tạo các cặp Hán Nôm–Quốc ngữ, nút này tạo khung cho tất cả cặp còn thiếu: ứng dụng đếm số ký tự Hán Nôm trong từng cặp, lấy bấy nhiêu box OCR nhỏ theo thứ tự đã đánh số và tạo một khung bao; không cần chữ trong từng box OCR. Nếu nhóm box chạy qua nhiều dòng/cột hoặc không đủ box, kiểm tra thứ tự rồi kéo thủ công khi cần. Có thể chọn câu trong thanh công cụ trên ảnh, phóng to, chỉnh vị trí/kích thước. Nhấp box đã vẽ để chọn, rồi nhấn Delete hoặc nút thùng rác để xóa. Box nhãn xuất được lưu riêng và không sửa box chữ OCR. Danh sách dưới ảnh cho phép sửa số thứ tự hoặc dùng mũi tên để đổi thứ tự xuất; thứ tự phải liên tục từ 1 và không trùng. Khi tách cặp, đặt một con trỏ tại ranh giới ở một trong hai vế rồi bấm Tách; vế Quốc ngữ được chia theo ranh giới từ gần nhất và Hán Nôm được chia theo tỷ lệ tương ứng. Kiểm tra ranh giới và lưu căn chỉnh trước khi xuất.
   - **Câu nằm lệch trang:** ở bước **Gắn nhãn trang**, chọn trang rồi đánh dấu các trang liên kết trong ô **Trang liên kết**. Có thể tìm theo số trang và sửa liên kết sau khi OCR; trạng thái duyệt, box và checkpoint OCR được giữ nguyên. Ở **Căn chỉnh song ngữ**, chọn trang Hán Nôm: ứng dụng lưu cặp mặc định theo thứ tự dòng. Kéo một dòng Quốc ngữ sang dòng Hán Nôm cần ghép, hoặc chọn dòng rồi bấm **Gắn vào dòng**; các dòng Quốc ngữ phía sau được đẩy xuống. Dùng ô tìm và các dấu chọn trang để thu gọn danh sách khi liên kết nhiều trang. **Tự căn toàn sách** bỏ qua các trang liên kết và giữ các cặp đã căn của chúng.
   - **ID và tệp kết quả:** `sentence_id` và `img_id` luôn dùng số trang Hán Nôm, ví dụ `Tên sách.007.1` và `Tên sách.007.jpg`. `alignments.json` lưu thêm ID trang và số dòng của hai vế để truy vết. `pairs.csv`, CSV và XLSX vẫn dùng bốn cột `img_id`, `sentence_id`, `SinoNom_Char`, `ChuQN_txt`; `pages.json` lưu danh sách `linked_page_ids`.
6. **Xuất:** trong Xuất dữ liệu, tải CSV, XLSX và ZIP PPOCRLabel. CSV/XLSX là ngữ liệu cặp câu; ZIP gồm `Label.txt`, `fileState.txt` và ảnh. Nhãn Hán Nôm trong ZIP dùng riêng box nhãn xuất ở bước căn chỉnh; box Quốc ngữ giữ theo hàng/đoạn.

## 6. Dữ liệu, đầu ra và sao lưu

- PDF/TXT nguồn: `backend/data/raw_data/`.
- DB và bản nháp: `backend/data/.workspace/` (SQLite `workspace.sqlite3`, các trang sách và checkpoint).
- Ảnh đã xử lý: `backend/data/processed_images/`.
- Kết quả xuất: `backend/data/output_alignment/<book_id>/`.
- Model/tài nguyên setup: `backend/.tools/`.

Trước khi chuyển máy, dừng OCR, chờ tác vụ kết thúc, lưu bản nháp rồi dừng server. Sao lưu toàn bộ `backend/data/` và PDF/TXT nguồn. SQLite có WAL nên không chép riêng `workspace.sqlite3` khi server đang chạy. Giữ backup dữ liệu cùng PDF để khôi phục đúng sách/trang.

## 7. Kiểm thử và phát triển

```powershell
.\.venv\Scripts\python.exe backend/test.py
npm --prefix frontend run check
npm --prefix frontend run build
```

Ubuntu thay đường dẫn Python bằng `.venv/bin/python`. Khi phát triển frontend, chạy backend trong một terminal và `npm --prefix frontend run dev` trong terminal khác; Vite proxy `/api` về `http://127.0.0.1:8000`.

## 8. Xử lý sự cố

- **Sách không xuất hiện:** xác nhận file là PDF và nằm trong `backend/data/raw_data/`; đồng bộ nguồn trong ứng dụng hoặc khởi động lại.
- **401/403 từ OCR Hán Nôm:** token hết hạn/sai hoặc tài khoản thiếu quyền. Cập nhật `KHN_token` trong `backend/.env`, sau đó khởi động lại backend.
- **Trình duyệt cảnh báo kết nối không an toàn khi mở Kim Hán Nôm, hoặc OCR báo lỗi chứng chỉ HTTPS:** đây là lỗi chứng chỉ của dịch vụ. Không chọn tiếp tục truy cập, không tắt xác minh chứng chỉ; hãy báo đơn vị quản trị Kim Hán Nôm gia hạn chứng chỉ rồi thử lại. Lỗi này không thể sửa bằng cách đổi token.
- **VietOCR chưa sẵn sàng:** chạy lại `backend/setup_vietocr.py`, xem thông báo lỗi trong Cài đặt. Cần mạng để tải model lần đầu.
- **ONNX báo `DLL load failed` trên Windows:** xác nhận Python 64-bit và cài Microsoft Visual C++ Redistributable x64.
- **Thiếu từ điển:** chạy `backend/setup_dictionary.py`, rồi khởi động lại backend.
- **Font check hoặc build lỗi:** chạy `npm --prefix frontend ci`, sau đó `npm --prefix frontend run build`; không xóa `package-lock.json`.
- **Không thấy box/nhận dạng kém:** kiểm tag ngôn ngữ, hướng đọc, vùng ảnh, độ phân giải và chất lượng ảnh; có thể vẽ box thủ công rồi lưu.
