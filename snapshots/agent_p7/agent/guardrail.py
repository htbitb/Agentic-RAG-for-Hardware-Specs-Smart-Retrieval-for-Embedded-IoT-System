"""Hardware Safety Guardrail + prompt-injection filter (plan 4.2, R6, AT4).

Guardrails are implemented as deterministic code, not as prompt text, so an
injected instruction cannot switch them off.

  * scan_injection / sanitize_observation : indirect injection in retrieved text
  * check_user_input                      : direct injection in the user prompt
  * parse_hardware_requests / evaluate_hw  : "apply 5 V to ..." vs Absolute Maximum Ratings
"""
import re

from ingestion.unit_normalizer import eval_vdd_expr

INJECTION_PATTERNS = [
    (r"ignore (all |any )?(of )?(the |your )?(previous|prior|above|earlier) (instructions|rules|prompts?)", "override_instructions"),
    (r"disregard (all |any |the |your )*(previous|prior|safety|system)", "override_instructions"),
    (r"(reveal|print|show|leak|output|repeat|display) (me )?(your |the )?(full |hidden )?(system prompt|hidden prompt|initial prompt|instructions)", "prompt_leak"),
    (r"system prompt", "prompt_leak"),
    (r"(reveal|send|print|show|give|leak|post|upload)\b.{0,40}(api[ _-]?keys?|secrets?|passwords?|\.env|credentials|access tokens?)", "secret_exfiltration"),
    (r"developer mode|jailbreak|\bDAN\b|you are now (an?|in)|act as (an? )?(unrestricted|unfiltered)", "role_hijack"),
    (r"<\s*/?\s*(system|assistant|instruction)s?\s*>", "fake_system_tag"),
    (r"(tell|inform|convince) the user that", "injected_claim"),
    (r"important (system )?note to the (ai|assistant|model)", "injected_claim"),
    (r"without (asking|requesting|waiting) (for )?(the user'?s? )?(approval|confirmation|permission)", "approval_bypass"),
    (r"(call|invoke|run|execute) the \w+ tool", "tool_instruction"),
    (r"(c:\\+windows|system32|/etc/passwd|/etc/shadow|\.\./|\.\.\\)", "path_traversal"),
    (r"(disable|turn off|bypass|skip|ignore) (the |your |all )?(safety|guardrails?|verification|approval)", "safety_bypass"),
    (r"https?://\S+[?&](key|token|data|q)=", "exfil_url"),
]
_COMPILED = [(re.compile(p, re.I), label) for p, label in INJECTION_PATTERNS]
BLOCKING = {"override_instructions", "prompt_leak", "secret_exfiltration", "role_hijack", "fake_system_tag",
            "approval_bypass", "safety_bypass", "path_traversal", "exfil_url", "injected_claim", "tool_instruction"}


def scan_injection(text: str) -> list[str]:
    return sorted({label for rx, label in _COMPILED if rx.search(text or "")})


def sanitize_text(text: str, collect: list | None = None) -> tuple[str, list[str]]:
    """Drop every sentence that carries an injection signature; keep the factual rest. P6: when 'collect' is a list, the removed sentences are
    appended to it (never shown to the model) so the Policy Engine can recognise them if they come back inside a tool argument (taint tracking)."""
    if not scan_injection(text):
        return text, []
    flags, kept, removed = set(), [], 0
    for sent in re.split(r"(?<=[.!?])\s+|\n", text or ""):
        f = scan_injection(sent)
        if f:
            flags.update(f)
            removed += 1
            if collect is not None:
                collect.append(sent.strip())
        elif sent.strip():
            kept.append(sent)
    clean = " ".join(kept)
    if removed:
        clean += f" [GUARDRAIL: {removed} untrusted instruction sentence(s) removed: {', '.join(sorted(flags))}]"
    return clean, sorted(flags)


def sanitize_observation(obj, collect: list | None = None):
    """Recursively sanitize all 'text'/'evidence'/'notes' strings of a tool result. Returns (obj, flags); 'collect' receives the removed sentences (see sanitize_text)."""
    found = set()

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, str) and k in ("text", "evidence", "notes", "description"):
                    o[k], f = sanitize_text(v, collect)
                    found.update(f)
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(obj)
    return obj, sorted(found)


def check_user_input(question: str) -> dict:
    flags = scan_injection(question)
    return {"blocked": bool(set(flags) & BLOCKING), "flags": flags}


