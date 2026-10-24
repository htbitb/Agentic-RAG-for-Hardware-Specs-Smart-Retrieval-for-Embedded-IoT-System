"""Unit normalization and VDD-expression evaluation for hardware verification & guardrails."""
import ast
import operator
import re

_UNITS: dict[str, tuple[float, str]] = {
    "kv": (1e3, "V"),
    "v": (1.0, "V"),
    "volt": (1.0, "V"),
    "volts": (1.0, "V"),
    "mv": (1e-3, "V"),
    "uv": (1e-6, "V"),
    "µv": (1e-6, "V"),
    "μv": (1e-6, "V"),
    "a": (1.0, "A"),
    "ma": (1e-3, "A"),
    "ua": (1e-6, "A"),
    "µa": (1e-6, "A"),
    "μa": (1e-6, "A"),
    "na": (1e-9, "A"),
    "ghz": (1e9, "Hz"),
    "mhz": (1e6, "Hz"),
    "khz": (1e3, "Hz"),
    "hz": (1.0, "Hz"),
    "mohm": (1e6, "ohm"),
    "mω": (1e6, "ohm"),
    "kohm": (1e3, "ohm"),
    "kω": (1e3, "ohm"),
    "ohm": (1.0, "ohm"),
    "ω": (1.0, "ohm"),
    "mf": (1e-3, "F"),
    "uf": (1e-6, "F"),
    "µf": (1e-6, "F"),
    "μf": (1e-6, "F"),
    "nf": (1e-9, "F"),
    "pf": (1e-12, "F"),
    "°c": (1.0, "C"),
    "degc": (1.0, "C"),
}

_UNIT_PAT = "|".join(sorted((re.escape(k) for k in _UNITS), key=len, reverse=True))
_QTY_RX = re.compile(
    rf"(?<![A-Za-z0-9_.\-])(-?\d+(?:\.\d+)?)\s*({_UNIT_PAT})(?![A-Za-z0-9_])",
    re.I,
)

_SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def find_quantities(text: str) -> list[tuple[float, str, float, str]]:
    """Extract (raw_value, unit_str, normalized_si_value, base_unit) tuples from text."""
    if not text:
        return []
    out: list[tuple[float, str, float, str]] = []
    for m in _QTY_RX.finditer(text):
        val = float(m.group(1))
        unit_raw = m.group(2)
        scale, base = _UNITS[unit_raw.lower()]
        out.append((val, unit_raw, val * scale, base))
    return out


def _eval_ast(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval_ast(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_OPS:
        return _SAFE_OPS[type(node.op)](_eval_ast(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_OPS:
        return _SAFE_OPS[type(node.op)](_eval_ast(node.left), _eval_ast(node.right))
    raise ValueError("unsupported expression")


def eval_vdd_expr(expr, vdd: float = 3.3) -> float | None:
    """Evaluate a numeric value or VDD-dependent expression such as 'VDD+0.3' or '0.75*VDD'."""
    if expr is None:
        return None
    if isinstance(expr, (int, float)):
        return float(expr)
    s = str(expr).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        pass
    s = re.sub(r"\bVDD[A-Z0-9_]*\b", str(float(vdd)), s, flags=re.I)
    s = re.sub(r"\s*[Vv]\s*$", "", s)
    s = s.replace("×", "*").replace("−", "-")
    try:
        return round(_eval_ast(ast.parse(s, mode="eval")), 6)
    except Exception:
        return None
