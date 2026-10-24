# Bản đóng băng của `hwmodel` dành cho grader (D19)

- **Ngày chụp:** 2026-10-23
- **Nguồn:** `agent/hwmodel/` (mã) và `agent/data/{hw_specs.sqlite, svd_attrs.json}` (dữ liệu), gốc dự án.
- **Lý do:** D24: header_gen sinh header theo tên/giá trị/offset của header chính thức ST (cmsis-device-g4 v1.2.6); thay đổi chỉ ở hwmodel/header_gen.py (kèm test); chấm lại mọi hệ không gọi LLM
- **Quy tắc:** KHÔNG sửa tay các file ở đây. Grader (`eval/graders/functional_sim.py`, `compile.py`) chỉ import bản này, **không** import `agent/hwmodel`. Lỗi simulator phát hiện sau P2 ⇒ sửa `agent/hwmodel`, đóng băng lại (`--force`), chấm lại mọi hệ và ghi vào `post_run_changes` của manifest.
- **Kiểm lệch:** `eval/.venv/bin/python -m eval.tools.freeze_hwmodel --check`.
- **Phụ thuộc ngoài:** `pycparser>=3.0` (Python) và `clang` (hệ thống; thiếu clang ⇒ `compile_check` trả `skipped`, `analyze_c_code` báo `no_toolchain`).
- **Đối chiếu snapshot P1:** `hw_specs.sqlite` TRÙNG `snapshots/agent_p1/data/hw_specs.sqlite` (sha256 5195f4f967febd1994e5f65cd6434532a522ad55420c2f6dfa186f998688357d).

## SHA-256 các file .py

```text
a0f7b6c2b2e35cdd1c108a3dd429899927dde5b84fa709004683e7c04791b0ec  __init__.py
1c2cef679ec567638a2564ebb55dc01c5077959c0107d3f8ef811ff6b7e55b33  clock_tree.py
4d490a8fd9e08790e7b671c3df9768f849848d99dc6ca530420c82bf1372e21d  codeparse.py
5a8fc11a442fef13223241a008c6ba3af71b3c8101d4c5e32f7f25f99b45cbdb  compile_check.py
e83327cc0b8ecca64ed0a2c2026929463af071305a4eed648cd6db68b64f6cc1  data.py
5ddd8f14417758af3793e450ea7a1ca5ecabd12c2dc78d607f24e490b20890b4  errata.py
181cb1cd367a24ab16e993f0d233b5ad1d38cd8fb82bd1e228d9f99048e5357c  header_gen.py
39247794fb5a5ea453d62c3b50f314935d62c01926980297cdd1f91da8890312  periph/__init__.py
ba88d9d13cbc5fee7096afc549ddbe2a3d9ce1a1d1161f20c30778dd9ccf7dd9  periph/gpio.py
d2045c6aa0b2409d5dd9bf2ff6160d1b9c4a8ab0bb9032ec6757d78e467094af  periph/i2c.py
8bc9628356555ef8fcf3e913e96276abe69d00e1f5377e4de13056c538d94b1a  periph/rcc.py
370818268d337c375edcfbcabf05af69a9fca31db0bbccf38781fd2dab1921d3  periph/tim.py
e74b3346d8f5f125bdebf5679e543adf1b49c5965c8e82a74754229f32136334  periph/usart.py
4282f55136838fd80a67d1323099954ebc17bd46ecb3f5d4da8d5525470b454b  regmap.py
4088ee63c249852e2c386cad4765fbb26229496dfecbd9774d48acc8b28ca7b7  sim.py
eb2f6572de191484419d4246b6f0c6c3ec9bcd0f8ca42adbc1645c3a1abe03b8  solver.py
```

## SHA-256 dữ liệu (`../hwmodel_data/`)

```text
5195f4f967febd1994e5f65cd6434532a522ad55420c2f6dfa186f998688357d  hw_specs.sqlite  (6,299,648 bytes)
3ef80f9b48963a144c5af60572f3a6df2e8a289dfee3fd60e85ff1f0519d2cbb  svd_attrs.json  (7,027 bytes)
```

Checksum mã (sha256 của danh sách `sha256  ./đường-dẫn`, sắp theo đường dẫn; manifest eval ghi giá trị này):

hwmodel_vendor_sha256: 7b10cafdd8087bb8af0190222cc1102080d0f8466aa0bbda9efcc462b6cdfb27

Checksum dữ liệu (cùng công thức trên `hw_specs.sqlite` và `svd_attrs.json`):

hwmodel_data_sha256: 3c293c60e0739d3706b1e011d957d34863c380ef9f70468311bf4f62697184b4