# ---------------------------------------------------------------- hardware safety
_ACTION = re.compile(r"\b(apply|applying|feed|connect|power(ed|ing)?|drive|override|set|put|use|tie|wire|"
                     r"overclock|raise|increase|boost|inject|force|hook)\b", re.I)
_VOLT = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(m?v|volts?)\b", re.I)
_SUPPLY = re.compile(r"\b(vdd\w*|vcc|supply|power (pin|rail|input)|power(?:ed|ing)? (?:from|by|with|via|through)|core voltage|vdd_core|rail|vbat|3v3 pin)\b", re.I)
_PIN = re.compile(r"\b(gpio\s?\d+|pin|input|io\d+|p[a-h]\d{1,2}|p[01]\.\d{1,2}|adc|signal)\b", re.I)


# P6 (D45): the limit a request is held to depends on WHICH rail / pin class it names. A request that names a rail (VDD, VDDH, VBUS...) or a pin
# class (FT_c, TT...) is held to the strictest limit among the ones it names; a request that names none is refused only when NO rail / pin class of the
# chip could take it (so "can the nRF52840 run from 5 V?" is not refused: VDDH takes up to 5.5 V) - the exact rail is then checked on the action
# (set_target / connect, Policy Engine + DRC) and in the answer (G4).
_RAIL = re.compile(r"(?<![A-Za-z0-9_])(VDDH|VDDA|VDDIO|VDD|VBUS|VBAT|VREF\+?)(?![A-Za-z0-9_])", re.I)
_PIN_CLASS = re.compile(r"(?<![A-Za-z0-9])(FT_[A-Za-z]+|FT|TT_[A-Za-z]+|TT)(?![A-Za-z0-9_])", re.I)
SUPPLY_FIELD_TYPES = ("supply_voltage", "supply_voltage_high", "supply_voltage_usb")


def named_rails(text: str) -> list[str]:
    return sorted({m.group(1).upper() for m in _RAIL.finditer(text or "")})


def named_pin_class(text: str) -> str | None:
    m = _PIN_CLASS.search(text or "")
    return m.group(1).upper() if m else None


_PIN_NAME = re.compile(r"(?<![A-Za-z0-9_])(P[A-K]\d{1,2})(?![A-Za-z0-9_])")


def named_pins(text: str) -> list[str]:
    """STM32-style pin names (PA0, PB4...) mentioned in the text, in order, unique."""
    return list(dict.fromkeys(m.group(1).upper() for m in _PIN_NAME.finditer(text or "")))


def io_class(io_structure) -> str | None:
    """Pin tolerance class from the pin record's io_structure (TT_a -> TT, FT_c -> FT_C, FT_a/FT_f/FT_h... -> FT_XXX, NRST/BOOT/other -> OTHER); None when the chip has no such field."""
    s = str(io_structure or "").upper()
    if not s:
        return None
    return "TT" if s.startswith("TT") else ("FT_C" if s.startswith("FT_C") else ("FT_XXX" if s.startswith("FT") else "OTHER"))


def with_pin_classes(req: dict, question: str, lookup) -> dict:
    """P6 (D45): a request that names concrete pins is held to the class of THOSE pins (lookup(pin) -> pin record with io_structure; None/error -> unresolved).
    Unresolved pins leave the request unchanged (INTAKE then refuses only when no pin class could take the voltage)."""
    if req.get("target") != "pin" or req.get("pin_class"):
        return req
    classes = []
    for pin in named_pins(question):
        rec = lookup(pin)
        c = io_class(rec.get("io_structure")) if isinstance(rec, dict) and "error" not in rec else None
        if c:
            classes.append(c)
    return {**req, "pin_classes": sorted(set(classes))} if classes else req


def _row_class(applies_to) -> str:
    a = str(applies_to or "").upper()
    if not a or a.startswith(("ALL", "ANY")):
        return "ALL"
    if a.startswith("FT_C"):
        return "FT_C"
    if a.startswith("FT"):
        return "FT_XXX"
    if a.startswith("TT"):
        return "TT"
    return "OTHER"


def _req_class(token: str) -> str:
    t = token.upper()
    return "FT_C" if t.startswith("FT_C") else ("FT_XXX" if t.startswith("FT") else "TT")


