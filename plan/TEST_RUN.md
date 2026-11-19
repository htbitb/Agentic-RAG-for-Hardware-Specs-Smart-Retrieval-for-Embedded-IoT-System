# Runbook — split test niêm phong (đã bắt đầu 2026-11-19 ~08:07 ICT)

Khoá: `eval/GRADER_LOCK.json` (commit a419ce7, merge f0e6dca) được ghi TRƯỚC khi có bất kỳ đầu ra test nào. `eval.run --split test` tự kiểm khoá.

## Lệnh đang chạy (lõi, ước tính tối đa ≈ 13,1 USD theo giá cấu hình, ≥ 9 giờ do giới hạn 20 lời gọi/phút)
```
eval/.venv/bin/python -m eval.run --systems S0,S1,S2,S2D,S3@P7 --split test --categories C1,C2,C3,C4,C5,C6,C7,C8,C10 \
  --seeds 3 --cache record --v3-wall-s 2400 --timeout 600 --workers 5 --llm-rpm 20 --out eval/results/test_p7 --yes
```
Log: scratchpad `test_p7.log`. Tiến độ: `wc -l eval/results/test_p7/runs.jsonl` (đích 1470 dòng).

## Nếu bị ngắt (máy ngủ, gateway lỗi hàng loạt → dừng sau 12 lỗi hạ tầng liên tiếp)
Chạy lại cùng lệnh nhưng thay `--out` bằng `--resume eval/results/test_p7`; thêm `--retry-infra` để chạy lại các run lỗi hạ tầng (404/timeout) sau khi gateway ổn.

## Sau khi xong (theo thứ tự)
1. `eval.score --run eval/results/test_p7` và `eval.report --run eval/results/test_p7` (run.py tự làm khi không có `--no-report`).
2. Nhãn mù trên đầu ra test cho C4 (nhận diện xung đột), C5 (checklist), C8 (abstain) trước khi công bố (D29/D34/D42). Nếu sửa grader sau khi thấy đầu ra: báo CẢ HAI số, ghi `post_run_changes` trong manifest, chấm lại MỌI hệ (D18/D38).
3. Điền số liệu test vào `docs/reports/final-report/final-report.tex`, biên dịch `tectonic final-report.tex`; mục tiêu 6–8 trang.

## Chưa chạy (cần duyệt chi phí, ước tính tối đa theo giá cấu hình)
- FI test cho S2D + S3@P7: ≈ 2,6 USD (186 run). C9 test cho S0 + S3@P7: ≈ 3,4 USD (270 run).
- S3@P5 trên test (để so cặp McNemar S3@P7 vs S3@P5): ≈ 10,8 USD; mỗi ablation (A5 `-Lessons`, A7 `-Guardrail`) ≈ 10,8 USD (hoặc ít hơn nếu chỉ chạy C4/C5/C6/C7/C10). Mọi hệ S3 phải dùng cùng `--v3-wall-s 2400`.
