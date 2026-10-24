### 1. Trade-Off Analysis: 1.8 V Sensor vs 3.3 V Sensor

At VDD = 3.3 V, the STM32G474 input high threshold is:
VIH(min) = 0.7 * VDD = 0.7 * 3.3 V = 2.31 V [STM32G474_Datasheet p.128].

Because the sensor outputs a high level at VOH = 1.8 V, it cannot reach the minimum high threshold (1.8 V < 2.31 V). A direct connection is therefore incompatible.

* **Option A — Keep 1.8 V Sensor + Level Shifter (Chosen, Decision D1):**
  * **Pros:** Reuses existing hardware module immediately.
  * **Cons:** Requires an external bidirectional I2C level shifter IC (or discrete MOSFET circuit) and dual power rails (3.3 V and 1.8 V).
* **Option B — Replace with 3.3 V Compatible Sensor:**
  * **Pros:** Direct glueless connection, single 3.3 V power rail, lower BOM count and routing complexity.
  * **Cons:** Requires procuring a new sensor module.

---

### 2. STM32G474 I2C3 Pin Allocation

For the STM32G474, the I2C3 signals can be mapped to:
* **PC8**: **`I2C3_SCL`** (Alternate Function **AF8**) [STM32G474_Datasheet p.75]
* **PC9**: **`I2C3_SDA`** (Alternate Function **AF8**) [STM32G474_Datasheet p.75]

PC8 and PC9 are adjacent I/O pins, both feature FT_f I/O structure, and both use AF8 for I2C3.

---

### 3. I2C3 Configuration and Bare-Metal C Code

Configured for 100 kHz Standard Mode with a 16 MHz kernel clock (HSI16 / PCLK default):

```c
#include "stm32g4xx.h"

/**
 * @brief Initialize I2C3 on PC8 (SCL) and PC9 (SDA) for BME280 communication.
 *        Configured for 100 kHz Standard Mode with f_I2CCLK = 16 MHz.
 */
void I2C3_Init(void) {
    // 1. Enable GPIOC and I2C3 peripheral clocks
    RCC->AHB2ENR  |= RCC_AHB2ENR_GPIOCEN;
    RCC->APB1ENR1 |= RCC_APB1ENR1_I2C3EN;

    // 2. Configure PC8 (SCL) and PC9 (SDA)
    // MODER: Alternate Function mode ('10') on pins 8 and 9
    GPIOC->MODER &= ~((3U << (8 * 2)) | (3U << (9 * 2)));
    GPIOC->MODER |=  ((2U << (8 * 2)) | (2U << (9 * 2)));

    // OTYPER: Open-drain ('1') on pins 8 and 9
    GPIOC->OTYPER |= ((1U << 8) | (1U << 9));

    // OSPEEDR: Very high speed ('11')
    GPIOC->OSPEEDR |= ((3U << (8 * 2)) | (3U << (9 * 2)));

    // PUPDR: Internal pull-ups enabled
    GPIOC->PUPDR &= ~((3U << (8 * 2)) | (3U << (9 * 2)));
    GPIOC->PUPDR |=  ((1U << (8 * 2)) | (1U << (9 * 2)));

    // AFR[1] (AFRH): Route AF8 (I2C3) to PC8 (pin 8) and PC9 (pin 9)
    GPIOC->AFR[1] &= ~((0xFU << ((8 - 8) * 4)) | (0xFU << ((9 - 8) * 4)));
    GPIOC->AFR[1] |=  ((8U   << ((8 - 8) * 4)) | (8U   << ((9 - 8) * 4)));

    // 3. Configure I2C3 timing: 100 kHz standard mode with 16 MHz kernel clock
    // PRESC=3, SCLDEL=4, SDADEL=2, SCLH=15, SCLL=19
    I2C3->CR1 &= ~I2C_CR1_PE;
    I2C3->TIMINGR = (3U << 28) | (4U << 20) | (2U << 16) | (15U << 8) | (19U << 0);

    // 4. Enable I2C3 peripheral
    I2C3->CR1 |= I2C_CR1_PE;
}
```

---

### 4. Level Shifter Connection Guidelines
* **High side (3.3 V):** Connect to 3.3 V with pull-up resistors on SCL and SDA to 3.3 V, wired to STM32G474 PC8 and PC9.
* **Low side (1.8 V):** Connect to 1.8 V with pull-up resistors to 1.8 V, wired to BME280 SCL and SDA pins.
* Connect STM32G474 ground and BME280 ground together.