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


def sanitize_text(text: str) -> tuple[str, list[str]]:
    """Drop every sentence that carries an injection signature; keep the factual rest."""
    if not scan_injection(text):
        return text, []
    flags, kept, removed = set(), [], 0
    for sent in re.split(r"(?<=[.!?])\s+|\n", text or ""):
        f = scan_injection(sent)
        if f:
            flags.update(f)
            removed += 1
        elif sent.strip():
            kept.append(sent)
    clean = " ".join(kept)
    if removed:
        clean += f" [GUARDRAIL: {removed} untrusted instruction sentence(s) removed: {', '.join(sorted(flags))}]"
    return clean, sorted(flags)


def sanitize_observation(obj):
    """Recursively sanitize all 'text'/'evidence'/'notes' strings of a tool result. Returns (obj, flags)."""
    found = set()

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, str) and k in ("text", "evidence", "notes", "description"):
                    o[k], f = sanitize_text(v)
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
_SUPPLY = re.compile(r"\b(vdd\w*|vcc|supply|power (pin|rail|input)|core voltage|vdd_core|rail|vbat|3v3 pin)\b", re.I)
_PIN = re.compile(r"\b(gpio\s?\d+|pin|input|io\d+|p[a-h]\d{1,2}|p[01]\.\d{1,2}|adc|signal)\b", re.I)


def parse_hardware_requests(question: str) -> list[dict]:
    """Find requested voltages that the user wants to APPLY (not 'at 3.3 V' conditions)."""
    if not _ACTION.search(question):
        return []
    reqs = []
    for m in _VOLT.finditer(question):
        before = question[max(0, m.start() - 6): m.start()].lower()
        if re.search(r"(\bat|@|under|\bof|\bis|\bare|\bwas|=)\s*$", before):
            continue  # operating condition or a claim ("... is 6 V"), not a request
        v = float(m.group(1)) / (1000 if m.group(2).lower() == "mv" else 1)
        target = "supply" if _SUPPLY.search(question) else ("pin" if _PIN.search(question) else "supply")
        reqs.append({"volts": v, "target": target, "text": m.group(0)})
    return reqs


def evaluate_hw(req: dict, facts: list[dict], vdd: float = 3.3) -> dict:
    """Compare a requested voltage with absolute-max / operating limits from the fact store."""
    abs_limits, op_limits = [], []
    for f in facts:
        mx = eval_vdd_expr(f.get("max"), vdd) if f.get("max") else None
        if mx is None:
            continue
        if f.get("unit") == "mV":
            mx /= 1000
        ft = f.get("field_type", "")
        if req["target"] == "supply" and ft != "supply_voltage":
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
    if abs_limits:
        lim, fact = min(abs_limits, key=lambda x: x[0])
        if req["volts"] > lim:
            return {"verdict": "refuse", "limit": lim, "fact": fact}
    if op_limits:
        lim, fact = max(op_limits, key=lambda x: x[0])
        if req["volts"] > lim:
            return {"verdict": "warn", "limit": lim, "fact": fact}
    lim, fact = (abs_limits or op_limits)[0]
    return {"verdict": "ok", "limit": lim, "fact": fact}
