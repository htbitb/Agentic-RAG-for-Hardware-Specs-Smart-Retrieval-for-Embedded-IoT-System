# Đối chiếu header sinh tự động với header chính thức của ST

- ST: `/Users/loc4atnt/Master-Course/Ky3/AgenticAI/project/corpus/headers/cmsis-device-g4_v1.2.6/Include` (stm32g474xx.h e7e585172145, stm32g4xx.h 493603c55af5, system_stm32g4xx.h 36304c07e9ce)
- Header sinh: `/var/folders/15/qmflbb9d5yv46fkp4qr83nqc0000gn/T/hwmodel_hdr_n1dzehn8` (stm32g474xx.h 97aebdaf07db, stm32g4xx.h f31d2cba0e19)
- clang: Apple clang version 21.0.0 (clang-2100.3.34.2)

## Tổng quan

Macro (không tính chốt chặn include): ST 14349, sinh 21020, chung 10304; **thiếu 4045**, **thừa 10716**; coverage = chung/ST = 71.8%.

| loại | ST | sinh | chung | thiếu | thừa | coverage |
|---|---:|---:|---:|---:|---:|---:|
| pos | 3840 | 5960 | 2751 | 1089 | 3209 | 71.6% |
| msk | 3840 | 5960 | 2751 | 1089 | 3209 | 71.6% |
| field | 3837 | 5957 | 2748 | 1089 | 3209 | 71.6% |
| field_bit | 1705 | 2368 | 1263 | 442 | 1105 | 74.1% |
| value | 724 | 472 | 472 | 252 | 0 | 65.2% |
| instance | 138 | 136 | 127 | 11 | 9 | 92.0% |
| base | 163 | 160 | 152 | 11 | 8 | 93.3% |
| function_like | 88 | 0 | 0 | 88 | 0 | 0.0% |
| other | 14 | 7 | 6 | 8 | 1 | 42.9% |

Instance: ST 138, sinh 136, chung 127 (coverage 92.0%); thiếu 11, thừa 9, khác kiểu struct 0.

## (a) Thiếu trong header sinh (có ở ST)

- **register_absent** (3822): `DMAMUX_IPHW_CFGR1_NUM_DMA_PERIPH_REQ0`, `DMAMUX_IPHW_CFGR1_NUM_DMA_PERIPH_REQ0_Msk`, `DMAMUX_IPHW_CFGR1_NUM_DMA_PERIPH_REQ0_Pos`, `DMAMUX_IPHW_CFGR1_NUM_DMA_PERIPH_REQ1`, `DMAMUX_IPHW_CFGR1_NUM_DMA_PERIPH_REQ1_Msk`, `DMAMUX_IPHW_CFGR1_NUM_DMA_PERIPH_REQ1_Pos`, `DMAMUX_IPHW_CFGR1_NUM_DMA_PERIPH_REQ2`, `DMAMUX_IPHW_CFGR1_NUM_DMA_PERIPH_REQ2_Msk`, `DMAMUX_IPHW_CFGR1_NUM_DMA_PERIPH_REQ2_Pos`, `DMAMUX_IPHW_CFGR1_NUM_DMA_PERIPH_REQ3`, `DMAMUX_IPHW_CFGR1_NUM_DMA_PERIPH_REQ3_Msk`, `DMAMUX_IPHW_CFGR1_NUM_DMA_PERIPH_REQ3_Pos`, … (+3810)
- **field_absent** (105): `FMC_ECCR_ECC`, `FMC_ECCR_ECC_Msk`, `FMC_ECCR_ECC_Pos`, `FMC_PATT_ATTHIZ`, `FMC_PATT_ATTHIZ_0`, `FMC_PATT_ATTHIZ_1`, `FMC_PATT_ATTHIZ_2`, `FMC_PATT_ATTHIZ_3`, `FMC_PATT_ATTHIZ_4`, `FMC_PATT_ATTHIZ_5`, `FMC_PATT_ATTHIZ_6`, `FMC_PATT_ATTHIZ_7`, … (+93)
- **function_like** (88): `IS_ADC_ALL_INSTANCE`, `IS_ADC_COMMON_INSTANCE`, `IS_ADC_MULTIMODE_MASTER_INSTANCE`, `IS_COMP_ALL_INSTANCE`, `IS_CORDIC_ALL_INSTANCE`, `IS_CRC_ALL_INSTANCE`, `IS_DAC_ALL_INSTANCE`, `IS_DMA_ALL_INSTANCE`, `IS_DMA_REQUEST_GEN_ALL_INSTANCE`, `IS_FDCAN_ALL_INSTANCE`, `IS_FDCAN_CONFIG_INSTANCE`, `IS_FMAC_ALL_INSTANCE`, … (+76)
- **instance** (11): `FMC_Bank1E_R`, `FMC_Bank1_R`, `FMC_Bank3_R`, `HRTIM1`, `HRTIM1_COMMON`, `HRTIM1_TIMA`, `HRTIM1_TIMB`, `HRTIM1_TIMC`, `HRTIM1_TIMD`, `HRTIM1_TIME`, `HRTIM1_TIMF`
- **base** (11): `FMC_Bank1E_R_BASE`, `FMC_Bank1_R_BASE`, `FMC_Bank3_R_BASE`, `HRTIM1_BASE`, `HRTIM1_COMMON_BASE`, `HRTIM1_TIMA_BASE`, `HRTIM1_TIMB_BASE`, `HRTIM1_TIMC_BASE`, `HRTIM1_TIMD_BASE`, `HRTIM1_TIME_BASE`, `HRTIM1_TIMF_BASE`
- **other** (8): `USB_EP1R`, `USB_EP2R`, `USB_EP3R`, `USB_EP4R`, `USB_EP5R`, `USB_EP6R`, `USB_EP7R`, `c7amba_hrtim1_v2_0`

