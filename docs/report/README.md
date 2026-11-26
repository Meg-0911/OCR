# Báo cáo LaTeX

`main.tex` là mã nguồn báo cáo. Thư mục `assets/` chứa ảnh minh họa được trích từ dữ liệu nguồn; giữ thư mục này cạnh `main.tex`.

## Biên dịch

Trên Overleaf, tải toàn bộ thư mục lên, chọn `main.tex` làm tài liệu chính và chọn compiler **XeLaTeX**.

Với TeX Live hoặc MiKTeX, chạy trong thư mục này:

```sh
xelatex main.tex
xelatex main.tex
```

Với Tectonic:

```sh
tectonic main.tex
```

Báo cáo dùng phông TeX Gyre Termes, có trong các bản phân phối TeX thông dụng. Các sơ đồ được vẽ trực tiếp bằng TikZ và có thể chỉnh sửa trong mã nguồn.

## Ảnh minh họa

- `ca-dao.jpg`: ảnh 005 của CA dao digcoll_14470.
- `ngan-ngu.jpg`: ảnh 006 của Ca Dao Ngạn Ngư Phương Ngôn, Nôm.
- `tien-pha.jpg`: ảnh 008 của Tiên Phả Dịch Lục, Nôm, 2 volumes.
- `truyen-kieu.png`: trang 110 theo thứ tự PDF Truyện Kiều.
- `ocr-boxes.jpg`: vùng trích ảnh 008 của Tiên Phả Dịch Lục, với ba box đầu được vẽ theo tọa độ trong `Label.txt`.

Các ảnh trích minh họa đầu vào và quy trình, không biểu thị số liệu đánh giá chất lượng.
