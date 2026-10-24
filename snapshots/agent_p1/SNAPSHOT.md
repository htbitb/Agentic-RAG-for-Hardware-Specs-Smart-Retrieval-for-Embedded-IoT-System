# Snapshot — Agent P1 (S2D), đóng băng

- **Ngày chụp:** 2026-10-22
- **Nguồn:** `agent/` (gốc dự án)
- **Lý do:** P1 của plan/AgenticUpgradePlan.md (§8) — S2D = vòng lặp Agent v1 (giữ nguyên) + dữ liệu thật của P1 (D04). Đo đóng góp của DỮ LIỆU: S2 -> S2D; đóng góp của kiến trúc agentic: S2D -> S3. Adapter S2D (eval/adapters/agent_v1.py, snapshot=snapshots/agent_p1) chỉ import từ thư mục này. Bản này thay bản chụp đầu (trước review độc lập): đã sửa khoảng chỉ số mảng ESP32 và VIH max của nRF.
- **Loại trừ:** `.env*`, `.venv*`, `logs/`, `data/memory.sqlite`, `workspace_out/`, `__pycache__/`, `.pytest_cache/`, `.DS_Store`. Không chứa bí mật. **Giữ** `data/hw_specs.sqlite` và các file chỉ mục.
- **Cấu hình LLM/đường dẫn:** `config.py` đọc biến môi trường lúc import; snapshot không có `.env` → adapter nạp giá trị vào môi trường của tiến trình worker (không ghi/in giá trị).
- **Known issue:** Vòng lặp ReAct, verifier V1–V4, guardrail, memory, approval và SYSTEM_PROMPT KHÔNG đổi so với agent_v1 (D10, byte-identical); chỉ lớp dữ liệu + 2 MCP server + tools.py/config.py đổi (agent/CHANGELOG_P1.md).
- **Known issue:** guardrail.evaluate_hw lấy MIN trên mọi hàng input_voltage nên 5 V vào chân STM32 FT cũng bị từ chối; không chặn VDDH nRF (để P6).
- **Known issue:** 779 thanh ghi chỉ có trong SVD (STM32 101, ESP32 661, nRF 17; page=null) không qua được verifier V3: xem plan/P1_data_quality.md.

## SHA-256 các file dữ liệu

```text
5195f4f967febd1994e5f65cd6434532a522ad55420c2f6dfa186f998688357d  data/hw_specs.sqlite  (6,299,648 bytes)
6cd86c23ffb958e8ff52ab46f78e64dcf458393cd51857ac89cf14d71fa9519a  data/text_index.npy  (14,719,616 bytes)
ab5d9a192d41a98cf74712255e58e921cc814bee1c77bafbe48d6e42bb6c35c9  data/text_index.sqlite  (30,400,512 bytes)
```

## SHA-256 các file .py

