#ifndef PWM_PA8_CFG_H
#define PWM_PA8_CFG_H

/* STM32G474 TIM1 Channel 1 (PA8) PWM Configuration
 * System Clock: 170 MHz (all APB prescalers = 1)
 * PWM Target Frequency: 20 kHz
 * PWM Target Duty Cycle: 25 %
 */

#define TIM1_PSC_VAL           0U
#define TIM1_ARR_VAL           8499U
#define TIM1_CCR1_VAL          2125U

#define TIM1_CCMR1_VAL         0x00000068U  /* OC1M = PWM mode 1 (0110b), OC1PE = 1 */
#define TIM1_CCER_VAL          0x00000001U  /* CC1E = 1 (Channel 1 output enable) */
#define TIM1_BDTR_VAL          0x00008000U  /* MOE = 1 (Main Output Enable) */
#define TIM1_CR1_VAL           0x00000081U  /* ARPE = 1, CEN = 1 (Counter enable) */

#define GPIOA_AFRH_AF6_PA8     0x00000006U  /* AFRH8 = AF6 (TIM1_CH1) */
#define GPIOA_MODER_AF_PA8     0x00020000U  /* MODER8 = 10b (Alternate function) */

#endif /* PWM_PA8_CFG_H */
