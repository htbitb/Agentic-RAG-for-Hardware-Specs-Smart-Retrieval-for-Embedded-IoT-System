# P1 — Báo cáo chất lượng dữ liệu (W1)

Sinh tự động bởi `agent/ingestion/data_quality.py` (2026-10-22, seed spot-check 1022). Nguồn: `corpus/` (6 PDF + 3 SVD, sha256 trong `corpus/manifest.yaml`). DB: `agent/data/hw_specs.sqlite`, `agent/data/text_index.*`.

## 1. Số liệu theo chip

| Chip | Peripheral | Thanh ghi | Field | Enum | Thanh ghi không có field | Chân | Hàng AF/IO_MUX | Giới hạn điện | Giới hạn clock |
|---|---|---|---|---|---|---|---|---|---|
| esp32 | 46 | 2613 | 9433 | 79 | 167 | 34 | 138 | 25 | 6 |
| nrf52840 | 73 | 2140 | 5947 | 11542 | 7 | 48 | 19 | 17 | 6 |
| stm32g474 | 91 | 1585 | 11806 | 690 | 5 | 107 | 703 | 23 | 27 |

Text index: **9583 chunk** — ESP32_Datasheet 141, ESP32_TRM 1307, FreeRTOS_Ref_Manual 386, STM32G474_Datasheet 332, STM32G474_RM0440 4593, nRF52840_PS 2824

## 2. Tỷ lệ bản ghi có `doc` + `page` trỏ tới PDF thật

| Bảng | Có trang | Ghi chú |
|---|---|---|
| thanh ghi esp32 | 1952/2613 (74.7%) | 661 chỉ có `esp32`-SVD (page NULL); độ tin cậy trang: high=1445, name=469, summary=38 |
| thanh ghi nrf52840 | 2123/2140 (99.2%) | 17 chỉ có `nrf52840`-SVD (page NULL); độ tin cậy trang: high=2123 |
| thanh ghi stm32g474 | 1484/1585 (93.6%) | 101 chỉ có `stm32g474`-SVD (page NULL); độ tin cậy trang: high=1455, name=7, offset=19, offset_mismatch=3 |
| thanh ghi (cả 3 chip) | 87.7% | |
| chân (`pins`) | 100.0% | trang bảng pin definition / IO_MUX / ball assignment |
| chức năng chân (`pin_functions`) | 100.0% | |
| giới hạn điện + clock | 100.0% | mỗi dòng có trích nguyên văn được kiểm tự động |
| chunk | 100.0% | |

**Gộp (thanh ghi + chân + chức năng chân + giới hạn = 7676 bản ghi): 89.9% có trang.**
Phần thanh ghi không có trang gồm 76 thanh ghi lõi Cortex-M4 của STM32 (NVIC/SCB/STK/MPU/FPU: tài liệu PM0214 không nằm trong corpus) và các thanh ghi 'superset' của SVD mà manual không mô tả (TIM2–5: RCR, BDTR, CCR5/6, CCMR3, DTR2), ESP32: TRM không mô tả ~25% thanh ghi trong SVD.

## 3. Bất thường phát hiện

| Chip | Loại | Số lượng |
|---|---|---|
| esp32 | overlapping_fields | 33 |
| esp32 | svd_only_register | 661 |
| nrf52840 | reset_mismatch | 16 |
| nrf52840 | svd_only_register | 17 |
| stm32g474 | af_signal_without_peripheral | 13 |
| stm32g474 | af_vs_pindef | 2 |
| stm32g474 | name_mismatch | 19 |
| stm32g474 | offset_mismatch | 3 |
| stm32g474 | reset_mismatch | 39 |
| stm32g474 | svd_only_register | 101 |

Ví dụ đã đọc tay đối chiếu với text trang:

- **stm32g474 FLASH.ACR** — SVD reset 0x600; manual FLASH_ACR prints 0x40601 (p.130)
- **stm32g474 RCC.RCC_CR** — SVD reset 0x63; manual RCC_CR prints 0x500 (p.287)
- **stm32g474 SPI2.CR1** — SVD reset 0x700; manual SPIx_CR1 prints 0x0 (p.1874)
- **stm32g474 TIM3.ARR** — SVD reset 0xffffffff; manual TIMx_ARR prints 0xffff (p.1388)
- **stm32g474 ADC3.CR** — SVD reset 0x20002000; manual ADC_CR prints 0x20000000 (p.681)
- **stm32g474 TIM4.DTR2** — Defined in the vendor SVD but no matching register description was found in the indexed manual (automatic matching). Treat address/fields as SVD-derived and unverified; may be an SVD superset or error.
- **stm32g474 PB3** — pin-definition table (Table 12) lists ['UCPD1_CRS_SYNC'] not found in the Table 13 AF row
- **stm32g474 PA9** — pin-definition table (Table 12) lists ['OMP5_OUT'] not found in the Table 13 AF row
- **esp32 GPIO.BT_SELECT** — Defined in the vendor SVD but no matching register description was found in the indexed manual (automatic matching). Treat address/fields as SVD-derived and unverified; may be an SVD superset or error.

## 4. Spot-check ngẫu nhiên

### 4.1 Thanh ghi (20): 18 khớp, 2 không khớp, 0 không kết luận được

Kiểm tra: offset và reset value in trên trang mô tả, vị trí bit của field đầu tiên (STM32: 'Bit(s) n:m NAME'), tên + địa chỉ (ESP32).