```text
7eb70257593da06f682a3ddda54a9d260d4fc514f645237f5ca74b08f8da61a6  agent/__init__.py
956ceab640513a8b502e31df406ce6bfb46d5b0731c5dd8aefc4f91ee9fdbd13  agent/approval.py
49c713c6d54b2ba1d3138d793ea9e425d079530225a861895c10d11a5ca53774  agent/audit.py
3e93d01745db70e246ff83a4eb554df62bc6d0ed40c1f013e394928aa08b5212  agent/guardrail.py
c00c4e02e0a03f88eecf2641c1731304001efd20bd7317349d6ebb13db1e234e  agent/llm.py
5cf25d8b19c1a95abdf8e7d32fba07b24602b76a8cba5f4a8a4d9120c4535ded  agent/memory.py
76a5e77395db08a506d5e5c4c11200cb8e429a41b6c0a3a11bfb7ec57ea04e1d  agent/react_agent.py
f7e45e44f808b3917ef00244ab29afad9655895f93dd584f76111f00b3bfcad0  agent/tools.py
2b8b81504b64a16865ab15b3b92f4c0152e5e9d8b4cac23e5e650001b5bd2c23  agent/verifier.py
770567d13e425bc5c0f0af870bfab0c6f8c6e487ad0ee759c0c87a8dd4736582  config.py
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  ingestion/__init__.py
53ffd0a4da70827c266d48a9164ce3e47f5417b0310bac8514f52de958c66753  ingestion/build_all.py
14007759dda0bb16229a8b35891f285078ab75560fa8c3428ebe3f15ec6dd38d  ingestion/build_text_index.py
a35b5c19d4ed854fad57453c910d544e3d6670ef3d3b0041883ae564b6008f75  ingestion/data_quality.py
bd0bb935d41f7f0acc78bb85dae71b170c06275a13459dcd6783279c2d139cd6  ingestion/hwdb.py
a5a168992fc0713286892a2475dd5eba6e1ec48ace7b5af536fe3eba029c5e53  ingestion/limits_curate.py
87055fba96669b442f576a400aeae6b67662e8bdb02f4a2bdc38bd8040635f10  ingestion/pdf_chunker.py
2768d33fcfe5301fd9f01ab977a1effa9f130700ac2323c10b329ebd156945e9  ingestion/pdfdocs.py
19a26174b0bf6fea62fbe86cf100430e27437e8396acff6b389467fb308eff32  ingestion/pinout_extract.py
56551263ae59ee369f3d8bba4cfbe42aff3f74bad73b793cc329551237ad4533  ingestion/register_pages.py
d387c40a0cd1c7196afd61025c7f489efc20aa8ddb598a084c33f2768acd5204  ingestion/svd_ingest.py
1af116cd74741b272b40108001d342bf5b555782611a61acba92c9f5e9f9631d  ingestion/text_index.py
ff4aa8f46b0e3ae5fda1dd78dfa9f213a02619cc2090fc5addb3054e7d7ae2c6  ingestion/unit_normalizer.py
4fade34d4d143ff8879b267e0da1c8246425eaaab25ad9e53da86166ef54cd01  mcp_servers/__init__.py
eb4eeb521bed4209d18d33902695d7af58f1dc85107102729bcf8c252e1da768  mcp_servers/hw_knowledge_server.py
3518abe62ae93b69f873e4aea3f0984735dd0312a5e8828aede0fad90f3acdfb  mcp_servers/hw_queries.py
6229d224115eaaed0d3f1e9d39801a6c3041881dfd17f193c962ee923de6cfdd  mcp_servers/text_manual_server.py
3387de8c5ede61865c008291460df8fe657fdf9046e2b89cc3e323a02666a944  tests/conftest.py
d7677c9ee3e7eac483c44df3efeab5f87cec17ada27f884de3ccb4e2e8672fe6  tests/test_agent_data_path.py
7ca0a1dd478444f274c6c8eac21b4dc8a9d1b0ba1ec3a6fb27c8e67819f3c59f  tests/test_build_all.py
7b32fce1706b4cf06e3114be4b73e33965db2fa0759e700c69dc9da792cbd9ba  tests/test_data_quality.py
d02f69a7e2a3a6d3701d29904cecfa8382d1d31dac9fbc38b808dc0c9caad8d2  tests/test_hw_queries.py
137b9fc86941954ca165609cdd7ef45b9d76562c672c4fe9c42c899860be4f4f  tests/test_limits_curate.py
0544377634bfecb683d55491186bb1eaefa97456ab6c36b00d33313a83325871  tests/test_pdf_chunker.py
d554b01c75ef30f46d298e0d2c453584dc9b81fe51f378d76993f678932ef041  tests/test_pdfdocs.py
9a93798b0ecb15491ac3bc8dae107cb324a89dc10624d318ea0ed0388c288f55  tests/test_pinout_db.py
521a9d53a6dbfb85053bc1e6beb24f07dc6591c5c6949fbfa28dcd503af29c0c  tests/test_pinout_esp_nrf.py
1bfca4d1cba25c5da4b45b63b36a5301875b33076c49666de6cd5101b4141e87  tests/test_pinout_stm32.py
bd164c5415551bc114e96185356b10caec07fd6de129aca0e70c31f4ae04c796  tests/test_register_pages_nrf_esp.py
93094fe07bc359f1a9bf815b5bd285fb112fc92319d86d814a65b75ae64c9dec  tests/test_register_pages_st.py
8a666ce42e406a342e8ce3ddd794b164f82612251ad8e8495d7e2953158f0219  tests/test_servers.py
f3c07afc8e5705eaaf5770801b1f86a1047333c31dec1a4fb4d6a0cf6d5a4003  tests/test_svd_db.py
6cb7dc76d169acee572625307e29de8d1410398ecd3452edc6516093aba8fda8  tests/test_svd_golden.py
51b29484cadbec4a71a0450ce281ee69497aaadc905e3d1c08ed3d484e98eda4  tests/test_svd_parity.py
153142bada125db13367b4743a37502b46e1931c65406031b6b1f922d4a5b52d  tests/test_svd_parser.py
48fee7e3616b1839f1e57b12d830439f0e9eba2615079b1c87ad47975f4224bd  tests/test_text_index.py
7eb70257593da06f682a3ddda54a9d260d4fc514f645237f5ca74b08f8da61a6  ui/__init__.py
48f071f2b01d093b668af57ed830632a04cc19f1c8005a74fff07308859134e2  ui/server.py
```

Checksum tổng (sha256 của đầu ra `find . -name '*.py' | sort | xargs shasum -a 256`, đường dẫn dạng `./...`; `eval.run.snapshot_checksum()` tái tạo đúng giá trị này): 285dbd1f4fc067ccc94b3fc0b8390532a4df95db67efb4432c5a8cf9a36017d7

Checksum dữ liệu (sha256 của danh sách `sha256  ./đường-dẫn` các file *.sqlite, *.npy, sắp theo đường dẫn; `eval.run.snapshot_data_checksum()` tái tạo; manifest ghim và ép khớp khi --resume): 9fe98cd356545fa525e910451439afd550233410d83b08f600be07a1975c7981
