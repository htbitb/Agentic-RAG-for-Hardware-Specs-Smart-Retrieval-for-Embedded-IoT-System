# Đối chiếu header sinh tự động với header chính thức của ST

- ST: `/Users/loc4atnt/Master-Course/Ky3/AgenticAI/project/corpus/headers/cmsis-device-g4_v1.2.6/Include` (stm32g474xx.h e7e585172145, stm32g4xx.h 493603c55af5, system_stm32g4xx.h 36304c07e9ce)
- Header sinh: `/private/tmp/claude-501/-Users-loc4atnt-Master-Course-Ky3-AgenticAI-project/ad321631-49fc-4c9f-8c62-71d1a95a9c16/scratchpad/gen_before2` (stm32g474xx.h 97993ea6faa0, stm32g4xx.h 35e727146bde)
- clang: Apple clang version 21.0.0 (clang-2100.3.34.2)

## Tổng quan

Macro (không tính chốt chặn include): ST 14349, sinh 34837, chung 6739; **thiếu 7610**, **thừa 28098**; coverage = chung/ST = 47.0%.

| loại | ST | sinh | chung | thiếu | thừa | coverage |
|---|---:|---:|---:|---:|---:|---:|
| pos | 3840 | 7270 | 1886 | 1954 | 5384 | 49.1% |
| msk | 3840 | 7270 | 1886 | 1954 | 5384 | 49.1% |
| field | 3837 | 7267 | 1883 | 1954 | 5384 | 49.1% |
| field_bit | 1705 | 12796 | 755 | 950 | 12041 | 44.3% |
| value | 724 | 43 | 41 | 683 | 2 | 5.7% |
| instance | 138 | 91 | 66 | 72 | 25 | 47.8% |
| base | 163 | 95 | 70 | 93 | 25 | 42.9% |
| function_like | 88 | 0 | 0 | 88 | 0 | 0.0% |
| other | 14 | 5 | 0 | 14 | 5 | 0.0% |

Instance: ST 138, sinh 91, chung 66 (coverage 47.8%); thiếu 72, thừa 25, khác kiểu struct 8.

## (a) Thiếu trong header sinh (có ở ST)