def _rail_key(symbol) -> frozenset:
    return frozenset(t for t in re.split(r"[^A-Z0-9]+", str(symbol or "").upper()) if t and t != "VSS")


def parse_hardware_requests(question: str) -> list[dict]:
    """Find requested voltages that the user wants to APPLY (not 'at 3.3 V' conditions). Each request also carries the rails / pin class the sentence names."""
    if not _ACTION.search(question):
        return []
    reqs = []
    rails, pin_class = named_rails(question), named_pin_class(question)
    for m in _VOLT.finditer(question):
        before = question[max(0, m.start() - 6): m.start()].lower()
        if re.search(r"(\bat|@|under|\bof|\bis|\bare|\bwas|=)\s*$", before):
            continue  # operating condition or a claim ("... is 6 V"), not a request
        v = float(m.group(1)) / (1000 if m.group(2).lower() == "mv" else 1)
        target = "supply" if _SUPPLY.search(question) else ("pin" if _PIN.search(question) else "supply")
        reqs.append({"volts": v, "target": target, "text": m.group(0), "rails": rails, "pin_class": pin_class})
    return reqs


def _group_key(req: dict, fact: dict):
    """Rail (supply) or pin class (pin) a limit row belongs to."""
    return _rail_key(fact.get("symbol")) if req["target"] == "supply" else _row_class(fact.get("applies_to"))


def _in_scope(req: dict, key) -> bool:
    if req["target"] == "supply":
        named = {r.upper() for r in req.get("rails") or []}
        return bool(named & key)
    classes = set(req.get("pin_classes") or ([_req_class(req["pin_class"])] if req.get("pin_class") else []))
    return bool(classes) and (key == "ALL" or key in classes)


def _scoped(req: dict, entries: list, strict: bool = False):
    """entries: [(limit, fact)] -> (limit, fact) the request is held to. Rows of ONE rail / pin class are alternatives (conditions on VDD...): the strictest
    applies. Across rails / classes: strictest among the NAMED ones; if none is named (or none matches), the most permissive one."""
    if not entries:
        return None
    groups: dict = {}
    for e in entries:
        k = _group_key(req, e[1])
        if k not in groups or e[0] < groups[k][0]:
            groups[k] = e
    named = [e for k, e in groups.items() if _in_scope(req, k)]
    if named:
        return min(named, key=lambda x: x[0])
    explicit = bool(req.get("rails")) if req["target"] == "supply" else bool(req.get("pin_class") or req.get("pin_classes"))
    return (min if explicit or strict else max)(groups.values(), key=lambda x: x[0])


def evaluate_hw(req: dict, facts: list[dict], vdd: float = 3.3, strict: bool = False) -> dict:
    """Compare a requested voltage with absolute-max / operating limits from the fact store (rail- and pin-class-aware since P6, D45).
    strict=False (INTAKE): a request that names no rail / pin class is refused only if NO rail / class could take it. strict=True (G4 on the final answer): unnamed
    scope is held to the strictest limit of the chip, as before P6 - a possible overvoltage in the answer stays a finding even when the pin or rail is not named."""
    abs_limits, op_limits = [], []
    for f in facts:
        mx = eval_vdd_expr(f.get("max"), vdd) if f.get("max") else None
        if mx is None:
            continue
        if f.get("unit") == "mV":
            mx /= 1000
        ft = f.get("field_type", "")
        if req["target"] == "supply" and ft not in SUPPLY_FIELD_TYPES:
            continue
        if req["target"] == "pin" and ft not in ("input_voltage", "input_voltage_high"):
            continue
        entry = (mx, f)
        if f.get("category") == "absolute_max" or ft == "input_voltage_high":
            abs_limits.append(entry)
        elif f.get("category") == "recommended_operating":
            op_limits.append(entry)
    if not abs_limits and not op_limits:
        return {"verdict": "insufficient_evidence", "limit": None, "fact": None}
    hit = _scoped(req, abs_limits, strict)
    if hit and req["volts"] > hit[0]:
        return {"verdict": "refuse", "limit": hit[0], "fact": hit[1]}
    hit = _scoped(req, op_limits, strict)
    if hit and req["volts"] > hit[0]:
        return {"verdict": "warn", "limit": hit[0], "fact": hit[1]}
    lim, fact = _scoped(req, abs_limits or op_limits, strict)
    return {"verdict": "ok", "limit": lim, "fact": fact}
