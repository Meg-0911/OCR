# Báo cáo đồ án Hán Nôm – Quốc ngữ

[Mở bản PDF](./main.pdf) · [Chỉnh sửa bản LaTeX](./main.tex)

Ba trang đầu trình bày sáu mục của báo cáo, gồm quy trình Duyệt nhanh và kết quả Truyện Kiều. Trang thứ tư dành cho Ca dao (digcoll_14470), Ca Dao Ngạn Ngư Phương Ngôn và Tiên Phả Dịch Lục. Có thể điền kết quả dưới tên từng sách ở cuối `main.tex`.

## Nguồn của phần Truyện Kiều

- Tệp [TruyenKieu.txt](../../TruyenKieu.txt) dùng để đối chiếu với bản quét. Nguồn văn bản là [Wikisource tiếng Việt, *Truyện Kiều* (bản Duy Minh Thị 1872)](https://vi.wikisource.org/wiki/Truy%E1%BB%87n_Ki%E1%BB%81u_%28b%E1%BA%A3n_Duy_Minh_Th%E1%BB%8B_1872%29).
- Số cặp, số ảnh và màu đánh giá lấy từ [gói xuất Truyện Kiều](../../exports/TruyenKieuBanDuyMinhThi1872AnChiPhienAmChuGiaiVaThaoLuan_NguyenDu/). Độ tương đồng tính trên cột `SinoNom_Char` của XLSX, theo tỷ lệ chữ Nôm không mang màu đỏ.
- Hai ảnh trong báo cáo là `assets/kieu-046.jpg` và `assets/kieu-047.jpg`. Khung câu đầu lấy từ tọa độ trong `ch/Label.txt` và `vi/Label.txt` của gói xuất.

## Biên dịch

Giữ thư mục `assets/` cạnh `main.tex`. Trên Overleaf, chọn **XeLaTeX** và đặt `main.tex` làm tài liệu chính. Khi biên dịch cục bộ, chạy hai lần `xelatex main.tex` hoặc một lần `tectonic main.tex` trong thư mục này.
