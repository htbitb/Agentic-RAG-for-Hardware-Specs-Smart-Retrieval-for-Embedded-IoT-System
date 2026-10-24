### 1. Tính toán cấu hình PWM trên STM32G474 (Clock 170 MHz)

Chân **PA8** được sử dụng làm kênh xuất xung PWM cho **TIM1_CH1** (Alternate Function **AF6**).
Tần số Timer Clock $f_{TIM} = 170\text{ MHz}$.

Công thức tạo tần số PWM (Edge-aligned up-counting):
$$f_{PWM} = \frac{f_{TIM}}{(PSC + 1) \times (ARR + 1)}$$

Với yêu cầu:
- Tần số xung $f_{PWM} = 20\text{ kHz}$
- Hệ số làm việc $Duty = 25\%$

Ta chọn:
- **Prescaler ($PSC$)**: $0$ (chạy trực tiếp ở $170\text{ MHz}$ để độ phân giải PWM đạt mức cao nhất)
- **Auto-Reload Register ($ARR$)**:
  $$ARR + 1 = \frac{170\,000\,000}{20\,000 \times (0 + 1)} = 8500 \implies ARR = 8499$$
- **Capture/Compare Register 1 ($CCR1$)**:
  $$CCR1 = 8500 \times 25\% = 2125$$
  - Độ phân giải: $\approx 13\text{ bits}$ (8500 bước), sai số tần số và duty cycle: $0.0\%$.

> **Lưu ý quan trọng đối với TIM1**: Là timer nâng cao (Advanced-control timer), cần bật bit **`MOE`** (Main Output Enable) trong thanh ghi `TIM1->BDTR` thì chân output mới xuất tín hiệu ra ngoại vi.

---

### 2. Mã nguồn CMSIS (`tim1_pwm_pa8.c`)

```c
#include "stm32g4xx.h"

/**
 * @brief Khởi tạo PWM 20 kHz, duty 25% trên PA8 (TIM1_CH1) với Clock hệ thống 170 MHz.
 */
void tim1_pa8_pwm_init(void)
{
    /* 1. Cấp xung clock cho GPIOA và TIM1 */
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN;
    RCC->APB2ENR |= RCC_APB2ENR_TIM1EN;

    /* 2. Cấu hình chân PA8 thành Alternate Function mode (AF6 - TIM1_CH1) */
    GPIOA->MODER &= ~GPIO_MODER_MODE8_Msk;
    GPIOA->MODER |= (2U << GPIO_MODER_MODE8_Pos);        /* AF Mode (10b) */

    GPIOA->AFR[1] &= ~(0xFU << ((8U - 8U) * 4U));
    GPIOA->AFR[1] |= (6U << ((8U - 8U) * 4U));           /* AF6: TIM1_CH1 */

    GPIOA->OSPEEDR |= (3U << GPIO_OSPEEDR_OSPEED8_Pos);  /* Very high speed */
    GPIOA->PUPDR   &= ~GPIO_PUPDR_PUPD8_Msk;             /* No pull-up / pull-down */

    /* 3. Cấu hình chu kỳ và độ rộng xung cho TIM1 */
    TIM1->PSC  = 0U;     /* Prescaler = 0 => f_cnt = 170 MHz */
    TIM1->ARR  = 8499U;  /* ARR = 8499 => f_pwm = 170 MHz / 8500 = 20 kHz */
    TIM1->CCR1 = 2125U;  /* CCR1 = 2125 => Duty = 2125 / 8500 = 25% */

    /* 4. Cấu hình kênh 1 ở PWM Mode 1 (OC1M = 0110b) và bật preload (OC1PE) */
    TIM1->CCMR1 &= ~TIM_CCMR1_OC1M_Msk;
    TIM1->CCMR1 |= (6U << TIM_CCMR1_OC1M_Pos) | TIM_CCMR1_OC1PE;

    /* 5. Cho phép ngõ ra kênh 1 (CC1E = 1), cực tính tích cực mức cao (CC1P = 0) */
    TIM1->CCER &= ~TIM_CCER_CC1P;
    TIM1->CCER |= TIM_CCER_CC1E;

    /* 6. Bật tính năng Preload cho thanh ghi ARR */
    TIM1->CR1 |= TIM_CR1_ARPE;

    /* 7. Kích hoạt Main Output Enable (MOE) đối với Advanced Timer */
    TIM1->BDTR |= TIM_BDTR_MOE;

    /* 8. Tạo sự kiện cập nhật để load ngay giá trị thanh ghi đệm */
    TIM1->EGR |= TIM_EGR_UG;

    /* 9. Bật bộ đếm timer */
    TIM1->CR1 |= TIM_CR1_CEN;
}

/**
 * @brief Thay đổi duty cycle theo phần trăm (0.0% - 100.0%)
 */
void tim1_set_duty(float duty_percent)
{
    if (duty_percent < 0.0f) duty_percent = 0.0f;
    if (duty_percent > 100.0f) duty_percent = 100.0f;

    TIM1->CCR1 = (uint32_t)((duty_percent / 100.0f) * (TIM1->ARR + 1U));
}
```