## (b) Thừa trong header sinh (ST không có)

- **register_not_in_st** (10503): `FMC_BCR2_ASYNCWAIT`, `FMC_BCR2_ASYNCWAIT_Msk`, `FMC_BCR2_ASYNCWAIT_Pos`, `FMC_BCR2_BURSTEN`, `FMC_BCR2_BURSTEN_Msk`, `FMC_BCR2_BURSTEN_Pos`, `FMC_BCR2_CBURSTRW`, `FMC_BCR2_CBURSTRW_Msk`, `FMC_BCR2_CBURSTRW_Pos`, `FMC_BCR2_CCLKEN`, `FMC_BCR2_CCLKEN_Msk`, `FMC_BCR2_CCLKEN_Pos`, … (+10491)
- **field_not_in_st** (196): `FMC_BCR1_ASYNCWAIT`, `FMC_BCR1_ASYNCWAIT_Msk`, `FMC_BCR1_ASYNCWAIT_Pos`, `FMC_BCR1_BURSTEN`, `FMC_BCR1_BURSTEN_Msk`, `FMC_BCR1_BURSTEN_Pos`, `FMC_BCR1_CBURSTRW`, `FMC_BCR1_CBURSTRW_Msk`, `FMC_BCR1_CBURSTRW_Pos`, `FMC_BCR1_CPSIZE`, `FMC_BCR1_CPSIZE_0`, `FMC_BCR1_CPSIZE_1`, … (+184)
- **instance** (9): `FMC`, `HRTIM_Common`, `HRTIM_Master`, `HRTIM_TIMA`, `HRTIM_TIMB`, `HRTIM_TIMC`, `HRTIM_TIMD`, `HRTIM_TIME`, `HRTIM_TIMF`
- **base** (8): `HRTIM_Common_BASE`, `HRTIM_Master_BASE`, `HRTIM_TIMA_BASE`, `HRTIM_TIMB_BASE`, `HRTIM_TIMC_BASE`, `HRTIM_TIMD_BASE`, `HRTIM_TIME_BASE`, `HRTIM_TIMF_BASE`

### Instance

- thiếu (11): `FMC_Bank1E_R`, `FMC_Bank1_R`, `FMC_Bank3_R`, `HRTIM1`, `HRTIM1_COMMON`, `HRTIM1_TIMA`, `HRTIM1_TIMB`, `HRTIM1_TIMC`, `HRTIM1_TIMD`, `HRTIM1_TIME`, `HRTIM1_TIMF`
- thừa (9): `FMC`, `HRTIM_Common`, `HRTIM_Master`, `HRTIM_TIMA`, `HRTIM_TIMB`, `HRTIM_TIMC`, `HRTIM_TIMD`, `HRTIM_TIME`, `HRTIM_TIMF`
- khác kiểu struct (0): 

