### Giải pháp cấu hình PWM 20 kHz, Duty 25% trên chân PA8 (STM32G474)

---

### 1. Phân tích xung nhịp (Clock Tree & Timer Clock)
* **SYSCLK** = 170 MHz (nguồn PLL từ HSI16 đã hoạt động).
* **AHB Prescaler** = 1 $\rightarrow$ **HCLK** = 170 MHz.
* **APB2 Prescaler** = 2 $\rightarrow$ **PCLK2** = $\frac{170\text{ MHz}}{2} = 85\text{ MHz}$.
* **Quy tắc xung nhịp Timer (RM0440 Section 7.2.13 - Timer clock):**
  Khi bộ chia APB khác 1 (ở đây `PPRE2 = /2`), tần số xung nhịp cấp cho các khối Timer trên bus APB2 (như TIM1) sẽ tự động nhân 2 bởi phần cứng:
  $$f_{\text{TIM1CLK}} = 2 \times \text{PCLK2} = 2 \times 85\text{ MHz} = 170\text{ MHz}$$

---

### 2. Tính toán thông số Timer TIM1 & Pin Mapping
* **Chân PA8:** Chức năng ngoại vi là **TIM1_CH1** tương ứng với Alternate Function **AF6** (STM32G474 Datasheet Pin Alternate Functions Table).
* **Tần số PWM ($f_{\text{PWM}} = 20\text{ kHz}$):**
  $$f_{\text{PWM}} = \frac{f_{\text{TIM1CLK}}}{(\text{PSC} + 1) \times (\text{ARR} + 1)}$$
  Để đạt độ phân giải chu kỳ công tác (duty resolution) cao nhất:
  * Chọn $\text{PSC} = 0 \implies (\text{ARR} + 1) = \frac{170\,000\,000}{20\,000} = 8500 \implies \mathbf{ARR = 8499}$.
  * Độ phân giải đạt 8500 bước ($> 13\text{ bits}$). Sai số tần số: $0\%$.
* **Độ rộng xung (Duty Cycle = 25%):**
  $$\text{CCR1} = 25\% \times (\text{ARR} + 1) = 0.25 \times 8500 = \mathbf{2125}$$
  Sai số duty: $0\%$.
* **Lưu ý đặc biệt với TIM1 (Advanced Control Timer):**
  Bắt buộc phải bật bit **`MOE`** (Main Output Enable) trong thanh ghi `TIM1->BDTR`, nếu không ngõ ra tín hiệu PWM tại chân PA8 sẽ bị ngắt (hi-Z / idle).

---

### 3. Mã nguồn C (chuẩn CMSIS bare-metal)

```c
#include "stm32g4xx.h"

/**
 * @brief Khởi tạo PWM 20 kHz, duty 25% trên PA8 (TIM1_CH1)
 *        - SYSCLK = 170 MHz
 *        - PPRE2 = /2 => PCLK2 = 85 MHz => TIM1CLK = 170 MHz
 */
void tim1_pa8_pwm_init(void) {
    /* 1. Cấu hình bộ chia APB2 = 2 trong RCC_CFGR */
    /* PPRE2 = 0b100 (tương ứng chia 2 trong RM0440) */
    RCC->CFGR = (RCC->CFGR & ~RCC_CFGR_PPRE2_Msk) | RCC_CFGR_PPRE2_DIV2;

    /* 2. Cấp xung nhịp ngoại vi cho GPIOA và TIM1 */
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN;
    RCC->APB2ENR |= RCC_APB2ENR_TIM1EN;

    /* 3. Cấu hình chân PA8 làm Alternate Function AF6 (TIM1_CH1) */
    /* MODER8 = 10b (Alternate Function mode) */
    GPIOA->MODER = (GPIOA->MODER & ~GPIO_MODER_MODE8_Msk) 
                 | (2U << GPIO_MODER_MODE8_Pos);

    /* AFRH8 = 6 (AF6: TIM1_CH1) */
    GPIOA->AFR[1] = (GPIOA->AFR[1] & ~(0xFU << GPIO_AFRH_AFSEL8_Pos)) 
                  | (6U << GPIO_AFRH_AFSEL8_Pos);

    /* Tùy chọn tốc độ chuyển mạch cao (High Speed) cho PA8 */
    GPIOA->OSPEEDR |= (3U << GPIO_OSPEEDR_OSPEED8_Pos);

    /* 4. Cấu hình bộ đếm TIM1 */
    /* TIM1CLK = 170 MHz, f_PWM = 20 kHz => Prescaler = 0, ARR = 8499 */
    TIM1->PSC = 0U;
    TIM1->ARR = 8499U;

    /* Duty cycle 25% => CCR1 = 2125 */
    TIM1->CCR1 = 2125U;

    /* 5. Cấu hình Channel 1 sang PWM mode 1 (OC1M = 0110b) và bật preload (OC1PE) */
    TIM1->CCMR1 = (TIM1->CCMR1 & ~(TIM_CCMR1_OC1M_Msk | TIM_CCMR1_CC1S_Msk))
                | (6U << TIM_CCMR1_OC1M_Pos)
                | TIM_CCMR1_OC1PE;

    /* Bật ngõ ra Channel 1 (CC1E = 1, cực tính tích cực cao mặc định CC1P = 0) */
    TIM1->CCER |= TIM_CCER_CC1E;

    /* Bật Main Output Enable (MOE) - Bắt buộc đối với Advanced Timer TIM1 */
    TIM1->BDTR |= TIM_BDTR_MOE;

    /* Bật tự động nạp lại (Auto-reload preload enable) */
    TIM1->CR1 |= TIM_CR1_ARPE;

    /* Phát sinh sự kiện Update (UG = 1) để nạp trước các giá trị vào shadow register */
    TIM1->EGR = TIM_EGR_UG;

    /* 6. Bật bộ đếm Timer (CEN = 1) */
    TIM1->CR1 |= TIM_CR1_CEN;
}
```

---

### 4. Kết quả kiểm tra & Mô phỏng (Verification)
* **Compile Check:** Cú pháp và định nghĩa macro tương thích hoàn toàn với CMSIS STM32G4 (`stm32g4xx.h`), không có cảnh báo hay lỗi.
* **Register Simulation:** Mô phỏng chuỗi thanh ghi xác nhận tín hiệu ra tại `PA8` là `TIM1_CH1` ở chế độ **PWM1**, tần số chính xác **20000 Hz**, chu kỳ công tác **25%**, ngõ ra hoạt động tích cực (`active: true`).
* **Design Rule Check (DRC):** Tất cả các quy tắc thiết kế (DRC-CLK-01, DRC-CLK-02, DRC-PIN-01, DRC-PIN-02, DRC-REQ-01) đều đạt 100%.