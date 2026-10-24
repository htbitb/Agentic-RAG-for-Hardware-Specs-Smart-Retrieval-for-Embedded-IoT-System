"""SimulatedHuman (plan/P5_interfaces.md §2; AgenticUpgradePlan §7.5): người dùng mô phỏng TẤT ĐỊNH theo `human_policy` của task — không LLM, không mạng.

* `respond(interrupt)` trả lời interrupt của hệ có HITL (S3): `clarify` ghép câu hỏi với `hidden_info[*].keywords` (đủ một từ khoá, không phân biệt hoa/thường,
  bỏ qua dấu câu và sở hữu cách 's, nguyên từ, cho phép số nhiều -s/-es; xét TỪNG CÂU của câu hỏi: câu chứa cụm `exclude` của mục thì không khớp mục đó;
  khớp nhiều mục ⇒ trả lời gộp theo thứ tự hidden_info) và chỉ tiết lộ câu trả lời của các mục
  ĐÃ được hỏi; không khớp ⇒ `unknown` + UNKNOWN_ANSWER, `necessary=False` (câu hỏi thừa). Hỏi lại mục đã được trả lời ⇒ vẫn trả lời nhưng
  `necessary=False` (thừa). `choice` chọn option ĐẦU TIÊN có từ khoá `prefer` trong label/pros/cons; không khớp ⇒ `unknown`.
  `approval`: approve | reject (+ góp ý). Task không khai `approval` ⇒ reject với NO_POLICY_REJECT_FEEDBACK (người dùng không yêu cầu ghi file;
  gần với P4, nơi lệnh ghi chờ duyệt không bao giờ được duyệt).
* `max_answers` (mặc định 3) giới hạn số câu trả lời CÓ NỘI DUNG cho clarify/văn bản/choice (thông tin trao cho hệ); quá giới hạn ⇒ `unknown`,
  `answered=False`. Approval không bị giới hạn (quyết định duyệt luôn phải có).
* Baseline không có cơ chế hỏi: `detect_question(answer)` tìm câu hỏi HƯỚNG TỚI NGƯỜI DÙNG trong câu trả lời; `reply_to_text` trả lời nó như clarify
  (`kind="text"`, `source="baseline_text"`, decision luôn "answer" để runner gửi payload["answer"] như lượt người dùng kế tiếp).

Quy tắc `detect_question` (tất định, có test):
  1. bỏ khối code ``` / ~~~ (kể cả khối chưa đóng), code inline `...`, chú thích HTML, URL, chuỗi trong ngoặc kép có chứa '?' (chuỗi C, câu được trích);
  2. bỏ dòng tiêu đề (#), dòng bảng (|), trích dẫn (>);
  3. một câu (tách theo . ! ? + khoảng trắng) là câu hỏi khi KHÔNG thuộc mẫu mời/xã giao (OFFER: "would you like me to", "do you want me to",
     "shall I", "let me know if you need", "feel free", "did you know", "any questions"...) và
       (a) kết thúc bằng '?' và có ngôi thứ hai (you/your/you're…/bạn) hoặc là câu yêu cầu (b); hoặc
       (b) là câu yêu cầu thông tin: "(…,) please|kindly confirm/specify/provide/let me know/tell me/share/clarify/…", "could/can/would you confirm/tell/…",
           "let me know the/what/which/whether/your…", "I need you to confirm…", "I need to know…";
  4. dòng (không phải mục danh sách) kết thúc bằng ':' và có từ hỏi lại (question(s), clarifying, need to know, confirm the following, "I need the
     following information", please answer/provide/confirm…, let me know, could/can you) mở một khối: MỌI mục danh sách ngay sau đó là câu hỏi (kể cả không có '?', vd "- HSE crystal
     frequency"); dòng mở khối không tính. "Before I write the code, here are the steps:", "To confirm it works, check:" hay "You need the
     following parts:" KHÔNG mở khối.
  5. tiêu đề (#) hay dòng chỉ in đậm có từ hỏi lại (kể cả không có ':') cũng mở khối: "**Open questions**", "### Missing information".
  6. câu '?' không có ngôi thứ hai vẫn tính khi nêu rõ thông tin của người dùng còn thiếu: cùng câu ("The HSE frequency is not given; which crystal
     is fitted?") hoặc ngay sau câu như vậy trong cùng đoạn ("… is not specified. Which crystal is fitted?"); "unknown", "why" không tính.
  Câu hỏi tu từ không có ngôi thứ hai ("Why 4 wait states?") và câu trong code KHÔNG tính. Trả các câu hỏi (đã bỏ markdown) nối bằng khoảng trắng.
  Kiểm trên 730 câu trả lời thật của dev_baseline_v2 (task đủ thông tin): 0 dương tính (test).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# D40 + review C5 G15: giữ nguyên câu tiếng Việt và thêm bản tiếng Anh (đề và checklist C5 bằng tiếng Anh; tránh hệ chuyển sang trả lời tiếng Việt)
UNKNOWN_ANSWER = "Không biết, hãy tự chọn phương án hợp lý (I don't know - please choose a reasonable option yourself and state your assumption.)"
DEFAULT_REJECT_FEEDBACK = "Not approved. Please do not write this file."
NO_POLICY_REJECT_FEEDBACK = ("Not approved: the user did not ask for any file to be written. Do not write files; put the content in your answer instead.")
DEFAULT_MAX_ANSWERS = 3


@dataclass
class HumanReply:
    decision: str
    payload: dict
    record: dict


# ------------------------------------------------------------------ khớp từ khoá
def _norm(s: str) -> str:
    """' hse frequency 8 mhz ': chữ thường, bỏ sở hữu cách ("nRF52840's VDD" -> 'nrf52840 vdd'), tách số/chữ ('1.8V' -> '1 8 v'),
    mọi ký tự không phải chữ/số thành khoảng trắng."""
    s = re.sub(r"(?<=\w)['’]s\b", "", str(s or ""))
    s = re.sub(r"(?<=\d)(?=[^\W\d_])|(?<=[^\W\d_])(?=\d)", " ", s.lower())
    return " " + " ".join(re.sub(r"[\W_]+", " ", s).split()) + " "


def _has_phrase(text_n: str, phrase: str) -> bool:
    p = _norm(phrase).strip()
    return bool(p) and any(f" {p}{suf} " in text_n for suf in ("", "s", "es"))


# ------------------------------------------------------------------ phát hiện câu hỏi (baseline)
_FENCE = re.compile(r"(```|~~~).*?(?:\1|\Z)", re.S)
_INLINE = re.compile(r"`[^`\n]*`")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_URL = re.compile(r"\b(?:https?|ftp)://\S+|\bwww\.\S+", re.I)
_QUOTED_Q = re.compile(r"\"[^\"\n]{0,300}?\?[^\"\n]{0,300}?\"|“[^”\n]{0,300}?\?[^”\n]{0,300}?”")
_LIST = re.compile(r"^\s*(?:[-*+•]|\d{1,2}[.)])\s+")
_SECOND = re.compile(r"\b(?:you|your|yours|yourself|yourselves)\b|\byou['’](?:re|ve|d|ll)\b|\bbạn\b", re.I)
_OFFER = re.compile(
    r"\b(?:would|do|did|will)\s+you\s+(?:like|want|need)\s+me\b|\bwant\s+me\s+to\b|\bshall\s+i\b|\bshould\s+i\b|\bmay\s+i\b|\bcan\s+i\s+help\b|"
    r"\bwould\s+you\s+like\s+(?:a|an|me|more|further|additional|any|to\s+see|help|some)\b|\bif\s+you(?:['’]d|\s+would)\s+like\b|"
    r"\blet\s+me\s+know\s+if\s+you\b|\bif\s+you\s+(?:need|want|have\s+(?:any|more|further|other))\b|\bfeel\s+free\b|\bhappy\s+to\s+help\b|"
    r"\bhope\s+(?:this|that|it)\s+helps\b|\bhow\s+(?:else\s+)?(?:i|we)\s+can\s+(?:help|assist)\b|\bhow\s+can\s+(?:i|we)\s+(?:help|assist)\b|"
    r"\banything\s+else\b|\bany\s+(?:other\s+|further\s+|more\s+)?questions\b|\bdid\s+you\s+know\b|\bhave\s+you\s+ever\b", re.I)
_LEAD = r"(?:[\w’' ,]{0,60}?[,:]\s*)?"
_REQUEST = re.compile(
    rf"^{_LEAD}(?:please|kindly)\s+(?:confirm|specify|provide|let\s+me\s+know|tell\s+me|share|clarify|advise|indicate|send|state|answer|check\s+and\s+(?:tell|let))\b|"
    rf"^{_LEAD}(?:could|can|would|will)\s+you\s+(?:please\s+)?(?:confirm|specify|provide|tell|share|clarify|let\s+me\s+know|check|send|indicate|advise)\b|"
    r"^let\s+me\s+know\s+(?:the|what|which|whether|how|your|if\s+your|about)\b|"
    r"^(?:i|we)\s+(?:need|would\s+need|will\s+need|still\s+need)\s+(?:to\s+know|you\s+to\s+(?:confirm|tell|specify|provide|share|clarify))\b", re.I)
_INTRO = re.compile(r"\b(?:questions?|clarifying|clarifications?\s+(?:needed|required)|need\s+(?:some\s+)?clarification|need\s+to\s+know|confirm\s+the\s+following|"
                    r"(?:i|we)\s+(?:still\s+|would\s+|will\s+)?need\s+(?:the\s+following\s+|(?:\w+\s+){0,2})"
                    r"(?:information|details?|answers|inputs?|values?|parameters?|things|facts|points)|"
                    r"(?:information|details?|inputs?|values?|parameters?|data|things|specs?|specifications?|facts)\s+(?:\w+\s+){0,2}(?:is|are)\s+(?:still\s+)?missing|"
                    r"missing\s+(?:information|details?|inputs?|values?|parameters?|data)|"
                    r"(?:is|are|was|were)\s+(?:not|n't)\s+(?:given|specified|stated|provided)|unspecified|"
                    r"please\s+(?:answer|provide|specify|confirm|tell|let\s+me\s+know)|let\s+me\s+know|could\s+you|can\s+you)\b", re.I)
# review C5 G14: câu hỏi trực tiếp không có "you" vẫn tính khi nó nói rõ thông tin của người dùng còn thiếu — cùng câu ("X is not given; which …?")
# hoặc ngay sau một câu như vậy trong cùng đoạn ("X is not specified. Which …?"). "unknown"/"why" không tính (tu từ: "Why does it matter?").
_MISSING = (r"(?:(?:is|are|was|were)\s+(?:not|n't)\s+(?:given|specified|stated|provided|mentioned)|(?:is|are)\s+(?:still\s+)?missing|(?:is|are)\s+unspecified|"
            r"(?:you|the\s+(?:prompt|task|question|request|spec(?:ification)?))\s+(?:did\s+not|didn't|does\s+not|doesn't)\s+(?:say|specify|state|mention|give))")
_INTERROGATIVE = r"(?:which|what|how\s+(?:much|many|fast|high|large|long)|is|are|does|do|can|could|should|where|when)\b"
_MISSING_Q = re.compile(rf"\b{_MISSING}\b[^?]{{0,80}}?[;:,—–]\s*(?:so\s+|but\s+|then\s+)?{_INTERROGATIVE}[^?]*[?？]", re.I)
_MISSING_STMT = re.compile(rf"\b{_MISSING}\b", re.I)
_FOLLOW_Q = re.compile(rf"^{_INTERROGATIVE}[^?]*[?？]$", re.I)
_BOLD_LINE = re.compile(r"^(?:\*\*[^*]+\*\*|__[^_]+__):?$")


def _strip_non_prose(text: str) -> str:
    t = _FENCE.sub("\n", text or "")
    t = _HTML_COMMENT.sub(" ", t)
    t = _INLINE.sub(" ", t)
    t = _URL.sub(" ", t)
    return _QUOTED_Q.sub(" ", t)


def _clean(s: str) -> str:
    return " ".join(re.sub(r"\*\*|__|\*", "", s).split())


def _is_question(s: str, after_missing: bool = False) -> bool:
    if not s or _OFFER.search(s):
        return False
    request = bool(_REQUEST.match(s))
    if s.rstrip(" \"'_").endswith(("?", "？")):
        return bool(_SECOND.search(s)) or request or bool(_MISSING_Q.search(s)) or (after_missing and bool(_FOLLOW_Q.match(s)))
    return request


def detect_question(answer_text: str) -> str | None:
    """Các câu hỏi hướng tới người dùng trong câu trả lời (theo thứ tự, nối bằng khoảng trắng); None nếu không có. Quy tắc: docstring module."""
    out: list[str] = []
    block = missing = False
    for raw in _strip_non_prose(answer_text).splitlines():
        line = raw.strip()
        if not line:
            missing = False                                     # dòng trống: hết đoạn (nhưng không đóng khối câu hỏi)
            continue
        if line.startswith(("|", ">")):
            block = missing = False
            continue
        if line.startswith("#") or _BOLD_LINE.match(line):     # tiêu đề / dòng chỉ in đậm: mở khối nếu là lời hỏi ("**Open questions**", "### Missing information")
            block, missing = bool(_INTRO.search(_clean(line.lstrip("#")))), False
            continue
        item = bool(_LIST.match(line))
        content = _clean(_LIST.sub("", line, count=1) if item else line)
        if item and block:
            if content and not _OFFER.search(content):
                out.append(content)
            continue
        if not item:
            block = content.endswith(":") and bool(_INTRO.search(content))
            if block:
                continue
        for s in (x.strip() for x in re.split(r"(?<=[.!?？])\s+", content)):
            if _is_question(s, missing):
                out.append(s)
            missing = bool(_MISSING_STMT.search(s)) and not s.rstrip(" \"'_").endswith(("?", "？"))
    return " ".join(out) or None


# ------------------------------------------------------------------ người dùng mô phỏng
class SimulatedHuman:
    def __init__(self, policy: dict | None, hidden_info: list[dict] | None = None):
        self.policy = dict(policy or {})
        self.hidden = [h for h in (hidden_info or []) if isinstance(h, dict) and h.get("id")]
        self.clarify = dict(self.policy.get("clarify") or {})
        self.max_answers = int(self.policy.get("max_answers", DEFAULT_MAX_ANSWERS))
        self.records: list[dict] = []
        self._given = 0                       # câu trả lời có nội dung đã trao (clarify / văn bản / choice)
        self._answered_ids: set[str] = set()

    # ---------------------------------------------------------------- công khai
    def respond(self, interrupt: dict) -> HumanReply:
        interrupt = interrupt or {}
        kind, question = interrupt.get("kind"), str(interrupt.get("question") or "")
        if kind == "clarify":
            return self._clarify(question, "clarify", "interrupt")
        if kind == "choice":
            return self._choice(question, interrupt.get("options") or [])
        if kind == "approval":
            return self._approval(question)
        return self._reply(str(kind or "?"), question, [], False, False, "unknown", {"answer": UNKNOWN_ANSWER}, "interrupt")

    def detect_question(self, answer_text: str) -> str | None:
        return detect_question(answer_text)

    def reply_to_text(self, answer_text: str) -> HumanReply | None:
        q = detect_question(answer_text)
        return None if q is None else self._clarify(q, "text", "baseline_text")

    # ---------------------------------------------------------------- nội bộ
    def match(self, question: str) -> list[str]:
        """id các mục hidden_info (theo thứ tự hidden_info) có một CÂU của câu hỏi chứa >= 1 từ khoá của mục và không chứa cụm `exclude` nào
        của mục (vd 'LSE' với mục HSE: "What load capacitance does the 32.768 kHz LSE crystal need?" không hỏi về thạch anh HSE).
        Câu tách theo . ? ! ; + khoảng trắng và xuống dòng (không tách '1.8 V', '32.768 kHz')."""
        parts = [_norm(p) for p in re.split(r"[.?!;？]+(?=\s|$)|\n+", question or "") if p.strip()]
        return [h["id"] for h in self.hidden
                if any(any(_has_phrase(p, k) for k in h.get("keywords") or []) and not any(_has_phrase(p, x) for x in h.get("exclude") or [])
                       for p in parts)]

    def _reply(self, kind, question, matched, necessary, answered, decision, payload, source) -> HumanReply:
        answer = payload.get("answer", payload.get("feedback", payload.get("option", "")))
        record = {"kind": kind, "question": question, "matched": list(matched), "necessary": bool(necessary), "answered": bool(answered),
                  "decision": decision, "answer": str(answer), "source": source, "index": len(self.records)}
        self.records.append(record)
        return HumanReply(decision=decision, payload=payload, record=record)

    def _clarify(self, question: str, kind: str, source: str) -> HumanReply:
        matched = self.match(question)
        answerable = [i for i in matched if i in self.clarify]
        necessary = any(i not in self._answered_ids for i in answerable)
        if answerable and self._given < self.max_answers:
            self._given += 1
            self._answered_ids.update(answerable)
            return self._reply(kind, question, matched, necessary, True, "answer", {"answer": " ".join(self.clarify[i] for i in answerable)}, source)
        decision = "answer" if kind == "text" else "unknown"           # văn bản: runner luôn gửi payload["answer"] như lượt kế tiếp
        return self._reply(kind, question, matched, necessary, False, decision, {"answer": UNKNOWN_ANSWER}, source)

    def _choice(self, question: str, options: list) -> HumanReply:
        prefer = (self.policy.get("choice") or {}).get("prefer")
        pick = None
        if prefer:
            for opt in options:
                if isinstance(opt, dict) and _has_phrase(_norm(" ".join(str(opt.get(k) or "") for k in ("label", "pros", "cons"))), prefer):
                    pick = opt
                    break
        if pick is not None and self._given < self.max_answers:
            self._given += 1
            return self._reply("choice", question, [], True, True, "choose", {"option": pick.get("id") or pick.get("label")}, "interrupt")
        return self._reply("choice", question, [], False, False, "unknown", {"answer": UNKNOWN_ANSWER}, "interrupt")

    def _approval(self, question: str) -> HumanReply:
        ap = self.policy.get("approval")
        if ap == "approve":
            return self._reply("approval", question, [], True, True, "approve", {}, "interrupt")
        feedback = ap["reject"] if isinstance(ap, dict) else DEFAULT_REJECT_FEEDBACK if ap == "reject" else NO_POLICY_REJECT_FEEDBACK
        return self._reply("approval", question, [], True, True, "reject", {"feedback": feedback}, "interrupt")