- **register_absent** (4693): `COMP_CSR_BLANKING`, `COMP_CSR_BLANKING_0`, `COMP_CSR_BLANKING_1`, `COMP_CSR_BLANKING_2`, `COMP_CSR_BLANKING_Msk`, `COMP_CSR_BLANKING_Pos`, `COMP_CSR_BRGEN`, `COMP_CSR_BRGEN_Msk`, `COMP_CSR_BRGEN_Pos`, `COMP_CSR_EN`, `COMP_CSR_EN_Msk`, `COMP_CSR_EN_Pos`, `COMP_CSR_HYST`, `COMP_CSR_HYST_0`, `COMP_CSR_HYST_1`, `COMP_CSR_HYST_2`, `COMP_CSR_HYST_Msk`, `COMP_CSR_HYST_Pos`, `COMP_CSR_INMSEL`, `COMP_CSR_INMSEL_0`, `COMP_CSR_INMSEL_1`, `COMP_CSR_INMSEL_2`, `COMP_CSR_INMSEL_3`, `COMP_CSR_INMSEL_Msk`, `COMP_CSR_INMSEL_Pos`, `COMP_CSR_INPSEL`, `COMP_CSR_INPSEL_Msk`, `COMP_CSR_INPSEL_Pos`, `COMP_CSR_LOCK`, `COMP_CSR_LOCK_Msk`, … (+4663)
- **field_absent** (1718): `CRC_INIT_INIT`, `CRC_INIT_INIT_Msk`, `CRC_INIT_INIT_Pos`, `DMAMUX_CFR_CSOF0`, `DMAMUX_CFR_CSOF0_Msk`, `DMAMUX_CFR_CSOF0_Pos`, `DMAMUX_CFR_CSOF1`, `DMAMUX_CFR_CSOF10`, `DMAMUX_CFR_CSOF10_Msk`, `DMAMUX_CFR_CSOF10_Pos`, `DMAMUX_CFR_CSOF11`, `DMAMUX_CFR_CSOF11_Msk`, `DMAMUX_CFR_CSOF11_Pos`, `DMAMUX_CFR_CSOF12`, `DMAMUX_CFR_CSOF12_Msk`, `DMAMUX_CFR_CSOF12_Pos`, `DMAMUX_CFR_CSOF13`, `DMAMUX_CFR_CSOF13_Msk`, `DMAMUX_CFR_CSOF13_Pos`, `DMAMUX_CFR_CSOF14`, `DMAMUX_CFR_CSOF14_Msk`, `DMAMUX_CFR_CSOF14_Pos`, `DMAMUX_CFR_CSOF15`, `DMAMUX_CFR_CSOF15_Msk`, `DMAMUX_CFR_CSOF15_Pos`, `DMAMUX_CFR_CSOF1_Msk`, `DMAMUX_CFR_CSOF1_Pos`, `DMAMUX_CFR_CSOF2`, `DMAMUX_CFR_CSOF2_Msk`, `DMAMUX_CFR_CSOF2_Pos`, … (+1688)
- **group_absent** (928): `ADC_AWD2CR_AWD2CH`, `ADC_AWD2CR_AWD2CH_0`, `ADC_AWD2CR_AWD2CH_1`, `ADC_AWD2CR_AWD2CH_10`, `ADC_AWD2CR_AWD2CH_11`, `ADC_AWD2CR_AWD2CH_12`, `ADC_AWD2CR_AWD2CH_13`, `ADC_AWD2CR_AWD2CH_14`, `ADC_AWD2CR_AWD2CH_15`, `ADC_AWD2CR_AWD2CH_16`, `ADC_AWD2CR_AWD2CH_17`, `ADC_AWD2CR_AWD2CH_18`, `ADC_AWD2CR_AWD2CH_2`, `ADC_AWD2CR_AWD2CH_3`, `ADC_AWD2CR_AWD2CH_4`, `ADC_AWD2CR_AWD2CH_5`, `ADC_AWD2CR_AWD2CH_6`, `ADC_AWD2CR_AWD2CH_7`, `ADC_AWD2CR_AWD2CH_8`, `ADC_AWD2CR_AWD2CH_9`, `ADC_AWD2CR_AWD2CH_Msk`, `ADC_AWD2CR_AWD2CH_Pos`, `ADC_AWD3CR_AWD3CH`, `ADC_AWD3CR_AWD3CH_0`, `ADC_AWD3CR_AWD3CH_1`, `ADC_AWD3CR_AWD3CH_10`, `ADC_AWD3CR_AWD3CH_11`, `ADC_AWD3CR_AWD3CH_12`, `ADC_AWD3CR_AWD3CH_13`, `ADC_AWD3CR_AWD3CH_14`, … (+898)
- **base** (93): `ADC12_COMMON_BASE`, `ADC345_COMMON_BASE`, `AHB1PERIPH_BASE`, `AHB2PERIPH_BASE`, `APB1PERIPH_BASE`, `APB2PERIPH_BASE`, `CCMSRAM_BASE`, `CCMSRAM_BB_BASE`, `COMP1_BASE`, `COMP2_BASE`, `COMP3_BASE`, `COMP4_BASE`, `COMP5_BASE`, `COMP6_BASE`, `COMP7_BASE`, `DAC_BASE`, `DMA1_Channel1_BASE`, `DMA1_Channel2_BASE`, `DMA1_Channel3_BASE`, `DMA1_Channel4_BASE`, `DMA1_Channel5_BASE`, `DMA1_Channel6_BASE`, `DMA1_Channel7_BASE`, `DMA1_Channel8_BASE`, `DMA2_Channel1_BASE`, `DMA2_Channel2_BASE`, `DMA2_Channel3_BASE`, `DMA2_Channel4_BASE`, `DMA2_Channel5_BASE`, `DMA2_Channel6_BASE`, … (+63)
- **function_like** (88): `IS_ADC_ALL_INSTANCE`, `IS_ADC_COMMON_INSTANCE`, `IS_ADC_MULTIMODE_MASTER_INSTANCE`, `IS_COMP_ALL_INSTANCE`, `IS_CORDIC_ALL_INSTANCE`, `IS_CRC_ALL_INSTANCE`, `IS_DAC_ALL_INSTANCE`, `IS_DMA_ALL_INSTANCE`, `IS_DMA_REQUEST_GEN_ALL_INSTANCE`, `IS_FDCAN_ALL_INSTANCE`, `IS_FDCAN_CONFIG_INSTANCE`, `IS_FMAC_ALL_INSTANCE`, `IS_GPIO_AF_INSTANCE`, `IS_GPIO_ALL_INSTANCE`, `IS_GPIO_LOCK_INSTANCE`, `IS_HRTIM_ALL_INSTANCE`, `IS_I2C_ALL_INSTANCE`, `IS_I2C_WAKEUP_FROMSTOP_INSTANCE`, `IS_I2S_ALL_INSTANCE`, `IS_IRDA_INSTANCE`, `IS_IWDG_ALL_INSTANCE`, `IS_LPTIM_ENCODER_INSTANCE`, `IS_LPTIM_ENCODER_INTERFACE_INSTANCE`, `IS_LPTIM_INSTANCE`, `IS_LPUART_INSTANCE`, `IS_OPAMP_ALL_INSTANCE`, `IS_PCD_ALL_INSTANCE`, `IS_QSPI_ALL_INSTANCE`, `IS_RNG_ALL_INSTANCE`, `IS_RTC_ALL_INSTANCE`, … (+58)
- **instance** (71): `ADC12_COMMON`, `ADC345_COMMON`, `COMP1`, `COMP2`, `COMP3`, `COMP4`, `COMP5`, `COMP6`, `COMP7`, `DAC`, `DMA1_Channel1`, `DMA1_Channel2`, `DMA1_Channel3`, `DMA1_Channel4`, `DMA1_Channel5`, `DMA1_Channel6`, `DMA1_Channel7`, `DMA1_Channel8`, `DMA2_Channel1`, `DMA2_Channel2`, `DMA2_Channel3`, `DMA2_Channel4`, `DMA2_Channel5`, `DMA2_Channel6`, `DMA2_Channel7`, `DMA2_Channel8`, `DMAMUX1`, `DMAMUX1_Channel0`, `DMAMUX1_Channel1`, `DMAMUX1_Channel10`, … (+41)
- **other** (19): `ADC_MULTIMODE_SUPPORT`, `DAC_CHANNEL2_SUPPORT`, `RCC_HSI48_SUPPORT`, `RCC_PLLP_DIV_2_31_SUPPORT`, `RTC_TAMP_INT_6_SUPPORT`, `SPI_I2S_SUPPORT`, `USB_EP1R`, `USB_EP2R`, `USB_EP3R`, `USB_EP4R`, `USB_EP5R`, `USB_EP6R`, `USB_EP7R`, `__CM4_REV`, `__FPU_PRESENT`, `__MPU_PRESENT`, `__NVIC_PRIO_BITS`, `__Vendor_SysTickConfig`, `c7amba_hrtim1_v2_0`

