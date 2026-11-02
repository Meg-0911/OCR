# Hướng dẫn chạy Nôm Workspace

## 1. Cài trên máy mới

Cần Git, Python 3.13 và Node.js 22.12 trở lên. Đã thử trên Windows: Python 3.13.5, Node.js 24.11.1, npm 11.6.2. Chưa kiểm tra trực tiếp trên Ubuntu. Backend dùng CPU, chưa nạp mô hình OCR; RAM phụ thuộc kích thước PDF, nên có ít nhất 4 GB cho luồng thông thường.

Mở terminal tại thư mục repo. Dùng virtualenv để tránh ảnh hưởng Python hệ thống.

Windows PowerShell:

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
npm --prefix frontend ci
npm --prefix frontend run build
.venv\Scripts\python.exe run.py
```

Ubuntu với Python 3.13 và Node.js đã cài:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
npm --prefix frontend ci
npm --prefix frontend run build
.venv/bin/python run.py
```

Mở **http://127.0.0.1:8000**. Giữ terminal Python chạy; Ctrl + C để dừng. Sau khi sửa frontend, chạy lại build; sau khi sửa backend, khởi động lại Python. Muốn hot reload frontend, chạy `npm --prefix frontend run dev` ở terminal thứ hai và mở địa chỉ Vite in ra.

## 2. Thử bộ minh họa

Ứng dụng tạo sách **Thiên tự văn – Minh họa**, gồm 12 trang dựng và sáu cặp mẫu. Đây không phải ảnh sách được giao hay đầu ra mô hình. Chọn **Hiệu đính OCR** để thử trước khi nhập sách thật.

## 3. Nhập và phân loại

1. Giữ nguyên tên PDF được giao. Đặt file vào `data/` hoặc bấm **Nhập tài liệu** rồi chọn/kéo thả PDF.
2. PDF phải hợp lệ, không mật khẩu. Giới hạn tải qua giao diện: **150 MB**; sách lớn hơn dùng `data/`.
3. Bản gốc được sao chép vào `data/raw_data/<book_id>/`; nguồn trong `data/` không đổi. Kiểm tra hai bản cùng phạm vi nội dung trước khi OCR hàng loạt ở giai đoạn sau.
4. Sách mới thuộc **Chưa phân loại / Khác**. Chọn nhóm ở cuối cột hiệu đính rồi **Lưu bản nháp**. Có `ch`, `vi`, `intro`, `ref`, `toc`, `blank`, `misc`.
5. Trang đánh số theo vị trí PDF, từ 001. JPEG chỉ render khi mở hoặc lưu, chưa có tác vụ tách hàng loạt.

Một tên PDF chỉ nhập một lần; nếu đã tồn tại, mở sách cũ để tiếp tục. Mọi trang có bản dịch, kể cả bìa hoặc mục lục, vẫn cần dóng hàng theo yêu cầu gốc.

## 4. Hiệu đính từng trang

1. Chọn sách và nhóm trang. Lọc trạng thái hoặc tìm số trang ở cột trái.
2. Bật **Vẽ vùng mới**, kéo trên ảnh để tạo box.
3. Dùng công cụ chọn để kéo vùng; kéo một trong bốn điểm góc để đổi kích thước.
4. Nhập nội dung ở ô tương ứng bên phải. Nút thùng rác xóa vùng; nút khôi phục dưới phần phân loại quay về bản đã lưu gần nhất.
5. **Ctrl + S** hoặc **Lưu bản nháp** ghi SQLite và nhãn. **Hoàn thành & tiếp theo** ghi `fileState = 1`, mở trang chờ kế tiếp trong bộ lọc.

“Bản nháp trên trình duyệt” nghĩa là **chưa ghi vào backend**. Nháp tự giữ bằng localStorage khi chuyển màn hình; cần lưu trước khi đổi trình duyệt, xóa dữ liệu duyệt web hoặc xuất file. Sửa rồi lưu nháp trên trang đã hoàn thành sẽ đưa trang về chờ duyệt. Xung đột phiên bản giữa hai cửa sổ bị từ chối; tải lại để nhận bản mới.

Nhóm văn bản chỉ được hoàn thành khi có vùng và mọi vùng đều có nội dung. Trang trắng hoặc không liên quan có thể hoàn thành không có box.

Với ảnh có hai ngôn ngữ: lưu ở một nhóm trước rồi bấm **Tạo bản Quốc ngữ / Hán Nôm**. Bản còn lại giữ cùng ảnh/số trang, bắt đầu với box rỗng để gán nhãn riêng. Nếu đã có bản ở nhóm kia thì không tạo trùng.

Loại số trang, tiêu đề, chân trang và ảnh minh họa. Mỗi box đúng bốn điểm, nằm trong ảnh. UI hiện chỉnh box chữ nhật. Nôm dọc xuất phải → trái, trên → dưới; Quốc ngữ theo dòng trên → dưới, trong dòng trái → phải. Nôm ngang và ảnh hai trang cần bộ cấu hình ở bước sau.

## 5. Căn chỉnh song ngữ

