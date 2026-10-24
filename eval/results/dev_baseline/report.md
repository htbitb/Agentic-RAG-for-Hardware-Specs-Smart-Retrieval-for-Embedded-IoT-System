# Báo cáo đánh giá — S0 (Direct LLM), S1 (Native RAG), S2 (Agent v1 đóng băng), S2D (Agent v1 + dữ liệu P1)

Split: **dev** | seeds: **3** | model: `gemini-3.5-flash-lite` (temperature 0.0) | cache: `record` | tạo lúc 2026-10-21T12:13:09+00:00 | 394 run đã chấm | số task: 33

**TSR** = tỷ lệ task đạt mọi grader *về tính đúng* (exact, keyfacts, safety, attack, abstain, functional_sim; C4: final_state + conflict_detected); gộp seed trước (trung bình qua seed của từng task), rồi trung bình qua task, CI 95% bootstrap (10.000 mẫu) theo task. Với C7, 'pass' = tấn công thất bại. Run lỗi hạ tầng bị loại khỏi TSR nhưng được đếm bên dưới. `citation` và `numeric_claims` là chỉ số báo cáo riêng, không gate TSR.

## Kết quả chính
| Hệ | C1 | C2 | C3 | C6 | C7 | C8 | Tổng |
|---|---|---|---|---|---|---|---|
| S0 | 41.7% [12.5–75.0] | 66.7% [33.3–94.4] | 55.6% [22.2–88.9] | 40.0% [6.7–73.3] | 100.0% [100.0–100.0] | 100.0% [100.0–100.0] | 62.6% [47.5–76.8] |
| S1 | 8.3% [0.0–25.0] | 50.0% [16.7–83.3] | 0.0% [0.0–0.0] | 0.0% [0.0–0.0] | 100.0% [100.0–100.0] | 100.0% [100.0–100.0] | 35.4% [20.2–51.5] |
| S2 | 0.0% [0.0–0.0] | 5.6% [0.0–16.7] | 11.1% [0.0–33.3] | 26.7% [0.0–66.7] | 100.0% [100.0–100.0] | 100.0% [100.0–100.0] | 31.3% [17.2–47.5] |
| S2D | 95.8% [87.5–100.0] | 100.0% [100.0–100.0] | 22.2% [5.6–44.4] | 60.0% [26.7–93.3] | 100.0% [100.0–100.0] | 100.0% [100.0–100.0] | 78.8% [65.7–89.9] |

## Grounded TSR
Đúng **và** có ít nhất một trích dẫn hợp lệ (trang được trích chứa giá trị kỳ vọng). Chỉ tính trên các nhóm có grader `citation`; với S1, trích dẫn là các trang được truy hồi. Đây là chỉ số chính cho câu hỏi tra cứu: trả lời đúng mà không truy được nguồn thì không kiểm chứng được.

| Hệ | C1 | C2 | Grounded (gộp) | TSR thường trên cùng tập (đối chiếu) |
|---|---|---|---|---|
| S0 | 0.0% [0.0–0.0] | 0.0% [0.0–0.0] | 0.0% [0.0–0.0] | 52.4% [28.6–76.2] |
| S1 | 8.3% [0.0–25.0] | 50.0% [16.7–83.3] | 26.2% [7.1–50.0] | 26.2% [7.1–50.0] |
| S2 | 0.0% [0.0–0.0] | 0.0% [0.0–0.0] | 0.0% [0.0–0.0] | 2.4% [0.0–7.1] |
| S2D | 83.3% [58.3–100.0] | 100.0% [100.0–100.0] | 90.5% [73.8–100.0] | 97.6% [92.9–100.0] |

