"""Phép tính tay cho task C5 (P5, c5-author). Thuần Python, không import repo, không mạng.

Giới hạn dùng (trang PDF trong corpus):
  DS12288 p.117 Table 41: HSE 4..48 MHz.  DS12288 p.123 Table 46: f_PLL_IN 2.66..16 MHz, f_VCO 96..344 MHz (Range 1),
  PLL R out <= 170 MHz (boost) / 150 MHz (Range 1 normal).  RM0440 p.292-293: PLLM 1..16, PLLN 8..127, PLLR in {2,4,6,8}.
  RM0440 p.98 Table 9: wait states (boost <=34/68/102/136/170; normal <=30/60/90/120/150).
"""
from fractions import Fraction as F

PLL_IN = (2.66e6, 16e6)
VCO = (96e6, 344e6)


def pll_solutions(f_in, target, max_out=170e6):
    out = []
    for m in range(1, 17):
        fin = f_in / m
        if not (PLL_IN[0] <= fin <= PLL_IN[1]):
            continue
        for n in range(8, 128):
            vco = fin * n
            if not (VCO[0] <= vco <= VCO[1]):
                continue
            for r in (2, 4, 6, 8):
                f = vco / r
                if abs(f - target) / target <= 1e-3 and f <= max_out:
                    out.append((m, n, r, fin, vco, f))
    return out


def ws(hclk, boost):
    lim = [34e6, 68e6, 102e6, 136e6, 170e6] if boost else [30e6, 60e6, 90e6, 120e6, 150e6]
    return next(i for i, l in enumerate(lim) if hclk <= l)


def brr(fck, baud):
    div = round(fck / baud)
    return div, fck / div, (fck / div - baud) / baud * 100


def pwm(ftim, f, duty):
    ticks = ftim / f
    assert ticks == int(ticks) and ticks <= 65536, ticks
    return 0, int(ticks) - 1, round(duty * ticks)


def check(name, f_in, target, boost, chosen):
    sols = pll_solutions(f_in, target, 170e6 if boost else 150e6)
    print(f"{name}: in={f_in/1e6:g} MHz -> {target/1e6:g} MHz, {len(sols)} valid (M,N,R): {[(m, n, r) for m, n, r, *_ in sols]}")
    assert chosen in [(m, n, r) for m, n, r, *_ in sols], chosen
    m, n, r = chosen
    print(f"   chosen M={m} N={n} R={r}: PLL in {f_in/m/1e6:g} MHz, VCO {f_in/m*n/1e6:g} MHz, SYSCLK {f_in/m*n/r/1e6:g} MHz, "
          f"WS={ws(target, boost)} ({'boost, R1MODE=0' if boost else 'Range 1 normal, R1MODE=1'})")


def wrong(name, f_true, m, n, r):
    fin, vco, f = f_true / m, f_true / m * n, f_true / m * n / r
    ok = PLL_IN[0] <= fin <= PLL_IN[1] and VCO[0] <= vco <= VCO[1] and f <= 170e6
    print(f"   wrong guess {name}: M={m} N={n} R={r} with true input {f_true/1e6:g} MHz -> in {fin/1e6:.3g}, VCO {vco/1e6:.4g}, out {f/1e6:.4g} MHz, legal={ok}")


print("== clock trees ==")
check("C5-001 HSE", 24e6, 170e6, True, (6, 85, 2))
for g, (m, n, r) in {"8MHz": (2, 85, 2), "16MHz": (4, 85, 2), "12MHz": (3, 85, 2), "25MHz": (5, 68, 2)}.items():
    wrong(g, 24e6, m, n, r)
check("C5-002 HSE", 12e6, 170e6, True, (3, 85, 2))
for g, (m, n, r) in {"8MHz": (2, 85, 2), "16MHz": (4, 85, 2), "24MHz": (6, 85, 2), "25MHz": (5, 68, 2)}.items():
    wrong(g, 12e6, m, n, r)
check("C5-004 HSE", 12e6, 170e6, True, (3, 85, 2))
check("C5-005 HSE", 16e6, 150e6, False, (4, 75, 2))
check("C5-006 HSE", 25e6, 150e6, False, (5, 60, 2))
for g, (m, n, r) in {"8MHz": (2, 75, 2), "16MHz": (4, 75, 2), "12MHz": (3, 75, 2), "24MHz": (6, 75, 2)}.items():
    wrong(g, 25e6, m, n, r)
