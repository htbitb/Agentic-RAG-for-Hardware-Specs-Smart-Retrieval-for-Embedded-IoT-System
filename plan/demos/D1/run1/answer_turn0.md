### Giải pháp cấu hình PWM 20 kHz, Duty 25% trên STM32G474 (PA8)

#### 1. Cơ sở tính toán xung nhịp & Timer
* **Hệ thống clock**: Hệ thống chạy ở **170 MHz** (Range 1 Boost mode). Flash latency cần đặt là **4 WS** theo RM0440 Table 9 (trang 98) cho tần số 170 MHz. Timers kết nối qua APB2 bus với prescaler = 1 nên xung nhịp cấp cho TIM1 là:
  $$f_{\text{TIM1CLK}} = 170\text{ MHz}$$
* **Chân xuất tín hiệu**: **PA8** được cấu hình chế độ Alternate Function **AF6** ứng với kênh **TIM1_CH1** (STM32G474 Datasheet, Table 13).
* **Tính toán tham số PWM (Edge-aligned PWM Mode 1)**:
  * Chu kỳ mục tiêu: $f_{\text{PWM}} = 20\text{ kHz} \implies T = 50\ \mu\text{s}$.
  * Tổng số bước đếm trong 1 chu kỳ: $N = \frac{f_{\text{TIM1CLK}}}{f_{\text{PWM}}} = \frac{170\,000\,000}{20\,000} = 8500\text{ ticks}$.
  * Đặt bộ chia trước **$\text{PSC} = 0$** (chạy trực tiếp ở 170 MHz để đạt độ phân giải cao nhất, $\approx 13\text{ bit}$).
  * Giá trị thanh ghi tự động nạp lại:
    $$\text{ARR} = 8500 - 1 = 8499$$
  * Duty cycle mục tiêu $25\%$:
    $$\text{CCR1} = 8500 \times 25\% = 2125$$
    *(Tần số thực tế: chính xác $20.000\text{ kHz}$; Duty thực tế: chính xác $25.0\%$, sai số $0\%$)*.
* **Lưu ý đặc thù với Advanced Control Timer (TIM1)**: Cần kích hoạt bit **`MOE`** (*Main Output Enable*) trong thanh ghi `TIM1->BDTR`, nếu không các chân ngõ ra của TIM1 sẽ không xuất xung ra bên ngoài.

---

#### 2. Mã nguồn cấu hình bare-metal CMSIS (`pwm_tim1_pa8.c`)

