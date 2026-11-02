# Đối chiếu yêu cầu và phạm vi giai đoạn đầu

Nguồn chính: [Quy_định_đồ_án.pdf](Quy_định_đồ_án.pdf), 13 trang. Bản Gemini chỉ tham khảo hướng triển khai.

| Nội dung | Quy định gốc | Repo giai đoạn đầu |
| --- | --- | --- |
| Công nghệ | Không giới hạn, ưu tiên Python; không bắt buộc Gradio (trang 1, 9) | React/TypeScript + FastAPI/Python chạy local |
| Nhóm trang | `ch`, `vi`, `intro`, **`ref`**, `toc`, `blank`, `misc` (trang 4–5) | Đủ bảy nhóm, bổ sung `ref` bị thiếu ở Gemini |
| Tên sách | Giữ nguyên tên PDF (trang 4–5) | ID nội bộ riêng; tên file giữ nguyên Unicode/khoảng trắng |
| Số trang | Vị trí PDF, từ 1, ít nhất ba số (trang 5) | `.001.jpg`, `.011.jpg`, `.1000.jpg` |
| Nhãn | Đường dẫn + TAB + JSON, box bốn điểm (trang 5–6) | Validate API, xuất hai trường chính; ID box chỉ giữ nội bộ |
| Tiến trình | `fileState.txt`, TAB, 0/1 (trang 5–6) | SQLite checkpoint, TXT ghi nguyên tử và tái tạo lúc khởi động |
| Ảnh song ngữ | Cùng ảnh ở `ch` và `vi`, box riêng (trang 7) | Tạo bản ở nhóm ngôn ngữ còn lại với nhãn rỗng |
| Thứ tự đọc | Nôm dọc phải → trái; Quốc ngữ theo dòng; có ngoại lệ hai trang/Nôm ngang (trang 6–7) | Trang đơn Nôm dọc và Quốc ngữ theo dòng; ngoại lệ để giai đoạn sau |
| Căn chỉnh | `img_id`, `sentence_id`, `SinoNom_Char`, `ChuQN_txt` (trang 8) | CSV/XLSX đúng bốn cột, ID gắn trang Nôm |
| Chất lượng | ≥95% tương đồng theo chữ; chữ thiếu từ điển cũng sai (trang 8–10) | Không giả điểm chất lượng; cặp chưa kiểm chứng xuất đỏ |
| Mã nguồn | Dependency cố định, README và USER_GUIDE (trang 9) | Version trực tiếp cố định, npm lockfile và hướng dẫn máy mới |

Quốc ngữ được sắp theo dòng trên xuống dưới, trong dòng trái sang phải. Nôm ngang và hai nửa trang cần cấu hình bố cục riêng, không áp dụng sắp xếp toàn cục cho mọi sách.

## Dùng được trong giai đoạn này

Yêu cầu bổ sung từ người dùng: tối thiểu **2.000 cặp Nôm – Quốc ngữ**. Bộ đếm toàn không gian tính các cặp đã lưu, đủ hai vế và không trùng văn bản, loại dữ liệu minh họa; báo số còn thiếu và cho mở nhập tài liệu ngay. Đây là mục tiêu số lượng riêng với tiêu chí ≥95% tương đồng của PDF gốc.

Nhập PDF, duyệt/phân loại trang, dựng JPEG khi cần, sửa box/văn bản, lưu qua khởi động lại, căn chỉnh thủ công và xuất bản làm việc. UI chỉnh box chữ nhật; API lưu đúng bốn điểm theo tọa độ ảnh.

`data/.workspace/books/<book_id>/` là vùng dữ liệu theo sách. ZIP nhãn bọc bằng tên sách và chỉ chứa TXT. Bộ mẫu dựng bằng mã, không dùng sách trong `data/`. Chưa thực hiện xuất toàn bộ ảnh hoặc đóng gói bàn giao cuối cùng.

## Chưa triển khai

- Mã đề tài/thành viên, xác nhận phạm vi và kiểm tra tỷ lệ trang chất lượng kém.
- OCR Kim Hán Nôm, voting, tự phát hiện box/phân loại và nhập kết quả OCR bên ngoài.
- Deskew, xoay/tăng tương phản, PDF `<Tên sách>_updated.pdf` khi sửa ảnh.
- Từ điển, spellcheck, đối chiếu từng chữ, màu đen/đỏ theo nghĩa và đánh giá ≥95%.
- Tự ghép câu qua trang, căn chỉnh ngữ nghĩa, cấu hình hai trang/Nôm ngang.
- Tách toàn bộ ảnh, gói đồ án có PDF/ảnh/báo cáo/source.zip và kiểm tra bằng PPOCRLabel/Excel.

Quy định làm mọi trang có bản dịch, kiểm tra chất lượng và bàn giao đủ vẫn áp dụng cho đầu ra cuối cùng. Các mục này sẽ nối vào nền Python khi có hướng dẫn/dữ liệu cần thiết.