check("C5-007 HSE", 8e6, 170e6, True, (2, 85, 2))
check("C5-008 HSE", 16e6, 170e6, True, (4, 85, 2))
check("C5-010 HSE", 25e6, 150e6, False, (5, 60, 2))
check("C5-011 HSE", 12e6, 160e6, True, (3, 80, 2))
check("C5-012 HSE", 8e6, 160e6, True, (2, 80, 2))

print("== timers (TIMxCLK = PCLK, APB prescaler 1) ==")
print("C5-001 TIM1 16 kHz 40 %:", pwm(170e6, 16e3, 0.40))
print("C5-001 wrong 20 kHz 40 %:", pwm(170e6, 20e3, 0.40))
print("C5-007 TIM1 20 kHz 25 %:", pwm(170e6, 20e3, 0.25))
print("C5-010 TIM3 4 kHz 50 % @150 MHz:", pwm(150e6, 4e3, 0.50))

print("== USART BRR (OVER8=0, BRR = round(fck/baud), RM0440 p.1708) ==")
for name, fck, baud in [("C5-001/007 USART1 115200 @170", 170e6, 115200), ("C5-002 USART2 921600 @170", 170e6, 921600),
                        ("C5-002 wrong 115200 @170", 170e6, 115200), ("C5-004 USART3 1 Mbaud @170", 170e6, 1e6),
                        ("C5-008 USART2 1 Mbaud @170", 170e6, 1e6), ("C5-010 USART3 460800 @150", 150e6, 460800)]:
    d, real, err = brr(fck, baud)
    print(f"{name}: BRR={d} -> {real:.1f} baud ({err:+.3f} %)")

print("== logic levels (DS12288 p.128/130, ESP32 DS p.52, nRF52840 PS p.370/972/63/82/155) ==")
VDD = 3.3
print(f"STM32 @3.3 V: VIH min 0.7*VDD={0.7*VDD:.3f} V (by design 0.49*VDD+0.26={0.49*VDD+0.26:.3f} V), VIL max 0.3*VDD={0.3*VDD:.2f} V, VOH min VDD-0.4={VDD-0.4:.1f} V, VOL max 0.4 V")
print(f"ESP32 @3.3 V: VIH min 0.75*VDD={0.75*VDD:.3f} V, VIL max 0.25*VDD={0.25*VDD:.3f} V, VOH min 0.8*VDD={0.8*VDD:.2f} V, VOL max 0.1*VDD={0.1*VDD:.2f} V")
print(f"nRF @1.8 V (REGOUT0 default): VIH min {0.7*1.8:.2f} V, VI/O max VDD+0.3={1.8+0.3:.1f} V, VOH min VDD-0.4={1.8-0.4:.1f} V")
print(f"nRF REGOUT0=3.3 V needs VDDH >= 3.3+0.3 = 3.6 V; Li-ion 3.0..4.2 V -> not guaranteed. REGOUT0=2.7 V -> VI/O max 3.0 V < STM32 VOH up to 3.3 V")
print(f"sensor 1.8 V: VOH <= 1.8 V < STM32 VIH 2.31 V (and < 1.877 V design value) -> level shifter")

print("== sleep budgets (typ, 25 C; STM32 3 V row DS p.102-106; ESP32 DS p.30; nRF PS p.76) ==")
STOP1 = 80.5; SB_LSE = 0.655; SB_LSI = 0.885; SB = 0.130; SRAM2 = 0.305
ESP_DS = 10.0; ESP_HIB = 5.0; ESP_OFF = 1.0; NRF_OFF = 0.40
def tot(name, parts, budget):
    t = sum(v for _, v in parts)
    print(f"{name}: " + " + ".join(f"{k} {v}" for k, v in parts) + f" = {t:.3f} uA (budget {budget} uA) -> {'OK' if t <= budget else 'EXCEEDS'}")
    return t