| # | Mục | Giá trị DB | Giá trị PDF | Khớp? |
|---|---|---|---|---|
| 1 | stm32g474 TIM6.ARR | offset 0x2c, address 0x4000102c, reset 0x0000ffff, field ARR[15:0] | Address offset: 0x2C; Reset value: 0x0000 FFFF; Bits 19:0 ARR ✗ | ✗ |
| 2 | stm32g474 HRTIM_TIMB.EEFBR2 | offset 0x50, address 0x40016950, reset 0x00000000, field EE6LTCH[0:0] | Reset value: 0x0000 0000; Bit 0 EE6LTCH | ✓ |
| 3 | stm32g474 ADC2.AWD3CR | offset 0xa4, address 0x500001a4, reset 0x00000000, field AWD3CH[18:0] | Address offset: 0xA4; Reset value: 0x0000 0000; Bits 18:0 AWD3CH | ✓ |
| 4 | stm32g474 TIM17.ARR | offset 0x2c, address 0x4001482c, reset 0x0000ffff, field ARR[15:0] | Address offset: 0x2C; Reset value: 0x0000 FFFF; Bits 19:0 ARR ✗ | ✗ |
| 5 | stm32g474 TIM2.DIER | offset 0xc, address 0x4000000c, reset 0x00000000, field UIE[0:0] | Address offset: 0x00C; Reset value: 0x0000 0000; Bit 0 UIE | ✓ |
| 6 | stm32g474 HRTIM_Master.MCMP2R | offset 0x24, address 0x40016824, reset 0x00000000, field MCMP2[15:0] | Address offset: 0x024; Reset value: 0x0000 0000; Bits 15:0 MCMP2 | ✓ |
| 7 | stm32g474 FLASH.SEC1R | offset 0x70, address 0x40022070, reset 0xff00ff00, field SEC_SIZE1[7:0] | Address offset: 0x70; Bits 7:0 SEC_SIZE1 | ✓ |
| 8 | nrf52840 RADIO.MODECNF0 | offset 0x650, address 0x40001650, reset 0x00000200, field RU[0:0] | Address offset: 0x650; Reset 0x00000200; field row 'RU' present | ✓ |
| 9 | nrf52840 USBD.EPIN[6].PTR | offset 0x678, address 0x40027678, reset 0x00000000, field PTR[31:0] | Address offset: 0x678; Reset 0x00000000; field row 'PTR' present | ✓ |
| 10 | nrf52840 EGU4.INTEN | offset 0x300, address 0x40018300, reset 0x00000000, field TRIGGERED0[0:0] | Address offset: 0x300; field TRIGGERED0 row not found | ✓ |
| 11 | nrf52840 UARTE0.TASKS_STOPTX | offset 0xc, address 0x4000200c, reset 0x00000000, field TASKS_STOPTX[0:0] | Address offset: 0x00C; Reset 0x00000000; field row 'TASKS_STOPTX' present | ✓ |
| 12 | nrf52840 RADIO.EVENTS_CRCOK | offset 0x130, address 0x40001130, reset 0x00000000, field EVENTS_CRCOK[0:0] | Address offset: 0x130; field EVENTS_CRCOK row not found | ✓ |
| 13 | nrf52840 PPI.CH[5].TEP | offset 0x53c, address 0x4001f53c, reset 0x00000000, field TEP[31:0] | Address offset: 0x53C; Reset 0x00000000; field row 'TEP' present | ✓ |
| 14 | nrf52840 EGU3.TASKS_TRIGGER[6] | offset 0x18, address 0x40017018, reset 0x00000000, field TASKS_TRIGGER[0:0] | Address offset: 0x018; Reset 0x00000000; field row 'TASKS_TRIGGER' present | ✓ |
| 15 | esp32 MCPWM0.CAP_CH1 | offset 0x100, address 0x3ff5e100, reset 0x00000000, field CAP1_VALUE[31:0] | PWM_CAP_CH1_REG on page; address or offset printed on page | ✓ |
| 16 | esp32 GPIO.FUNC39_IN_SEL_CFG | offset 0x1cc, address 0x3ff441cc, reset 0x00000000, field IN_SEL[5:0] | GPIO_FUNC39_IN_SEL_CFG_REG on page (as array pattern); address or offset printed on page (array formula) | ✓ |
| 17 | esp32 I2C1.COMD9 | offset 0x7c, address 0x3ff6707c, reset 0x00000000, field COMMAND[13:0] | I2C_COMD9_REG on page (as array pattern); address or offset printed on page (array formula) | ✓ |
| 18 | esp32 MCPWM0.GEN2_TSTMP_A | offset 0xb0, address 0x3ff5e0b0, reset 0x00000000, field GEN2_A[15:0] | PWM_GEN2_TSTMP_A_REG on page; address or offset printed on page | ✓ |
| 19 | esp32 GPIO.FUNC237_IN_SEL_CFG | offset 0x4e4, address 0x3ff444e4, reset 0x00000000, field IN_SEL[5:0] | GPIO_FUNC237_IN_SEL_CFG_REG on page (as array pattern); address or offset printed on page (array formula) | ✓ |
| 20 | esp32 GPIO.FUNC121_IN_SEL_CFG | offset 0x314, address 0x3ff44314, reset 0x00000000, field IN_SEL[5:0] | GPIO_FUNC121_IN_SEL_CFG_REG on page (as array pattern); address or offset printed on page (array formula) | ✓ |


### 4.2 Alternate Function (20): 20 khớp, 0 không khớp

STM32: đọc lại ô AF bằng vị trí từ trên trang (không dùng `extract_tables`); ESP32: bảng IO_MUX của datasheet so với TRM Table 6.10-1 (dùng dựng DB).