1. Mở **Căn chỉnh song ngữ**, chọn trang Nôm và **Thêm cặp**.
2. Nhập hai vế tương ứng. Ghép câu bị ngắt qua trang trước khi chia thành các đơn vị có ý nghĩa.
3. Nút liên kết gộp hàng hiện tại với hàng tiếp theo. Có thể biểu diễn 1–n, n–1, n–m bằng nội dung trong cùng ô.
4. Để tách: đặt con trỏ tại điểm tách trong từng ô của hai vế, rồi bấm tách. Cả hai bên phải có chữ trước và sau con trỏ.
5. **Đã đọc lại** chỉ quản lý lượt kiểm tra, không xác nhận đúng nghĩa. **Lưu căn chỉnh** ghi vào máy và đánh lại số câu từ 1 theo trang, ví dụ `Tên sách.024.1`.

Nháp căn chỉnh cũng được giữ trong trình duyệt đến khi lưu. Gộp chỉ nối nội dung, chưa phân tích ngữ nghĩa.

Bộ đếm ở đầu mỗi màn hình theo dõi mục tiêu **2.000 cặp** trên toàn bộ sách thật. Mỗi hàng căn chỉnh đã lưu và đủ hai vế tính là một cặp; bản nháp, bộ minh họa, hàng thiếu nội dung và cặp trùng văn bản không được cộng. Đối chiếu trùng có chuẩn hóa Unicode, khoảng trắng và chữ hoa/thường Quốc ngữ. Với các hàng gộp 1–n/n–1/n–m, mỗi hàng vẫn tính là một cặp, không tự tách câu để tăng số lượng.

Sau khi **Lưu căn chỉnh**, bộ đếm cập nhật tổng, số đã đọc lại và số còn thiếu. Khi thiếu, tiếp tục căn chỉnh hoặc dùng **Bổ sung tài liệu** để nhập thêm sách. Khi đạt/vượt 2.000, số còn thiếu về 0 và trạng thái đổi sang đã đủ mục tiêu. Đây là thống kê số lượng, không xác nhận độ tương đồng ngữ nghĩa. Số liệu được tính từ SQLite và giữ qua lần khởi động lại.

Nút thu/mở sidebar nằm ở góc trái thanh trên; trạng thái được nhớ trong trình duyệt, kể cả khi chuyển màn hình hoặc tải lại.

## 6. Xuất dữ liệu

Lưu nháp trang và căn chỉnh trước, sau đó mở **Xuất dữ liệu**.

| Định dạng | Nội dung |
| --- | --- |
| CSV | UTF-8 BOM; `img_id`, `sentence_id`, `SinoNom_Char`, `ChuQN_txt` |
| XLSX | Cùng bốn cột, giữ Unicode, ghi nội dung nguồn dưới dạng text |
| ZIP nhãn | `Label.txt`, `fileState.txt` của `ch`, `vi`, `intro`, `ref`, `toc`; **không gồm ảnh** |

`img_id` không chứa thư mục. Nhãn dùng một TAB giữa đường dẫn và JSON. Box có `transcription`, `points` đúng bốn điểm. Trạng thái dùng 0/1. File tải về trình duyệt và lưu bản sao trong `data/output_alignment/<book_id>/`.

Đây là bản xuất làm việc, chưa phải gói đồ án đầy đủ. Ảnh nằm trong `data/.workspace/books/<book_id>/<nhóm>/` và cache trong `data/processed_images/`. Khi chưa có từ điển, mọi cặp XLSX đều đỏ. Không thể suy ra đạt ≥95% từ tỷ lệ duyệt trang.

## 7. Tiến trình và sao lưu

`data/.workspace/workspace.sqlite3` là checkpoint chính. TXT được dựng lại từ SQLite lúc khởi động để phục hồi ghi file bị gián đoạn. Dừng server rồi sao lưu `data/.workspace/`, `data/raw_data/`, `data/output_alignment/`; có thể sao lưu thêm `data/processed_images/` để tránh render lại. Lưu nháp trên trình duyệt vào backend trước khi sao lưu. Không commit dữ liệu vào Git.

Chỉ chạy một tiến trình backend trên kho. Phiên bản hiện tại phục vụ cá nhân tại `127.0.0.1`, chưa có tài khoản, phân quyền, cộng tác nhiều người hoặc tác vụ nền hàng loạt.

## 8. Kiểm tra và xử lý lỗi

```powershell
.venv\Scripts\python.exe backend/test.py
npm --prefix frontend run check
npm --prefix frontend run build
```

- **Yêu cầu kết nối:** chạy Python, kiểm tra cổng 8000. `/api/health` phải trả `status: ok`.
- **Trang chủ 404:** build frontend rồi khởi động lại backend để mount `frontend/dist/`.
- **Không thấy nguồn:** đặt PDF vào `data/`, đóng và mở lại hộp nhập.
- **PDF không đọc được:** kiểm tra file không hỏng, không mật khẩu.
- **Xung đột trang:** giữ nội dung cần thiết, tải lại để nhận bản mới.
- **Chữ Nôm ô vuông:** cài font đủ ký tự như HAN NOM A/B hoặc Nom Na Tong. App ưu tiên các font này nếu có trên máy; chưa phân phối font Nôm riêng.
- **Không xuất CSV/XLSX:** cần ít nhất một cặp căn chỉnh đã lưu.

## 9. Tích hợp tiếp theo

Chưa cần API key, token hay mô hình trả phí. `backend/ocr.py` định nghĩa adapter và báo chưa cấu hình. Chờ tài liệu API Kim Hán Nôm và từ điển để triển khai OCR, spellcheck và đánh giá. Hiện không sử dụng prompt mô hình. Deskew, cập nhật PDF, căn chỉnh tự động và gói nộp cuối cùng thuộc giai đoạn sau.