## (b) Thừa trong header sinh (ST không có)

- **register_not_in_st** (15837): `COMP_C1CSR_BLANKSEL`, `COMP_C1CSR_BLANKSEL_0`, `COMP_C1CSR_BLANKSEL_1`, `COMP_C1CSR_BLANKSEL_2`, `COMP_C1CSR_BLANKSEL_Msk`, `COMP_C1CSR_BLANKSEL_Pos`, `COMP_C1CSR_BRGEN`, `COMP_C1CSR_BRGEN_Msk`, `COMP_C1CSR_BRGEN_Pos`, `COMP_C1CSR_EN`, `COMP_C1CSR_EN_Msk`, `COMP_C1CSR_EN_Pos`, `COMP_C1CSR_HYST`, `COMP_C1CSR_HYST_0`, `COMP_C1CSR_HYST_1`, `COMP_C1CSR_HYST_2`, `COMP_C1CSR_HYST_Msk`, `COMP_C1CSR_HYST_Pos`, `COMP_C1CSR_INMSEL`, `COMP_C1CSR_INMSEL_0`, `COMP_C1CSR_INMSEL_1`, `COMP_C1CSR_INMSEL_2`, `COMP_C1CSR_INMSEL_Msk`, `COMP_C1CSR_INMSEL_Pos`, `COMP_C1CSR_INPSEL`, `COMP_C1CSR_INPSEL_Msk`, `COMP_C1CSR_INPSEL_Pos`, `COMP_C1CSR_LOCK`, `COMP_C1CSR_LOCK_Msk`, `COMP_C1CSR_LOCK_Pos`, … (+15807)
- **field_not_in_st** (4877): `CORDIC_RDATA_RES_0`, `CORDIC_RDATA_RES_1`, `CORDIC_RDATA_RES_10`, `CORDIC_RDATA_RES_11`, `CORDIC_RDATA_RES_12`, `CORDIC_RDATA_RES_13`, `CORDIC_RDATA_RES_14`, `CORDIC_RDATA_RES_15`, `CORDIC_RDATA_RES_16`, `CORDIC_RDATA_RES_17`, `CORDIC_RDATA_RES_18`, `CORDIC_RDATA_RES_19`, `CORDIC_RDATA_RES_2`, `CORDIC_RDATA_RES_20`, `CORDIC_RDATA_RES_21`, `CORDIC_RDATA_RES_22`, `CORDIC_RDATA_RES_23`, `CORDIC_RDATA_RES_24`, `CORDIC_RDATA_RES_25`, `CORDIC_RDATA_RES_26`, `CORDIC_RDATA_RES_27`, `CORDIC_RDATA_RES_28`, `CORDIC_RDATA_RES_29`, `CORDIC_RDATA_RES_3`, `CORDIC_RDATA_RES_30`, `CORDIC_RDATA_RES_31`, `CORDIC_RDATA_RES_4`, `CORDIC_RDATA_RES_5`, `CORDIC_RDATA_RES_6`, `CORDIC_RDATA_RES_7`, … (+4847)
- **per_instance** (4589): `ADC1_AWD2CR_AWD2CH`, `ADC1_AWD2CR_AWD2CH_0`, `ADC1_AWD2CR_AWD2CH_1`, `ADC1_AWD2CR_AWD2CH_10`, `ADC1_AWD2CR_AWD2CH_11`, `ADC1_AWD2CR_AWD2CH_12`, `ADC1_AWD2CR_AWD2CH_13`, `ADC1_AWD2CR_AWD2CH_14`, `ADC1_AWD2CR_AWD2CH_15`, `ADC1_AWD2CR_AWD2CH_16`, `ADC1_AWD2CR_AWD2CH_17`, `ADC1_AWD2CR_AWD2CH_18`, `ADC1_AWD2CR_AWD2CH_2`, `ADC1_AWD2CR_AWD2CH_3`, `ADC1_AWD2CR_AWD2CH_4`, `ADC1_AWD2CR_AWD2CH_5`, `ADC1_AWD2CR_AWD2CH_6`, `ADC1_AWD2CR_AWD2CH_7`, `ADC1_AWD2CR_AWD2CH_8`, `ADC1_AWD2CR_AWD2CH_9`, `ADC1_AWD2CR_AWD2CH_Msk`, `ADC1_AWD2CR_AWD2CH_Pos`, `ADC1_AWD3CR_AWD3CH`, `ADC1_AWD3CR_AWD3CH_0`, `ADC1_AWD3CR_AWD3CH_1`, `ADC1_AWD3CR_AWD3CH_10`, `ADC1_AWD3CR_AWD3CH_11`, `ADC1_AWD3CR_AWD3CH_12`, `ADC1_AWD3CR_AWD3CH_13`, `ADC1_AWD3CR_AWD3CH_14`, … (+4559)
- **core_peripheral** (2461): `FPU`, `FPU_BASE`, `FPU_CPACR`, `FPU_CPACR_BASE`, `FPU_CPACR_CPACR_CP`, `FPU_CPACR_CPACR_CP_0`, `FPU_CPACR_CPACR_CP_1`, `FPU_CPACR_CPACR_CP_2`, `FPU_CPACR_CPACR_CP_3`, `FPU_CPACR_CPACR_CP_Msk`, `FPU_CPACR_CPACR_CP_Pos`, `FPU_FPCAR_ADDRESS`, `FPU_FPCAR_ADDRESS_0`, `FPU_FPCAR_ADDRESS_1`, `FPU_FPCAR_ADDRESS_10`, `FPU_FPCAR_ADDRESS_11`, `FPU_FPCAR_ADDRESS_12`, `FPU_FPCAR_ADDRESS_13`, `FPU_FPCAR_ADDRESS_14`, `FPU_FPCAR_ADDRESS_15`, `FPU_FPCAR_ADDRESS_16`, `FPU_FPCAR_ADDRESS_17`, `FPU_FPCAR_ADDRESS_18`, `FPU_FPCAR_ADDRESS_19`, `FPU_FPCAR_ADDRESS_2`, `FPU_FPCAR_ADDRESS_20`, `FPU_FPCAR_ADDRESS_21`, `FPU_FPCAR_ADDRESS_22`, `FPU_FPCAR_ADDRESS_23`, `FPU_FPCAR_ADDRESS_24`, … (+2431)
- **group_not_in_st** (296): `ADC12_COMMON_CCR_CKMODE`, `ADC12_COMMON_CCR_CKMODE_0`, `ADC12_COMMON_CCR_CKMODE_1`, `ADC12_COMMON_CCR_CKMODE_Msk`, `ADC12_COMMON_CCR_CKMODE_Pos`, `ADC12_COMMON_CCR_DELAY`, `ADC12_COMMON_CCR_DELAY_0`, `ADC12_COMMON_CCR_DELAY_1`, `ADC12_COMMON_CCR_DELAY_2`, `ADC12_COMMON_CCR_DELAY_3`, `ADC12_COMMON_CCR_DELAY_Msk`, `ADC12_COMMON_CCR_DELAY_Pos`, `ADC12_COMMON_CCR_DMACFG`, `ADC12_COMMON_CCR_DMACFG_Msk`, `ADC12_COMMON_CCR_DMACFG_Pos`, `ADC12_COMMON_CCR_DUAL`, `ADC12_COMMON_CCR_DUAL_0`, `ADC12_COMMON_CCR_DUAL_1`, `ADC12_COMMON_CCR_DUAL_2`, `ADC12_COMMON_CCR_DUAL_3`, `ADC12_COMMON_CCR_DUAL_4`, `ADC12_COMMON_CCR_DUAL_Msk`, `ADC12_COMMON_CCR_DUAL_Pos`, `ADC12_COMMON_CCR_MDMA`, `ADC12_COMMON_CCR_MDMA_0`, `ADC12_COMMON_CCR_MDMA_1`, `ADC12_COMMON_CCR_MDMA_Msk`, `ADC12_COMMON_CCR_MDMA_Pos`, `ADC12_COMMON_CCR_PRESC`, `ADC12_COMMON_CCR_PRESC_0`, … (+266)
- **instance** (17): `ADC12_Common`, `ADC345_Common`, `COMP`, `DMAMUX`, `FDCAN`, `FMC`, `HRTIM_Common`, `HRTIM_Master`, `HRTIM_TIMA`, `HRTIM_TIMB`, `HRTIM_TIMC`, `HRTIM_TIMD`, `HRTIM_TIME`, `HRTIM_TIMF`, `LPTIMER1`, `SAI`, `USB_FS_device`
- **base** (17): `ADC12_Common_BASE`, `ADC345_Common_BASE`, `COMP_BASE`, `DMAMUX_BASE`, `FDCAN_BASE`, `HRTIM_Common_BASE`, `HRTIM_Master_BASE`, `HRTIM_TIMA_BASE`, `HRTIM_TIMB_BASE`, `HRTIM_TIMC_BASE`, `HRTIM_TIMD_BASE`, `HRTIM_TIME_BASE`, `HRTIM_TIMF_BASE`, `LPTIMER1_BASE`, `QUADSPI_BASE`, `SAI_BASE`, `USB_FS_device_BASE`
- **other** (4): `STM32G474xx`, `__I`, `__IO`, `__O`

