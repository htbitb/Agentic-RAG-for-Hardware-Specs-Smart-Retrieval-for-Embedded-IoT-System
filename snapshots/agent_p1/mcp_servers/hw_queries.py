"""Truy vấn dữ liệu phần cứng thật (hw_specs.sqlite) cho MCP server `hw-knowledge`.

Mọi giá trị trả về đều truy được về SVD hoặc trang PDF (`doc` + `page`). Đầu ra lớn được phân trang / cắt có kiểm soát và
luôn báo `truncated` / `next_offset` để tác tử biết còn dữ liệu. Cấu trúc `results[*]` của `get_electrical_specs`
(category, field_type, min, max, unit, parameter, doc, page) được giữ nguyên vì guardrail và verifier đọc nó.
"""
from __future__ import annotations

import difflib
import json
import re
from pathlib import Path

from ingestion import hwdb
from ingestion.unit_normalizer import eval_vdd_expr

CHIP_ALIASES = {"stm32": "stm32g474", "stm32g4": "stm32g474", "stm32g474": "stm32g474", "esp32": "esp32",
                "nrf52": "nrf52840", "nrf52840": "nrf52840"}
DEFAULT_LIMIT = 30
MAX_LIMIT = 100
_FIELD_TYPE_WORDS = {
    "supply_voltage": "supply vdd power rail operating voltage",
    "input_voltage": "input vin pin voltage tolerant",
    "input_voltage_high": "input vih high level pin voltage logic",
    "input_voltage_low": "input vil low level pin voltage logic",
    "output_voltage_high": "output voh high level voltage logic",
    "output_voltage_low": "output vol low level voltage logic",
    "current": "current source sink output",
    "temperature": "temperature ambient junction storage",
}
_CATEGORY_RANK = {"absolute_max": 0, "recommended_operating": 1, "dc_characteristics": 2}
_TOK = re.compile(r"[a-z0-9_]{2,}")


def _hex(v, width=8) -> str | None:
    return None if v is None else f"0x{int(v):0{width}X}"


def _bits(off: int, width: int) -> str:
    return f"[{off}]" if width == 1 else f"[{off + width - 1}:{off}]"


def _norm(s: str) -> str:
    return re.sub(r"[\s]+", "", (s or "")).upper()


