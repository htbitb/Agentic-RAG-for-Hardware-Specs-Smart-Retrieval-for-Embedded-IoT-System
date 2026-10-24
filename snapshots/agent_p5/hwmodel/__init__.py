"""hwmodel — mô hình thanh ghi ở mức hành vi (P2, W3): lớp chung từ SVD (3 chip) + ngữ nghĩa STM32G474.

Nguyên tắc trung thực: phần không mô hình hoá được trả về trong `unmodeled` và KHÔNG BAO GIỜ được tính là pass.
Gói này KHÔNG import `config` của agent (config nạp .env và tạo thư mục); mọi đường dẫn dữ liệu đi qua `hwmodel.data`.
"""