### Instance

- thiếu (72): `ADC12_COMMON`, `ADC345_COMMON`, `COMP1`, `COMP2`, `COMP3`, `COMP4`, `COMP5`, `COMP6`, `COMP7`, `DAC`, `DMA1_Channel1`, `DMA1_Channel2`, `DMA1_Channel3`, `DMA1_Channel4`, `DMA1_Channel5`, `DMA1_Channel6`, `DMA1_Channel7`, `DMA1_Channel8`, `DMA2_Channel1`, `DMA2_Channel2`, `DMA2_Channel3`, `DMA2_Channel4`, `DMA2_Channel5`, `DMA2_Channel6`, `DMA2_Channel7`, `DMA2_Channel8`, `DMAMUX1`, `DMAMUX1_Channel0`, `DMAMUX1_Channel1`, `DMAMUX1_Channel10`, … (+42)
- thừa (25): `ADC12_Common`, `ADC345_Common`, `COMP`, `DMAMUX`, `FDCAN`, `FMC`, `FPU`, `FPU_CPACR`, `HRTIM_Common`, `HRTIM_Master`, `HRTIM_TIMA`, `HRTIM_TIMB`, `HRTIM_TIMC`, `HRTIM_TIMD`, `HRTIM_TIME`, `HRTIM_TIMF`, `LPTIMER1`, `MPU`, `NVIC`, `NVIC_STIR`, `SAI`, `SCB`, `SCB_ACTLR`, `STK`, `USB_FS_device`
- khác kiểu struct (8): `ADC1`: ST ADC_TypeDef / sinh ADC1_TypeDef, `ADC2`: ST ADC_TypeDef / sinh ADC2_TypeDef, `ADC3`: ST ADC_TypeDef / sinh ADC3_TypeDef, `ADC4`: ST ADC_TypeDef / sinh ADC4_TypeDef, `ADC5`: ST ADC_TypeDef / sinh ADC5_TypeDef, `FDCAN1`: ST FDCAN_GlobalTypeDef / sinh FDCAN_TypeDef, `FDCAN2`: ST FDCAN_GlobalTypeDef / sinh FDCAN_TypeDef, `FDCAN3`: ST FDCAN_GlobalTypeDef / sinh FDCAN_TypeDef