def _short(s: str | None, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "…"


def _size_of(obj) -> int:
    return len(json.dumps(obj, ensure_ascii=False, default=str))


class HwStore:
    def __init__(self, path: str | Path = hwdb.DEFAULT_DB):
        self.conn = hwdb.connect(path, readonly=True)
        self._chips = [r["chip"] for r in self.conn.execute("SELECT chip FROM chips ORDER BY chip")]
        self._reg_cache: dict[str, list[dict]] = {}

    # ------------------------------------------------------------------ chip / peripheral resolution
    def chip(self, name: str | None) -> str | None:
        k = re.sub(r"[\s_-]", "", (name or "").lower())
        c = CHIP_ALIASES.get(k)
        if c is None and k.startswith("stm32g4"):
            c = "stm32g474"
        return c if c in self._chips else None

    def _unknown_chip(self, name) -> dict:
        return {"error": f"Unknown chip {name!r}. Supported chips: {', '.join(self._chips)}.", "chips": self._chips}

    def _peripherals(self, chip: str) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT name, group_name, derived_from, alternate_peripheral, base_address, description FROM peripherals "
            "WHERE chip=? ORDER BY name", (chip,))]

    def _find_peripheral(self, chip: str, name: str):
        """-> (peripheral row | None, [candidates]). Khớp tên, rồi alias (alternatePeripheral), rồi tên nhóm."""
        pers = self._peripherals(chip)
        key = _norm(name)
        for p in pers:
            if _norm(p["name"]) == key:
                return p, []
        alt = [p for p in pers if p["alternate_peripheral"] and _norm(p["alternate_peripheral"]) == key]
        if len(alt) == 1:
            return alt[0], []
        grp = [p["name"] for p in pers if p["group_name"] and _norm(p["group_name"]) == key]
        if grp or alt:
            return None, sorted(set(grp + [p["name"] for p in alt]))
        names = [p["name"] for p in pers]
        return None, difflib.get_close_matches(name, names, n=5, cutoff=0.5) or [n for n in names if _norm(n).startswith(key[:3])][:5]

    def _registers_of(self, chip: str, peripheral: str) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM registers WHERE chip=? AND peripheral=? ORDER BY id", (chip, peripheral))]

    @staticmethod
    def _register_keys(per: str, r: dict) -> set[str]:
        keys = {r["name"], r["short_name"] or r["name"], f"{per}_{r['name']}", f"{per}_{r['short_name'] or r['name']}"}
        if r["rm_name"]:
            keys.add(r["rm_name"])
        keys |= {k.replace(".", "_") for k in list(keys)} | {k.replace("[", "").replace("]", "") for k in list(keys)}
        return {_norm(k) for k in keys}

    def _match_register(self, chip: str, per: str, token: str) -> list[dict]:
        key = _norm(token)
        regs = self._registers_of(chip, per)
        exact = [r for r in regs if _norm(r["name"]) == key]
        if exact:
            return exact
        return [r for r in regs if key in self._register_keys(per, r)]

    # ------------------------------------------------------------------ registers
    def _display_name(self, r: dict) -> str:
        n, p = r["name"], r["peripheral"]
        return n if n.upper().startswith(p.upper() + "_") or re.match(r"^[A-Z0-9]+_[A-Z0-9_]+$", n) and \
            n.upper().startswith((p.upper().rstrip("0123456789"), )) else f"{p}_{n}"

    def _register_record(self, r: dict, field: str | None, max_enums: int, with_fields: bool = True) -> dict:
        rec = {
            "peripheral": r["peripheral"], "register": r["name"], "name": self._display_name(r), "address": _hex(r["address"]),
            "offset": _hex(r["offset"], 2), "size": r["size"], "access": r["access"],
            "reset_value": _hex(r["reset_value"], r["size"] // 4), "reset_mask": _hex(r["reset_mask"], r["size"] // 4),
            "reserved_mask": _hex(r["reserved_mask"], r["size"] // 4), "rw_mask": _hex(r["rw_mask"], r["size"] // 4),
            "description": r["description"], "doc": r["doc"], "page": r["page"],
        }
        if r["address_alias"] is not None:
            rec["address_alias"] = _hex(r["address_alias"])
        if r["alt_pages"]:
            rec["alt_pages"] = json.loads(r["alt_pages"])
        if r["rm_name"]:
            rec["manual_name"] = r["rm_name"]
        if r["page_confidence"]:
            rec["page_confidence"] = r["page_confidence"]
        if r["rm_reset_value"] is not None and r["rm_reset_value"] != r["reset_value"]:
            rec["manual_reset_value"] = _hex(r["rm_reset_value"], r["size"] // 4)
        warnings = []
        if r["svd_only"]:
            warnings.append("Not found in the indexed manual (automatic matching): " + (r["note"] or "values come from the vendor SVD only."))
        if "manual_reset_value" in rec:
            warnings.append(f"Vendor SVD reset {rec['reset_value']} differs from the reset value printed in the manual "
                            f"{rec['manual_reset_value']} (p.{r['page']}); both are shown, verify against the manual.")
        if r["page_confidence"] == "offset":
            warnings.append(f"Matched to manual register {r['rm_name']} by offset (the SVD name differs).")
        if r["page_confidence"] == "cluster":
            warnings.append("Described together with its parent cluster in the manual.")
        if r["page_confidence"] == "summary":
            warnings.append("Listed in the manual's register summary table (no per-register description page found).")
        if r["page_confidence"] == "offset_mismatch":
            warnings.append("The offset printed in the manual differs from the SVD offset.")
        if r["address_alias"] is not None:
            warnings.append("address_alias is the same register seen through the other bus window (ESP32 TRM p.73).")
        if r["alternate_register"]:
            rec["alternate_register"] = r["alternate_register"]
        if warnings:
            rec["warnings"] = warnings
        if with_fields:
            q = "SELECT * FROM fields WHERE register_id=?" + (" AND upper(name)=upper(?)" if field else "") + " ORDER BY bit_offset"
            fields = []
            for f in self.conn.execute(q, (r["id"], field) if field else (r["id"],)):
                item = {"name": f["name"], "bits": _bits(f["bit_offset"], f["bit_width"]), "bit_offset": f["bit_offset"],
                        "bit_width": f["bit_width"], "access": f["access"], "description": _short(f["description"], 200)}
                if f["write_constraint"]:
                    item["write_constraint"] = f["write_constraint"]
                enums = self.conn.execute("SELECT name, value, value_raw, description, is_default FROM enum_values WHERE field_id=? "
                                          "ORDER BY value", (f["id"],)).fetchall()
                if enums:
                    cap = 64 if field else max_enums
                    item["enums"] = [{"name": e["name"], "value": e["value"] if e["value"] is not None else e["value_raw"],
                                      "description": _short(e["description"], 80)} for e in enums[:cap]]
                    if len(enums) > cap:
                        item["enums_truncated"] = len(enums)
                fields.append(item)
            rec["fields"] = fields
            if field and not fields:
                rec["warnings"] = rec.get("warnings", []) + [f"No field named {field!r} in this register."]
        return rec

    def get_register_bitfields(self, chip: str, peripheral: str | None = None, register: str | None = None,
                               field: str | None = None, limit: int = DEFAULT_LIMIT, offset: int = 0,
                               max_chars: int = 12000) -> dict:
        c = self.chip(chip)
        if c is None:
            return self._unknown_chip(chip)
        limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
        offset = max(0, int(offset or 0))
        if not peripheral and not register:
            return {"chip": c, "error": "Give a peripheral (e.g. TIM1) and/or a register name (e.g. TIM1_CR1). "
                    "Use search_registers when the exact name is unknown.", "peripherals": [p["name"] for p in self._peripherals(c)]}
        per = None
        if peripheral:
            p, cand = self._find_peripheral(c, peripheral)
            if p is None:
                if cand and any(_norm(x) != _norm(peripheral) for x in cand) and not register:
                    return {"chip": c, "peripheral": peripheral, "count": 0, "registers": [], "peripherals": cand,
                            "note": f"{peripheral!r} is a group of peripherals; pick one of the listed instances."}
                return {"chip": c, "peripheral": peripheral, "count": 0, "registers": [],
                        "error": f"No peripheral {peripheral!r} for {c}.", "suggestions": cand}
            per = p["name"]
        if register:
            hits: list[dict] = []
            if per:
                hits = self._match_register(c, per, register)
            else:
                tok = register
                for m in re.finditer("_", tok):                          # 'TIM1_CR1' -> peripheral TIM1 + register CR1
                    pp, rr = tok[: m.start()], tok[m.end():]
                    cand_p, _ = self._find_peripheral(c, pp)
                    if cand_p:
                        hits = self._match_register(c, cand_p["name"], rr) or self._match_register(c, cand_p["name"], tok)
                        if hits:
                            break
                if not hits:
                    key = _norm(tok)
                    hits = [r for r in self._all_registers(c) if key in self._register_keys(r["peripheral"], r)]
            if not hits:
                pool = [r["name"] for r in self._registers_of(c, per)] if per else [r["name"] for r in self._all_registers(c)]
                return {"chip": c, "peripheral": per, "register": register, "count": 0, "registers": [],
                        "error": f"No register {register!r}" + (f" in {per}" if per else "") + f" for {c}.",
                        "suggestions": difflib.get_close_matches(register, pool, n=6, cutoff=0.4)}
            records = []
            budget_note = {}
            for r in hits[:5]:
                rec = self._register_record(r, field, max_enums=10)
                records.append(rec)
            out = {"chip": c, "peripheral": per or (records[0]["peripheral"] if len(records) == 1 else None),
                   "count": len(records), "registers": records}
            if len(hits) > 5:
                out["truncated"] = True
                out["total"] = len(hits)
            if _size_of(out) > max_chars:                                  # 1) bỏ enum
                for rec in records:
                    for f in rec.get("fields", []):
                        if "enums" in f:
                            f["enums_truncated"] = len(f["enums"])
                            del f["enums"]
                    rec["enums_omitted"] = True
                    rec["note_enums"] = "enumerated values omitted for size; call again with field=<name>."
            if _size_of(out) > max_chars:                                  # 2) cắt field
                for rec in records:
                    total = len(rec.get("fields", []))
                    while rec.get("fields") and _size_of(out) > max_chars:
                        rec["fields"].pop()
                    if rec.get("fields") is not None and len(rec["fields"]) < total:
                        rec["fields_truncated"] = True
                        rec["total_fields"] = total
                        rec["note_fields"] = "field list cut for size; call again with field=<name> for a specific field."
            out.update(budget_note)
            return out
        regs = self._registers_of(c, per)
        page = regs[offset: offset + limit]
        rows = [{"register": r["name"], "name": self._display_name(r), "address": _hex(r["address"]), "offset": _hex(r["offset"], 2),
                 "reset_value": _hex(r["reset_value"], r["size"] // 4), "access": r["access"],
                 "description": _short(r["description"], 90), "doc": r["doc"], "page": r["page"],
                 **({"svd_only": True} if r["svd_only"] else {})} for r in page]
        out = {"chip": c, "peripheral": per, "base_address": _hex(next(p["base_address"] for p in self._peripherals(c) if p["name"] == per)),
               "count": len(rows), "total": len(regs), "truncated": offset + limit < len(regs), "registers": rows}
        if out["truncated"]:
            out["next_offset"] = offset + limit
        return out

    def _all_registers(self, chip: str) -> list[dict]:
        if chip not in self._reg_cache:
            rows = self.conn.execute(
                "SELECT r.*, (SELECT group_concat(f.name, ' ') FROM fields f WHERE f.register_id = r.id) AS field_names "
                "FROM registers r WHERE r.chip=? ORDER BY r.id", (chip,)).fetchall()
            self._reg_cache[chip] = [dict(r) for r in rows]
        return self._reg_cache[chip]

    def search_registers(self, chip: str, query: str, limit: int = 15) -> dict:
        c = self.chip(chip)
        if c is None:
            return self._unknown_chip(chip)
        limit = max(1, min(int(limit or 15), MAX_LIMIT))
        q = (query or "").strip()
        regs = self._all_registers(c)
        m = re.fullmatch(r"0[xX]([0-9A-Fa-f]+)", q)
        if m:
            addr = int(m.group(1), 16)
            hits = [r for r in regs if r["address"] == addr or r["address_alias"] == addr]
            scored = [(10.0, r) for r in hits]
        else:
            toks = [t for t in _TOK.findall(q.lower()) if t not in {"the", "of", "for", "and", "register", "registers"}] or _TOK.findall(q.lower())
            scored = []
            for r in regs:
                names = " ".join(filter(None, [r["name"], r["short_name"], r["peripheral"], r["rm_name"]])).lower().replace("[", "").replace("]", "")
                nameset = set(re.split(r"[^a-z0-9]+", names))
                desc = (r["description"] or "").lower()
                fnames = (r["field_names"] or "").lower()
                sc = 0.0
                for t in toks:
                    if t in nameset:
                        sc += 4.0
                    elif t in names:
                        sc += 2.5
                    if re.search(rf"\b{re.escape(t)}", desc):
                        sc += 2.0
                    if t in fnames:
                        sc += 1.0
                if sc > 0:
                    scored.append((sc + (0.25 if r["doc"] != f"{c}_SVD" and not r["svd_only"] else 0.0), r))
            scored.sort(key=lambda x: (-x[0], x[1]["id"]))
        out = []
        for sc, r in scored[:limit]:
            out.append({"chip": c, "peripheral": r["peripheral"], "register": r["name"], "name": self._display_name(r),
                        "address": _hex(r["address"]), "offset": _hex(r["offset"], 2), "description": _short(r["description"], 120),
                        "doc": r["doc"], "page": r["page"], "match_score": round(sc, 2),
                        **({"svd_only": True} if r["svd_only"] else {})})
        res = {"chip": c, "query": query, "count": len(out), "total": len(scored), "truncated": len(scored) > limit, "results": out}
        if not out:
            res["error"] = f"No register matches {query!r} for {c}."
        return res

    # ------------------------------------------------------------------ pins
    def _norm_pin(self, chip: str, pin: str) -> str | None:
        p = (pin or "").strip().upper()
        rows = {r["pin"].upper(): r["pin"] for r in self.conn.execute("SELECT pin FROM pins WHERE chip=?", (chip,))}
        cands = [p, p.replace(" ", "")]
        if chip == "esp32":
            if re.fullmatch(r"\d{1,2}", p):
                cands.append(f"GPIO{p}")
            if p.startswith("IO") and p[2:].isdigit():
                cands.append(f"GPIO{p[2:]}")
        if chip == "nrf52840":
            m = re.fullmatch(r"P?([01])[._]?(\d{1,2})", p)
            if m:
                cands.append(f"P{m.group(1)}.{int(m.group(2)):02d}")
        for c in cands:
            if c in rows:
                return rows[c]
        pad = self.conn.execute("SELECT pin FROM pins WHERE chip=? AND upper(replace(pad_name,' ','')) = ?", (chip, p.replace(" ", ""))).fetchone()
        if pad:
            return pad["pin"]
        if chip == "stm32g474":                       # PC14-OSC32_IN, PF0-OSC_IN, PG10-NRST...
            pad = self.conn.execute("SELECT pin FROM pins WHERE chip=? AND upper(pad_name) LIKE ?", (chip, p + "-%")).fetchone()
            if pad:
                return pad["pin"]
        return None

    def query_pin_alternate_function(self, chip: str, pin: str) -> dict:
        c = self.chip(chip)
        if c is None:
            return self._unknown_chip(chip)
        pid = self._norm_pin(c, pin)
        if pid is None:
            allp = [r["pin"] for r in self.conn.execute("SELECT pin FROM pins WHERE chip=?", (c,))]
            return {"chip": c, "pin": pin, "functions": [], "error": f"No pin {pin!r} for {c}.",
                    "suggestions": difflib.get_close_matches(pin.upper(), allp, n=5, cutoff=0.5)}
        p = self.conn.execute("SELECT * FROM pins WHERE chip=? AND pin=?", (c, pid)).fetchone()
        funcs = [{"af": f["af"], "function": f["signal"], "peripheral": f["peripheral"], "kind": f["kind"],
                  "notes": f["notes"] or "", "doc": f["doc"], "page": f["page"]}
                 for f in self.conn.execute("SELECT * FROM pin_functions WHERE chip=? AND pin=? ORDER BY coalesce(af, 99), signal", (c, pid))]
        flags = [{"kind": f["kind"], "note": f["note"], "doc": f["doc"], "page": f["page"], "quote": f["quote"]}
                 for f in self.conn.execute("SELECT * FROM pin_flags WHERE chip=? AND pin=? ORDER BY kind", (c, pid))]
        out = {"chip": c, "pin": pid, "pad_name": p["pad_name"], "functions": funcs, "doc": p["doc"], "page": p["page"],
               "io_structure": p["io_structure"],
               "is_5v_tolerant": None if p["is_5v_tolerant"] is None else bool(p["is_5v_tolerant"]),
               "input_only": bool(p["input_only"]) if p["input_only"] is not None else None, "flags": flags,
               "packages": json.loads(p["packages"]) if p["packages"] else {}, "notes": p["notes"] or ""}
        if c == "stm32g474":
            used = {f["af"] for f in funcs if f["kind"] == "af"}
            out["unused_af"] = [i for i in range(16) if i not in used]
        else:
            note = self.conn.execute("SELECT value, doc, page FROM chip_notes WHERE chip=? AND topic IN ('psel_routing','gpio_matrix') "
                                     "ORDER BY topic LIMIT 1", (c,)).fetchone()
            if note:
                out["routing_note"] = f"{note['value']} [{note['doc']} p.{note['page']}]"
        return out

    def find_pins_for_signal(self, chip: str, signal: str, limit: int = 50) -> dict:
        c = self.chip(chip)
        if c is None:
            return self._unknown_chip(chip)
        limit = max(1, min(int(limit or 50), 200))
        sig = (signal or "").strip()
        rows = self.conn.execute("SELECT * FROM pin_functions WHERE chip=? AND upper(signal)=upper(?) ORDER BY pin", (c, sig)).fetchall()
        if not rows:
            like = sig.upper().replace("%", "").replace("_", r"\_") + r"\_%"
            rows = self.conn.execute("SELECT * FROM pin_functions WHERE chip=? AND upper(signal) LIKE ? ESCAPE '\\' ORDER BY pin, af", (c, like)).fetchall()
        if not rows:
            rows = self.conn.execute("SELECT * FROM pin_functions WHERE chip=? AND upper(peripheral)=upper(?) ORDER BY pin, af", (c, sig)).fetchall()

        def order(r):
            m = re.fullmatch(r"(P[A-Z]|GPIO|P\d\.)(\d+)", r["pin"])
            return (m.group(1), int(m.group(2))) if m else (r["pin"], 0)

        rows = sorted(rows, key=order)
        total = len(rows)
        matches = [{"pin": r["pin"], "af": r["af"], "function": r["signal"], "peripheral": r["peripheral"], "kind": r["kind"],
                    "notes": r["notes"] or "", "doc": r["doc"], "page": r["page"]} for r in rows[:limit]]
        out = {"chip": c, "signal": signal, "count": len(matches), "total": total, "truncated": total > limit, "matches": matches}
        if c != "stm32g474":
            note = self.conn.execute("SELECT value, doc, page FROM chip_notes WHERE chip=? AND topic IN ('psel_routing','gpio_matrix') "
                                     "ORDER BY topic LIMIT 1", (c,)).fetchone()
            if note:
                out["routing_note"] = f"{note['value']} [{note['doc']} p.{note['page']}]"
        if not matches:
            out["error"] = f"No pin function {signal!r} for {c}."
        return out

    # ------------------------------------------------------------------ electrical / clock
    @staticmethod
    def _score(row: dict, tokens: set[str], extra: str = "") -> float:
        hay = " ".join([row.get("parameter") or "", row.get("symbol") or "", row.get("field_type") or "", row.get("category") or "",
                        row.get("condition") or "", row.get("applies_to") or "", extra]).lower()
        words = set(_TOK.findall(hay))
        sc = float(len(tokens & words))
        sc += 2.0 * sum(1 for t in tokens if t in (row.get("parameter") or "").lower() or t == (row.get("symbol") or "").lower())
        return sc

    def get_electrical_specs(self, chip: str, parameter: str = "", category: str | None = None, vdd: float | None = None,
                             limit: int = 12, field_type: str | None = None) -> dict:
        c = self.chip(chip)
        if c is None:
            return {**self._unknown_chip(chip), "results": []}
        rows = [dict(r) for r in self.conn.execute("SELECT * FROM electrical_limits WHERE chip=? ORDER BY id", (c,))]
        if not rows:
            return {"chip": c, "results": [], "error": f"No electrical specifications indexed for chip '{chip}'."}
        tokens = set(_TOK.findall((parameter or "").lower()))
        out = []
        for r in rows:
            if category and r["category"] != category:
                continue
            if field_type and r["field_type"] != field_type:
                continue
            extra = _FIELD_TYPE_WORDS.get(r["field_type"], "")
            score = self._score(r, tokens, extra) if tokens else 1.0
            rec = {"parameter": r["parameter"], "category": r["category"], "field_type": r["field_type"], "symbol": r["symbol"],
                   "min": r["min"], "typ": r["typ"], "max": r["max"], "unit": r["unit"], "condition": r["condition"],
                   "applies_to": r["applies_to"], "doc": r["doc"], "page": r["page"], "quote": r["quote"], "match_score": score}
            if vdd is not None and any("VDD" in str(r[k] or "").upper() for k in ("min", "typ", "max")):
                rec["evaluated_at_vdd"] = {"vdd": vdd, **{k: eval_vdd_expr(r[k], vdd) for k in ("min", "typ", "max")}}
            out.append((score, _CATEGORY_RANK.get(r["category"], 9), r["id"], rec))
        out.sort(key=lambda x: (-x[0], x[1], x[2]))
        limit = max(1, min(int(limit or 12), 60))
        res = {"chip": c, "results": [x[3] for x in out[:limit]], "total": len(out), "truncated": len(out) > limit}
        if len(out) > limit:
            res["note"] = "more rows match; narrow with `category` / `parameter` or raise `limit`."
        return res

    def get_clock_limits(self, chip: str, parameter: str = "", limit: int = 15) -> dict:
        c = self.chip(chip)
        if c is None:
            return {**self._unknown_chip(chip), "results": []}
        rows = [dict(r) for r in self.conn.execute("SELECT * FROM clock_limits WHERE chip=? ORDER BY id", (c,))]
        tokens = set(_TOK.findall((parameter or "").lower()))
        scored = []
        for r in rows:
            sc = self._score(r, tokens) if tokens else 1.0
            if tokens and sc <= 0:
                continue
            scored.append((sc, r["id"], {"parameter": r["parameter"], "symbol": r["symbol"], "min": r["min"], "typ": r["typ"],
                                         "max": r["max"], "unit": r["unit"], "condition": r["condition"], "doc": r["doc"],
                                         "page": r["page"], "quote": r["quote"], "match_score": sc}))
        scored.sort(key=lambda x: (-x[0], x[1]))
        limit = max(1, min(int(limit or 15), 60))
        res = {"chip": c, "results": [x[2] for x in scored[:limit]], "total": len(scored), "truncated": len(scored) > limit}
        if not scored:
            res["error"] = f"No clock limit matches {parameter!r} for {c}."
        return res

    def check_logic_level_compatibility(self, src_chip: str, dst_chip: str, src_vdd: float = 3.3, dst_vdd: float = 3.3,
                                        dst_io_structure: str | None = None) -> dict:
        s, d = self.chip(src_chip), self.chip(dst_chip)
        if s is None or d is None:
            return self._unknown_chip(src_chip if s is None else dst_chip)

        def row(chip, ftype, category=None):
            q = "SELECT * FROM electrical_limits WHERE chip=? AND field_type=?" + (" AND category=?" if category else "")
            return [dict(r) for r in self.conn.execute(q + " ORDER BY id", (chip, ftype) + ((category,) if category else ()))]

        voh, vol = row(s, "output_voltage_high"), row(s, "output_voltage_low")
        vih, vil = row(d, "input_voltage_high"), row(d, "input_voltage_low")
        if not (voh and vol and vih and vil):
            return {"error": f"Missing logic-level specs for {src_chip} -> {dst_chip}"}
        voh, vol, vih, vil = voh[0], vol[0], vih[0], vil[0]
        voh_min = eval_vdd_expr(voh["min"], src_vdd)
        voh_max = src_vdd if eval_vdd_expr(voh["max"], src_vdd) is None else eval_vdd_expr(voh["max"], src_vdd)
        vol_max = eval_vdd_expr(vol["max"], src_vdd)
        vih_min = eval_vdd_expr(vih["min"], dst_vdd)
        vil_max = eval_vdd_expr(vil["max"], dst_vdd)
        # Giới hạn điện áp vào TỐI ĐA của chân đích: ưu tiên mức khuyến nghị theo loại chân (input_voltage / recommended),
        # rồi absolute max (input_voltage), cuối cùng VIH max. VIH max (vd. nRF: VDD) là dải logic-high chứ không phải giới hạn hỏng.
        def applicable(r):
            if not dst_io_structure or not r["applies_to"]:
                return True
            io = _norm(dst_io_structure)
            return any(_norm(t) and (_norm(t) in io or io.startswith(_norm(t).split("_")[0]))
                       for t in re.split(r"[,/]|\bexcept\b|\band\b", r["applies_to"]))

        limits = []
        for pool in (row(d, "input_voltage", "recommended_operating"), row(d, "input_voltage", "absolute_max"), [vih]):
            for r in pool:
                if r["max"] is None or not applicable(r):
                    continue
                v = eval_vdd_expr(r["max"], dst_vdd)
                if v is not None:
                    limits.append((v, r))
            if limits:
                break
        dst_max, dst_row = min(limits, key=lambda x: x[0]) if limits else (None, None)
        checks = [
            {"rule": "VOH_min >= VIH_min (high-level noise margin)",
             "status": "PASS" if voh_min is not None and vih_min is not None and voh_min >= vih_min else "FAIL",
             "detail": f"src VOH_min = {voh_min} V >= dst VIH_min = {vih_min} V"},
            {"rule": "VOL_max <= VIL_max (low-level noise margin)",
             "status": "PASS" if vol_max is not None and vil_max is not None and vol_max <= vil_max else "FAIL",
             "detail": f"src VOL_max = {vol_max} V <= dst VIL_max = {vil_max} V"},
        ]
        if dst_max is not None:
            checks.append({"rule": "VOH_max <= destination maximum input voltage (overvoltage safety)",
                           "status": "PASS" if voh_max <= dst_max + 1e-9 else "FAIL",
                           "detail": f"src VOH_max = {voh_max} V vs dst max input voltage = {dst_max} V ({dst_row['parameter']})"})
        verdict = "compatible" if all(c["status"] == "PASS" for c in checks) else "incompatible (overvoltage / level mismatch)"
        evidence = [{"doc": r["doc"], "page": r["page"]} for r in (voh, vih, vil, vol)]
        if dst_row:
            evidence.append({"doc": dst_row["doc"], "page": dst_row["page"]})
        seen, ev = set(), []
        for e in evidence:
            if (e["doc"], e["page"]) not in seen:
                seen.add((e["doc"], e["page"]))
                ev.append(e)
        out = {"src": s, "dst": d, "src_vdd": src_vdd, "dst_vdd": dst_vdd, "verdict": verdict, "checks": checks, "evidence": ev}
        if dst_io_structure is None and any(r["applies_to"] for _v, r in limits):
            out["assumption"] = ("Destination pin type not specified: the most conservative maximum input voltage across pin "
                                 "types was used; pass dst_io_structure (e.g. 'FT', 'TT') to refine.")
        return out

    # ------------------------------------------------------------------ misc
    def list_chips(self) -> dict:
        details = {}
        for c in self._chips:
            q = lambda t: self.conn.execute(f"SELECT count(*) FROM {t} WHERE chip=?", (c,)).fetchone()[0]  # noqa: E731
            row = self.conn.execute("SELECT device, svd_file FROM chips WHERE chip=?", (c,)).fetchone()
            details[c] = {"device": row["device"], "svd_file": row["svd_file"], "peripherals": q("peripherals"),
                          "registers": q("registers"), "pins": q("pins"), "electrical_limits": q("electrical_limits"),
                          "clock_limits": q("clock_limits")}
        return {"chips": list(self._chips), "details": details}
