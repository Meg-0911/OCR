# Nôm Workspace — OCR và căn chỉnh Hán Nôm – Quốc ngữ

Ứng dụng chạy tại máy để chọn sách, gắn nhãn/bỏ qua trang, OCR toàn bộ quyển, Gán nhãn từng chữ, tra từ điển và tạo ngữ liệu song song. Kết quả hiện dần khi từng phần hoàn tất; checkpoint theo ngôn ngữ/trang giúp dừng rồi tiếp tục đúng chỗ.

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

Mặc định giao diện chọn **Nôm + Quốc ngữ**. Không cần vẽ box: Nôm qua Kim Hán Nôm, Quốc ngữ qua **VietOCR `vgg_transformer` tinh chỉnh chữ viết tay tiếng Việt**, chạy ONNX Runtime trên CPU tại máy. Bộ tìm dòng dùng màu mực khi phù hợp hoặc ảnh xám và tọa độ Nôm thực để giảm lẫn hai lớp chữ. VietOCR nhận ảnh màu gốc của từng dòng, không chuyển sang ảnh chỉ giữ một màu mực.

Ở bước **Gắn nhãn trang**, chọn **Màu mực trong quyển** phù hợp với cả quyển: mặc định **Quốc ngữ đỏ · Hán/Nôm đen hoặc xám**, hoặc **Quốc ngữ xanh · Hán/Nôm đỏ**. Lựa chọn này điều khiển cách tách vùng trước khi nhận dạng. Nếu màu thay đổi giữa các trang, profile theo quyển không đủ; cần kiểm tra box và chỉnh vùng OCR thủ công. Đổi profile chỉ lưu cấu hình và đánh dấu lại trang; không tự chạy OCR.

Đã cài sẵn trên máy hiện tại. Khi cài máy mới, cài các thư viện trong `backend/requirements.txt` rồi tải mô hình:

```powershell
py backend/setup_vietocr.py
```

