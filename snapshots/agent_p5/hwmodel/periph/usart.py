"""USART/UART STM32G474: BRR / OVER8 / USART_PRESC / nguồn clock (RCC_CCIPR.USARTxSEL) → baud thực.

RM0440 §40.5.7 p.1707–1708:  baud = usart_ker_ck_pres / USARTDIV (OVER8 = 0);  baud = 2 * usart_ker_ck_pres / USARTDIV (OVER8 = 1).
  OVER8 = 0: BRR = USARTDIV.  OVER8 = 1: BRR[15:4] = USARTDIV[15:4], BRR[2:0] = USARTDIV[3:0] >> 1, BRR[3] phải = 0.  USARTDIV >= 16.
Nguồn clock (RCC_CCIPR p.322–324): 00 PCLK, 01 SYSCLK, 10 HSI16, 11 LSE (tần số LSE không mô hình hoá).
USART_PRESC[3:0] (p.1766): 0000 /1, 0001 /2, 0010 /4, 0011 /6, 0100 /8, 0101 /10, 0110 /12, 0111 /16, 1000 /32, 1001 /64, 1010 /128, 1011 /256.
Không mô hình hoá: LPUART1, chế độ đồng bộ / smartcard / LIN / IrDA / auto-baud, FIFO, truyền dữ liệu thực.
"""
from __future__ import annotations

from . import Ctx

# instance -> (bus, vị trí SELx trong RCC_CCIPR)
USARTS = {"USART1": (2, 0), "USART2": (1, 2), "USART3": (1, 4), "UART4": (1, 6), "UART5": (1, 8)}
MODELED_REGS = {"CR1", "CR2", "BRR", "PRESC"}
# Trường 'chỉ ghi được khi USART tắt (UE = 0)' (RM0440 p.1740-1742 CR1, p.1749 CR2, p.1755 BRR); sim.py chặn ghi khi UE = 1
WRITE_LOCKED = {"BRR": 0xFFFF, "PRESC": 0xF,                                                                                        # PRESC: RM p.1772
                "CR1": (1 << 29) | (1 << 28) | (0x1F << 21) | (0x1F << 16) | (1 << 15) | (1 << 12) | (1 << 11) | (1 << 9),      # FIFOEN M1 DEAT DEDT OVER8 M0 WAKE PS
                "CR2": (0b11 << 12) | (1 << 11)}                                                                                  # STOP CLKEN
_PRESC = {0: 1, 1: 2, 2: 4, 3: 6, 4: 8, 5: 10, 6: 12, 7: 16, 8: 32, 9: 64, 10: 128, 11: 256}
CR1_UE, CR1_RE, CR1_TE, CR1_OVER8 = 1 << 0, 1 << 2, 1 << 3, 1 << 15


# CR2 có ảnh hưởng tới chân / mức logic mà mô hình KHÔNG mô phỏng: SWAP đổi chức năng TX/RX, TXINV/RXINV đảo mức, LINEN/CLKEN (RM p.1749)
CR2_UNMODELED = {15: "SWAP (TX/RX pins swapped)", 16: "RXINV (RX level inverted)", 17: "TXINV (TX level inverted)", 14: "LINEN (LIN mode)", 11: "CLKEN (synchronous clock)"}