## Chỉ số phụ
| Hệ | Hallucination Rate | Citation Precision | Safety Acc. (C6) | Over-refusal (C6) | Unsafe compliance (C6) | ASR (C7, thấp hơn là tốt hơn) | Abstention Acc. (C8) | tokens in/out mỗi run | USD/task | latency p50 (s) | latency p95 (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| S0 | 19.0% [8.8–36.2] | 0.0% [0.0–0.0] | 40.0% [6.7–73.3] | 0.0% [0.0–0.0] | 0.0% [0.0–0.0] | 0.0% [0.0–0.0] | 100.0% [100.0–100.0] | 173 / 269 | 0.00009 | 11.8 | 23.9 |
| S1 | 15.4% [0.0–30.8] | 23.2% [10.7–39.3] | 0.0% [0.0–0.0] | 0.0% [0.0–0.0] | 0.0% [0.0–0.0] | 0.0% [0.0–0.0] | 100.0% [100.0–100.0] | 1215 / 20 | 0.00010 | 19.0 | 27.6 |
| S2 | 17.9% [0.0–37.5] | 0.0% [0.0–0.0] | 26.7% [0.0–66.7] | 33.3% [0.0–100.0] | 0.0% [0.0–0.0] | 0.0% [0.0–0.0] | 100.0% [100.0–100.0] | 14856 / 270 | 0.00120 | 79.8 | 160.0 |
| S2D | 22.6% [8.8–40.3] | 85.7% [72.5–100.0] | 60.0% [26.7–93.3] | 33.3% [0.0–100.0] | 0.0% [0.0–0.0] | 0.0% [0.0–0.0] | 100.0% [100.0–100.0] | 16904 / 721 | 0.00148 | 19.9 | 79.3 |

_Hallucination Rate là cận trên (claim số/hex không truy được về ground truth của task, kể cả giá trị đúng nhưng ngoài tập hỗ trợ). Citation Precision của C1 là 'yếu' (trang trích chứa tên thanh ghi **hoặc** giá trị); doc không có PDF thật được đếm riêng (unverifiable)._

## C3 — chức năng (functional_sim) và compile
`functional_sim` (gate TSR) chạy code trong câu trả lời qua `analyze_c_code` → `simulate_register_writes` của bản hwmodel ĐÓNG BĂNG (D19) và so `effects` với spec chức năng; `compile` (clang ARM `-fsyntax-only`) là chỉ số riêng, `skipped` không bao giờ là pass. **Phân tích được** = `analyze_c_code` thành công / số run có code. Pass@1 = đạt ở seed đầu; Pass@k = đạt ở ít nhất một seed.

| Hệ | TSR C3 | Pass@1 | Pass@3 | Phân tích được | Không có code | compile ok | compile error | compile skipped |
|---|---|---|---|---|---|---|---|---|
| S0 | 55.6% [22.2–88.9] | 66.7% | 66.7% | 13/18 | 0 | 13 | 5 | 0 |
| S1 | 0.0% [0.0–0.0] | 0.0% | 0.0% | 0/0 | 18 | 0 | 0 | 0 |
| S2 | 11.1% [0.0–33.3] | 16.7% | 16.7% | 3/4 | 14 | 3 | 1 | 0 |
| S2D | 22.2% [5.6–44.4] | 33.3% | 50.0% | 7/9 | 7 | 7 | 2 | 0 |

| Mã lỗi C3 (sim_violation:<mã mô phỏng>, inactive:<lý do>, wrong_*, unsupported_construct:<loại>, unmodeled, no_code) | S0 | S1 | S2 | S2D |
|---|---|---|---|---|
| no_code | 0 | 18 | 14 | 7 |
| unsupported_construct:unknown_symbol | 5 | 0 | 1 | 1 |
| sim_violation:SIM-CLK-LIMIT | 1 | 0 | 0 | 1 |
| sim_violation:SIM-CLK-NOSRC | 1 | 0 | 1 | 0 |
| wrong_clock | 1 | 0 | 1 | 0 |
| unmodeled | 1 | 0 | 0 | 0 |
| unsupported_construct:syntax_error | 0 | 0 | 0 | 1 |
| wrong_freq | 0 | 0 | 0 | 1 |
| wrong_i2c_timing | 0 | 0 | 0 | 1 |
| wrong_scl | 0 | 0 | 0 | 1 |

**TSR C3 theo loại task** (trung bình theo seed rồi theo task, không CI vì n nhỏ)

| Loại task (tag đầu) | S0 | S1 | S2 | S2D | Số task |
|---|---|---|---|---|---|
| combo | 66.7% | 0.0% | 0.0% | 66.7% | 1 |
| i2c | 0.0% | 0.0% | 0.0% | 0.0% | 1 |
| pll | 0.0% | 0.0% | 0.0% | 0.0% | 1 |
| pwm | 100.0% | 0.0% | 33.3% | 33.3% | 2 |
| uart | 66.7% | 0.0% | 0.0% | 0.0% | 1 |



## So sánh cặp
| Cặp | Nhóm | ΔTSR (điểm %, CI 95% bootstrap cặp) | McNemar (chính xác, đa số phiếu theo seed) | b/c (A đúng-B sai / A sai-B đúng) | Số task |
|---|---|---|---|---|---|
| S1 vs S0 | C1 | -33.3 pp [-62.5, -8.3] | p=0.500 | 0/2 | 8 |
| S1 vs S0 | C2 | -16.7 pp [-61.1, +33.5] | p=1.000 | 1/2 | 6 |
| S1 vs S0 | C3 | -55.6 pp [-88.9, -22.2] | p=0.125 | 0/4 | 6 |
| S1 vs S0 | C6 | -40.0 pp [-73.3, -6.7] | p=0.500 | 0/2 | 5 |
| S1 vs S0 | C7 | +0.0 pp [+0.0, +0.0] | p=1.000 | 0/0 | 5 |
| S1 vs S0 | C8 | +0.0 pp [+0.0, +0.0] | p=1.000 | 0/0 | 3 |
| S1 vs S0 | Tổng | -27.3 pp [-42.4, -12.1] | p=0.012 | 1/10 | 33 |
| S2 vs S1 | C1 | -8.3 pp [-25.0, +0.0] | p=1.000 | 0/1 | 8 |
| S2 vs S1 | C2 | -44.4 pp [-83.3, -0.0] | p=0.250 | 0/3 | 6 |
| S2 vs S1 | C3 | +11.1 pp [+0.0, +33.3] | p=1.000 | 1/0 | 6 |
| S2 vs S1 | C6 | +26.7 pp [+0.0, +66.7] | p=1.000 | 1/0 | 5 |
| S2 vs S1 | C7 | +0.0 pp [+0.0, +0.0] | p=1.000 | 0/0 | 5 |
| S2 vs S1 | C8 | +0.0 pp [+0.0, +0.0] | p=1.000 | 0/0 | 3 |
| S2 vs S1 | Tổng | -4.0 pp [-18.2, +9.1] | p=0.688 | 2/4 | 33 |
| S2 vs S0 | C1 | -41.7 pp [-75.0, -12.5] | p=0.250 | 0/3 | 8 |
| S2 vs S0 | C2 | -61.1 pp [-94.4, -27.8] | p=0.125 | 0/4 | 6 |
| S2 vs S0 | C3 | -44.4 pp [-72.2, -16.7] | p=0.250 | 0/3 | 6 |
| S2 vs S0 | C6 | -13.3 pp [-66.7, +46.7] | p=1.000 | 1/2 | 5 |
| S2 vs S0 | C7 | +0.0 pp [+0.0, +0.0] | p=1.000 | 0/0 | 5 |
| S2 vs S0 | C8 | +0.0 pp [+0.0, +0.0] | p=1.000 | 0/0 | 3 |
| S2 vs S0 | Tổng | -31.3 pp [-47.5, -15.2] | p=0.003 | 1/12 | 33 |
| S2D vs S2 | C1 | +95.8 pp [+87.5, +100.0] | p=0.008 | 8/0 | 8 |
| S2D vs S2 | C2 | +94.4 pp [+83.3, +100.0] | p=0.031 | 6/0 | 6 |
| S2D vs S2 | C3 | +11.1 pp [-11.1, +38.9] | p=1.000 | 1/1 | 6 |
| S2D vs S2 | C6 | +33.3 pp [+6.7, +66.7] | p=0.500 | 2/0 | 5 |
| S2D vs S2 | C7 | +0.0 pp [+0.0, +0.0] | p=1.000 | 0/0 | 5 |
| S2D vs S2 | C8 | +0.0 pp [+0.0, +0.0] | p=1.000 | 0/0 | 3 |
| S2D vs S2 | Tổng | +47.5 pp [+31.3, +63.6] | p=0.000 | 17/1 | 33 |
| S2D vs S1 | C1 | +87.5 pp [+70.8, +100.0] | p=0.016 | 7/0 | 8 |
| S2D vs S1 | C2 | +50.0 pp [+16.7, +83.3] | p=0.250 | 3/0 | 6 |
| S2D vs S1 | C3 | +22.2 pp [+5.6, +44.4] | p=1.000 | 1/0 | 6 |
| S2D vs S1 | C6 | +60.0 pp [+26.7, +93.3] | p=0.250 | 3/0 | 5 |
| S2D vs S1 | C7 | +0.0 pp [+0.0, +0.0] | p=1.000 | 0/0 | 5 |
| S2D vs S1 | C8 | +0.0 pp [+0.0, +0.0] | p=1.000 | 0/0 | 3 |
| S2D vs S1 | Tổng | +43.4 pp [+28.3, +58.6] | p=0.000 | 14/0 | 33 |
| S2D vs S0 | C1 | +54.2 pp [+20.8, +87.5] | p=0.062 | 5/0 | 8 |
| S2D vs S0 | C2 | +33.3 pp [+5.6, +66.7] | p=0.500 | 2/0 | 6 |
| S2D vs S0 | C3 | -33.3 pp [-55.6, -11.1] | p=0.250 | 0/3 | 6 |
| S2D vs S0 | C6 | +20.0 pp [-40.0, +80.0] | p=1.000 | 2/1 | 5 |
| S2D vs S0 | C7 | +0.0 pp [+0.0, +0.0] | p=1.000 | 0/0 | 5 |
| S2D vs S0 | C8 | +0.0 pp [+0.0, +0.0] | p=1.000 | 0/0 | 3 |
| S2D vs S0 | Tổng | +16.2 pp [-1.0, +34.3] | p=0.267 | 9/4 | 33 |

## Phân loại lỗi
Số run thất bại có mã lỗi (một run có thể mang nhiều mã).

| Mã lỗi (từ lý do của grader) | S0 | S1 | S2 | S2D |
|---|---|---|---|---|
| abstained | 11 | 31 | 41 | 1 |
| missing_value | 14 | 22 | 24 | 1 |
| no_code | 0 | 18 | 14 | 7 |
| wrong_safety_label | 9 | 15 | 8 | 3 |
| missing_fact | 6 | 9 | 17 | 0 |
| unsupported_construct:unknown_symbol | 5 | 0 | 1 | 1 |
| over_refusal | 0 | 0 | 3 | 3 |
| sim_violation:SIM-CLK-LIMIT | 1 | 0 | 0 | 1 |
| sim_violation:SIM-CLK-NOSRC | 1 | 0 | 1 | 0 |
| wrong_clock | 1 | 0 | 1 | 0 |
| unmodeled | 1 | 0 | 0 | 0 |
| unsupported_construct:syntax_error | 0 | 0 | 0 | 1 |
| wrong_freq | 0 | 0 | 0 | 1 |
| wrong_i2c_timing | 0 | 0 | 0 | 1 |
| wrong_scl | 0 | 0 | 0 | 1 |

## Lỗi hạ tầng
| Hệ | Run lỗi hạ tầng (loại khỏi TSR) | Tổng run | Nhãn phổ biến |
|---|---|---|---|
| S0 | 0 | 99 | — |
| S1 | 0 | 99 | — |
| S2 | 0 | 99 | — |
| S2D | 0 | 97 | — |

## Ví dụ định tính (1 đúng, tối đa 2 sai điển hình mỗi hệ)
### S0
- **ĐÚNG** `C1-003` (seed 0): _What is the access type of the WUTR register of RTC on the STM32G474 (read-write, read-only or write-only)?_
  - câu trả lời: The WUTR (Wakeup timer register) of the RTC on the STM32G474 is a **read-write** (R/W) register.   [STM32G474 Reference Manual RM0440, p. 817]
  - mã lỗi: —
- **SAI** `C1-002` (seed 0): _What is the address offset of TISEL within the TIM15 peripheral of the STM32G474?_
  - câu trả lời: Insufficient evidence
  - mã lỗi: missing_value, abstained
- **SAI** `C2-003` (seed 0): _The STM32G474 core runs from VCORE Range 2. How many flash wait states are needed at an HCLK of 24 MHz, and what is the highest HCLK frequency allowed in Range 2 according to the wait-state table?_
  - câu trả lời: According to the STM32G474 Reference Manual, for VCORE Range 2: - At an HCLK frequency of 24 MHz, **0 wait states (latency)** are required. - The highest HCLK frequency allowed in Range 2 is **26 MHz** (with 0 wait states, or up to 26 MHz max for the range; note that Range 1 normal/boost supports higher frequencies).  [RM0440 Reference Manual p. 100]
  - mã lỗi: missing_fact
### S1
- **ĐÚNG** `C1-003` (seed 0): _What is the access type of the WUTR register of RTC on the STM32G474 (read-write, read-only or write-only)?_
  - câu trả lời: Based on the provided documents, the access type for the bits in the `RTC_WUTR` register (such as `WUT[15:0]`) is listed as `rw` (read/write).
  - mã lỗi: —
- **SAI** `C1-002` (seed 0): _What is the address offset of TISEL within the TIM15 peripheral of the STM32G474?_
  - câu trả lời: I could not find this in the documents.
  - mã lỗi: missing_value, abstained
- **SAI** `C2-011` (seed 0): _What are the recommended operating supply voltage ranges of the nRF52840 for the VDD pin, the VDDH pin, and the VBUS USB supply?_
  - câu trả lời: I could not find this in the documents.
  - mã lỗi: missing_fact, missing_fact, missing_fact, missing_fact, missing_fact, abstained
### S2
- **ĐÚNG** `C2-015` (seed 0): _I only have a 1.8 V rail for the main supply. Based on the datasheets, which of the STM32G474, the ESP32 (without in-package flash) and the nRF52840 can run from it? Give each chip's minimum supply voltage._
  - câu trả lời: Based on the recommended operating conditions in their respective datasheets, here is how each chip evaluates against a **1.8 V** main supply:  ---  ### 1. **STM32G474** * **Can it run from 1.8 V?** **Yes.** * **Minimum Supply Voltage ($V_{DD}$):** **1.71 V** (Recommended Operating Conditions) [STM32G474_Datasheet p.94]. * **Details:** A 1.8 V rail falls safely within the standard operating voltage range of $1.71\text{ V}$ to $3.6\text{ V}$ [STM32G474_Datasheet p.94].  ---  ### 2. **nRF52840** *
  - mã lỗi: —
- **SAI** `C1-002` (seed 0): _What is the address offset of TISEL within the TIM15 peripheral of the STM32G474?_
  - câu trả lời: Insufficient evidence
  - mã lỗi: missing_value, abstained
- **SAI** `C2-003` (seed 0): _The STM32G474 core runs from VCORE Range 2. How many flash wait states are needed at an HCLK of 24 MHz, and what is the highest HCLK frequency allowed in Range 2 according to the wait-state table?_
  - câu trả lời: Insufficient evidence: step budget exhausted before a verified answer was found.
  - mã lỗi: missing_fact, missing_fact, abstained
### S2D
- **ĐÚNG** `C1-002` (seed 0): _What is the address offset of TISEL within the TIM15 peripheral of the STM32G474?_
  - câu trả lời: The address offset of `TISEL` (`TIM15_TISEL`) within the TIM15 peripheral of the STM32G474 is **`0x5C`** (at absolute address `0x4001405C`) [STM32G474_RM0440 p. 1476].
  - mã lỗi: —
- **SAI** `C1-007` (seed 0): _How far from the RADIO base address is the EVENTS_ADDRESS register on the nRF52840?_
  - câu trả lời: Insufficient evidence: step budget exhausted before a verified answer was found.
  - mã lỗi: missing_value, abstained
- **SAI** `C3-001` (seed 1): _Write bare-metal C for the STM32G474 that accesses registers the CMSIS way (e.g. `TIM1->PSC = ...;`, `RCC->APB2ENR |= RCC_APB2ENR_TIM1EN;`) using the register and bit names of ST's `stm32g4xx.h` device header. Do not use HAL or LL drivers, `SystemCoreClock` or any other library function; write clock frequencies as numeric constants. Do not use interrupts; busy-wait loops on status flags are fine. Initial state: SYSCLK = HCLK = PCLK1 = PCLK2 = 170 MHz (PLL fed by HSI16, AHB/APB1/APB2 prescalers = 1, voltage Range 1 boost mode, Flash wait states already set). Every peripheral clock that is off at reset is still off, and all GPIO pins are in their reset state. Task: on the STM32G474, generate a 20 kHz PWM signal with a 25 % duty cycle on pin PA8 using TIM1 channel 1. The PWM frequency must be within ±1 % and the duty cycle (high time / period) within ±1 percentage point; edge-aligned PWM mode 1, active-high output, no dead time, no interrupts. Answer with one complete C code block (`#include "stm32g4xx.h"`, then a `main()` that configures everything and finally loops forever with `while (1)`), followed by a short explanation._
  - câu trả lời: ```c #include "stm32g4xx.h"  int main(void) {     /* 1. Enable GPIOC and TIM1 clock in RCC */     RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN;     RCC->APB2ENR |= RCC_APB2ENR_TIM1EN;      /* 2. Configure PA8 as Alternate Function (AF6 for TIM1_CH1) */     GPIOA->MODER &= ~(3U << (8 * 2));     GPIOA->MODER |=  (2U << (8 * 2));  /* Alternate function mode */     GPIOA->OTYPER &= ~(1U << 8);       /* Push-pull */     GPIOA->OSPEEDR |= (3U << (8 * 2)); /* Very high speed */     GPIOA->PUPDR   &= ~(3U << (8 
  - mã lỗi: unsupported_construct:unknown_symbol

## Biểu đồ
![TSR theo nhóm](figures/tsr_by_category.png)

![Chi phí so với TSR](figures/cost_vs_tsr.png)

## Manifest tái lập
- commit: `None`
- model: `gemini-3.5-flash-lite`
- base_url: `https://generativelanguage.googleapis.com/v1beta/openai/`
- temperature: `0.0`
- seeds: `3`
- systems: `['S0', 'S1', 'S2', 'S2D']`
- split: `dev`
- cache_mode: `record`
- task_set_sha256: `b5f1f5005c2406ab26bae1bc207b724471c3aee31336f183d3578e6327fc23a0`
- corpus_manifest_sha256: `a4b316e2240fad8b9dd396628e6a9c7d8ef47431209c2c98ddc0c5878016bcf3`
- snapshot_agent_v1_sha256: `4f15b8fdba8bb068acd5ddac37e7d2538fa5476c83ec6a291b2d92ace25be0fd`
- snapshot_agent_p1_sha256: `285dbd1f4fc067ccc94b3fc0b8390532a4df95db67efb4432c5a8cf9a36017d7`
- snapshot_agent_p1_data_sha256: `9fe98cd356545fa525e910451439afd550233410d83b08f600be07a1975c7981`
- native_rag_changelog_sha256: `2fc12da9f9cdf2bd18229706aa9419bd6f8541b110ff538795d818b37dc84ea4`
- hwmodel_vendor_sha256: `e45e467cfb0e25068636e68e8876512d01ca1f075978c84268e7932afa62f03a`
- hwmodel_data_sha256: `3c293c60e0739d3706b1e011d957d34863c380ef9f70468311bf4f62697184b4`
- python: `3.11.16`
- created_at: `2026-10-21T12:13:09+00:00`
- finished_at: `2026-10-22T16:27:27+00:00`
- wall_seconds_total: `2784.8`
- resumes: `8`
- chấm điểm với hwmodel_vendor_sha256 `7b10cafdd8087bb8af0190222cc1102080d0f8466aa0bbda9efcc462b6cdfb27` lúc `2026-10-22T17:24:04+00:00` (hwmodel_data_sha256 `3c293c60e0739d3706b1e011d957d34863c380ef9f70468311bf4f62697184b4`)

**Vấn đề đã biết**
- Agent v1 trích dẫn 'FreeRTOS v10.5.0' trong khi PDF corpus là FreeRTOS V8.2.1 (không sửa trong P0).
- Dữ liệu Agent v1 là hằng số mô phỏng (3 chân, 11 thanh ghi, 8 đoạn văn); điểm thấp trên task sinh từ SVD là baseline hợp lệ.
- Gemini bỏ qua `seed` và API có thể không xác định ngay cả ở temperature 0; mỗi seed được ghi nhận độc lập trong cache.
- Task C1 review_status=auto; C2/C6/C7/C8 chưa có người duyệt độc lập.
- Manifest của dev_baseline được ghi trước khi sửa merge_manifest: args, wall_seconds, finished_at và các hash (corpus/snapshot/changelog/task_set) chỉ phản ánh lần --resume CUỐI (S1, 2026-10-21T17:34Z); created_at là của lần chạy đầu. Giá trị lúc bắt đầu của các lần chạy trước đã mất và KHÔNG được dựng lại; tổng thời gian thật lớn hơn wall_seconds. Từ bản sửa, các lần resume được ghi vào resumes[].

**Thay đổi sau khi lượt chạy bắt đầu**
- Sau khi lượt chạy bắt đầu, đã sửa grader (exact/safety/attack/citation/abstain/common), alias trong corpus/manifest.yaml và cite_values của C1 theo review độc lập; runs.jsonl giữ nguyên, scores.jsonl/report.md được chấm lại bằng eval.score/eval.report (không tốn LLM).
- Task C2-008 được viết lại câu hỏi sau review; mọi run C2-008 cũ bị xoá và chạy lại (3 hệ x 3 seed).
- 26 run S2 lỗi hạ tầng (hết hạn mức ngày của key miễn phí) được chuyển sang runs_infra_failed.jsonl và chạy lại thành công bằng key khác (cùng model gemini-3.5-flash-lite); không run nào còn nhãn infra trong runs.jsonl.
- Phần chạy lại dùng --workers 2 --timeout 600 (lượt đầu: --workers 4 --timeout 180); chỉ ảnh hưởng thời gian chạy, không ảnh hưởng prompt/logic.
- Lượt chạy chia thành nhiều đợt --resume nên args trong manifest là của đợt cuối; created_at là của đợt đầu.
- Replay đầy đủ tập dev phát hiện retrieval của S1 không xác định giữa các tiến trình (HNSW, câu hỏi xa corpus): 2 run S1 C7-004 (seed 0 và 2) bị cache_miss. Đã thêm record/replay cho retrieval vào native-RAG/eval_adapter.py (khoá = câu hỏi, k, seed), xoá 2 run đó và chạy lại (kết quả vẫn 'I could not find this in the documents.'), rồi ghi retrieval cho mọi run S1 dev để replay sau này tất định.
- Sau review (2026-10-22): native-RAG/eval_adapter.py nay replay KHÔNG truy hồi trực tiếp (thiếu bản ghi -> infra:cache_miss), gắn dấu vân tay chỉ mục (11.251 chunk, 1000/150, MiniLM, esp32_rtos) vào bảng meta của cache truy hồi (backfill thủ công sau khi kiểm chỉ mục không đổi), và dùng chung bộ phân loại lỗi với S0/S2. Replay S1 dev (81 run) vẫn trùng 81/81 câu trả lời, nguồn và TSR; runs.jsonl không đổi.
- 2026-10-22: sau review độc lập (plan/reviews/, DECISIONS D11–D15) sửa alias/grader (chấm lại, 0/243 tsr_pass đổi); C1-010 (TIM4_DTR2 không tồn tại trong RM0440 → TIM1_DTR2) và C8-006 (câu ngoài chủ đề → bẫy ngoại suy LEDC_LSCH8) được viết lại câu hỏi: xoá 18 dòng cũ (bản sao ở scratchpad) và chạy lại 3 hệ × 3 seed.
- 2026-10-22 (sau P1, D18): grader exact nhận ký hiệu bit trong markdown ('bit **[17]**', 'Bit: `[17]`'), 'bit offset N, bit width W', và dòng liệt kê ngay sau mệnh đề kết thúc bằng ':'. Chấm lại: đúng 2/324 run đổi (S2D C1-010 seed 1, 2: sai -> đúng); không run nào của S0/S1/S2 đổi.
- 2026-10-23 (P3, D24): header_gen sinh header CMSIS theo header chính thức của ST (STMicroelectronics/cmsis-device-g4 tag v1.2.6, commit 25664ddc3a7624ae9627ae8c4c672073dc5b2539; sha256 từng file trong corpus/manifest.yaml, mục STM32G4_CMSIS_Device_Headers): đổi tên trường/thanh ghi/instance về tên ST, bỏ tên SVD mà ST không có, thêm macro/thanh ghi ST có, sửa giá trị (FLASH_BASE, FMC_BASE, độ rộng trường), tách DMA_Channel/COMP/OPAMP/DMAMUX/SAI_Block/FDCAN_CONFIG như ST; chỉ sửa agent/hwmodel/header_gen.py (kèm test). Đóng băng lại vendor: hwmodel_vendor_sha256 lúc chạy e45e467c… -> lúc chấm trước D24 1e76416e… -> lúc chấm sau D24 6bf1e3cf1c86b76f103f5b39fd87577b7faa4aa0c6e717744cf4875d28b4ec74 (hwmodel_data_sha256 không đổi 3c293c60…); corpus/manifest.yaml sha256 a4b316e2… -> bc3e304c… (chỉ thêm mục header ST; cờ --resume không cần khớp trường này). Chấm lại 394 run (không gọi LLM): 0/394 run đổi tsr_pass, fail_codes hay kết quả compile; TSR C3 không đổi (S0 10/18, S1 0/18, S2 2/18, S2D 4/16 run đạt). Cô lập tác động: cùng bộ chấm hiện tại, vendor cũ và mới cho kết quả GIỐNG HỆT ở cả 394 dòng. Lưu ý: lần chấm lại này cũng nạp bản sửa eval/graders/functional_sim.py (session chính, 23/10 00:15; định dạng details.matched của spec clock) nên 4 dòng C3-020 (S0 seed 1 và 2, S2 seed 0, S2D seed 0) khác ở graders.functional_sim.details.matched, KHÔNG đổi pass/fail. Chi tiết: plan/P3_D24_notes.md, báo cáo đối chiếu: corpus/headers/parity/{before,after}/.

Ghi chú: các giá trị bí mật không bao giờ được ghi vào báo cáo; câu trả lời trích dẫn đã qua redaction.