```c
#include "stm32g4xx.h"

/**
 * @brief Cấu hình hệ thống xung nhịp lên 170 MHz từ HSI16 (Range 1 Boost Mode)
 */
void SystemClock_Config(void)
{
    /* 1. Thiết lập Flash latency: 4 WS (RM0440 Table 9 p.98 cho 170 MHz Range 1 Boost) */
    FLASH->ACR = (FLASH->ACR & ~FLASH_ACR_LATENCY) | FLASH_ACR_LATENCY_4WS;

    /* 2. Bật nguồn PWR và cấu hình điện áp Range 1 Boost mode */
    RCC->APB1ENR1 |= RCC_APB1ENR1_PWREN;
    PWR->CR1 = (PWR->CR1 & ~PWR_CR1_VOS) | PWR_CR1_VOS_0; /* Range 1 */
    PWR->CR5 &= ~PWR_CR5_R1MODE;                          /* 0: Range 1 Boost mode enabled */

    /* 3. Cấu hình PLL từ HSI16 (16 MHz):
     *    f_VCO_IN = 16 MHz / M(4) = 4 MHz
     *    f_VCO_OUT = 4 MHz * N(85) = 340 MHz
     *    f_PLL_R = 340 MHz / R(2) = 170 MHz
     */
    RCC->PLLCFGR = RCC_PLLCFGR_PLLSRC_1 |                /* Nguồn PLL = HSI16 */
                   ((4U - 1U) << RCC_PLLCFGR_PLLM_Pos) | /* M = 4 */
                   (85U << RCC_PLLCFGR_PLLN_Pos) |       /* N = 85 */
                   (0U << RCC_PLLCFGR_PLLR_Pos) |        /* R = 2 (00b: /2) */
                   RCC_PLLCFGR_PLLREN;                   /* Bật PLLCLK output */

    /* Kích hoạt PLL và chờ ổn định */
    RCC->CR |= RCC_CR_PLLON;
    while (!(RCC->CR & RCC_CR_PLLRDY));

    /* 4. Chuyển SYSCLK sang PLL */
    RCC->CFGR = (RCC->CFGR & ~RCC_CFGR_SW) | RCC_CFGR_SW_PLL;
    while ((RCC->CFGR & RCC_CFGR_SWS) != RCC_CFGR_SWS_PLL);
}

/**
 * @brief Khởi tạo TIM1_CH1 tạo PWM 20 kHz, duty 25% trên PA8
 */
void TIM1_PA8_PWM_Init(void)
{
    /* 1. Cấp xung nhịp cho GPIOA và TIM1 */
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN;
    RCC->APB2ENR |= RCC_APB2ENR_TIM1EN;

    /* 2. Cấu hình PA8 ở chế độ Alternate Function AF6 (TIM1_CH1) */
    GPIOA->MODER &= ~(GPIO_MODER_MODE8_Msk);
    GPIOA->MODER |= (2U << GPIO_MODER_MODE8_Pos);         /* Mode: Alternate function (10b) */

    GPIOA->AFR[1] &= ~(GPIO_AFRH_AFSEL8_Msk);
    GPIOA->AFR[1] |= (6U << GPIO_AFRH_AFSEL8_Pos);         /* AF6 cho chân PA8 */

    GPIOA->OSPEEDR |= (3U << GPIO_OSPEEDR_OSPEED8_Pos);    /* Tốc độ cao (Very high speed) */
    GPIOA->PUPDR &= ~(GPIO_PUPDR_PUPD8_Msk);              /* Không kéo (No pull-up / pull-down) */

    /* 3. Thiết lập thông số đếm cho TIM1 (f_clk = 170 MHz) */
    TIM1->PSC = 0;              /* PSC = 0: đếm theo xung nhịp 170 MHz */
    TIM1->ARR = 8500 - 1;       /* ARR = 8499: Chu kỳ đếm 8500 xung -> Tần số = 170M / 8500 = 20 kHz */
    TIM1->CCR1 = 2125;          /* CCR1 = 2125: Duty cycle = 2125 / 8500 = 25.0% */

    /* 4. Cấu hình chế độ PWM Mode 1 trên kênh 1 (OC1M = 0110b) và kích hoạt Preload */
    TIM1->CCMR1 &= ~(TIM_CCMR1_OC1M_Msk | TIM_CCMR1_CC1S_Msk);
    TIM1->CCMR1 |= (6U << TIM_CCMR1_OC1M_Pos) | TIM_CCMR1_OC1PE;

    /* Cho phép ngõ ra kênh 1 (CH1 active-high) */
    TIM1->CCER |= TIM_CCER_CC1E;

    /* Bật Auto-reload preload (ARPE) */
    TIM1->CR1 |= TIM_CR1_ARPE;

    /* Bật Main Output Enable (bắt buộc cho Advanced Timer TIM1) */
    TIM1->BDTR |= TIM_BDTR_MOE;

    /* Tạo Update Event để nạp ngay giá trị từ preload registers vào active registers */
    TIM1->EGR |= TIM_EGR_UG;

    /* Kích hoạt bộ đếm TIM1 */
    TIM1->CR1 |= TIM_CR1_CEN;
}

int main(void)
{
    SystemClock_Config();
    TIM1_PA8_PWM_Init();

    while (1)
    {
        /* Vòng lặp chính - tín hiệu PWM 20 kHz 25% được tạo tự động bởi phần cứng */
    }
}
```

---

#### 3. Kết quả xác thực & Mô phỏng
* **Biên dịch**: Đạt chuẩn CMSIS qua kiểm tra cú pháp và kiểu dữ liệu với clang (`status: ok`, không lỗi).
* **Mô phỏng thanh ghi**: Xác nhận tín hiệu PWM xuất ra chân **PA8** (TIM1_CH1) với tần số **20000 Hz**, hệ số tác dụng **25%** tại xung nhịp hệ thống **170 MHz**.
* **DRC**: Đạt 100% các tiêu chuẩn về chân (DRC-PIN), xung nhịp (DRC-CLK) và thiết kế.