## (c) Offset thành viên struct (theo instance, clang `offsetof`)

Cặp (kiểu ST -> kiểu sinh) đã so: 32 cho 66 instance; thành viên (trừ RESERVED) 492: khớp 457, **lệch offset 0**, **thiếu ở sinh 35**, thừa ở sinh 78; kích thước struct khác nhau: 4.

| ST -> sinh | instance | kiểm | lệch offset | thiếu ở sinh | thừa ở sinh | size ST / sinh |
|---|---|---:|---:|---:|---:|---|
| `ADC_TypeDef->ADC1_TypeDef` | ADC1 | 29 | 0 | 0 | 0 | 196 / 196 |
| `ADC_TypeDef->ADC2_TypeDef` | ADC2 | 29 | 0 | 0 | 0 | 196 / 196 |
| `ADC_TypeDef->ADC3_TypeDef` | ADC3 | 29 | 0 | 0 | 0 | 196 / 196 |
| `ADC_TypeDef->ADC4_TypeDef` | ADC4 | 29 | 0 | 0 | 0 | 196 / 196 |
| `ADC_TypeDef->ADC5_TypeDef` | ADC5 | 29 | 0 | 0 | 0 | 196 / 196 |
| `CORDIC_TypeDef->CORDIC_TypeDef` | CORDIC | 3 | 0 | 0 | 0 | 12 / 12 |
| `CRC_TypeDef->CRC_TypeDef` | CRC | 5 | 0 | 0 | 0 | 24 / 24 |
| `CRS_TypeDef->CRS_TypeDef` | CRS | 4 | 0 | 0 | 0 | 16 / 16 |
| `DAC_TypeDef->DAC_TypeDef` | DAC1, DAC2, DAC3 (+1) | 23 | 0 | 23 | 23 | 100 / 100 |
| `DBGMCU_TypeDef->DBGMCU_TypeDef` | DBGMCU | 5 | 0 | 3 | 3 | 20 / 20 |
| `DMA_TypeDef->DMA_TypeDef` | DMA1, DMA2 | 2 | 0 | 0 | 32 | 8 / 164 |
| `EXTI_TypeDef->EXTI_TypeDef` | EXTI | 12 | 0 | 0 | 0 | 56 / 56 |
| `FDCAN_GlobalTypeDef->FDCAN_TypeDef` | FDCAN1, FDCAN2, FDCAN3 | 36 | 0 | 0 | 1 | 236 / 260 |
| `FLASH_TypeDef->FLASH_TypeDef` | FLASH | 18 | 0 | 5 | 0 | 120 / 116 |
| `FMAC_TypeDef->FMAC_TypeDef` | FMAC | 8 | 0 | 0 | 0 | 32 / 32 |
| `GPIO_TypeDef->GPIO_TypeDef` | GPIOA, GPIOB, GPIOC (+4) | 10 | 0 | 0 | 2 | 44 / 44 |
| `I2C_TypeDef->I2C_TypeDef` | I2C1, I2C2, I2C3 (+1) | 11 | 0 | 0 | 0 | 44 / 44 |
| `IWDG_TypeDef->IWDG_TypeDef` | IWDG | 5 | 0 | 0 | 0 | 20 / 20 |
| `OPAMP_TypeDef->OPAMP_TypeDef` | OPAMP | 2 | 0 | 2 | 12 | 28 / 48 |
| `PWR_TypeDef->PWR_TypeDef` | PWR | 22 | 0 | 0 | 0 | 132 / 132 |
| `QUADSPI_TypeDef->QUADSPI_TypeDef` | QUADSPI | 13 | 0 | 0 | 0 | 52 / 52 |
| `RCC_TypeDef->RCC_TypeDef` | RCC | 30 | 0 | 0 | 0 | 160 / 160 |
| `RNG_TypeDef->RNG_TypeDef` | RNG | 3 | 0 | 0 | 0 | 12 / 12 |
| `RTC_TypeDef->RTC_TypeDef` | RTC | 20 | 0 | 0 | 0 | 96 / 96 |
| `SPI_TypeDef->SPI_TypeDef` | SPI1, SPI2, SPI3 (+1) | 9 | 0 | 0 | 0 | 36 / 36 |
| `SYSCFG_TypeDef->SYSCFG_TypeDef` | SYSCFG | 7 | 0 | 1 | 4 | 40 / 40 |
| `TAMP_TypeDef->TAMP_TypeDef` | TAMP | 39 | 0 | 0 | 0 | 384 / 384 |
| `TIM_TypeDef->TIM_TypeDef` | TIM1, TIM15, TIM16 (+9) | 29 | 0 | 1 | 1 | 996 / 996 |
| `UCPD_TypeDef->UCPD_TypeDef` | UCPD1 | 14 | 0 | 0 | 0 | 60 / 60 |
| `USART_TypeDef->USART_TypeDef` | LPUART1, UART4, UART5 (+3) | 12 | 0 | 0 | 0 | 48 / 48 |
| `VREFBUF_TypeDef->VREFBUF_TypeDef` | VREFBUF | 2 | 0 | 0 | 0 | 8 / 8 |
| `WWDG_TypeDef->WWDG_TypeDef` | WWDG | 3 | 0 | 0 | 0 | 12 / 12 |

