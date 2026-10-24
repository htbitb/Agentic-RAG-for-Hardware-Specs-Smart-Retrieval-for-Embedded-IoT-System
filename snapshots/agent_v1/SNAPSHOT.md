# Snapshot — Agent v1 (S2), đóng băng

- **Ngày chụp:** 2026-10-21
- **Nguồn:** `agent/` (gốc dự án) tại thời điểm trước P0
- **Lý do:** P0 của `plan/AgenticUpgradePlan.md` (§7.2, §8) — S2 = Agent v1 đóng băng, đo *trước* khi nâng cấp. P1+ sửa `agent/` thoải mái; adapter S2 (`eval/adapters/agent_v1.py`) chỉ import từ thư mục này.
- **Loại trừ:** `.env*`, `.venv/`, `logs/`, `data/memory.sqlite`, `workspace_out/`, `__pycache__/`, `.DS_Store`. Không chứa bí mật.
- **Cấu hình LLM/đường dẫn:** `config.py` đọc biến môi trường lúc import (`LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_TEMPERATURE`, `PRICE_*`, `MEMORY_DB`, `AUDIT_LOG`, `SANDBOX_DIR`...). Snapshot không có `.env` → adapter nạp giá trị từ `agent/.env` vào môi trường của tiến trình worker (không ghi/in giá trị).
- **Known issue:** agent trích "FreeRTOS v10.5.0" trong khi PDF thật là V8.2.1; dữ liệu agent v1 là hằng số mô phỏng (3 chân, 11 thanh ghi, 8 đoạn văn). Không sửa — là baseline hợp lệ.

## SHA-256 các file .py

```text
7eb70257593da06f682a3ddda54a9d260d4fc514f645237f5ca74b08f8da61a6  agent/__init__.py
956ceab640513a8b502e31df406ce6bfb46d5b0731c5dd8aefc4f91ee9fdbd13  agent/approval.py
49c713c6d54b2ba1d3138d793ea9e425d079530225a861895c10d11a5ca53774  agent/audit.py
3e93d01745db70e246ff83a4eb554df62bc6d0ed40c1f013e394928aa08b5212  agent/guardrail.py
c00c4e02e0a03f88eecf2641c1731304001efd20bd7317349d6ebb13db1e234e  agent/llm.py
5cf25d8b19c1a95abdf8e7d32fba07b24602b76a8cba5f4a8a4d9120c4535ded  agent/memory.py
76a5e77395db08a506d5e5c4c11200cb8e429a41b6c0a3a11bfb7ec57ea04e1d  agent/react_agent.py
e182548b5545ef575b051280a994ba9469eb8e8893dc8b5fea7a5249f9897aeb  agent/tools.py
2b8b81504b64a16865ab15b3b92f4c0152e5e9d8b4cac23e5e650001b5bd2c23  agent/verifier.py
e7be3197f171312b04eab7596ef8ab513164481e06b5fa76d086e6b9d6bfd383  config.py
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  ingestion/__init__.py
ff4aa8f46b0e3ae5fda1dd78dfa9f213a02619cc2090fc5addb3054e7d7ae2c6  ingestion/unit_normalizer.py
4fade34d4d143ff8879b267e0da1c8246425eaaab25ad9e53da86166ef54cd01  mcp_servers/__init__.py
8abdbbb82c4b8cdd1e53184a4004d1b29e5b048acbb9f5d7b6c09853c4145992  mcp_servers/table_register_server.py
cc796188372f42ba49b11def15bb080ec702026c521fcd1af10230edfcd32fb4  mcp_servers/text_manual_server.py
7eb70257593da06f682a3ddda54a9d260d4fc514f645237f5ca74b08f8da61a6  ui/__init__.py
48f071f2b01d093b668af57ed830632a04cc19f1c8005a74fff07308859134e2  ui/server.py
```

Checksum tổng (sha256 của đầu ra `find . -name '*.py' | sort | xargs shasum -a 256`, đường dẫn dạng `./...`; `eval.run.snapshot_checksum()` tái tạo đúng giá trị này): 4f15b8fdba8bb068acd5ddac37e7d2538fa5476c83ec6a291b2d92ace25be0fd
