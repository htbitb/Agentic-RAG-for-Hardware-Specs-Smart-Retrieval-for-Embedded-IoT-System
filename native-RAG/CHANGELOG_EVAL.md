# CHANGELOG_EVAL — thay đổi native-RAG (S1) phục vụ đánh giá P0

Nguyên tắc: **giữ nguyên bản chất "naive"** (chunk cố định, vector top-k, một lượt gọi LLM). Chỉ sửa những gì cần cho công bằng và đo lường.
Không bất kỳ thay đổi nào ở đây nhằm tăng điểm trên `dev`.

Ngày: 2026-10-21 (P0). Dự án không phải git repo → file này là bản ghi thay đổi duy nhất.

## Giữ nguyên (không đổi)
- `CHUNK_SIZE=1000`, `CHUNK_OVERLAP=150`, `RETRIEVE_K=4`, embedding `all-MiniLM-L6-v2` (normalize), Chroma, `COLLECTION_NAME="esp32_rtos"` (tên cũ, không đổi để tránh sửa vô ích).
- LLM qua `ChatOpenAI` cùng endpoint/model/temperature với agent (đọc `../agent/.env`).
- Câu abstain của prompt: `"I could not find this in the documents."`.

## Thay đổi
| File | Thay đổi | Lý do |
|---|---|---|
| `config.py` | `PDF_DIR` lấy từ env `RAG_PDF_DIR`, mặc định `../corpus/pdfs`; thêm `MANIFEST_PATH` (`RAG_MANIFEST`, mặc định `../corpus/manifest.yaml`); thêm `EMBED_DEVICE` (env, mặc định `cpu`) | Corpus chung cho mọi hệ; thiết bị embedding tuỳ chọn |
| `rag_core.py` | `get_embeddings()` truyền `model_kwargs={"device": EMBED_DEVICE}` | Như trên |
| `rag_core.py` | `PROMPT_TEMPLATE`: "ESP32 and FreeRTOS" → "embedded hardware questions: ESP32, STM32G474, nRF52840 and FreeRTOS" | Corpus mở rộng 4 nguồn; câu abstain giữ nguyên |
| `rag_core.py` | Thêm `load_doc_index`, `enrich_metadata`, `split_message`, `answer_question_ex` (trả `answer, docs, usage`); `answer_question` giữ chữ ký `(answer, docs)` và gọi `answer_question_ex` | Lấy token usage (`AIMessage.usage_metadata`) mà không đổi hành vi |
| `ingest.py` | Thêm `metadata["page_1based"]` (= `page`+1, vì `PyPDFDirectoryLoader` ghi 0-based) và `metadata["doc_id"]` (tra `corpus/manifest.yaml` theo tên file) | Citation grader cần trang 1-based và doc_id thống nhất |
| `ask.py` | Hiển thị `page_1based` thay cho `page` 0-based | Nguồn trỏ đúng số trang PDF |
| `eval_adapter.py` (mới) | Tiến trình sống lâu, giao thức JSONL; cache LLM `record`/`replay` có khoá theo seed | Harness `eval/` gọi qua subprocess |
| `rag_core.py` | `ChatOpenAI(max_retries=int(env LLM_MAX_RETRIES, mặc định 2))` | Mặc định giữ nguyên (2); harness đặt 0 để tự điều tiết tốc độ gọi API |
| `eval_adapter.py` | `call_with_retry` + bộ giới hạn tốc độ dùng chung (`eval/ratelimit.py`) trước mỗi lời gọi LLM thật; tôn trọng `retry in Ns` của server | Free tier Gemini giới hạn 15 request/phút/model; không đổi nội dung prompt/truy hồi |
| `requirements.txt` | Thêm `fonttools`, `pyyaml` | pypdf giải mã font toán học trong TRM; đọc manifest |

## Re-ingest (2026-10-21)
- Corpus: 6 PDF (ESP32 DS v5.3, ESP32 TRM v5.8, FreeRTOS Ref Manual V8.2.1, STM32G474 DS12288 Rev 6, RM0440 Rev 9, nRF52840 PS v1.11) — 4.380 trang.
- Kết quả: **11.251 chunk** (STM32G474_RM0440 5674, nRF52840_PS 2545, ESP32_TRM 1762, FreeRTOS_Ref_Manual 590, STM32G474_Datasheet 506, ESP32_Datasheet 174), 228 s trên CPU (Apple M2, `EMBED_DEVICE=cpu`).
- Mọi chunk có `page_1based` và `doc_id`.

## Retrieval record/replay (2026-10-22)
- Chroma/HNSW có thể trả top-k khác nhau giữa các tiến trình với câu hỏi xa corpus → prompt đổi → khoá cache LLM lệch (phát hiện khi replay đầy đủ tập dev: 2/243 run bị `cache_miss`).
- `eval_adapter.make_cache(...).retrieve(question, k, fetch)` ghi/phát lại kết quả truy hồi (bảng `retrieval` trong cùng file SQLite, khoá = câu hỏi, k, seed). `replay` mà chưa có bản ghi → `CacheMiss` (xem mục dưới; trước 2026-10-22 là truy hồi trực tiếp).

## Kiểm tra
- `ask.py` vẫn chạy: câu STM32G474 → nguồn `stm32g474re.pdf` trang 88/132/97/91 (chân trang in "132/236"... khớp 1-based); câu ESP32 → `esp32_datasheet_en.pdf` trang 51/19/24/18.
- `pytest eval/tests/test_native_rag_changes.py eval/tests/test_native_rag_adapter.py` (gồm test tích hợp tiến trình thật ở chế độ `replay` với cache rỗng → `cache_miss`, không gọi API).

## Đã biết
- Truy hồi nhiễu (top-4 MiniLM trên 11k chunk) là *đặc tính baseline*, không phải lỗi cần sửa ở P0.

## Replay không truy hồi trực tiếp + dấu vân tay chỉ mục + phân loại lỗi dùng chung (2026-10-22, sau review P0)
- `replay`: thiếu bản ghi truy hồi → `CacheMiss` → `cache_miss` (harness gắn `infra:cache_miss`); không truy hồi trực tiếp, không CREATE TABLE/ghi gì (cache mở chỉ-đọc; file chưa có thì dùng DB rỗng trong bộ nhớ); không cần `chroma_db` (Chroma/embedder nạp lười, replay không bao giờ nạp).
- Bảng `meta` của cache lưu dấu vân tay chỉ mục (`embedding_model`, `chunk_size`, `chunk_overlap`, `collection`, `count`); khoá truy hồi giữ nguyên (câu hỏi, k, seed) để không mất bản ghi cũ. `record`: lần đầu ghi, khác → từ chối (mọi request trả `fatal:` với hướng dẫn dùng file cache mới); đã có dòng retrieval mà chưa có dấu vân tay → từ chối (phải backfill sau khi kiểm chỉ mục không đổi). `replay`: so khi có chỉ mục, không có thì tin bản đã lưu. Cache hiện có đã backfill (11.251 chunk, 1000/150, all-MiniLM-L6-v2, `esp32_rtos`; segment HNSW sửa lần cuối 21/10 18:39, trước mọi bản ghi).
- Phân loại lỗi nay nạp từ `eval/llm_errors.py` (cùng bộ với S0/S2): thêm HTTP 400 `API_KEY_INVALID`/"API key not valid"/"API key expired" → `fatal`; `TimeoutError`/`ConnectError`/`RemoteProtocolError` → `infra`; sqlite "database is locked" → `infra`.
- Không đổi prompt, truy hồi hay LLM; replay S1 dev (81 run) trùng 81/81 câu trả lời/nguồn/TSR.
