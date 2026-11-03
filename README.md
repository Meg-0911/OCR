# Nôm Workspace — OCR và căn chỉnh Hán Nôm – Quốc ngữ

Ứng dụng chạy tại máy để chọn sách, gắn nhãn/bỏ qua trang, OCR toàn bộ quyển, hiệu đính từng chữ, tra từ điển và tạo ngữ liệu song song. Kết quả hiện dần khi từng phần hoàn tất; checkpoint theo ngôn ngữ/trang giúp dừng rồi tiếp tục đúng chỗ.

## 1. Bắt đầu nhanh trên máy hiện tại

Tại thư mục gốc dự án:

```powershell
py run.py
```

Mở **http://127.0.0.1:8000**. Sau khi cập nhật mã nguồn, dừng server cũ bằng `Ctrl + C`, chạy lại lệnh trên và tải lại trang trình duyệt.

- PDF nguồn nằm trong **`backend/data/raw_data/`**. Bộ 16 file nằm trong drive (có 1 file .txt là để đối chiếu nên tổng chỉ có 15 cuốn)
- Yêu cầu của thầy là đủ 2000 cặp nôm - quốc ngữ nên cần tổng hợp và đếm lại để đảm bảo đủ data (báo lại các anh chị để thêm data)
- Có chức năng upload file mới trong quá trình chạy.

## 2. Cài trên máy mới