Script tải encoder/decoder ONNX, vocab và thông tin giấy phép vào `backend/.tools/vietocr/`, kiểm tra SHA256 và khóa revision `f1973b930f907c378f6e3152ce9d8658724b228a`. Nguồn: [model card chữ viết tay](https://huggingface.co/vudang449/vietocr-vietnamese-handwriting), [VietOCR gốc](https://github.com/pbcquoc/vietocr), giấy phép Apache-2.0. Chỉ bước tải cần Internet; lúc đọc Quốc ngữ không gọi dịch vụ ngoài, không cần API key. Không tự tải mô hình khi server đang xử lý sách.

**Giới hạn đã kiểm tra:** VietOCR đọc được 11 dòng viết tay trên toàn trang PDF số 6 của Tiên Phả Dịch Lục, khoảng 11 giây trên CPU máy hiện tại. Vẫn sai từ, dấu và một số dòng lẫn chữ Nôm; cần Gán nhãn, chưa đại diện cho mọi sách. Bộ tìm dòng phù hợp với các hàng ngang; nhiều cột, mực nhạt hoặc bố cục khác nhau có thể cần vùng mẫu cho quyển. Không tự coi kết quả OCR là nhãn chuẩn, không tự đánh dấu trang hoàn thành. Khi không có nội dung Quốc ngữ đủ dùng, tác vụ báo lỗi và giữ phần Nôm đã xong.

Cấu hình trong `backend/.env` (Google Cloud Vision đã bỏ):

```dotenv
VI_OCR_PROVIDER=vietocr
VI_OCR_THREADS=4
```

**Local không đồng nghĩa với GPU:** VietOCR hiện chạy bằng CPU; không cần GPU hoặc CUDA. Phần Nôm vẫn gửi tới Kim Hán Nôm như trước. Mô hình được nạp một lần khi cần, các lượt nhận dạng dùng chung phiên ONNX và được xếp tuần tự để tránh chiếm quá nhiều RAM/CPU.

Tesseract `vie+eng` là dự phòng khi VietOCR không tìm được dòng có nội dung. Trên máy này đã có sẵn. Để cài dự phòng trên Windows, cài 7-Zip rồi chạy `py backend/setup_vietnamese_ocr.py`; script chỉ giải nén Tesseract vào `backend/.tools/tesseract/`, không chạy trình cài hệ thống. Trên Ubuntu cài `tesseract-ocr`, `tesseract-ocr-vie`, `tesseract-ocr-eng`. Có thể đặt `TESSERACT_CMD` và `TESSDATA_DIR` nếu đường dẫn khác mặc định. Đặt `VI_OCR_PROVIDER=tesseract` nếu cần chủ động chuyển hẳn sang Tesseract cho tài liệu chữ in.

VietOCR dùng luồng OCR toàn bộ quyển và cơ chế checkpoint theo từng phần. Đổi mô hình không làm mất phần Nôm đã lưu hoặc văn bản đã Gán nhãn. Nội dung đã sửa vẫn được giữ khi chạy hoặc tiếp tục tác vụ; không tự thay thế văn bản bằng kết quả mới.

### Font chữ Hán Nôm đã đóng gói

Ứng dụng tải font từ chính backend/frontend đang chạy: Nôm Na Tống v5.19 và hai font dự phòng đầy đủ bộ chữ HanaMin A/B (tên web `Nom Workspace Han A/B`). Không cần cài font vào Windows để xem trên web. Các chữ ngoài BMP như `𠊛𡗶𠬠𡗺` được giữ nguyên; không cắt bộ chữ theo văn bản mẫu. Tệp, checksum và độ phủ nằm trong `frontend/public/fonts/manifest.json`; giấy phép nằm trong `frontend/public/licenses/`.

Font đã kèm trong mã nguồn. Nếu cần tạo lại tài nguyên, chạy tại thư mục gốc (cần Internet ở bước tải):

```powershell
py -m pip install --target .tools/font-build -r frontend/scripts/requirements-fonts.txt
py frontend/scripts/setup_fonts.py
npm --prefix frontend run check:fonts
```

Chuyển TTF sang WOFF2 toàn bộ bộ chữ có thể mất nhiều phút trên CPU. `npm run build` tự kiểm tra đủ font và checksum trước khi biên dịch. Trong Cài đặt có trạng thái tải font Nôm. Nếu thấy ô vuông, kiểm tra yêu cầu `/fonts/` trong trình duyệt và tải lại bằng Ctrl + F5.

### Vùng đọc chung và trang cắt riêng

Ở bước 2, chọn **Chiều đọc của sách**, rồi vẽ trực tiếp trên ảnh bằng **Vẽ vùng đọc**. Vùng đọc luôn áp dụng chung cho toàn PDF và cho các ngôn ngữ đã bật trong nhãn Hán/Nôm, Quốc ngữ ở phía trên. Không có bước chọn lại ngôn ngữ cho vùng đọc hoặc chọn phạm vi áp dụng. Khung nét đứt bao toàn ảnh cho biết mặc định đang đọc toàn trang. Vùng dùng tọa độ theo tỷ lệ ảnh, tự lưu ngay khi thả chuột và hiển thị trên mọi trang kế thừa.

Dùng **Cắt lại trang này** cho trang có bố cục khác. Vùng cắt riêng là ngoại lệ của trang đó; **Dùng vùng chung** khôi phục kế thừa toàn PDF. Trang bỏ qua không chạy OCR. Vùng đọc là chung cho hai engine, còn các nhãn ngôn ngữ quyết định engine nào chạy. Box ký tự do OCR trả về, được Gán nhãn ở bước 4. Không có nút Apply hoặc Lưu mẫu riêng.

Vùng mới dùng cho lượt OCR tiếp theo. Tác vụ đang chạy giữ vùng chung đã chốt lúc bắt đầu; vùng riêng được đọc khi xử lý từng trang. Thay vùng khiến trang liên quan cần xác nhận lại. Văn bản và box đã sửa thủ công được giữ khi nhận kết quả mới.

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
- Tải TXT tại bước 1 **Thêm nội dung**, vào ô Hán/Nôm hoặc Quốc ngữ tương ứng. Tên TXT có thể tùy ý; không tự gắn file theo tên PDF.
- Giữ TXT ở UTF-8. Các dấu `Page ...` trong TXT được giữ nguyên; chúng không tự tạo trang hay cặp căn chỉnh.
- PDF có sẵn được đọc trực tiếp tại `raw_data/`, không sao chép thành một bộ nguồn khác. Tải PDF qua giao diện cũng lưu vào thư mục này.
- Sau khi bắt đầu làm, giữ nguyên tên và nội dung PDF. Đổi tên sẽ có thể được nhận thành sách khác; thay nội dung cùng tên chưa có cơ chế cập nhật lại số trang/cache an toàn.
- Quét lại không xóa nhãn hoặc tiến trình. PDF lỗi được báo riêng, các PDF hợp lệ vẫn được nhận.


## 4. Luồng làm việc trên một màn hình

**Tủ sách** dùng để xem ảnh các trang sách và kết quả Hán Nôm/Quốc ngữ đã lưu. Bấm **Xem trang & kết quả**, tìm số trang rồi chọn trang để đọc; có thể chuyển trang tự do, kể cả trang chưa xác nhận hoặc chưa có kết quả.

Để chạy OCR hoặc sửa văn bản, mở tab **Gán nhãn OCR** và chọn sách. Bước 1 để tải TXT tùy chọn. Bước 2 chỉ hiển thị ảnh gốc, nhãn và vùng quét; không có khung văn bản hay chọn nguồn OCR/TXT. Ở bước 4, văn bản xuất hiện cạnh ảnh; chọn **Ảnh + Hán Nôm** hoặc **Ảnh + Quốc ngữ** ở cột phải. Số trang là vị trí trong PDF, bắt đầu từ 1. Nút hai mũi tên mở ảnh toàn màn hình; bấm lại hoặc Esc để thoát. Nút phần trăm đưa ảnh về vừa chiều rộng.

Trong **Gán nhãn OCR**, có bốn bước chi tiết:

1. **Thêm nội dung**: tải TXT Hán/Nôm và/hoặc Quốc ngữ nếu có, mỗi ngôn ngữ một nguồn riêng. TXT tự lưu và có thể xem lại/thay tệp. Có thể tiếp tục mà không tải TXT; bước này không chạy OCR.
2. **Gắn nhãn trang**: mặc định mọi trang mới là nội dung với cả Hán/Nôm và Quốc ngữ. Chuyển trang tự do để chỉnh ngoại lệ, không cần xác nhận từng trang. Nhãn, chiều đọc và vùng quét tự lưu; mở bước này không tự chạy OCR. Nhấn **Ctrl+A** để chọn các trang đang hiện, hoặc **Ctrl + nhấp** vào ảnh để chọn nhiều trang rồi đổi nhãn cùng lúc. Vùng chung hiển thị theo tỷ lệ trên mỗi trang, trừ trang có vùng riêng hoặc bỏ qua.
3. **Lưu & OCR toàn bộ sách**: bấm **Tiếp tục: Lưu & OCR** ở bước 2 để lưu toàn bộ nhãn rồi khởi chạy OCR. Tiến trình OCR có thanh tiến trình, trạng thái từng trang và nút Tạm dừng/Tiếp tục. Có thể chuyển trang hoặc sang bước 4 trong lúc OCR đang chạy; kết quả tiếp tục được lưu theo từng trang. Trang đã có kết quả phù hợp sẽ được bỏ qua khi tiếp tục, không tự chạy lại.
4. **Gán nhãn & hoàn thành**: sửa chữ theo box OCR trên ảnh, tra cứu chữ và bấm **Lưu & hoàn thành**. Dùng **Vẽ box chữ** để kéo thêm khung (hoặc giữ **Alt** rồi kéo trên ảnh), nhập chữ ở cột bên phải; **Chọn box chữ** để di chuyển hoặc kéo các góc chỉnh kích thước. **OCR lại trang** chạy lại riêng ảnh đang mở; kết quả mới nằm trong nháp để kiểm tra trước khi lưu. **Xóa box** hoặc phím Delete xóa box đang chọn cùng chữ tương ứng. Chỉnh sửa tự lưu; box mới phải được điền chữ trước khi hoàn thành. Vùng đọc chung vẫn thiết lập tại bước 2, TXT tải ở bước 1.

Có thể chuyển giữa bốn bước bằng thanh phía trên. Bước 1 chỉ quản lý TXT đối chiếu; bước 2 dùng cột thiết lập gọn cho nhãn và vùng quét; bước 3 hiển thị thông tin xử lý; bước 4 hiển thị văn bản đối chiếu cạnh ảnh. Các mục chính Tủ sách, Gán nhãn OCR, Căn chỉnh song ngữ và Xuất dữ liệu chỉ dùng thanh sidebar.

### Tag và OCR

Trang mới mặc định là nội dung với cả **Hán/Nôm + Quốc ngữ**. Hai tag ngôn ngữ bật độc lập, phải giữ ít nhất một tag. Các tag giới thiệu, chú thích, mục lục, trang trắng hoặc khác độc lập với lựa chọn ngôn ngữ. **Bỏ qua OCR** loại trang khỏi xử lý; trang trắng luôn bỏ qua. Có thể gắn tag cho nhiều trang cùng lúc ở bước 2 bằng Ctrl+A hoặc Ctrl + nhấp. Trang `misc` cũ được chuyển sang nội dung song ngữ một lần khi nâng cấp schema.

Bấm **OCR toàn sách** để chạy các trang còn cần xử lý, theo các ngôn ngữ đã bật. Nôm dùng Kim Hán Nôm, mặc định chữ Nôm, chiều đọc chọn ở bước 2 và kiểu thông thường tương ứng; Quốc ngữ dùng engine local. Kết quả lưu theo từng ngôn ngữ và xuất hiện ngay, kèm tọa độ box nhận dạng. OCR xử lý tuần tự và có thể tạm dừng/tiếp tục từ checkpoint.

### Gán nhãn và xác nhận

Di chuột hoặc chuyển focus tới dòng/ký tự ở cột phải để ảnh cuộn tới và tô sáng box OCR tương ứng. Bộ tách vùng dùng profile mực đã chọn ở bước **Gắn nhãn trang**. Với trang Nôm mực đen xen Quốc ngữ mực đỏ, hoặc Nôm đỏ xen Quốc ngữ xanh, ứng dụng tách nét mực và khoảng trống thực để lấy box ký tự, ghép các hàng sát nhau trước khi nhận dạng rồi ánh xạ về tọa độ ảnh gốc. Chỉ gán chữ khi số chữ OCR khớp số vùng ký tự; chỗ chưa ghép được hiện `□` và phải sửa trước khi hoàn thành. Không chia đều box dòng để giả lập tọa độ chữ. Nếu bố cục chưa tách được, giữ box dòng thực do engine trả về. Bấm nút tra cạnh ô chữ Nôm để tra từ điển và thay dị thể.

Ảnh scan dùng cho OCR được dựng lại từ PDF ở độ phân giải cao hơn ảnh thu nhỏ; tọa độ được đổi về cùng hệ với ảnh hiển thị. Chiều đọc độc lập với loại mô hình Kim Hán Nôm: loại thông thường dùng `ocr_id=1`, không dùng `ocr_id=4` (y học) để chọn chiều ngang. Bản nâng cấp vô hiệu checkpoint OCR tự động của pipeline cũ khi tiếp tục; trang đã xác nhận và trường đã sửa tay vẫn được giữ.

Văn bản và vùng quét tự lưu; Ctrl + S lưu ngay văn bản. Tự lưu hoặc OCR xong vẫn là **Chưa xác nhận**. Bước 4 cho phép chuyển trang và trở lại các bước khác mà không cần xác nhận trang hiện tại; nháp được giữ khi đổi trang. Không thể xác nhận trang còn đang chờ/chạy trong tác vụ OCR đang hoạt động. Bộ đếm hoàn thành ở Tủ sách chỉ tính các trang đã xác nhận; đủ các trang nội dung thì hiện **Đã hoàn thành quyển**. Khi mở lại sách, bước đang làm được khôi phục; OCR tiếp tục bỏ qua kết quả đã hoàn tất phù hợp, còn **OCR lại trang** dùng khi cần chạy lại riêng một ảnh.

### Nguồn TXT hoặc OCR ngay cạnh ảnh

Tải hoặc thay TXT chỉ tại bước 1 **Thêm nội dung**. Ở bước 4, nếu ngôn ngữ đó đã có TXT, chọn **Nguồn đối chiếu: TXT đã tải** để xem lại. Hỗ trợ UTF-8, tối đa 2 MB; mỗi sách có thể lưu riêng hai bản TXT. Bản TXT được giữ nguyên làm tham chiếu phía trên bản Gán nhãn trong cùng cột. OCR vẫn chạy để lấy văn bản và bounding box; TXT không thay engine hoặc xóa kết quả OCR.

Nếu TXT có dấu `******* Page 06 *******` hoặc ký tự ngắt trang form feed, cột tham chiếu hiển thị phần có số trang tương ứng. Nếu không có ranh giới trang, hiển thị toàn TXT để người Gán nhãn tự đối chiếu; không tự chia theo số ký tự hay số dòng Nôm. Chuyển **Nguồn: OCR** để tập trung vào bản OCR. Nội dung TXT được lưu trong SQLite và dùng được sau khi mở lại ứng dụng.

## 5. Lưu, dừng và tiếp tục đúng chỗ đang làm

### Những gì được giữ

| Mục | Cách lưu |
| --- | --- |
| Nhãn và trang bỏ qua | Tự lưu vào SQLite; nháp trình duyệt ngay khi sửa |
| Tiến trình OCR | Lưu sau mỗi ngôn ngữ và mỗi trang; trạng thái hàng đợi lưu trong SQLite |
| Nội dung hai ngôn ngữ / box | Tự lưu từng trường và Ctrl + S |
| Căn chỉnh | Tự lưu khoảng 1,2 giây sau chỉnh sửa; vẫn có nút Lưu căn chỉnh |
| Vị trí làm việc | Lưu sách, trang và mục đang mở vào SQLite; khôi phục khi vào lại |
| Nguồn TXT | Lưu tên file và nguyên văn riêng cho Nôm/Quốc ngữ trong SQLite |
| File kết quả | Tự cập nhật snapshot và thống kê sau lưu/OCR/căn chỉnh |

Nếu mất kết nối trong khi sửa, bản nháp trình duyệt vẫn được giữ và trạng thái báo chưa lưu vào máy. Mở lại cùng trình duyệt để khôi phục và lưu tiếp. Không xóa dữ liệu trình duyệt hoặc sao lưu sang máy khác trước khi những bản nháp đó được ghi thành công vào backend.

### Dừng chủ động

1. Bấm **Tạm dừng**; trạng thái chuyển sang **Đang dừng OCR**. Lượt nhận dạng đang gửi được phép hoàn tất và ghi checkpoint; tác vụ dừng trước ngôn ngữ hoặc trang kế tiếp. Khi **OCR tạm dừng**, có thể bấm **Tiếp tục OCR**; phần ngôn ngữ đã xong không bị gọi lại.
2. Lưu các nội dung đang sửa/căn chỉnh hoặc đợi trạng thái đã lưu.
3. Dừng server bằng Ctrl + C rồi mới tắt máy hoặc sao lưu.

Đóng tab khi backend vẫn chạy không dừng tác vụ. Có thể mở lại và tiếp tục xem kết quả đang về.

### Mở lại

1. Chạy backend từ cùng thư mục và cùng dữ liệu, bằng Python của môi trường đã cài.
2. Ứng dụng khôi phục sách, trang và mục đang làm. Không nhập lại sách, không xóa `.workspace/`.
3. Nếu tác vụ bị ngắt, nó hiển thị **Đã tạm dừng**. Bấm **Tiếp tục đúng phần chưa xong** để chạy phần còn lại.
4. Những trang/ngôn ngữ đã có checkpoint không bị gọi lại. Bản Gán nhãn được giữ. Nếu Nôm đã xong mà Quốc ngữ chưa xong, chỉ tiếp tục phần Quốc ngữ.

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

1. Trong cột Gán nhãn, bên dưới mỗi ô văn bản có dòng **Bấm từng chữ để tra nghĩa và dị thể**.
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

Sau khi OCR và lưu bản Gán nhãn, mở **Căn chỉnh song ngữ**:

1. Chọn trang Nôm làm nguồn; ảnh gốc hiện trong khung riêng phía trên hai văn bản để dễ đối chiếu, bấm **Mở ảnh kích thước đầy đủ** để xem lớn.
2. Bấm **Tự căn toàn sách** để ghép theo cùng số trang và thứ tự dòng. Nguồn Quốc ngữ ưu tiên văn bản cùng trang, rồi trang `vi` tương ứng, rồi TXT có dấu trang hoặc form feed. TXT không có ranh giới trang chỉ tự căn khi sách có một trang; không tự chép toàn TXT vào mọi trang.
3. Tự căn thay toàn bộ cặp hiện có sau khi xác nhận. Mỗi dòng dư ở một bên được giữ thành cặp chưa đủ vế để bổ sung thủ công; mọi cặp mới đều ở trạng thái chưa duyệt.
4. Kiểm tra từng cặp trên ảnh và văn bản nguồn. Có thể gộp hàng hoặc tách tại vị trí con trỏ ở hai vế; tự ghép theo dòng chỉ là bản nháp, không xác nhận tương đồng ngữ nghĩa.
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
| `backend/data/.workspace/workspace.sqlite3` | Checkpoint sách/trang, bản Gán nhãn, căn chỉnh, kết quả OCR và trạng thái tác vụ |
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

Đây là lệnh kiểm tra riêng: in kết quả ra terminal, **không lập tác vụ theo quyển và không ghi checkpoint làm việc của trang**. Muốn giữ kết quả để Gán nhãn/tiếp tục, chạy qua giao diện ứng dụng.

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
| `GET /api/books/{book_id}/pages` | Trang và bản Gán nhãn đã lưu |
| `PUT /api/books/{book_id}/plan` | Lưu nhãn và trang bỏ qua, chưa bắt đầu OCR |
| `POST /api/books/{book_id}/workflow` | Lưu nhãn và bắt đầu OCR toàn bộ trang được chọn trong sách |
| `PATCH /api/pages/{page_id}` | Tự lưu từng trường để không ghi đè ngôn ngữ đang hoàn tất OCR |
| `GET/PUT /api/books/{book_id}/session` | Vị trí sách, trang, mục làm việc để tiếp tục |
| `GET /api/books/{book_id}/results/{filename}` | Tải thống kê, snapshot hoặc nhật ký kết quả |
| `POST /api/pages/{page_id}/ocr` | OCR một trang; có version, cấu hình và `force` tùy chọn |
| `GET /api/pages/{page_id}/ocr` | Kết quả OCR đã lưu gần nhất; không gọi dịch vụ ngoài |
| `POST /api/books/{book_id}/ocr-job` | Tạo tác vụ theo quyển/phạm vi |
| `GET /api/books/{book_id}/ocr-job` | Tác vụ gần nhất và trạng thái từng trang |
| `POST /api/ocr-jobs/{job_id}/pause` | Yêu cầu dừng tại checkpoint ngôn ngữ/trang tiếp theo |
| `POST /api/ocr-jobs/{job_id}/resume` | Tiếp tục phần chưa xong |
| `GET /api/dictionary/lookup?character=漢` | Tra một chữ tại máy |
| `GET /api/dictionary/search?q=hán` | Tìm chữ hoặc âm đọc Việt |
| `GET /api/dictionary/reverse?q=thiên%20địa` | Tìm chữ theo từng tiếng Quốc ngữ; không dịch nghĩa cả cụm |
| `GET /api/books/{book_id}/reference` | TXT Quốc ngữ đã tải lên nếu có |
| `GET /api/books/{book_id}/text-sources` | Hai nguồn TXT đã tải cho sách |
| `PUT /api/books/{book_id}/text-sources/{han hoặc vi}` | Lưu nguồn TXT theo ngôn ngữ |

Schema đầy đủ ở **http://127.0.0.1:8000/docs**.