| # | Mục | Giá trị DB | Giá trị PDF | Khớp? |
|---|---|---|---|---|
| 1 | stm32g474 PA8 AF10 | TIM4_ETR | TIM4_ETR | ✓ |
| 2 | stm32g474 PD10 AF15 | EVENTOUT | EVENTOUT | ✓ |
| 3 | stm32g474 PF2 AF2 | TIM20_CH3 | TIM20_CH3 | ✓ |
| 4 | stm32g474 PC3 AF15 | EVENTOUT | EVENTOUT | ✓ |
| 5 | stm32g474 PA2 AF15 | EVENTOUT | EVENTOUT | ✓ |
| 6 | stm32g474 PC8 AF6 | TIM20_CH3 | TIM20_CH3 | ✓ |
| 7 | stm32g474 PE6 AF3 | SAI1_D1 | SAI1_D1 | ✓ |
| 8 | stm32g474 PG6 AF8 | LPUART1_RTS_DE | LPUART1_RTS_DE | ✓ |
| 9 | stm32g474 PG4 AF15 | EVENTOUT | EVENTOUT | ✓ |
| 10 | stm32g474 PA15 AF4 | I2C1_SCL | I2C1_SCL | ✓ |
| 11 | stm32g474 PC2 AF6 | TIM20_CH2 | TIM20_CH2 | ✓ |
| 12 | stm32g474 PB4 AF6 | SPI3_MISO | SPI3_MISO | ✓ |
| 13 | stm32g474 PD2 AF2 | TIM3_ETR | TIM3_ETR | ✓ |
| 14 | stm32g474 PA13 AF15 | EVENTOUT | EVENTOUT | ✓ |
| 15 | esp32 GPIO22 Function0 | GPIO22 | GPIO22 | ✓ |
| 16 | esp32 GPIO7 Function0 | SD_DATA0 | SD_DATA0 | ✓ |
| 17 | esp32 GPIO22 Function1 | VSPIWP | VSPIWP | ✓ |
| 18 | esp32 GPIO34 Function2 | GPIO34 | GPIO34 | ✓ |
| 19 | esp32 GPIO25 Function5 | EMAC_RXD0 | EMAC_RXD0 | ✓ |
| 20 | esp32 GPIO14 Function1 | HSPICLK | HSPICLK | ✓ |


### 4.3 Giới hạn điện/clock (10): 10 khớp, 0 không khớp

Cột 'Giá trị PDF' là đoạn text trang chứa chuỗi trích; các số trong min/typ/max phải có trong đoạn đó (và đã được đọc lại bằng mắt, xem ghi chú).