Chi tiết các cặp có khác biệt:

- `DAC_TypeDef->DAC_TypeDef`: lệch ; thiếu ở sinh `CCR`, `CR`, `DHR12L1`, `DHR12L2`, `DHR12LD`, `DHR12R1`, `DHR12R2`, `DHR12RD`, `DHR8R1`, `DHR8R2`, `DHR8RD`, `DOR1`, `DOR2`, `MCR`, `SHHR`, `SHRR`, `SHSR1`, `SHSR2`, `SR`, `STMODR`, `STR1`, `STR2`, `SWTRIGR`; thừa ở sinh `DAC_CCR`, `DAC_CR`, `DAC_DHR12L1`, `DAC_DHR12L2`, `DAC_DHR12LD`, `DAC_DHR12R1`, `DAC_DHR12R2`, `DAC_DHR12RD`, `DAC_DHR8R1`, `DAC_DHR8R2`, `DAC_DHR8RD`, `DAC_DOR1`, `DAC_DOR2`, `DAC_MCR`, `DAC_SHHR`, `DAC_SHRR`, `DAC_SHSR1`, `DAC_SHSR2`, `DAC_SR`, `DAC_STMODR`, `DAC_STR1`, `DAC_STR2`, `DAC_SWTRGR`
- `DBGMCU_TypeDef->DBGMCU_TypeDef`: lệch ; thiếu ở sinh `APB1FZR1`, `APB1FZR2`, `APB2FZ`; thừa ở sinh `APB1H_FZ`, `APB1L_FZ`, `APB2_FZ`
- `DMA_TypeDef->DMA_TypeDef`: lệch ; thiếu ở sinh ; thừa ở sinh `CCR1`, `CCR2`, `CCR3`, `CCR4`, `CCR5`, `CCR6`, `CCR7`, `CCR8`, `CMAR1`, `CMAR2`, `CMAR3`, `CMAR4`, `CMAR5`, `CMAR6`, `CMAR7`, `CMAR8`, `CNDTR1`, `CNDTR2`, `CNDTR3`, `CNDTR4`, `CNDTR5`, `CNDTR6`, `CNDTR7`, `CNDTR8`, `CPAR1`, `CPAR2`, `CPAR3`, `CPAR4`, `CPAR5`, `CPAR6`, … (+2)
- `FDCAN_GlobalTypeDef->FDCAN_TypeDef`: lệch ; thiếu ở sinh ; thừa ở sinh `CKDIV`
- `FLASH_TypeDef->FLASH_TypeDef`: lệch ; thiếu ở sinh `PCROP2ER`, `PCROP2SR`, `SEC2R`, `WRP2AR`, `WRP2BR`; thừa ở sinh 
- `GPIO_TypeDef->GPIO_TypeDef`: lệch ; thiếu ở sinh ; thừa ở sinh `AFRH`, `AFRL`
- `OPAMP_TypeDef->OPAMP_TypeDef`: lệch ; thiếu ở sinh `CSR`, `TCMR`; thừa ở sinh `OPAMP1_CSR`, `OPAMP1_TCMR`, `OPAMP2_CSR`, `OPAMP2_TCMR`, `OPAMP3_CSR`, `OPAMP3_TCMR`, `OPAMP4_CSR`, `OPAMP4_TCMR`, `OPAMP5_CSR`, `OPAMP5_TCMR`, `OPAMP6_CSR`, `OPAMP6_TCMR`
- `SYSCFG_TypeDef->SYSCFG_TypeDef`: lệch ; thiếu ở sinh `EXTICR`; thừa ở sinh `EXTICR1`, `EXTICR2`, `EXTICR3`, `EXTICR4`
- `TIM_TypeDef->TIM_TypeDef`: lệch ; thiếu ở sinh `OR`; thừa ở sinh `OR1`

