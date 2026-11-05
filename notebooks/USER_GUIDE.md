# VietOCR trên GPU Colab trong luồng Nôm Workspace

Repo đã dùng VietOCR ONNX làm mặc định, không dùng EasyOCR. Thay đổi này đưa cùng
checkpoint VietOCR và bộ tìm dòng hiện có lên Colab; backend local vẫn chạy CPU.

## Luồng sử dụng

1. Chạy ứng dụng như README. Nhập PDF, phân loại trang và chọn ngôn ngữ Quốc ngữ
   hoặc Nôm + Quốc ngữ. Chọn **Màu mực trong quyển** phù hợp; profile màu được ghi
   vào gói input và dùng cho bộ tìm dòng chạy trên GPU. Đặt vùng Quốc ngữ theo từng
   cột nếu bố cục phức tạp.
2. Dừng và chờ OCR local hoàn tất. Trong workbench tải **Notebook VietOCR GPU**,
   **Mã chạy Colab**, rồi **Xuất ảnh cho Colab**.
3. Upload notebook lên colab.research.google.com. Chọn runtime GPU (không local).
4. Chạy lần lượt các ô: mount Drive, upload `vietocr-colab-source.zip`, cài dependencies,
   upload `vietocr-colab-input.zip`, tải trọng số và chạy. Không cần token Kim Hán Nôm.
5. Mặc định thử 3 trang. Kiểm tra preview và errors; đổi `LIMIT=0` để chạy tất cả.
   Chỉ nhập về local sau khi chạy đủ phạm vi mong muốn. Cache lưu trên Drive theo bundle ID.
6. Tải `<bundle_id>-results.zip`; chọn **Nhập kết quả Colab** tại đúng quyển sách.
   Trang vẫn chưa duyệt. Chỉnh box/chữ trong giao diện rồi xác nhận, dóng hàng và xuất
   dữ liệu theo luồng cũ. Không cần PPOCRLabel để nhập gói trung gian này.

## Dữ liệu và kiểm tra

- Xuất ảnh ở đúng cách render OCR hiện tại (tối đa cạnh 3200, cùng tham số backend).
  Gói chứa ID trang, phiên bản, SHA256, vùng Quốc ngữ, mask Nôm đã có, profile màu
  và kích thước ảnh.
- Import chuyển tọa độ ảnh GPU về kích thước workspace, kiểm tra polygon, phiên bản,
  trạng thái trang và job local. Chỉ cập nhật nháp Quốc ngữ, giữ nguyên Nôm.
- Nếu đã sửa hoặc nhập trang sau khi xuất, gói cũ bị từ chối; xuất gói mới. Gói lỗi
  bị từ chối trước khi ghi bất kỳ trang nào. Các trang lỗi trên Colab không được đưa vào results.
- Mã nguồn xuất theo allowlist, không kèm `.env`, token, SQLite hay dữ liệu sách khác.
  Ảnh của gói được upload lên Colab/Drive theo thao tác của người dùng.
- CUDAExecutionProvider phải có và phải khởi tạo ở cả encoder/decoder. Không tự đổi
  sang engine khác khi lỗi. Một số toán tử có thể được ONNX Runtime đặt lên CPU.
  Bộ tìm dòng và tiền xử lý vẫn chạy CPU; chưa khẳng định toàn pipeline nhanh hơn CPU.
- `requirements-colab.txt` pin dependencies trực tiếp; phiên bản PyTorch/CUDA do
  Colab cung cấp được ghi trong pip freeze. Không cài backend/requirements.txt trên Colab.
- Checkpoint đang dùng là VietOCR vgg_transformer fine-tune **chữ viết tay**, revision
  `f1973b930f907c378f6e3152ce9d8658724b228a`, tải và kiểm tra SHA256 như local.
  Chữ in/sách cổ cần thử thực tế; đây không phải thay đổi nhằm chứng minh tăng độ chính xác.
- Bộ phát hiện dòng theo màu/xám hiện có không tự hiểu nhiều cột. Chọn vùng hẹp hơn
  nếu box ghép hai cột. Các box tự động luôn cần duyệt; confidence không phải độ chính xác.

Tài liệu: https://github.com/pbcquoc/vietocr và
https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html.