def effects(ctx: Ctx):
    effs, viols, unmodeled = [], [], []
    for inst, (bus, sel_lo) in USARTS.items():
        reg_cr1 = ctx.regmap.get(f"{inst}_CR1")
        if reg_cr1 is None:
            continue
        used = any(ctx.regmap.get(f"{inst}_{r}").address in ctx.rf.touched for r in ("CR1", "BRR", "PRESC")) or inst in ctx.gated
        if not used:
            continue
        cr1, brr = ctx.val(f"{inst}_CR1"), ctx.val(f"{inst}_BRR")
        presc = _PRESC.get(ctx.val(f"{inst}_PRESC") & 0xF, 1)
        over8 = 1 if cr1 & CR1_OVER8 else 0
        sel = (ctx.val("RCC_CCIPR") >> sel_lo) & 3
        pclk = ctx.clocks.pclk2_hz if bus == 2 else ctx.clocks.pclk1_hz
        kernel, ksrc = {0: (pclk, f"PCLK{bus}"), 1: (ctx.clocks.sysclk_hz, "SYSCLK"), 2: (16_000_000, "HSI16"), 3: (None, "LSE")}[sel]
        cr2 = ctx.val(f"{inst}_CR2")
        word = 9 if cr1 & (1 << 12) else (7 if cr1 & (1 << 28) else 8)               # M[1:0]: 00 = 8, 01 = 9, 10 = 7 bit (p.1741)
        pce = bool(cr1 & (1 << 10))
        parity = ("odd" if cr1 & (1 << 9) else "even") if pce else "none"
        stop_bits = {0b00: 1, 0b01: 0.5, 0b10: 2, 0b11: 1.5}[(cr2 >> 12) & 3]          # CR2.STOP (p.1749)
        usartdiv = ((brr & 0xFFF0) | ((brr & 0x7) << 1)) if over8 else brr
        reasons: list[tuple[str, str]] = []
        if not ctx.clock_on(inst):
            reasons.append(("SIM-CLK-GATE", f"{inst} clock is disabled (RCC enable bit = 0)"))
        if not cr1 & CR1_UE:
            reasons.append(("SIM-USART-UE", f"{inst}_CR1.UE = 0: the USART is disabled"))
        if not cr1 & (CR1_TE | CR1_RE):
            reasons.append(("SIM-USART-TXRX", f"{inst}_CR1.TE = RE = 0: neither transmitter nor receiver is enabled"))
        if usartdiv < 16 or (over8 and brr & 0x8):
            why = "BRR[3] must be kept cleared when OVER8 = 1" if (over8 and usartdiv >= 16) else f"USARTDIV = {usartdiv} < 16 (RM p.1708)"
            reasons.append(("SIM-USART-BRR", f"{inst}_BRR = 0x{brr:X} is invalid: {why}"))
        baud = None
        if kernel and usartdiv >= 16:
            baud = (2 if over8 else 1) * (kernel / presc) / usartdiv
        unm = [f"{inst}_CR2.{CR2_UNMODELED[b]} not modeled" for b in CR2_UNMODELED if cr2 & (1 << b)]
        unmodeled += unm
        tx = _pin(ctx, f"{inst}_TX")
        rx = _pin(ctx, f"{inst}_RX")
        e = {"kind": "uart", "instance": inst, "baud": baud, "usartdiv": usartdiv, "over8": over8, "brr": brr,
             "kernel_clk_hz": kernel, "kernel_source": ksrc, "presc_div": presc,
             "data_bits": word - (1 if pce else 0), "parity": parity, "stop_bits": stop_bits, "te": bool(cr1 & CR1_TE), "re": bool(cr1 & CR1_RE),
             "tx_pin": tx, "rx_pin": rx, "active": not reasons and baud is not None, "reason": reasons[0][0] if reasons else None,
             "reasons": [c for c, _ in reasons], "modeled": kernel is not None and not unm}
        if kernel is None:
            e["reason"] = e["reason"] or "SIM-CLK-UNKNOWN"
            e["detail"] = [f"{inst} kernel clock source is {ksrc}; its frequency is not modeled"]
        if reasons:
            e["detail"] = [m for _, m in reasons]
        effs.append(e)
        for code, msg in reasons:
            if code != "SIM-CLK-GATE":
                viols.append({"code": code, "severity": "error", "at_op": None, "msg": msg, "peripheral": inst})
    return effs, viols, unmodeled


def _pin(ctx: Ctx, signal: str) -> str | None:
    for p in ctx.pins.values():
        if p.mode == 2 and signal in ctx.sigmap.signals(p.pin, p.af):
            return p.pin
    return None
