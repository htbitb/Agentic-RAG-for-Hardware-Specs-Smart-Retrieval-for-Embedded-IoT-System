"""hw-sandbox MCP Server (quyền `sandboxed-exec`: không tác động ra ngoài): solver timer, mô phỏng ghi thanh ghi, phân tích mã C, kiểm biên dịch.

Mã C đưa vào là dữ liệu KHÔNG tin cậy: chỉ tiền xử lý / parse / `-fsyntax-only`, không bao giờ chạy. Có giới hạn kích thước (mã, số op) và timeout.
Nguyên tắc trung thực: `unmodeled` / `skipped` KHÔNG BAO GIỜ là pass. P2 chưa đăng ký server này vào ToolHub của agent (S2D là snapshot P1); P4 sẽ làm.
"""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as _Timeout

import config

os.environ.setdefault("HWMODEL_DATA_DIR", str(config.HW_DB.parent))

from hwmodel import codeparse, compile_check as _cc, solver, sim          # noqa: E402
from mcp_servers import create_mcp                                         # noqa: E402

mcp = create_mcp("hw-sandbox")
MAX_OPS = 2000
MAX_CODE_BYTES = _cc.MAX_CODE_BYTES
TIMEOUT_S = 60.0
_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="hw-sandbox")


def _run(fn, *args, **kw) -> dict:
    fut = _POOL.submit(fn, *args, **kw)
    try:
        return fut.result(timeout=TIMEOUT_S)
    except _Timeout:
        fut.cancel()
        return {"error": f"timed out after {TIMEOUT_S:g} s"}
    except (ValueError, KeyError, TypeError) as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def _simulate(chip, ops, initial, hse_hz):
    return sim.simulate_register_writes(chip, ops, initial=initial, hse_hz=hse_hz)


def _ops(ops) -> list[dict]:
    if isinstance(ops, str):
        try:
            ops = json.loads(ops)
        except json.JSONDecodeError as exc:
            raise ValueError(f"ops is not valid JSON: {exc}") from None
    if not isinstance(ops, list) or not all(isinstance(o, dict) for o in ops):
        raise ValueError("ops must be a list of objects like {'op': 'write', 'reg': 'TIM1_PSC', 'value': 0}")
    if len(ops) > MAX_OPS:
        raise ValueError(f"too many ops ({len(ops)} > {MAX_OPS})")
    return ops


@mcp.tool()
def solve_timer_config(chip: str, timer: str, target_hz: float, duty_pct: float, channel: int = 1, tim_clk_hz: float | None = None,
                       pclk_hz: float | None = None, apb_prescaler: int | None = None) -> dict:
    """Solve PWM timer settings (STM32G474, edge-aligned PWM mode 1): find PSC, ARR and CCRx for a target frequency and duty cycle with the smallest frequency error, then the finest duty resolution. Provide the timer kernel clock as `tim_clk_hz`, or `pclk_hz` + `apb_prescaler` (TIMxCLK = PCLK x 2 when the APB prescaler is not 1). Respects 16-bit (TIM1/3/4/8/15/16/17/20) vs 32-bit (TIM2/5) counters. Returns the registers to write, the resulting frequency/duty and their errors. The register simulator remains the referee."""
    clock = {"tim_clk_hz": tim_clk_hz} if tim_clk_hz else ({"pclk_hz": pclk_hz, "apb_prescaler": apb_prescaler} if pclk_hz and apb_prescaler else None)
    return _run(solver.solve_timer_config, chip, timer, target_hz, duty_pct, channel, clock)


@mcp.tool()
def simulate_register_writes(chip: str, ops: list[dict] | str, initial: str = "reset", hse_hz: int | None = None) -> dict:
    """Simulate a sequence of register operations (memory map from the SVD, reset values from the manual, access masks, reserved bits, W1C). ops: [{"op": "write"|"set_bits"|"clear_bits"|"toggle_bits"|"modify"|"rmw"|"read", "reg": "TIM1_PSC" (or "addr": 0x40012C28), "value"/"mask"}]; modify takes mask+value (or field+value). STM32G474 also has a behavioural layer: RCC clock gates and clock tree, GPIO alternate functions, timers (PWM), USART baud, I2C SCL. initial: "reset" or a preset such as "sysclk_170mhz_pll_hsi16_apb_div1"; hse_hz for HSE-based clock trees. Returns final_registers, effects (e.g. PA8 outputs TIM1_CH1 at 20000 Hz, 25 %, or active=false with the reason), violations with codes (SIM-CLK-GATE, SIM-TIM-MOE, SIM-GPIO-AF, SIM-CLK-LIMIT...), unmodeled (never counts as a pass), assumptions."""
    try:
        parsed = _ops(ops)
    except ValueError as exc:
        return {"error": str(exc)}
    return _run(_simulate, chip, parsed, initial, hse_hz)


@mcp.tool()
def analyze_c_code(code: str, chip: str = "stm32g474") -> dict:
    """Translate bare-metal CMSIS-style C (e.g. `TIM1->PSC = 0; RCC->APB2ENR |= RCC_APB2ENR_TIM1EN; GPIOA->AFR[1] &= ~(0xF << 0);`) into the ordered ops that `simulate_register_writes` accepts. Handles constant expressions and macros, read-modify-write forms, helper functions, counted loops, raw register addresses. Register polling loops (`while(!(RCC->CR & RCC_CR_PLLRDY));`) and delay loops are skipped with a note; HAL/LL calls, data-dependent branches, arithmetic on register values and other unsupported constructs stop the analysis with `unsupported_construct` and a line number (never guessed). The code is only parsed, never executed."""
    if len(code.encode("utf-8", "replace")) > MAX_CODE_BYTES:
        return {"error": f"code exceeds {MAX_CODE_BYTES} bytes"}
    return _run(codeparse.analyze_c_code, code, chip)


@mcp.tool()
def compile_check(code: str, chip: str = "stm32g474") -> dict:
    """Syntax/semantic check of C code with clang for ARM Cortex-M4 (`-fsyntax-only -Wall -Werror=implicit-function-declaration`) against CMSIS-style headers generated from the SVD (stm32g4xx.h: TIM1->PSC, RCC_APB2ENR_TIM1EN, GPIO_MODER_MODE8_1, SET_BIT/MODIFY_REG...). Returns status ok | error | skipped with structured errors (line, col, message). `skipped` (other chip, or no toolchain) is never a pass. The code is never executed."""
    if len(code.encode("utf-8", "replace")) > MAX_CODE_BYTES:
        return {"status": "error", "errors": [{"line": 1, "col": 1, "msg": f"code exceeds {MAX_CODE_BYTES} bytes", "kind": "too_large"}], "warnings": []}
    return _run(_cc.compile_check, code, chip)


if __name__ == "__main__":
    mcp.run()