Cần **Python 3.13 bản 64-bit**, **Node.js từ 22.12 trở lên** (kèm npm). Trên Windows, cài **Microsoft Visual C++ Redistributable x64** nếu chưa có: ONNX Runtime cần runtime C++ để nạp DLL. Xem [yêu cầu ONNX Runtime](https://onnxruntime.ai/docs/install/#requirements) và [trang tải runtime chính thức của Microsoft](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist). Không cần CUDA, GPU hoặc PyTorch.

Các file cài đặt và tải dữ liệu đã được cập nhật:

| File | Cài/tải gì |
| --- | --- |
| `backend/requirements.txt` | Thư viện Python đã chốt phiên bản, gồm `numpy==2.5.4`, `onnxruntime==1.31.1`, Pillow, PyMuPDF, FastAPI và các thư viện xuất dữ liệu/kiểm tra |
| `frontend/package.json`, `frontend/package-lock.json` | Thư viện giao diện; dùng `npm ci` để cài đúng lockfile |
| `backend/setup_vietocr.py` | Mô hình ONNX và vocab VietOCR, kiểm tra SHA256, lưu trong `backend/.tools/vietocr/` |
| `backend/setup_dictionary.py` | Dữ liệu và giấy phép Unihan, dựng từ điển SQLite local |
| `backend/setup_vietnamese_ocr.py` | Tesseract và mô hình `vie+eng` dự phòng; trên Windows cần 7-Zip |
| `backend/.env.example` | Mẫu cấu hình token Kim Hán Nôm, VietOCR CPU và số luồng |
| `frontend/public/fonts/`, `frontend/public/licenses/` | Font Nôm đã đóng gói và giấy phép; không cần tải lại hay cài font hệ thống |
| `frontend/scripts/requirements-fonts.txt`, `frontend/scripts/setup_fonts.py` | Công cụ và lệnh tạo lại font web, chỉ cần nếu thiếu hoặc muốn dựng lại tài nguyên font |

**Cài `requirements.txt` chưa tải mô hình hoặc từ điển.** Cần chạy hai script setup riêng trong các bước dưới (setup_vietocr.py và setup_dictionary.py). Mô hình, từ điển và PDF không nằm trong Git; mỗi máy phải tải/copy riêng. Giữ đầy đủ thư mục font và giấy phép khi chia sẻ mã nguồn.

### Windows PowerShell

Mở terminal tại thư mục gốc dự án. Tạo `.env` nếu chưa có (giữ nguyên file đang chứa token):

```powershell
if (-not (Test-Path backend/.env)) {
    Copy-Item backend/.env.example backend/.env
}
```

Điền `KHN_token` của tài khoản vào file này, rồi cài và build:

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
npm --prefix frontend ci
npm --prefix frontend run build
.venv\Scripts\python.exe backend/setup_dictionary.py
.venv\Scripts\python.exe backend/setup_vietocr.py
```

Tesseract là dự phòng tùy chọn. Nếu muốn có cùng cấu hình dự phòng như máy hiện tại, cài 7-Zip và đảm bảo lệnh `7z` hoặc `7zz` có trong PATH, rồi chạy:

```powershell
.venv\Scripts\python.exe backend/setup_vietnamese_ocr.py
```

Đặt các PDF được phân công vào `backend/data/raw_data/`, sau đó mở ứng dụng:

```powershell
.venv\Scripts\python.exe run.py
```

Các lần mở sau trên máy cài bằng `.venv` cũng dùng `.venv\Scripts\python.exe run.py`. Những ví dụ `py ...` ở các phần tiếp theo là cách chạy trên máy hiện tại có thư viện local trong `backend/.tools/python/`; trên máy mới hãy thay `py` bằng `.venv\Scripts\python.exe` để dùng đúng môi trường đã cài. Không cần kích hoạt venv bằng PowerShell.

Sau khi mở, kiểm tra **Cài đặt**: OCR Quốc ngữ hiển thị VietOCR sẵn sàng, từ điển có dữ liệu và font Nôm đã tải. Có thể kiểm tra thư viện trước khi chạy server:

```powershell
.venv\Scripts\python.exe -c "import numpy, onnxruntime, pymupdf; print('Python dependencies OK'); print(onnxruntime.get_available_providers())"
```

Danh sách provider cần có `CPUExecutionProvider`. Nếu báo `DLL load failed` khi import ONNX Runtime, kiểm tra Python 64-bit và runtime C++ x64 nêu trên. Bước setup chỉ tải dữ liệu công khai; ảnh sách chỉ gửi tới Kim Hán Nôm khi bạn chủ động chạy OCR Nôm.

### Cấu hình OCR

Sao chép `backend/.env.example` thành `backend/.env` rồi điền token tài khoản Kim Hán Nôm lấy từ cookie `token` trên website.

```dotenv
KHN_token=<token tài khoản của bạn>
KHN_BASE_URL=https://kimhannom.fit.hcmus.edu.vn
KHN_TIMEOUT_SECONDS=180
KHN_USER_AGENT=NomWorkspace/0.1
```

Backend tự thêm `Authorization: Bearer ...`. Không đưa token vào frontend, README, URL hoặc Git. Đổi `.env` cần khởi động lại backend. Biến môi trường của tiến trình được ưu tiên hơn file `.env`.

`GET /api/health` trả `ocr: configured` chỉ có nghĩa là đã cấu hình token; token còn hạn và có quyền sử dụng hay không được xác định khi gọi API thật.

### Cài dữ liệu từ điển

```powershell
py backend/setup_dictionary.py
```

Lệnh tải dữ liệu công khai **Unicode Unihan 17.0.0** và giấy phép từ `unicode.org`, rồi dựng SQLite tại máy.

Có thể dùng file ZIP đã tải sẵn:

```powershell
py backend/setup_dictionary.py --zip "D:\Downloads\Unihan.zip"
```

Khi cài bằng ZIP, dùng bản Unicode 17.0.0 và giữ giấy phép Unicode tương ứng cùng dữ liệu. Khởi động lại backend/tải lại giao diện sau khi cài để trạng thái sẵn sàng được cập nhật.

Nguồn: [Unihan 17.0.0](https://www.unicode.org/Public/17.0.0/ucd/Unihan.zip), [tài liệu thuộc tính Unihan](https://www.unicode.org/reports/tr38/), [giấy phép Unicode](https://www.unicode.org/license.txt). Metadata URL, phiên bản và SHA-256 của gói đã tải được lưu trong `backend/data/dictionaries/unihan-source.json`.

### OCR Quốc ngữ trên cùng trang

Mặc định giao diện chọn **Nôm + Quốc ngữ**. Không cần vẽ box: Nôm qua Kim Hán Nôm, Quốc ngữ qua **VietOCR `vgg_transformer` tinh chỉnh chữ viết tay tiếng Việt**, chạy ONNX Runtime trên CPU tại máy. Bộ tìm dòng dùng màu mực khi phù hợp hoặc ảnh xám và tọa độ Nôm thực để giảm lẫn hai lớp chữ. VietOCR nhận ảnh màu gốc của từng dòng, không chuyển sang ảnh chỉ giữ mực đỏ. Kết quả hai ngôn ngữ được lưu độc lập và hiển thị trên cùng trang.

Đã cài sẵn trên máy hiện tại. Khi cài máy mới, cài các thư viện trong `backend/requirements.txt` rồi tải mô hình:

```powershell
py backend/setup_vietocr.py
```

Script tải encoder/decoder ONNX, vocab và thông tin giấy phép vào `backend/.tools/vietocr/`, kiểm tra SHA256 và khóa revision `f1973b930f907c378f6e3152ce9d8658724b228a`. Nguồn: [model card chữ viết tay](https://huggingface.co/vudang449/vietocr-vietnamese-handwriting), [VietOCR gốc](https://github.com/pbcquoc/vietocr), giấy phép Apache-2.0. Chỉ bước tải cần Internet; lúc đọc Quốc ngữ không gọi dịch vụ ngoài, không cần API key. Không tự tải mô hình khi server đang xử lý sách.

**Giới hạn đã kiểm tra:** VietOCR đọc được 11 dòng viết tay trên toàn trang PDF số 6 của Tiên Phả Dịch Lục, khoảng 11 giây trên CPU máy hiện tại. Vẫn sai từ, dấu và một số dòng lẫn chữ Nôm; cần hiệu đính, chưa đại diện cho mọi sách. Bộ tìm dòng phù hợp với các hàng ngang; nhiều cột, mực nhạt hoặc bố cục khác nhau có thể cần vùng mẫu cho quyển. Không tự coi kết quả OCR là nhãn chuẩn, không tự đánh dấu trang hoàn thành. Khi không có nội dung Quốc ngữ đủ dùng, tác vụ báo lỗi và giữ phần Nôm đã xong.

Cấu hình trong `backend/.env` (Google Cloud Vision đã bỏ):

```dotenv
VI_OCR_PROVIDER=vietocr
VI_OCR_THREADS=4
```

**Local không đồng nghĩa với GPU:** VietOCR hiện chạy bằng CPU; không cần GPU hoặc CUDA. Phần Nôm vẫn gửi tới Kim Hán Nôm như trước. Mô hình được nạp một lần khi cần, các lượt nhận dạng dùng chung phiên ONNX và được xếp tuần tự để tránh chiếm quá nhiều RAM/CPU.

Tesseract `vie+eng` là dự phòng khi VietOCR không tìm được dòng có nội dung. Trên máy này đã có sẵn. Để cài dự phòng trên Windows, cài 7-Zip rồi chạy `py backend/setup_vietnamese_ocr.py`; script chỉ giải nén Tesseract vào `backend/.tools/tesseract/`, không chạy trình cài hệ thống. Trên Ubuntu cài `tesseract-ocr`, `tesseract-ocr-vie`, `tesseract-ocr-eng`. Có thể đặt `TESSERACT_CMD` và `TESSDATA_DIR` nếu đường dẫn khác mặc định. Đặt `VI_OCR_PROVIDER=tesseract` nếu cần chủ động chuyển hẳn sang Tesseract cho tài liệu chữ in.

VietOCR dùng luồng OCR toàn bộ quyển và cơ chế checkpoint theo từng phần. Đổi mô hình không làm mất phần Nôm đã lưu hoặc văn bản đã hiệu đính. Nội dung đã sửa vẫn được giữ khi chạy hoặc tiếp tục tác vụ; không tự thay thế văn bản bằng kết quả mới.

### Font chữ Hán Nôm đã đóng gói

Ứng dụng tải font từ chính backend/frontend đang chạy: Nôm Na Tống v5.19 và hai font dự phòng đầy đủ bộ chữ HanaMin A/B (tên web `Nom Workspace Han A/B`). Không cần cài font vào Windows để xem trên web. Các chữ ngoài BMP như `𠊛𡗶𠬠𡗺` được giữ nguyên; không cắt bộ chữ theo văn bản mẫu. Tệp, checksum và độ phủ nằm trong `frontend/public/fonts/manifest.json`; giấy phép nằm trong `frontend/public/licenses/`.

Font đã kèm trong mã nguồn. Nếu cần tạo lại tài nguyên, chạy tại thư mục gốc (cần Internet ở bước tải):

```powershell
py -m pip install --target .tools/font-build -r frontend/scripts/requirements-fonts.txt
py frontend/scripts/setup_fonts.py
npm --prefix frontend run check:fonts
```

Chuyển TTF sang WOFF2 toàn bộ bộ chữ có thể mất nhiều phút trên CPU. `npm run build` tự kiểm tra đủ font và checksum trước khi biên dịch. Trong Cài đặt có trạng thái tải font Nôm. Nếu thấy ô vuông, kiểm tra yêu cầu `/fonts/` trong trình duyệt và tải lại bằng Ctrl + F5.

### Vùng mẫu dùng cho toàn bộ quyển — chỉ khi cần

1. Mở một trang đại diện. Mặc định có thể OCR cả trang, không cần bước này.
2. Bật công cụ vẽ, vẽ/chọn một vùng trên ảnh rồi mở **Vùng mẫu cho cả quyển**.
3. Bấm **Gán vùng đang chọn cho Nôm** hoặc **... Quốc ngữ**. Có thể gán nhiều vùng, phù hợp với cả bố cục chia nửa trang lẫn nhiều hàng Nôm trên/Quốc ngữ dưới.
4. Bấm **Lưu mẫu cho toàn bộ quyển**. Mẫu dùng tọa độ tỷ lệ 0–1, nên áp dụng được khi kích thước ảnh các trang khác nhau. Chỉ giới hạn vùng đọc, không sao chép chữ hay nhãn giả sang các trang.
5. Lưu nháp trang mẫu nếu vừa vẽ rồi mới chạy theo quyển. Có thể xóa box mẫu sau khi lưu profile; profile vẫn được giữ.

Các lượt OCR mới dùng mẫu đã lưu. Tác vụ đang chạy/tiếp tục giữ phạm vi mẫu đã chốt khi tạo tác vụ. Bản hiệu đính đã có không bị ghi đè. **Bỏ vùng mẫu → Lưu mẫu** trở về đọc tự động toàn trang. Với các trang có bố cục khác nhau nhiều, chia phạm vi hoặc hiệu chỉnh riêng, không áp một mẫu sai cho cả sách.

## 3. Chuẩn bị và chia sách cho ba thành viên

Mỗi người đặt các PDF được phân công vào `backend/data/raw_data/` trên máy mình. Nếu mỗi người làm 5 quyển thì thư mục trên từng máy chỉ cần chứa 5 quyển đó. Ứng dụng đọc toàn bộ PDF trong thư mục, không giới hạn cứng 5 hoặc 15 và không tự chia sách theo tài khoản.

```text
backend/
  .env
  data/
    raw_data/
      <Tên sách thứ nhất>.pdf
      <Tên sách thứ hai>.PDF
      Tiên Phả Dịch Lục, Nôm, 2 volumes_Y.pdf
      Tiên Phả Dịch Lục_Dịch.txt
    .workspace/
      workspace.sqlite3
      books/
      ocr/
    processed_images/
    dictionaries/
    output_alignment/
```

- Chỉ PDF là sách. File `.PDF` viết hoa cũng được nhận.
- `Tiên Phả Dịch Lục_Dịch.txt` là Quốc ngữ đối chiếu của `Tiên Phả Dịch Lục, Nôm, 2 volumes_Y.pdf`, **không phải sách thứ 16**.
- TXT được gắn khi tên tác phẩm khớp duy nhất sau khi bỏ hậu tố `_Dịch`, `_Y`, phần mô tả sau dấu phẩy và chuẩn hóa khoảng trắng. Nếu tên mơ hồ thì không tự đoán.
- Giữ TXT ở UTF-8. Các dấu `Page ...` trong TXT được giữ nguyên; chúng không tự tạo trang hay cặp căn chỉnh.
- PDF có sẵn được đọc trực tiếp tại `raw_data/`, không sao chép thành một bộ nguồn khác. Tải PDF qua giao diện cũng lưu vào thư mục này.
- Sau khi bắt đầu làm, giữ nguyên tên và nội dung PDF. Đổi tên sẽ có thể được nhận thành sách khác; thay nội dung cùng tên chưa có cơ chế cập nhật lại số trang/cache an toàn.
- Quét lại không xóa nhãn hoặc tiến trình. PDF lỗi được báo riêng, các PDF hợp lệ vẫn được nhận.


## 4. Luồng làm việc: chọn sách → gắn nhãn → lưu và OCR toàn bộ → hiệu đính

### Bước 1 — Chọn sách

Vào **Tủ sách** hoặc chọn sách trong danh sách **Tài liệu đang làm việc**. Ứng dụng mở danh sách trang và ảnh PDF để đối chiếu. Mỗi trang có chung một ảnh và hai nội dung: **Hán / Nôm**, **Quốc ngữ**; không tạo hai bản sao trang theo ngôn ngữ.

Số trang là **vị trí trong PDF, bắt đầu từ 1**, không phải số in trong bản chụp. Ví dụ ảnh `.006.jpg` là trang PDF thứ 6. Khi mở lại, ứng dụng khôi phục sách, trang và mục làm việc đã lưu gần nhất.

### Bước 2 — Xem danh sách và gắn nhãn

Trong **Gắn nhãn và OCR toàn bộ sách**, xem ảnh từng trang, chọn nhãn và đánh dấu có OCR hay bỏ qua. Bấm số trang để mở ảnh lớn phía dưới. Có ô tìm số trang và nút **Gắn trang chưa phân loại là nội dung** để thao tác nhanh.

| Nhãn | Ý nghĩa |
| --- | --- |
| Hán Nôm (`ch`) | Nội dung chính, có thể chứa cả Nôm và Quốc ngữ trên cùng trang |
| Quốc ngữ (`vi`) | Trang chủ yếu chứa Quốc ngữ |
| Giới thiệu (`intro`), Chú thích (`ref`), Mục lục (`toc`) | Phân loại trang đặc biệt; tự quyết định có OCR bằng checkbox |
| Trang trắng (`blank`) | Luôn bỏ qua OCR |
| Chưa phân loại (`misc`) | Có thể gắn nhãn tiếp; nếu vẫn được chọn khi bắt đầu thì được xếp vào nội dung Hán Nôm |

**Bỏ chọn Thực hiện OCR** để loại trang bìa, phụ bản hoặc bất kỳ trang nào không cần xử lý. Trang bị bỏ qua vẫn còn trong sách và giữ văn bản/nhãn cũ, nhưng không được đưa vào hàng đợi OCR mới. Nếu loại một trang còn đang chờ trong tác vụ, worker bỏ qua khi đến trang đó. Trang đã bắt đầu xử lý có thể hoàn tất lượt đang chạy.

Nhãn được lưu tự động sau khoảng 0,8 giây và có bản nháp trình duyệt ngay khi sửa. Việc gắn nhãn tự động lưu **chưa gọi OCR**; nút Lưu nhãn & OCR ở bước sau là thao tác bắt đầu cả quyển.

### Bước 3 — Lưu để bắt đầu OCR toàn bộ trang đã chọn

Kiểm tra **Cấu hình OCR Nôm cho sách** rồi bấm **Lưu nhãn & OCR toàn bộ sách**. Đây là thao tác OCR chính; không cần bấm OCR ở từng trang, cũng không cần chọn khoảng trang.

- Kiểu 1: thông thường dọc; 2: hành chính; 3: ngoại cảnh; 4: thông thường ngang.
- Chiều 1: dọc, phải → trái; chiều 2: ngang.
- Loại chữ 0: chưa biết; 1: Hán; 2: Nôm.
- Trang PDF thứ 6 của Tiên Phả Dịch Lục có các hàng chữ ngang, phù hợp với kiểu 4, chiều 2, chữ Nôm.

Nút này lưu các chỉnh sửa đang có và danh sách nhãn, rồi tạo tác vụ cho **toàn bộ các trang được chọn trong quyển**. Backend xử lý tuần tự để lưu checkpoint an toàn; “OCR toàn bộ” là phạm vi cả sách, không có nghĩa là gửi tất cả ảnh cùng lúc. Mỗi ngôn ngữ đã xong được ghi ngay vào SQLite/JSON và đưa vào ô văn bản còn trống, không đợi cả quyển xong. Giao diện lấy tiến trình khoảng mỗi 1,5 giây.

Nôm dùng Kim Hán Nôm. Quốc ngữ dùng VietOCR local, trừ quyển có TXT đối chiếu thì lấy trực tiếp từ TXT. Không bắt buộc vẽ box. Vùng mẫu cho cả quyển vẫn là công cụ tùy chọn khi bố cục cần giới hạn vùng đọc.

Nếu thiếu token, mô hình hoặc dịch vụ gặp lỗi, nhãn vẫn được giữ; tác vụ dừng và hiển thị nguyên nhân để xử lý rồi tiếp tục. Không âm thầm gọi lại liên tục. Mỗi lần chỉ chạy một tác vụ OCR; vẫn được sửa các trang đã có kết quả.

### Bước 4 — Hiệu đính ngay khi từng phần xuất hiện

1. Mở trang đã có kết quả, đối chiếu với ảnh bên cạnh.
2. Trong **Hán / Nôm**, sửa văn bản và bấm từng chữ để tra từ điển, âm đọc, nghĩa và dị thể.
3. Trong **Quốc ngữ**, sửa dấu, từ và đoạn tương ứng. Với TXT, duyệt lại bản ghép nháp theo số dòng Nôm.
4. Có thể tiếp tục đổi nhãn hoặc bỏ qua trang. Box mặc định không bắt buộc; có thể vẽ thêm hoặc lấy box đã phát hiện trong **Box tùy chọn**, không chạy lại OCR.
5. Văn bản tự lưu khoảng 0,8 giây sau khi ngừng nhập. Rời ô cũng lưu. Mỗi mục có nút **Lưu Hán / Nôm hiện tại**, **Lưu Quốc ngữ hiện tại**; chân trang còn nút lưu toàn trang và Ctrl + S.
6. Khi đã đọc lại đầy đủ, bấm **Hoàn thành & tiếp theo**. OCR xong không tự đánh dấu đã duyệt; trang đã sửa vẫn được giữ khi các trang khác tiếp tục OCR.

Lưu dùng từng trường: sửa Quốc ngữ không xóa kết quả Nôm vừa về và ngược lại. Worker chỉ điền ô còn trống; không ghi đè văn bản đã hiệu đính, kể cả khi bạn sửa ngay trong lúc trang đang chạy. Giao diện giữ phần đang gõ khi nhận tiến trình mới.

### Quốc ngữ từ file TXT đi kèm

`Tiên Phả Dịch Lục_Dịch.txt` là nguồn đối chiếu của PDF cùng tên, không phải sách mới. TXT hiện có hai mốc **Page 06**, **Page 178**, không có ranh giới cho mọi trang PDF.

Theo cách ghép đã chọn, ứng dụng **trích văn bản nguyên gốc từ TXT**, ghép nháp theo số hàng/cột Nôm được phát hiện trên từng trang, giữ thứ tự trong mỗi mốc. Không chạy VietOCR cho Quốc ngữ của quyển này. Vị trí đã dùng được lưu trong bảng `reference_allocations` của SQLite; trang sau tiếp tục từ dòng chưa dùng, và mốc mới bắt đầu đoạn tương ứng. Không cắt chuỗi TXT theo số ký tự hoặc dịch từ Nôm để tạo đáp án.

Nguồn được ghi dạng `txt-draft:<tên file>:<dòng đầu>-<dòng cuối>`. Đây là **ghép nháp cần duyệt**, không phải căn trang chuẩn: số dòng Nôm nhận sai, câu kéo qua trang hoặc bỏ qua trang có nội dung đều có thể làm lệch đoạn. Bạn sửa/tách/gộp trong phần hiệu đính và căn chỉnh. Khi hết đoạn TXT hoặc chưa xác định được số dòng Nôm, hệ thống dừng để kiểm tra, không tự lấy sang mốc khác. Không sửa nội dung file nguồn trong khi đang chạy sách.

## 5. Lưu, dừng và tiếp tục đúng chỗ đang làm

### Những gì được giữ

| Mục | Cách lưu |
| --- | --- |
| Nhãn và trang bỏ qua | Tự lưu vào SQLite; nháp trình duyệt ngay khi sửa |
| Tiến trình OCR | Lưu sau mỗi ngôn ngữ và mỗi trang; trạng thái hàng đợi lưu trong SQLite |
| Nội dung hai ngôn ngữ / box | Tự lưu từng trường, có nút lưu ngay và Ctrl + S |
| Căn chỉnh | Tự lưu khoảng 1,2 giây sau chỉnh sửa; vẫn có nút Lưu căn chỉnh |
| Vị trí làm việc | Lưu sách, trang và mục đang mở vào SQLite; khôi phục khi vào lại |
| Ghép TXT | Lưu đoạn đã cấp cho từng trang, mốc và checksum nguồn |
| File kết quả | Tự cập nhật snapshot và thống kê sau lưu/OCR/căn chỉnh |

Nếu mất kết nối trong khi sửa, bản nháp trình duyệt vẫn được giữ và trạng thái báo chưa lưu vào máy. Mở lại cùng trình duyệt để khôi phục và lưu tiếp. Không xóa dữ liệu trình duyệt hoặc sao lưu sang máy khác trước khi những bản nháp đó được ghi thành công vào backend.

### Dừng chủ động

1. Bấm **Lưu và tạm dừng sau trang hiện tại**; đợi **Đã tạm dừng**. Lượt đang chạy được phép hoàn tất và ghi checkpoint.
2. Lưu các nội dung đang sửa/căn chỉnh hoặc đợi trạng thái đã lưu.
3. Dừng server bằng Ctrl + C rồi mới tắt máy hoặc sao lưu.

Đóng tab khi backend vẫn chạy không dừng tác vụ. Có thể mở lại và tiếp tục xem kết quả đang về.

### Mở lại

1. Chạy backend từ cùng thư mục và cùng dữ liệu, bằng Python của môi trường đã cài.
2. Ứng dụng khôi phục sách, trang và mục đang làm. Không nhập lại sách, không xóa `.workspace/`.
3. Nếu tác vụ bị ngắt, nó hiển thị **Đã tạm dừng**. Bấm **Tiếp tục đúng phần chưa xong** để chạy phần còn lại.
4. Những trang/ngôn ngữ đã có checkpoint không bị gọi lại. Bản hiệu đính được giữ. Nếu Nôm đã xong mà Quốc ngữ chưa xong, chỉ tiếp tục phần Quốc ngữ.

Ứng dụng không tự gửi thêm ảnh ra dịch vụ ngoài khi server vừa khởi động. Nếu máy bị tắt đột ngột giữa một lượt chưa ghi checkpoint, phần đó có thể cần chạy lại; các phần đã ghi thành công vẫn được giữ. Lỗi token: cập nhật `.env`, khởi động lại rồi tiếp tục tác vụ cũ.

### Kết quả, số cặp và nhật ký

Các file dưới `backend/data/output_alignment/<book_id>/` được cập nhật tự động:

| File | Nội dung |
| --- | --- |
| `summary.json` | Số trang, trang bỏ qua, đã OCR/đã duyệt, số cặp hoàn chỉnh, cặp đã đọc lại, trùng/thiếu vế và tiến trình tác vụ |
| `pages.json` | Văn bản hai ngôn ngữ, nhãn, trạng thái, nguồn TXT và phiên bản từng trang |
| `alignments.json` | Các cặp căn chỉnh đã lưu, gồm trạng thái đọc lại |
| `pairs.csv` | Bốn cột chuẩn để đối chiếu/tổng hợp, cập nhật ngay cả khi chưa bấm xuất |
| `events.jsonl` | Nhật ký lưu nhãn, chạy/dừng/tiếp tục/hoàn tất OCR và lưu căn chỉnh |

`backend/data/output_alignment/summary.json` giữ bộ đếm tổng cho các sách trên máy. **Số cặp chỉ tính cặp căn chỉnh đã lưu**, không suy từ số trang OCR. Giao diện **Xuất dữ liệu** có liên kết tải các file đối chiếu này và các nút xuất CSV/XLSX/ZIP để bàn giao cuối cùng.

SQLite là dữ liệu chính. Các file trên là snapshot có thể dựng lại từ checkpoint; lịch sử phản hồi OCR gốc vẫn ở `.workspace/ocr/`. Không xóa các nhật ký sản xuất này khi dọn cache kiểm tra.


## 6. Tra từng chữ để hỗ trợ kiểm tra chính tả

### Cách dùng trên giao diện

1. Trong cột hiệu đính, bên dưới mỗi ô văn bản có dòng **Bấm từng chữ để tra nghĩa và dị thể**.
2. Bấm chữ Hán/Nôm cần kiểm tra. Khung từ điển bên phải hiện chữ, mã Unicode, âm Việt, nghĩa và các dạng chữ khác nếu có.
3. Có thể bấm dạng chữ khác để xem mục từ của nó. Đọc nhãn quan hệ: giản thể, phồn thể, dị thể cùng nghĩa, dị thể nghĩa chuyên biệt, v.v.
4. Nếu muốn sửa bản OCR, bấm **Thay chữ đang chọn bằng ...**. Ứng dụng thay đúng vị trí chữ đã chọn, không thay hàng loạt các chữ giống nhau.
5. Kiểm tra lại trên ảnh gốc rồi **Ctrl + S** để lưu.

Cũng có thể mở **Tra từ điển** ở cuối sidebar và tìm bằng một chữ Hán/Nôm hoặc âm đọc Việt. Chữ ở các vùng Unicode mở rộng, chẳng hạn `𠊛`, được tra theo đúng mã ký tự. Nếu vị trí chữ đã thay đổi trong lúc sửa, ứng dụng yêu cầu bấm lại chữ trước khi áp dụng thay thế.

### Nguồn và phạm vi thực tế

- Từ điển chạy tại máy; mỗi lần bấm chữ chỉ gọi API backend local, không gửi cả trang/văn bản tới một dịch vụ từ điển ngoài.
- Khi có `nom.json`, ưu tiên mục Nôm của bộ dữ liệu đó. Nếu không có mục phù hợp, tra Unihan dự phòng.
- Unihan cung cấp `kDefinition` là **nghĩa tiếng Anh**, `kVietnamese` là âm Việt khi có, cùng một số quan hệ dị thể. Không tự dịch nghĩa hoặc suy đoán nghĩa Nôm bị thiếu.
- Có chữ chỉ có âm đọc, hoặc chỉ có dị thể, không có nghĩa. Giao diện báo rõ. Không có mục từ cũng chưa chứng minh chữ OCR sai.
- Một dị thể không nhất thiết thay được cho chữ gốc trong mọi văn cảnh. Phải đối chiếu ảnh và câu gốc trước khi dùng.
- Đây là hỗ trợ đọc lại từng chữ, **chưa phải bộ tự sửa chính tả theo ngữ cảnh, đối chiếu nghĩa cả câu hay phép chấm chất lượng ≥95%**. Tra được từ điển không tự biến một cặp thành đã kiểm chứng.

### Bổ sung từ điển Nôm có nghĩa tiếng Việt

Không cần API key để dùng Unihan hiện tại. Muốn có nghĩa Nôm/Vietnamese chuyên sâu, cần bộ dữ liệu hoặc API từ điển Nôm có quyền sử dụng. Ứng dụng đã hỗ trợ nạp dữ liệu local tại:

```text
backend/data/dictionaries/nom.json
```

File UTF-8, gốc là danh sách mục từ. Mỗi mục có:

| Trường | Nội dung |
| --- | --- |
| `character` | Đúng một ký tự Hán/Nôm |
| `readings` | Danh sách âm đọc, ví dụ các chuỗi Quốc ngữ |
| `definitions` | Danh sách nghĩa tiếng Việt từ nguồn từ điển |
| `variants` | Danh sách ký tự dị thể, có thể để `[]` |
| `source` | Tên từ điển/nguồn dữ liệu |
| `source_url` | URL nguồn nếu có |

Không có bộ Nôm giả được nạp sẵn. Khi có dữ liệu/API Nôm, cần biết nguồn, giấy phép/quyền sử dụng và định dạng phản hồi để nối đúng nghĩa và dị thể. Hiện API ngoài riêng cho từ điển Nôm chưa được cấu hình.

## 7. Căn chỉnh Hán Nôm và Quốc ngữ

Sau khi OCR và lưu bản hiệu đính, mở **Căn chỉnh song ngữ**:

1. Chọn trang Nôm làm nguồn.
2. Khung **Nguồn đối chiếu của sách** ưu tiên hai văn bản Nôm/Quốc ngữ đã lưu trên cùng trang. Nếu chưa có Quốc ngữ trên trang thì dùng TXT đối chiếu của sách hoặc trang `vi` cũ. Có thể bấm **Tạo cặp nháp từ toàn bộ trang để tách/gộp sau**, hoặc chọn từng đoạn có nghĩa.
3. Chọn đoạn tương ứng trong mỗi ô và bấm **Tạo cặp từ đoạn đã chọn**, hoặc **Thêm cặp** để nhập thủ công.
4. Ghép câu bị đứt qua trang trước khi chia thành đơn vị có nghĩa. Có thể gộp hàng hoặc tách tại vị trí con trỏ ở hai vế. Một hàng có thể biểu diễn 1–n, n–1, n–m.
5. Bấm **Lưu căn chỉnh**. Các `sentence_id` được đánh lại từ 1 theo trang, dạng `<Tên sách>.<trang ít nhất 3 số>.<thứ tự câu>`.
6. Đánh dấu **Đã đọc lại** sau khi kiểm tra; dấu này quản lý lượt duyệt, không tự chứng minh tương đồng ngữ nghĩa.


Nháp căn chỉnh được giữ ngay trên trình duyệt và tự lưu vào SQLite khoảng 1,2 giây sau khi sửa. Có thể bấm **Lưu căn chỉnh** để ghi ngay; chỉ các cặp đã ghi thành công mới vào bộ đếm và file kết quả. OCR xong một quyển chưa tự tạo ra cặp ngữ liệu nếu bạn chưa căn chỉnh.

## 8. Xuất dữ liệu và bộ đếm

Lưu nháp trang và căn chỉnh trước khi mở **Xuất dữ liệu**.

| Định dạng | Nội dung |
| --- | --- |
| CSV | UTF-8 BOM, bốn cột `img_id`, `sentence_id`, `SinoNom_Char`, `ChuQN_txt` |
| XLSX | Cùng bốn cột, giữ Unicode, nội dung được ghi dạng text |
| ZIP nhãn | `Label.txt`, `fileState.txt` theo nhóm và `page_texts.json` giữ hai văn bản cả khi không có box; không kèm ảnh |

Bản tải về có bản sao trong `backend/data/output_alignment/<book_id>/`. Nhãn có đường dẫn tương đối + TAB + JSON các box bốn điểm. Nôm dọc xuất phải → trái; Nôm ngang và Quốc ngữ theo dòng trên → dưới, trái → phải. Chiều đọc được lưu theo trang khi áp dụng và lưu kết quả OCR.

Bộ đếm mục tiêu **2.000 cặp** chỉ tính hàng căn chỉnh đã lưu, đủ hai vế và không trùng văn bản. Chỉ số OCR, số trang đã duyệt và số cặp là ba việc khác nhau.


## 9. Dữ liệu lưu ở đâu và sao lưu thế nào?

| Vị trí | Vai trò |
| --- | --- |
| `backend/data/raw_data/` | PDF nguồn, TXT Quốc ngữ đối chiếu |
| `backend/data/.workspace/workspace.sqlite3` | Checkpoint sách/trang, bản hiệu đính, căn chỉnh, kết quả OCR và trạng thái tác vụ |
| `backend/data/.workspace/ocr/<page_id>/<result_id>.json` | Phản hồi OCR gốc và tham số từng lượt; không lưu Authorization header |
| `backend/data/.workspace/books/<book_id>/` | Ảnh/nhãn theo nhóm và `page_texts.json` giữ Nôm, Quốc ngữ, box Quốc ngữ nếu có |
| `backend/data/processed_images/` | Cache ảnh/thumbnail dựng từ PDF |
| `backend/data/dictionaries/` | Từ điển Unihan, giấy phép, metadata và bộ Nôm nếu bổ sung |
| `backend/data/output_alignment/` | CSV/XLSX/ZIP đã xuất |
| `backend/data/output_alignment/<book_id>/summary.json`, `pages.json`, `alignments.json`, `pairs.csv`, `events.jsonl` | Snapshot và nhật ký tự cập nhật khi lưu/OCR/căn chỉnh |

SQLite là checkpoint chính. Khi khởi động, các TXT nhãn được dựng lại từ SQLite để phục hồi việc ghi file bị gián đoạn. Kết quả OCR có thể khôi phục từ JSON của phiên bản cũ nếu chưa có trong bảng checkpoint mới.

**Trước khi sao lưu/đổi máy:** tạm dừng OCR và đợi trang đang chạy xong → lưu nháp trang → lưu căn chỉnh → dừng server → sao chép toàn bộ `backend/data/`.

Nếu muốn sao lưu gọn, tối thiểu giữ `raw_data/`, `.workspace/`, `output_alignment/` và bộ Nôm riêng nếu có. Cache ảnh và Unihan có thể dựng/tải lại. Dừng server trước khi chép SQLite để tránh thiếu dữ liệu trong file WAL. Giữ `.env` riêng theo cách an toàn; không đưa token vào gói công khai.

`backend/data/`, `.env`, dependency, cache và bản build được bỏ qua trong Git. Không xóa `.workspace/` để “làm mới giao diện”, vì đây là nơi giữ tiến trình.

## 10. Kiểm tra và xử lý sự cố

### Kiểm tra local

```powershell
py backend/check_ocr.py
py backend/test.py
npm --prefix frontend run check
npm --prefix frontend run build
```

Nếu Windows/sandbox chặn thư mục tạm của pytest, dùng thư mục tạm mới trong workspace:

```powershell
py backend/test.py --basetemp D:/OCR/.tools/tests-manual-run -o cache_dir=D:/OCR/.tools/pytest-cache
```

Không trỏ `--basetemp` vào dữ liệu sách; pytest quản lý và có thể dọn thư mục đó.

### Kiểm tra một trang qua API thật

Lệnh sau gửi ảnh trang 6 của sách chỉ định tới Kim Hán Nôm, dùng token trong `.env`:

```powershell
py backend/check_ocr.py --live --pdf "Tiên Phả Dịch Lục, Nôm, 2 volumes_Y.pdf" --page 6 --ocr-id 4 --reading-direction 2
```

Đây là lệnh kiểm tra riêng: in kết quả ra terminal, **không lập tác vụ theo quyển và không ghi checkpoint làm việc của trang**. Muốn giữ kết quả để hiệu đính/tiếp tục, chạy qua giao diện ứng dụng.

| Hiện tượng | Cách xử lý |
| --- | --- |
| Không mở được giao diện | Chạy backend, kiểm tra cổng 8000 và `/api/health`; nếu thiếu frontend thì build rồi khởi động lại |
| Cổng 8000 đã được dùng | Dừng đúng server cũ trước khi chạy lại; chỉ giữ một tiến trình trên kho |
| Không thấy sách | Kiểm tra PDF ở đúng `backend/data/raw_data/`, bấm Quét lại thư mục, đọc danh sách file lỗi |
| Không thấy TXT như sách | Đây là hành vi đúng; mở sách PDF tương ứng trong Căn chỉnh song ngữ |
| Không bấm được chạy OCR | Lưu nháp trước, kiểm tra token, phân loại hoặc lựa chọn phạm vi/trang chưa phân loại |
| Token bị từ chối | Lấy token mới của chính tài khoản, sửa `.env`, khởi động lại backend và tiếp tục tác vụ |
| API giới hạn lượt gọi / timeout | Để tác vụ dừng, chờ dịch vụ rồi bấm Tiếp tục; không chạy lặp nhiều server |
| Tắt trình duyệt giữa lúc OCR | Nếu backend vẫn chạy thì tác vụ vẫn tiếp tục; mở lại sách để xem trạng thái |
| Tắt máy giữa lúc OCR | Chạy lại backend, mở sách cũ, bấm Tiếp tục phần chưa xong; xem giới hạn trang đang dở ở phần 5 |
| Chữ Nôm hiện ô vuông | Font đã kèm trong ứng dụng; chạy `npm --prefix frontend run check:fonts`, kiểm tra tải `/fonts/`, rồi Ctrl + F5. Thiếu font không đồng nghĩa mất mã Unicode |
| Từ điển chưa sẵn sàng | Chạy `py backend/setup_dictionary.py`, tải lại thông tin/khởi động lại backend |
| Từ điển có âm nhưng không có nghĩa | Nguồn hiện không có nghĩa cho chữ đó; bổ sung bộ Nôm, không tự suy ra nghĩa |
| Sửa từ điển rồi chưa thấy dữ liệu | Kiểm tra `nom.json` UTF-8 và schema; thao tác tra mới sẽ đọc lại bộ local |
| Không xuất được CSV/XLSX | Tạo và lưu ít nhất một cặp căn chỉnh trước |
| Lỗi phiên bản trang | Giữ nội dung cần thiết, tải lại và đối chiếu bản mới; không ghi đè mù |

### Phát triển frontend

```powershell
npm --prefix frontend run dev
```

## 11. API nội bộ dành cho tích hợp

Luồng giao diện chính dùng `/workflow` để OCR cả sách. Endpoint OCR từng trang được giữ để tương thích và kiểm tra nội bộ; không phải thao tác người dùng phải bấm cho mỗi trang.

| Endpoint | Vai trò |
| --- | --- |
| `GET /api/workspace` | Sách, bộ đếm, cấu hình OCR, trạng thái từ điển |
| `POST /api/sources/sync` | Quét thêm PDF nguồn |
| `GET /api/books/{book_id}/pages` | Trang và bản hiệu đính đã lưu |
| `PUT /api/books/{book_id}/plan` | Lưu nhãn và trang bỏ qua, chưa bắt đầu OCR |
| `POST /api/books/{book_id}/workflow` | Lưu nhãn và bắt đầu OCR toàn bộ trang được chọn trong sách |
| `PATCH /api/pages/{page_id}` | Tự lưu từng trường để không ghi đè ngôn ngữ đang hoàn tất OCR |
| `GET/PUT /api/books/{book_id}/session` | Vị trí sách, trang, mục làm việc để tiếp tục |
| `GET /api/books/{book_id}/results/{filename}` | Tải thống kê, snapshot hoặc nhật ký kết quả |
| `POST /api/pages/{page_id}/ocr` | OCR một trang; có version, cấu hình và `force` tùy chọn |
| `GET /api/pages/{page_id}/ocr` | Kết quả OCR đã lưu gần nhất; không gọi dịch vụ ngoài |
| `POST /api/books/{book_id}/ocr-job` | Tạo tác vụ theo quyển/phạm vi |
| `GET /api/books/{book_id}/ocr-job` | Tác vụ gần nhất và trạng thái từng trang |
| `POST /api/ocr-jobs/{job_id}/pause` | Yêu cầu dừng sau trang hiện tại |
| `POST /api/ocr-jobs/{job_id}/resume` | Tiếp tục phần chưa xong |
| `GET /api/dictionary/lookup?character=漢` | Tra một chữ tại máy |
| `GET /api/dictionary/search?q=hán` | Tìm chữ hoặc âm đọc Việt |
| `GET /api/books/{book_id}/reference` | TXT đối chiếu của sách nếu có |

Schema đầy đủ ở **http://127.0.0.1:8000/docs**.