## (d) Giá trị macro trùng tên và địa chỉ instance (clang)

Macro số nguyên trùng tên: 6672; tính được cả hai bên 6672: khớp 6594, **khác giá trị 78**; không tính được 0.
Địa chỉ cơ sở instance chung: kiểm 66, khớp 66, **khác 0**, không tính được 0.

Khác giá trị (tối đa 30):

- `DBGMCU_IDCODE_DEV_ID`: ST 0xfff / sinh 0xffff
- `DBGMCU_IDCODE_DEV_ID_Msk`: ST 0xfff / sinh 0xffff
- `FLASH_BASE`: ST 0x8000000 / sinh 0x40022000
- `FLASH_OPTR_BOR_LEV_0`: ST 0x0 / sinh 0x100
- `FLASH_OPTR_BOR_LEV_1`: ST 0x100 / sinh 0x200
- `FLASH_OPTR_BOR_LEV_2`: ST 0x200 / sinh 0x400
- `FMC_BASE`: ST 0x60000000 / sinh 0xa0000000
- `LPTIM_CFGR_TRIGSEL`: ST 0x2000e000 / sinh 0x1e000
- `LPTIM_CFGR_TRIGSEL_3`: ST 0x20000000 / sinh 0x10000
- `LPTIM_CFGR_TRIGSEL_Msk`: ST 0x2000e000 / sinh 0x1e000
- `LPTIM_OR_IN1`: ST 0xd / sinh 0x1
- `LPTIM_OR_IN1_Msk`: ST 0xd / sinh 0x1
- `LPTIM_OR_IN2`: ST 0x32 / sinh 0x2
- `LPTIM_OR_IN2_Msk`: ST 0x32 / sinh 0x2
- `PWR_SR2_PVMO1`: ST 0x1000 / sinh 0x4000
- `PWR_SR2_PVMO1_Msk`: ST 0x1000 / sinh 0x4000
- `PWR_SR2_PVMO1_Pos`: ST 0xc / sinh 0xe
- `PWR_SR2_PVMO2`: ST 0x2000 / sinh 0x8000
- `PWR_SR2_PVMO2_Msk`: ST 0x2000 / sinh 0x8000
- `PWR_SR2_PVMO2_Pos`: ST 0xd / sinh 0xf
- `QUADSPI_CR_FTHRES`: ST 0xf00 / sinh 0x1f00
- `QUADSPI_CR_FTHRES_Msk`: ST 0xf00 / sinh 0x1f00
- `SYSCFG_EXTICR1_EXTI0`: ST 0x7 / sinh 0xf
- `SYSCFG_EXTICR1_EXTI0_Msk`: ST 0x7 / sinh 0xf
- `SYSCFG_EXTICR1_EXTI1`: ST 0x70 / sinh 0xf0
- `SYSCFG_EXTICR1_EXTI1_Msk`: ST 0x70 / sinh 0xf0
- `SYSCFG_EXTICR1_EXTI2`: ST 0x700 / sinh 0xf00
- `SYSCFG_EXTICR1_EXTI2_Msk`: ST 0x700 / sinh 0xf00
- `SYSCFG_EXTICR1_EXTI3`: ST 0x7000 / sinh 0xf000
- `SYSCFG_EXTICR1_EXTI3_Msk`: ST 0x7000 / sinh 0xf000

## Giới hạn

- Tên macro so theo chuỗi đầy đủ, phân loại lý do chỉ là heuristic theo tiền tố <nhóm>_<thanh ghi> (không dùng để quyết định so khớp).
- Chỉ `#define` trong file chính được so (không theo #include); #if/#ifdef bị bỏ qua (lấy mọi nhánh).
- Giá trị chỉ so cho macro số nguyên (số, toán tử số học/bit, macro số nguyên khác); các macro khác (chuỗi, con trỏ, hàm) không so giá trị.
- core_cm4.h của ARM không nằm trong repo ST: stub chỉ gồm __I/__O/__IO/...; macro lõi Cortex-M (NVIC_*, SCB_*, SysTick_*) không được kiểm.