tot("C5-001 ref", [("STM32 Standby+RTC(LSE)", SB_LSE), ("ESP32 deep-sleep", ESP_DS), ("driver", 1.0)], 50)
tot("C5-001 Stop1 variant", [("STM32 Stop1", STOP1), ("ESP32 deep-sleep", ESP_DS), ("driver", 1.0)], 50)
tot("C5-006 ref", [("STM32 Standby+RTC(LSE)", SB_LSE), ("ESP32 off (CHIP_PU low)", ESP_OFF), ("sensor", 0.6), ("buck Iq", 1.0)], 5)
tot("C5-006 guess (deep-sleep kept)", [("STM32 Standby+RTC(LSE)", SB_LSE), ("ESP32 deep-sleep", ESP_DS), ("sensor", 0.6), ("buck Iq", 1.0)], 5)
tot("C5-006 hibernation", [("STM32 Standby+RTC(LSE)", SB_LSE), ("ESP32 hibernation", ESP_HIB), ("sensor", 0.6), ("buck Iq", 1.0)], 5)
tot("C5-007 ref", [("STM32 Standby+RTC(LSI)", SB_LSI), ("ESP32 deep-sleep", ESP_DS), ("driver", 2.0)], 50)
tot("C5-007 Stop1 variant", [("STM32 Stop1", STOP1), ("ESP32 deep-sleep", ESP_DS), ("driver", 2.0)], 50)
tot("C5-008 ref", [("STM32 Standby+RTC(LSE)", SB_LSE), ("nRF System OFF", NRF_OFF), ("sensor", 1.0)], 10)
tot("C5-011 ref", [("STM32 Standby+RTC(LSE)", SB_LSE), ("ESP32 off (CHIP_PU low)", ESP_OFF), ("sensor", 1.5), ("LDO Iq", 1.0)], 8)
tot("C5-011 deep-sleep", [("STM32 Standby+RTC(LSE)", SB_LSE), ("ESP32 deep-sleep", ESP_DS), ("sensor", 1.5), ("LDO Iq", 1.0)], 8)
tot("C5-011 hibernation", [("STM32 Standby+RTC(LSE)", SB_LSE), ("ESP32 hibernation", ESP_HIB), ("sensor", 1.5), ("LDO Iq", 1.0)], 8)
tot("C5-012 STM32 rail", [("STM32 Standby no RTC", SB), ("SRAM2 retention", SRAM2), ("pull-up/leak", 0.0)], 2)

print("== peak current C5-002 (ESP32 DS p.52 Table 5-4 TX 802.11b 240 mA; DS12288 p.89 Table 21 Run 170 MHz 29.5 mA typ) ==")
print(f"240 + 29.5 + 1 = {240 + 29.5 + 1} mA > 250 mA LDO; ESP32 DS p.51 Table 5-2: supply must deliver >= 0.5 A")

print("== battery life ==")
HOURS_PER_YEAR = 8760
def life(name, period_s, act_s, act_mA, sleep_uA, cap_mAh, target_y):
    avg_uA = act_mA * 1000 * act_s / period_s + sleep_uA * (period_s - act_s) / period_s
    h = cap_mAh / (avg_uA / 1000)
    need = avg_uA / 1000 * target_y * HOURS_PER_YEAR
    print(f"{name}: avg = {act_mA} mA*{act_s}/{period_s} + {sleep_uA:.3f}*({period_s - act_s}/{period_s}) = {avg_uA:.2f} uA; "
          f"life({cap_mAh} mAh) = {h:.0f} h = {h/HOURS_PER_YEAR:.2f} y = {h/HOURS_PER_YEAR*12:.1f} months; need {need:.0f} mAh for {target_y} y")
    return avg_uA, h / HOURS_PER_YEAR
s003 = SB_LSE + NRF_OFF + 1.0
print(f"C5-003 sleep = {SB_LSE} + {NRF_OFF} + 1.0 = {s003:.3f} uA")
life("C5-003 true 400 mAh", 900, 2, 8, s003, 400, 3)
life("C5-003 guess 2000 mAh", 900, 2, 8, s003, 2000, 3)
life("C5-003 guess 1000 mAh", 900, 2, 8, s003, 1000, 3)
life("C5-003 guess 225 mAh", 900, 2, 8, s003, 225, 3)
avg, _ = life("C5-003 trade-off check", 900, 2, 8, s003, 400, 3)
allowed = 400 / (3 * HOURS_PER_YEAR) * 1000
print(f"   allowed avg for 3 y = {allowed:.2f} uA -> interval >= {8000*2/(allowed - s003):.0f} s; active <= {(allowed - s003)*900/8000:.2f} s at 8 mA")
s009 = SB_LSE + NRF_OFF + 2.0
print(f"C5-009 sleep = {SB_LSE} + {NRF_OFF} + 2.0 = {s009:.3f} uA")
life("C5-009 2600 mAh", 600, 1.5, 10, s009, 2600, 12)
allowed = 2600 / (12 * HOURS_PER_YEAR) * 1000
print(f"   allowed avg for 12 y = {allowed:.2f} uA -> interval >= {10000*1.5/(allowed - s009):.0f} s")
