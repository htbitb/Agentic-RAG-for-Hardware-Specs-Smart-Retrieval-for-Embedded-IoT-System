# Chỉ mục task (P0)

Sinh bởi `python -m eval.tools.make_index`. P0 chỉ chạy split `dev`; `test` được niêm phong cho báo cáo cuối.

## Theo nhóm x split
| Nhóm | dev | test | Tổng |
|---|---|---|---|
| C1 | 8 | 17 | 25 |
| C2 | 6 | 14 | 20 |
| C3 | 6 | 14 | 20 |
| C4 | 5 | 10 | 15 |
| C6 | 5 | 10 | 15 |
| C7 | 5 | 10 | 15 |
| C8 | 3 | 7 | 10 |
| **Tổng** | 38 | 82 | 120 |

## Theo chip x split (task nhiều chip được tính cho từng chip)
| Chip | dev | test | Tổng |
|---|---|---|---|
| (không gắn chip) | 4 | 11 | 15 |
| esp32 | 6 | 13 | 19 |
| freertos | 1 | 2 | 3 |
| nrf52840 | 6 | 8 | 14 |
| stm32g474 | 23 | 50 | 73 |

## Theo trạng thái duyệt
| review_status | Số task |
|---|---|
| auto | 25 |
| verified | 95 |

`auto` = sinh tự động (C1, từ SVD, chỉ giữ khi PDF corpus nhắc tới thanh ghi/giá trị); `verified` = đã qua `eval.tools.verify_tasks` (bằng chứng trên text trang) nhưng CHƯA có người duyệt độc lập; `needs_human` = bị loại khỏi chạy chính thức.