## (c) Offset thành viên struct (theo instance, clang `offsetof`)

Cặp (kiểu ST -> kiểu sinh) đã so: 40 cho 127 instance; thành viên (trừ RESERVED) 425: khớp 423, **lệch offset 0**, **thiếu ở sinh 2**, thừa ở sinh 0; kích thước struct khác nhau: 1.

| ST -> sinh | instance | kiểm | lệch offset | thiếu ở sinh | thừa ở sinh | size ST / sinh |
|---|---|---:|---:|---:|---:|---|
| `ADC_Common_TypeDef->ADC_Common_TypeDef` | ADC12_COMMON, ADC345_COMMON | 3 | 0 | 0 | 0 | 16 / 16 |
| `ADC_TypeDef->ADC_TypeDef` | ADC1, ADC2, ADC3 (+2) | 29 | 0 | 0 | 0 | 196 / 196 |
| `COMP_TypeDef->COMP_TypeDef` | COMP1, COMP2, COMP3 (+4) | 1 | 0 | 0 | 0 | 4 / 4 |
| `CORDIC_TypeDef->CORDIC_TypeDef` | CORDIC | 3 | 0 | 0 | 0 | 12 / 12 |
| `CRC_TypeDef->CRC_TypeDef` | CRC | 5 | 0 | 0 | 0 | 24 / 24 |
| `CRS_TypeDef->CRS_TypeDef` | CRS | 4 | 0 | 0 | 0 | 16 / 16 |
| `DAC_TypeDef->DAC_TypeDef` | DAC, DAC1, DAC2 (+2) | 23 | 0 | 0 | 0 | 100 / 100 |
| `DBGMCU_TypeDef->DBGMCU_TypeDef` | DBGMCU | 5 | 0 | 0 | 0 | 20 / 20 |
| `DMAMUX_ChannelStatus_TypeDef->DMAMUX_ChannelStatus_TypeDef` | DMAMUX1_ChannelStatus | 2 | 0 | 0 | 0 | 8 / 8 |
| `DMAMUX_Channel_TypeDef->DMAMUX_Channel_TypeDef` | DMAMUX1, DMAMUX1_Channel0, DMAMUX1_Channel1 (+14) | 1 | 0 | 0 | 0 | 4 / 4 |
| `DMAMUX_RequestGenStatus_TypeDef->DMAMUX_RequestGenStatus_TypeDef` | DMAMUX1_RequestGenStatus | 2 | 0 | 0 | 0 | 8 / 8 |
| `DMAMUX_RequestGen_TypeDef->DMAMUX_RequestGen_TypeDef` | DMAMUX1_RequestGenerator0, DMAMUX1_RequestGenerator1, DMAMUX1_RequestGenerator2 (+1) | 1 | 0 | 0 | 0 | 4 / 4 |
| `DMA_Channel_TypeDef->DMA_Channel_TypeDef` | DMA1_Channel1, DMA1_Channel2, DMA1_Channel3 (+13) | 4 | 0 | 0 | 0 | 16 / 16 |
| `DMA_TypeDef->DMA_TypeDef` | DMA1, DMA2 | 2 | 0 | 0 | 0 | 8 / 8 |
| `EXTI_TypeDef->EXTI_TypeDef` | EXTI | 12 | 0 | 0 | 0 | 56 / 56 |
| `FDCAN_Config_TypeDef->FDCAN_Config_TypeDef` | FDCAN_CONFIG | 1 | 0 | 0 | 0 | 4 / 4 |
| `FDCAN_GlobalTypeDef->FDCAN_GlobalTypeDef` | FDCAN1, FDCAN2, FDCAN3 | 36 | 0 | 0 | 0 | 236 / 236 |
| `FLASH_TypeDef->FLASH_TypeDef` | FLASH | 18 | 0 | 0 | 0 | 120 / 120 |
| `FMAC_TypeDef->FMAC_TypeDef` | FMAC | 8 | 0 | 0 | 0 | 32 / 32 |
| `GPIO_TypeDef->GPIO_TypeDef` | GPIOA, GPIOB, GPIOC (+4) | 10 | 0 | 0 | 0 | 44 / 44 |
| `I2C_TypeDef->I2C_TypeDef` | I2C1, I2C2, I2C3 (+1) | 11 | 0 | 0 | 0 | 44 / 44 |
| `IWDG_TypeDef->IWDG_TypeDef` | IWDG | 5 | 0 | 0 | 0 | 20 / 20 |
| `LPTIM_TypeDef->LPTIM_TypeDef` | LPTIM1 | 9 | 0 | 0 | 0 | 36 / 36 |
| `OPAMP_TypeDef->OPAMP_TypeDef` | OPAMP, OPAMP1, OPAMP2 (+4) | 2 | 0 | 0 | 0 | 28 / 28 |
| `PWR_TypeDef->PWR_TypeDef` | PWR | 22 | 0 | 0 | 0 | 132 / 132 |
| `QUADSPI_TypeDef->QUADSPI_TypeDef` | QUADSPI | 13 | 0 | 0 | 0 | 52 / 52 |
| `RCC_TypeDef->RCC_TypeDef` | RCC | 30 | 0 | 0 | 0 | 160 / 160 |
| `RNG_TypeDef->RNG_TypeDef` | RNG | 3 | 0 | 0 | 0 | 12 / 12 |
| `RTC_TypeDef->RTC_TypeDef` | RTC | 20 | 0 | 0 | 0 | 96 / 96 |
| `SAI_Block_TypeDef->SAI_Block_TypeDef` | SAI1_Block_A, SAI1_Block_B | 8 | 0 | 0 | 0 | 32 / 32 |
| `SAI_TypeDef->SAI_TypeDef` | SAI1 | 2 | 0 | 0 | 0 | 76 / 76 |
| `SPI_TypeDef->SPI_TypeDef` | SPI1, SPI2, SPI3 (+1) | 9 | 0 | 0 | 0 | 36 / 36 |
| `SYSCFG_TypeDef->SYSCFG_TypeDef` | SYSCFG | 7 | 0 | 0 | 0 | 40 / 40 |
| `TAMP_TypeDef->TAMP_TypeDef` | TAMP | 39 | 0 | 0 | 0 | 384 / 384 |
| `TIM_TypeDef->TIM_TypeDef` | TIM1, TIM15, TIM16 (+9) | 29 | 0 | 0 | 0 | 996 / 996 |
| `UCPD_TypeDef->UCPD_TypeDef` | UCPD1 | 14 | 0 | 0 | 0 | 60 / 60 |
| `USART_TypeDef->USART_TypeDef` | LPUART1, UART4, UART5 (+3) | 12 | 0 | 0 | 0 | 48 / 48 |
| `USB_TypeDef->USB_TypeDef` | USB | 15 | 0 | 2 | 0 | 92 / 84 |
| `VREFBUF_TypeDef->VREFBUF_TypeDef` | VREFBUF | 2 | 0 | 0 | 0 | 8 / 8 |
| `WWDG_TypeDef->WWDG_TypeDef` | WWDG | 3 | 0 | 0 | 0 | 12 / 12 |

Chi tiết các cặp có khác biệt:

- `USB_TypeDef->USB_TypeDef`: lệch ; thiếu ở sinh `BCDR`, `LPMCSR`; thừa ở sinh 

## (d) Giá trị macro trùng tên và địa chỉ instance (clang)

Macro số nguyên trùng tên: 10170; tính được cả hai bên 10170: khớp 10170, **khác giá trị 0**; không tính được 0.
Địa chỉ cơ sở instance chung: kiểm 127, khớp 127, **khác 0**, không tính được 0.

## Giới hạn

- Tên macro so theo chuỗi đầy đủ, phân loại lý do chỉ là heuristic theo tiền tố <nhóm>_<thanh ghi> (không dùng để quyết định so khớp).
- Chỉ `#define` trong file chính được so (không theo #include); #if/#ifdef bị bỏ qua (lấy mọi nhánh).
- Giá trị chỉ so cho macro số nguyên (số, toán tử số học/bit, macro số nguyên khác); các macro khác (chuỗi, con trỏ, hàm) không so giá trị.
- core_cm4.h của ARM không nằm trong repo ST: stub chỉ gồm __I/__O/__IO/...; macro lõi Cortex-M (NVIC_*, SCB_*, SysTick_*) không được kiểm.
