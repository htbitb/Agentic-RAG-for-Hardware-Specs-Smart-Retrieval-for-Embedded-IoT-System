"""Interceptor: hook ở TẦNG KẾT QUẢ TOOL của ToolHub (dưới sanitize_observation), dùng cho
  * C7 v2: injection GIÁN TIẾP (kind inject_text): nội dung không tin cậy nằm trong kết quả mà tool trả về, không phải trong lời người dùng;
  * P9: tiêm lỗi công cụ (FaultInjector): kind raise (tool lỗi / timeout) và corrupt_number (dữ liệu sai).
Không sửa corpus hay snapshot (hash của chúng được ghim trong manifest): hook bọc hub._invoke của instance ngay trong worker của lượt chạy.

Chỉ dùng thư viện chuẩn: worker nạp file này theo đường dẫn (giống eval/llm_cache.py), không import package eval.

Luật (rule) = dict:
  tool   : tên tool bị bọc (bắt buộc)
  kind   : inject_text | raise | corrupt_number
  times  : số lời gọi KHỚP đầu tiên bị tác động (mặc định 1); after: bỏ qua n lời gọi khớp đầu tiên (mặc định 0)
  inject_text : payload (bắt buộc), mode append|prepend (mặc định append), field (khoá chuỗi muốn tiêm; mặc định chuỗi 'text-like' đầu tiên)
  raise       : error TimeoutError|ConnectionError|RuntimeError (mặc định RuntimeError), message
  corrupt_number : factor (mặc định 10.0): nhân MỌI số trong trường max/min/typ/value của các hàng kết quả (dữ liệu sai nhưng hợp lệ về hình dạng)
Mỗi lần hook tác động ghi một bản ghi {tool, rule, kind, call_no} vào self.log; worker trả chúng về adapter (drain) để thành sự kiện trace.
"""
from __future__ import annotations

import copy

KINDS = ("inject_text", "raise", "corrupt_number")
TEXT_KEYS = ("text", "evidence", "notes", "description", "quote", "condition", "snippet")
NUMERIC_KEYS = ("max", "min", "typ", "value")
ERRORS = {"TimeoutError": TimeoutError, "ConnectionError": ConnectionError, "RuntimeError": RuntimeError}


def validate_rule(rule) -> str | None:
    if not isinstance(rule, dict):
        return "a tool rule must be a mapping"
    if not isinstance(rule.get("tool"), str) or not rule["tool"]:
        return "a tool rule needs a non-empty 'tool'"
    if rule.get("kind") not in KINDS:
        return f"kind must be one of {list(KINDS)}, got {rule.get('kind')!r}"
    for k in ("times", "after"):
        if k in rule and (isinstance(rule[k], bool) or not isinstance(rule[k], int) or rule[k] < 0):
            return f"{k} must be a non-negative integer"
    if rule["kind"] == "inject_text" and (not isinstance(rule.get("payload"), str) or not rule["payload"].strip()):
        return "inject_text needs a non-empty string 'payload'"
    if rule["kind"] == "inject_text" and rule.get("mode", "append") not in ("append", "prepend"):
        return "mode must be append or prepend"
    if rule["kind"] == "raise" and rule.get("error", "RuntimeError") not in ERRORS:
        return f"error must be one of {sorted(ERRORS)}"
    if rule["kind"] == "corrupt_number" and (isinstance(rule.get("factor", 10.0), bool) or not isinstance(rule.get("factor", 10.0), (int, float))):
        return "factor must be a number"
    return None


def _inject(obj, rule) -> bool:
    """Tiêm payload vào chuỗi đầu tiên (DFS) có khoá phù hợp; trả True nếu đã tiêm."""
    keys = (rule["field"],) if rule.get("field") else TEXT_KEYS
    payload, mode = rule["payload"], rule.get("mode", "append")

    def walk(o) -> bool:
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, str) and k in keys:
                    o[k] = f"{payload} {v}" if mode == "prepend" else f"{v} {payload}"
                    return True
            for v in o.values():
                if isinstance(v, (dict, list)) and walk(v):
                    return True
        elif isinstance(o, list):
            for v in o:
                if walk(v):
                    return True
        return False

    return walk(obj)


def _corrupt(obj, factor: float) -> bool:
    done = False

    def num(v):
        nonlocal done
        try:
            if isinstance(v, bool) or v is None:
                return v
            x = float(v)
        except (TypeError, ValueError):
            return v
        done = True
        out = x * factor
        return f"{out:g}" if isinstance(v, str) else out

    def walk(o):
        if isinstance(o, dict):
            for k, v in list(o.items()):
                if k in NUMERIC_KEYS and not isinstance(v, (dict, list)):
                    o[k] = num(v)
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(obj)
    return done


class Interceptor:
    def __init__(self, hub, rules):
        bad = [m for r in rules if (m := validate_rule(r))]
        if bad:
            raise ValueError("; ".join(bad))
        self.rules = [dict(r) for r in rules]
        self.hub, self.log, self._seen = hub, [], {}
        self._orig = hub._invoke
        hub._invoke = self._invoke                    # thuộc tính của instance che phương thức của lớp: chỉ hub này bị bọc

    def _matching(self, name: str):
        for i, r in enumerate(self.rules):
            if r["tool"] != name:
                continue
            n = self._seen.get(i, 0)
            self._seen[i] = n + 1
            if r.get("after", 0) <= n < r.get("after", 0) + r.get("times", 1):
                yield i, r, n + 1

    def _invoke(self, name, args):
        hits = list(self._matching(name))
        for i, r, call_no in hits:
            if r["kind"] == "raise":
                self.log.append({"tool": name, "rule": i, "kind": "raise", "call_no": call_no, "error": r.get("error", "RuntimeError")})
                raise ERRORS[r.get("error", "RuntimeError")](r.get("message") or f"injected fault in {name}")
        res = self._orig(name, args)
        if not isinstance(res, dict) or not hits:
            return res
        res = copy.deepcopy(res)
        for i, r, call_no in hits:
            applied = _inject(res, r) if r["kind"] == "inject_text" else (_corrupt(res, float(r.get("factor", 10.0))) if r["kind"] == "corrupt_number" else False)
            self.log.append({"tool": name, "rule": i, "kind": r["kind"], "call_no": call_no, "applied": applied})
        return res

    def drain(self) -> list[dict]:
        out, self.log = self.log, []
        return out


def install(hub, rules) -> Interceptor | None:
    return Interceptor(hub, rules) if rules else None
