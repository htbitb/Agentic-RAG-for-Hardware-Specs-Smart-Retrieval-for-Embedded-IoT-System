# 30 giây: Vấn đề & người dùng
Bài toán thật, cho ai, và vì sao cần một agent chứ không phải một script.

```
Khi lập trình phần cứng như vi điều khiển STM32 hay ESP32, kỹ sư và sinh viên ngành nhúng phải đọc những tài liệu dài từ hàng trăm trang. Tìm kiếm từ khóa thì không liên kết được ngoại vi, còn Naïve RAG thông thường sẽ xé nát các bảng thanh ghi — dẫn đến ảo giác thông số và nguy cơ cháy, hỏng thật ngoài đời.

Tại sao một script thông thường không giải quyết được? Vì một cấu hình phần cứng đòi hỏi suy luận đa bước và liên kết chéo giữa Datasheet sơ đồ chân và Reference Manual về thanh ghi. Chúng ta bắt buộc phải có một Agent có khả năng chủ động lập kế hoạch, chọn công cụ và tự phản biện.
```

# 60 giây: Sơ đồ kiến trúc
Control loop, tools/MCP, memory, và đánh dấu (>= 3 trục kỹ thuật)

```
Kiến trúc của chúng em hoạt động theo vòng lặp Reasoning – Acting – Observation – Verification, tích hợp 4 trục kỹ thuật cốt lõi:

1. Tool Use qua chuẩn MCP: Gồm Manual-Text MCP chạy trên vector DB cục bộ LanceDB cho văn bản mô tả; và Hardware-Register MCP truy vấn dữ liệu cấu trúc trực tiếp từ DuckDB.

2. Reflection & Verification Layer: Trước khi đưa câu trả lời cho kỹ sư, Agent tự động đối soát chéo ngược lại cây SVD để triệt tiêu 100% ảo giác thanh ghi.

3. Hardware Safety Guardrail: Khi phát hiện yêu cầu cấu hình quá áp (như cấp 5V vào chân 3.6V), hệ thống sẽ chủ động từ chối (Refuse) và cảnh báo trang tài liệu tương ứng.

// Slide tiếp

Và Thứ 4. Dual-Source Ingestion:
Để hệ thống không bị ảo giác dữ liệu bảng biểu, thay vì chỉ parse PDF, pipeline nạp dữ liệu của chúng em đi theo nguyên tắc SVD-First, PDF-Enrichment phân tách thành 2 nhánh độc lập:
- Nhánh cấu trúc: Nhóm dùng XML CMSIS-SVD làm chân lý tuyệt đối, bóc tách chính xác 100% thanh ghi và bitfield nạp thẳng vào DuckDB.
- Nhánh phi cấu trúc: Tài liệu PDF được chia nhỏ theo ranh giới phân cấp tiêu đề (Hierarchical Chunking) thay vì cắt token ngẫu nhiên, nạp vào LanceDB để tìm kiếm kết hợp Hybrid Search."
```

# 45 giây: Kế hoạch đánh giá
Task set, metric + cách kiểm tra đúng/sai, số cấu hình so sánh, số lần chạy

```
Về kế hoạch kiểm thử, chúng em xây dựng bộ benchmark gồm hơn 40 tasks thực tế: 40% câu hỏi tra cứu chéo, 40% tra cứu bitfield chi tiết, và 20% kịch bản từ chối an toàn.

Kết quả được đánh giá bằng độ chính xác tuyệt đối Exact Match (EM) với file SVD và độ chuẩn xác từ chối an toàn. Nhóm tiến hành so sánh đối đầu giữa 4 cấu hình: Pure LLM, Naïve RAG, Agentic RAG không reflection, và Hệ thống đầy đủ; mỗi cấu hình được chạy lặp lại trên 3 hạt giống ngẫu nhiên (3 seeds) để bảo đảm độ tin cậy và ý nghĩa thống kê."
```

# 30 giây: Threat model v0
Tài sản cần bảo vệ, điểm vào của dữ liệu không tin cậy, một biện pháp giảm thiểu

```
Về an toàn hệ thống (Threat Model v0):

Tài sản cần bảo vệ: Bo mạch vi điều khiển vật lý không bị hỏng hóc do lệnh cấu hình sai, và sự toàn vẹn của mã nguồn dự án.

Điểm vào dữ liệu không tin cậy: Đến từ Prompt Injection của người dùng hoặc tài liệu thứ ba chứa văn bản độc hại.

Biện pháp phòng vệ: Nhóm triển khai Active Rule-based Guardrail bằng code logic độc lập — không dựa vào lời nhắc LLM — kết hợp cổng xác nhận người dùng trước khi ghi bất kỳ đoạn code nào ra file.
```

# 15 giây: Giả định rủi ro nhất và phương án thu hẹp phạm vi nếu sai

```
Giả định rủi ro nhất của đề tài là việc parse tự động các bảng PDF nhiều trang (multi-page Pinout tables) có thể bị lệch cột.

Phương án dự phòng: Nhóm dùng chuẩn CMSIS-SVD làm nguồn dữ liệu chính cho thanh ghi, đồng thời sẵn sàng fallback bằng cách định nghĩa schema JSON cố định cho sơ đồ chân của 2 chip mục tiêu là STM32G4 và ESP32-S3, đảm bảo hệ thống luôn demo và vận hành chính xác 100%.
```