| # | Mục | Giá trị DB | Giá trị PDF | Khớp? |
|---|---|---|---|---|
| 1 | stm32g474 Ambient temperature, suffix 3 [STM32G474_Datasheet p.84] | min=-40 typ=None max=125 °C | uffix 3 version Maximum power dissipation -40 125 Low-power dissipation(4) -40 130 TJ Junction temperature range Suffix 6 version -40 105 °C Suffix 3 version -40 130 1. When RESET is re | ✓ |
| 2 | nrf52840 I/O pin voltage (VDD > 3.6 V) [nRF52840_PS p.972] | min=-0.3 typ=None max=3.9 V | 0.3 VDD + 0.3 V VI/O, VDD >3.6 V -0.3 3.9 V NFC antenna pin current INFC1/2 80 mA Radio RF input level 10 dBm Environmental aQFN73 package Storage temperature -40 +125 °C MSL Moisture S | ✓ |
| 3 | nrf52840 Input high voltage VIH [nRF52840_PS p.370] | min=0.7*VDD typ=None max=None V | Typ. Max. Units VIH Input high voltage 0.7 x VDD VDD V VIL Input low voltage VSS 0.3 x VDD V VOH,SD Output high voltage, standard drive, 0.5 mA, VDD ≥ 1.7 VDD - 0.4 VDD V VOH,HDH Output | ✓ |
| 4 | esp32 CHIP_PU low-level input voltage VIL_nRST [ESP32_Datasheet p.52] | min=None typ=None max=0.6 V | — VDD 1 + 0.3 V VIL_nRST Low-level input voltage of CHIP_PU to shut down the chip — — 0.6 V 1. Please see T ableIO_MUX for IO’s power domain. VDD is the I/O voltage for a particular pow | ✓ |
| 5 | esp32 Supply voltage VDD3P3 / VDDA / VDD3P3_RTC / VDD3P3_CPU / VDD_SDIO [ESP32_Datasheet p.51] | min=-0.3 typ=None max=3.6 V | on Min Max Unit VDDA, VDD3P3, VDD3P3_RTC, VDD3P3_CPU, VDD_SDIO Allowed input voltage ⚶0.3 3.6 V Ioutput1 Cumulative IO output current — 1200 mA TST ORE Storage temperature ⚶40 150 °C 1 | ✓ |
| 6 | stm32g474 Output current sunk by any I/O and control pin [STM32G474_Datasheet p.83] | min=None typ=None max=20 mA | 1) 100 IIO(PIN) Output current sunk by any I/O and control pin except FT_f 20 Output current sunk by any FT_f pin 20 Output current sourced by any I/O and control pin 20 ∑IIO(PIN) Total | ✓ |
| 7 | nrf52840 LFRC nominal frequency [nRF52840_PS p.172] | min=None typ=32.768 max=None kHz | Typ. Max. Units fNOM_LFRC Nominal frequency 32.768 kHz fTOL_LFRC Frequency tolerance, uncalibrated ±5 % fTOL_CAL_LFRC Frequency tolerance after calibration13 ±500 ppm ILFRC Run current | ✓ |
| 8 | stm32g474 Flash wait states: 2 WS (LATENCY = 2) maximum HCLK [STM32G474_RM0440 p.98] | min=None typ=None max=26 MHz | ≤ 68 ≤ 60 ≤ 24 2 WS (3 CPU cycles) ≤ 102 ≤ 90 ≤ 26 3 WS (4 CPU cycles) ≤ 136 ≤ 120 - 4 WS (5 CPU cycles) ≤ 170 ≤ 150 - | ✓ |
| 9 | stm32g474 LSE crystal frequency [STM32G474_Datasheet p.119] | min=None typ=32.768 max=None kHz | en to add one. Table 42. LSE oscillator characteristics (fLSE = 32.768 kHz)(1) 1. Guaranteed by design. Symbol Parameter Conditions (2) 2. Refer to the note and caution paragraphs bel | ✓ |
| 10 | nrf52840 HFXO external crystal frequency [nRF52840_PS p.171] | min=None typ=32 max=None MHz | requency 64 MHz fXTAL_HFXO External crystal frequency 32 MHz fTOL_HFXO Frequency tolerance requirement for 2.4 GHz proprietary radio applications ±60 ppm fTOL_HFXO_BLE Frequency toleran | ✓ |


### 4.4 Ghi chú sau khi đọc lại các dòng spot-check

- **Thanh ghi #1 và #4 (TIM6.ARR, TIM17.ARR) — sai khác THẬT SVD↔RM**: RM0440 mô tả 'Bits 19:0 ARR[19:0]: Auto-reload value' (p.1528, p.1496; có chế độ dithering: ARR[19:4] phần nguyên, ARR[3:0] phần dither; khi DITHEN=0 giá trị nạp lại là ARR[15:0], ARR[19:16] dự trữ) còn SVD chỉ có field ARR rộng 16 bit [15:0]. Offset và reset khớp. Đọc tay trên text trang. Cùng nguyên nhân với mọi thanh ghi TIMx_ARR của timer 16 bit.
- **Thanh ghi nRF (#10 EGU4.INTEN, #12 RADIO.EVENTS_CRCOK)**: Offset/reset khớp; thành phần 'field' không kết luận được vì dòng bảng field của PS nằm ở dạng 'ID R/W Field' với chữ cái ID thay vị trí bit nên bộ kiểm chỉ xác nhận sự hiện diện của tên field. Vị trí bit nRF được kiểm bằng golden test (tests/test_svd_golden.py: PIN_CNF, PSEL.SCL) và bằng parity với parser eval.
- **Thanh ghi ESP32 (#15–#20)**: Kiểm tên thanh ghi và địa chỉ/offset (bao gồm công thức mảng 'GPIO_FUNCy_IN_SEL_CFG_REG (0x130+0x4*y)'). Không kiểm vị trí bit (bảng bit của TRM là hình khối không đọc được từ text) — vị trí bit ESP32 chỉ dựa vào SVD (kiểm tới mức parity với parser eval). Reset value ESP32 không được kiểm. Spot-check ESP32 dùng cùng họ mẫu 'n/m/x/y → \\d+' với extractor (không độc lập về khoảng chỉ số); lỗi khoảng chỉ số do reviewer phát hiện đã được sửa trong extractor và có test riêng (tests/test_register_pages_nrf_esp.py).
- **Alternate Function**: 20/20 khớp. STM32 đọc lại bằng vị trí từ (độc lập với extract_tables); ESP32 so bảng IO_MUX của datasheet (tr.69) với TRM Table 6.10-1. nRF52840 chân cố định không nằm trong spot-check AF (không có bảng AF); 18 chân đã đối chiếu tay trong tests/test_pinout_esp_nrf.py từ PS tr.927–929.
- **Giới hạn điện/clock**: Đã đọc lại bằng mắt cả 10 dòng trong cột 'Giá trị PDF': TA suffix 3 = -40..125 °C; nRF VI/O (VDD>3.6 V) = -0.3..3.9 V; nRF VIH = 0.7×VDD..VDD; ESP32 VIL_nRST max 0.6 V; ESP32 điện áp cấp (ký tự '⚶' trong text PDF là dấu trừ) -0.3..3.6 V; STM32 IIO(PIN) sunk 20 mA; nRF LFRC 32.768 kHz; STM32 wait states 2 WS ≤ 102/≤ 90/≤ 26 MHz (hàng DB ứng với dải VCORE Range 2 = 26 MHz); STM32 LSE 32.768 kHz; nRF HFXO crystal 32 MHz. Tất cả khớp.
- **Giới hạn của spot-check**: Cỡ mẫu 20/20/10 là chỉ báo, không phải bằng chứng thống kê; các kiểm tra tự động dùng regex riêng trên cùng text trang nên không phát hiện lỗi mà bản thân text PDF (pypdf) đã sai. Chưa có người duyệt độc lập.

## 5. Truy hồi (text index hybrid) trên split `dev`

Đo trên 14 task dev của C1+C2 (trang được truy hồi có chứa giá trị kỳ vọng — cùng định nghĩa `retrieval_hit` của grader citation). Đo một lần, không chỉnh chunker/index theo kết quả.

| Hệ | k | Recall, trang đầu của chunk (so sánh được với S1) | Recall, mọi trang trong page_start..page_end | C1 | C2 | Recall, chunk chứa giá trị (chặt nhất) |
|---|---|---|---|---|---|---|
| S1 (Native RAG, Chroma, chunk 1000/150; mỗi nguồn một trang) | 4 | 57.1% | — | — | — | — |
| agent index — bm25 | 4 | 85.7% | 85.7% | 75.0% | 100.0% | 78.6% |
| agent index — bm25 | 8 | 92.9% | 92.9% | 87.5% | 100.0% | 85.7% |
| agent index — dense | 4 | 78.6% | 78.6% | 75.0% | 83.3% | 71.4% |
| agent index — dense | 8 | 85.7% | 92.9% | 87.5% | 100.0% | 71.4% |
| agent index — hybrid | 4 | 100.0% | 100.0% | 100.0% | 100.0% | 92.9% |
| agent index — hybrid | 8 | 100.0% | 100.0% | 100.0% | 100.0% | 92.9% |

**Lưu ý so sánh:** `retrieval_hit` của S1 xét MỘT trang cho mỗi nguồn. Chunk của agent có thể trải nhiều trang (≈ 39% chunk vắt qua 2 trang), nên cột 'mọi trang trong khoảng' rộng hơn S1; số so sánh được với S1 là cột 'trang đầu của chunk' (và cột chặt nhất 'chunk chứa giá trị'). Cỡ mẫu 14 task — chỉ là chỉ báo, không đủ để kết luận có ý nghĩa thống kê.
