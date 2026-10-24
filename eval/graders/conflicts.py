"""Bộ nhận diện xung đột TẤT ĐỊNH (D25): một câu trả lời có NÊU một xung đột thiết kế cho trước (mã `FAMILY:arg`) hay không.

Quy tắc (không LLM, không thống kê):
  * Câu trả lời được tách thành CÂU (dấu câu, xuống dòng, mục danh sách); khối code chỉ giữ lại các chú thích `//` và `/* */`.
  * Một câu NÊU xung đột khi chứa (1) ĐỊNH DANH của xung đột — tên chân (PA8), hai mức áp (1.8 V và 3.3 V, kể cả viết 1V8/3V3), timer (TIM2),
    khối clock (SYSCLK, VCO...) — VÀ (2) một TỪ VỰNG xung đột của họ mã đó (conflict, already used, level shifter, exceeds, input-only...) trong CÙNG câu,
    và từ vựng không bị PHỦ ĐỊNH (no / not / without / n't trong 4 từ trước nó, cùng mệnh đề; "conflict-free", "conflict check" không tính).
  * Từ vựng "tự phủ định" (cannot share, is not 5 V tolerant, does not have, not available...) tính là dương mà không cần xét phủ định thêm.
  * Dạng phủ định có định danh đi kèm ("instead of PA8", "not PA8", "can't use PA8") tính là dương ngầm cho mã gắn với chân đó.
Độ chính xác được đo trên tập hiệu chỉnh gán nhãn tay (eval/tests/fixtures/conflict_calibration*.yaml, báo cáo precision/recall trong plan/P3_progress.md).
Sau khi hiệu chỉnh KHÔNG chỉnh theo kết quả của hệ thật; nếu buộc phải sửa thì áp dụng cho mọi hệ và công bố số run đổi (như D18).
"""
from __future__ import annotations

import re

# ------------------------------------------------------------------------------------------------ tách câu
MAX_TEXT = 200_000            # câu trả lời suy biến (hàng chục nghìn ký tự lặp) không được làm treo bộ chấm
MAX_SENTENCE = 1_500
_ABBR = re.compile(r"\b(e\.g|i\.e|vs|etc|approx|cf)\.", re.I)
_FENCE = re.compile(r"```[^\n`]*\n(.*?)(?:```|\Z)", re.S)
_LATEX_WRAP = re.compile(r"\\(?:text|mathrm|textbf|textrm|mathbf|mathit|textit|operatorname)\s*\{([^{}]{0,80})\}")
_LATEX_SUB = re.compile(r"_\{([^{}]{1,20})\}")
_LATEX_SPACE = re.compile(r"\\[,;:! ]|~|\\[()\[\]]|\\quad|\\qquad")
_LATEX_SYM = {r"\times": "x", r"\cdot": "*", r"\approx": "~", r"\le": "<=", r"\leq": "<=", r"\ge": ">=", r"\geq": ">=", r"\%": "%", r"\_": "_", r"\Omega": "ohm"}
_CHAR_MAP = str.maketrans({"\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"', "\u00a0": " ", "\u202f": " ", "\u2009": " ", "\u2212": "-", "\u2011": "-", "\u2013": "-", "\u2014": "-"})


def normalize(text: str) -> str:
    """Chuẩn hoá cách viết không ảnh hưởng nghĩa: LaTeX ($170\\text{ MHz}$, $V_{DD}=3.3\\,\\mathrm{V}$), dấu nháy cong, khoảng trắng đặc biệt, gạch nối Unicode."""
    t = (text or "")[:MAX_TEXT].translate(_CHAR_MAP)
    if "\\" in t or "$" in t:
        for _ in range(2):
            t = _LATEX_WRAP.sub(lambda m: m.group(1), t)
        t = _LATEX_SUB.sub(lambda m: m.group(1), t)
        for k, v in _LATEX_SYM.items():
            t = t.replace(k, v)
        t = _LATEX_SPACE.sub(" ", t).replace("$", " ")
    return t


def _code_to_comments(m: re.Match) -> str:
    """Chỉ giữ chú thích `//` và `/* */` của khối code (quét tuyến tính; `/*` không đóng lấy đến hết khối)."""
    code, pos, notes = m.group(1), 0, []
    while True:
        i, j = code.find("/*", pos), code.find("//", pos)
        if i < 0 and j < 0:
            break
        if i >= 0 and (j < 0 or i < j):
            k = code.find("*/", i + 2)
            end = len(code) if k < 0 else k
            notes.append(code[i + 2:end].strip())
            pos = end + 2
        else:
            k = code.find("\n", j)
            end = len(code) if k < 0 else k
            notes.append(code[j + 2:end].strip())
            pos = end
    return "\n" + "\n".join(n for n in notes if n) + "\n"


def sentences(text: str) -> list[str]:
    """Các câu của một câu trả lời (khối code → chỉ còn chú thích). Định danh như TIM1_CH1, 1.8 V không bị cắt."""
    t = _FENCE.sub(_code_to_comments, normalize(text))
    t = _ABBR.sub(lambda m: m.group(1).replace(".", ""), t)
    t = t.replace("`", " ").replace("**", " ").replace("__", " ").replace("|", " ")
    t = re.sub(r"^[ \t]*(?:[-*\u2022>]+|\d{1,3}[.)]|#+)[ \t]+", "", t, flags=re.M)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])|\n+", t)
    return [re.sub(r"\s+", " ", p).strip()[:MAX_SENTENCE] for p in parts if p and p.strip()]


# ------------------------------------------------------------------------------------------------ phủ định
_NEG = {"no", "not", "never", "without", "none", "nothing", "neither", "nor", "nobody", "hardly", "zero"}
_NEG_KEEP = {"can't", "cant", "couldn't", "mustn't", "shouldn't", "wouldn't"}              # "can't exceed" nêu một giới hạn, không phải phủ định
_CLAUSE = re.compile(r"[,;:]|\b(?:but|however|though|although|while|whereas|and|so|because|since)\b", re.I)


_LIMIT_WORD = re.compile(r"(?:exceed|above|beyond|over\b|higher|greater|more than|faster|surpass|go over|be over)", re.I)
_MODALS = {"must", "should", "shall", "may", "cannot"}


def negated(sentence: str, start: int, extra=(), window: int = 4) -> bool:
    """Có từ phủ định trong `window` từ ngay trước vị trí `start` (cùng mệnh đề)?
    "must/should/shall/may not exceed 16 MHz" nêu một GIỚI HẠN (cue exceed/above/higher... đứng sau "modal + not") nên không tính là phủ định."""
    head = _CLAUSE.split(sentence[:start])[-1]
    toks = re.findall(r"[a-z']+", head.lower())[-window:]
    if len(toks) >= 2 and toks[-1] == "not" and toks[-2] in _MODALS and _LIMIT_WORD.match(sentence, start):
        toks = toks[:-2]
    return any(t in _NEG or t in extra or (t.endswith("n't") and t not in _NEG_KEEP) for t in toks)


_DENIAL = re.compile(r"\bno\s+(?:\w+\s+){0,2}(?:mismatch|conflict|clash|issue|problem|concern)s?\b|nothing to worry|no need to worry|not\s+(?:a|an)\s+(?:issue|problem|concern)"
                     r"|(?:isn't|is not|aren't|are not)\s+(?:a|an)\s+(?:issue|problem|concern)", re.I)
_NEUTRAL_AFTER = re.compile(r"^[-\s]*(?:free\b|check\w*|test\w*|analysis)", re.I)
_NEG_AFTER = re.compile(r"^\W{0,3}(?:none|nil|zero|no\b|not (?:found|detected|present|an issue|a problem|needed|required|necessary)|absent|(?:and|,)?\s*(?:found|see|saw|detected|noticed|spotted)\s+(?:none|nothing|no\b)"
                        r"|(?:\w+\s+){0,2}(?:isn't|is not|aren't|are not|wasn't|won't|will not)\s+(?:something\s+|a\s+|an\s+)?(?:you\s+|we\s+)?(?:need\w*|required|necessary|an issue|a problem))", re.I)


# ------------------------------------------------------------------------------------------------ định danh
def pin_re(pin: str) -> str:
    p = re.escape(pin.strip())
    m = re.fullmatch(r"(?:GPIO|IO)(\d+)", pin.strip(), re.I)
    if m:
        p = rf"(?:GPIO|IO)[-_ ]?{m.group(1)}"
    return rf"(?<![A-Za-z0-9_]){p}(?![A-Za-z0-9])"


_V_NUM = re.compile(r"(\d{1,4}(?:\.\d{1,4})?)\s{0,3}-?\s{0,3}(?:v|volts?)\b", re.I)
_V_3V3 = re.compile(r"\b(\d)v(\d)\b", re.I)


def volts_in(sentence: str) -> set[float]:
    found = {round(float(m.group(1)), 3) for m in _V_NUM.finditer(sentence)}
    found |= {round(float(f"{m.group(1)}.{m.group(2)}"), 3) for m in _V_3V3.finditer(sentence)}
    return found


_CLOCK_ENTITY = {
    "SYSCLK": r"SYSCLK|sys[- ]?clk|system[- ]clock|HCLK|AHB clock|core (?:clock|frequency)|CPU (?:clock|frequency|speed)|clock (?:speed|frequency|tree)|operating frequency|PLLR|PLL R|R1MODE|Range\s*[12]\b|normal mode|boost mode",
    "HCLK": r"SYSCLK|HCLK|AHB clock|system[- ]clock|core clock",
    "PCLK1": r"PCLK1|APB1", "PCLK2": r"PCLK2|APB2",
    "VCO": r"VCO",
    "PLL_IN": r"PLL input|VCO input|PLL source|fPLL_IN|input (?:clock )?(?:to|of|for) the PLL|PLLM|PLL (?:input )?(?:clock|frequency)",
    "HSE": r"HSE|crystal|oscillator|external clock",
    "FLASH_WS": r"wait[- ]?states?|latency|FLASH_ACR|flash",
    "PLLN": r"PLLN|multiplier",
}

# dạng phủ định/né tránh CÓ định danh đi kèm ({E} = mẫu tên chân): "instead of PA8", "not PA8", "don't use PA8 for SCL", "left PB6 out" — dương ngầm cho mã gắn với chân đó
_AVOID_PIN = [r"(?:avoid\w*|never|stay away from)\s+(?:using\s+|use\s+|on\s+|at\s+|the\s+|pin\s+)*{E}",
              r"(?:can(?:'|no)t|cannot|can not|unable to|won't be able to|should not|shouldn't|must not)\s+(?:\w+\s+){0,3}(?:on|use|using|put|place|assign|route|map|move)\s+(?:\w+\s+){0,2}{E}",
              r"(?:don't|do not|never|must not|should not|shouldn't|avoid|stay away from)\s+(?:\w+\s+){0,6}?(?:connect\w*|wire\w*|route\w*|use\w*|put|place\w*|drive\w*|assign\w*|map\w*|feed\w*|tie|hook\w*)\b(?:[^.]|(?<=\d)\.(?=\d)){0,50}{E}",
              r"(?:left|leave|leaving)\s+{E}\s+out", r"(?:since|because)\s+{E}\s+(?:is|carries|hosts|serves|drives)\b"]


# "dùng PC8 thay cho PA8" nói im lặng KHÔNG phải là nêu xung đột (S3); chỉ tính khi cùng câu có mệnh đề LÝ DO
_AVOID_SILENT = [r"(?:instead of|rather than|away from|other than|except|unlike|not)\s+(?:using\s+|use\s+|on\s+|at\s+|the\s+|pin\s+)*{E}"]
_REASON = re.compile(r"\b(?:because|since|due to|owing to|which\s+(?:is|are|has|have|would|can|cannot|can't|doesn't|does not)|that\s+(?:is|are|has|have|would|cannot|can't)|to avoid|as (?:it|that|the|this|those)\b|for (?:this|that|these) reason)", re.I)

# ------------------------------------------------------------------------------------------------ từ vựng theo họ mã
# soft: có thể bị phủ định ("no conflict"); hard: tự mang nghĩa dương ("cannot share", "is not 5 V tolerant")
_CUES = {
    "PIN_CONFLICT": {
        "soft": [r"conflict\w*", r"clash\w*", r"collid\w+", r"(?:is|are)\s+(?:currently\s+)?(?:used|taken|needed|occupied|busy)\s+(?:by|for|as)\b(?:[^.]|(?<=\d)\.(?=\d)){0,60}\b(?:so|therefore|thus|hence|instead)\b",
                 r"(?:break|clobber|override|overwrite|steal|hijack)\w*\s+(?:the\s+)?(?:\w+\s+){0,2}(?:PWM|output|function|signal|pin)\w*", r"collision\w*", r"contention", r"contend\w*", r"overlap\w*", r"double[- ]?book\w*", r"mutually exclusive",
                 r"already\s+(?:\w+\s+)?(?:in use|use[sd]?|taken|tak\w+|assign\w+|alloc\w+|occup\w+|claim\w+|reserv\w+|busy|configur\w+|mapp\w+|driv\w+|own\w+|carr\w+|bound|dedicat\w+|committed)",
                 r"(?:taken|occupied|claimed|reserved|busy|unavailable|not available)\b", r"in use\b", r"no longer free", r"(?:isn't|is not|aren't|are not)\s+free\b",
                 r"(?:being|currently|presently)\s+(?:used|assigned|allocated|mapped|taken|occupied|driven)\s+(?:by|to|for|as)\b", r"has been\s+(?:assigned|allocated|mapped|given)\s+to\b",
                 r"already\s+(?:the\s+|a\s+)?\w*(?:USART|UART|I2C|SPI|TIM|ADC|CAN|SAI|COMP)\w*", r"\bshar\w+\s+(?:the\s+|this\s+|that\s+)?(?:pin\s+)?(?:P[A-G]\d+\s+)?with\b",
                 r"compet\w+\s+for", r"(?:two|multiple)\s+owners|double[- ]?assign\w*|over[- ]?subscri\w+", r"\bshared\s+(?:between|by|among)\b",
                 r"already\s+(?:the\s+|a\s+|an\s+|your\s+)?(?:\w+\s+){0,2}(?:PWM|output|input|TX|RX|SCL|SDA|CH\d)\b"],
        "hard": [r"(?:can(?:'|no)t|cannot|can not|unable to)\s+(?:[\w/]+\s+){0,8}?(?:share|be shared|both|also|simultaneously|coexist|at once|together|at the same time)",
                 r"(?:can(?:'|no)t|cannot)\s+(?:also\s+)?(?:carry|host|take|serve)\b", r"(?:only one|one and only one)\s+(?:\w+\s+){0,2}(?:function|signal|peripheral|owner|use)", r"only\s+(?:carry|host|serve|do|have)\s+one\b",
                 r"(?:can(?:'|no)t|cannot)\s+(?:\w+\s+){0,2}(?:use|take|have|get)\s+(?:it|that pin|the same pin)\b",
                 r"\bboth\s+[\w/]+\s+and\s+[\w/]+\s+(?:map|are mapped|want|need|use|share|claim|require)\b", r"same pin", r"at the same time"],
        "avoid": _AVOID_PIN,
    },
    "NO_SUCH_AF": {
        "soft": [r"unavailable", r"(?:isn't|is not|aren't|are not)\s+(?:\w+\s+){0,2}(?:valid|supported|available|routable|exposed)",
                 r"(?:belong|map|are assigned|is assigned)s?\s+to\s+(?:the\s+)?(?:USART|UART|LPUART|I2C|SPI)\d", r"\blacks?\b", r"cannot\s+function\s+as", r"(?:isn't|is not|aren't|are not)\s+(?:connected|attached|tied)\s+to",
                 r"cannot\s+be\s+placed", r"(?:USART|UART|I2C|SPI)\d\W?s\s+pins?",
                 r"(?:rout|connect|map|belong|wire)\w*\s+(?:[\w/]+\s+){0,5}to\s+(?:the\s+)?(?:USART|UART|LPUART|I2C|SPI)\d"],
        "hard": [r"not\s+(?:available|supported|routed|routable|mapped|wired|connected|present|exposed|possible|valid|carried|offered|provided)\b",
                 r"(?:does(?:n't| not)|do(?:es)? not|doesn't|cannot|can't|can not)\s+(?:\w+\s+){0,2}(?:have|support|carry|provide|offer|expose|map|route|host|include|bring out|exist)",
                 r"no\s+(?:such\s+)?(?:[\w-]+\s+){0,2}(?:alternate|alternative)[- ]?(?:function|mapping)s?", r"no\s+(?:I2C|USART|UART|SPI|TIM)\d*\w*\s+(?:function|mapping|AF|alternate)", r"no\s+(?:AF\d*|alternate function)\s+(?:for|on|available|mapping|slot|option|is)\b",
                 r"(?:can(?:'|no)t|cannot|can not)\s+be\s+(?:(?:used|configured)\s+(?:as|for)\s+)?(?:the\s+)?\w*(?:I2C|USART|UART|SPI|TIM)\w*",
                 r"(?:isn't|is not|aren't|are not)\s+(?:capable of|an?\s+\w*(?:I2C|USART|UART|SPI|TIM)\w*\s+pin|the right pin for)",
                 r"(?:isn't|is not|aren't|are not)\s+(?:an?\s+|the\s+)?\w*(?:I2C|USART|UART|SPI)\d*\w*", r"\bnot\s+\w*(?:I2C|USART|UART|SPI)\d*\w*\s+pins?\b", r"(?:wrong|incorrect|invalid)\s+pin", r"only\s+(?:available\s+)?(?:on|at|via|found on|exists on)", r"(?:doesn't|does not) exist"],
        "avoid": _AVOID_PIN,
    },
    "INPUT_ONLY": {
        "soft": [r"input[- ]?only", r"read[- ]?only pin"],
        "hard": [r"only\s+(?:be\s+)?(?:used\s+)?(?:as\s+)?(?:an?\s+)?inputs?\b", r"no\s+output\s+(?:driver|buffer|stage|capability)",
                 r"(?:cannot|can't|can not|isn't able to|is not able to|unable to)\s+(?:be\s+)?(?:used\s+|configured\s+|set\s+)?(?:as\s+|to\s+)?(?:an?\s+)?(?:output|drive|source|sink)",
                 r"not\s+(?:be\s+)?(?:used\s+)?as\s+(?:an?\s+)?output", r"\boutput\b(?:[^.]|(?<=\d)\.(?=\d)){0,25}(?:isn't|is not|not|impossible)\s+(?:possible|supported|allowed|available)",
                 r"can\s+only\s+be\s+(?:read|sampled|used)"],
        "avoid": _AVOID_PIN,
    },
    "LEVEL_MISMATCH": {
        "soft": [r"level[- ]?shift\w*", r"level[- ]?(?:translat|convert)\w*", r"voltage[- ]?(?:translat|shift|convert)\w*", r"translator", r"mismatch\w*", r"translate\s+the\s+(?:logic\s+)?levels?",
                 r"different\s+(?:voltage|logic|supply|I/?O)\s*(?:level|domain|rail)s?", r"different\s+(?:voltage\s+|logic\s+)?domains?", r"voltage domains?", r"bidirectional shifter"],
        "weak": [r"over[- ]?volt\w*", r"exceed\w*", r"damag\w+", r"too high", r"above\s+(?:the\s+)?(?:max\w*|abs\w*|rated)"],
        "hard": [r"incompatib\w+", r"(?:not|isn't|aren't|wasn't|weren't)\s+(?:\w+\s+){0,2}compatible", r"(?:cannot|can't|can not|should not|shouldn't|must not|mustn't|never|don't|do not)\s+(?:\w+\s+){0,3}(?:directly|straight|connect\w*|wire\w*)",
                 r"not\s+(?:safe|ok|okay)\s+to\s+(?:connect|wire|drive)"],
        "avoid": [],
    },
    "NOT_5V_TOLERANT": {
        "soft": [r"over[- ]?volt\w*", r"exceed\w*", r"damag\w+", r"level[- ]?shift\w*", r"(?:voltage|resistor)\s+divider", r"TT(?:_\w+)?\b",
                 r"max(?:imum)?\s+(?:input\s+)?voltage", r"abs\w*\s+max\w*", r"\bdividers?\b",
                 r"(?:limited|restricted|clamped)\s+to\b(?:[^.]|(?<=\d)\.(?=\d)){0,30}", r"VDD\s*\+\s*0\.3"],
        "hard": [r"(?:can(?:'|no)t|cannot|can not|doesn't|does not|isn't able to)\s+(?:['\w]+\s+){0,3}(?:accept|take|handle|tolerate|withstand|survive|cope with)\s+(?:['\w]+\s+){0,3}5\s?V",
                 r"only\s+(?:rated|specified|good|safe)\s+(?:for|to|up to)\s+(?:about\s+)?3\.\d", r"only\s+(?:about\s+)?[34](?:\.\d)?\s*V[- ]?tolerant", r"tops?\s+out\s+at\s+(?:about\s+)?[34](?:\.\d)?\s*V", r"(?:doesn't|does not)\s+qualify", r"not\s+(?:\w+\s+){0,3}tolerant", r"non[- ]?(?:5\s?v[- ]?)?tolerant", r"non[- ]?FT\b", r"not\s+(?:an?\s+)?FT\b", r"(?:isn't|is not|aren't|are not)\s+(?:5\s?v|FT)",
                 r"only\s+(?:take|accept|handle|tolerate|withstand)s?\s+(?:up to\s+)?(?:about\s+)?3\.\d", r"(?:no|without)\s+5\s?v\s+tolerance"],
        "avoid": _AVOID_PIN,
    },
    "TIMER_SHARED": {
        "soft": [r"conflict\w*", r"shar(?:e|es|ed|ing)\s+(?:the\s+|a\s+|one\s+|its\s+|their\s+)?(?:same\s+|single\s+|common\s+)?(?:counter|time[- ]?base|ARR|auto[- ]?reload|period|frequency|PSC|prescaler)",
                 r"(?:counter|time[- ]?base|ARR|auto[- ]?reload|period|frequency|PSC|prescaler)\s+(?:is|are)\s+shared",
                 r"common\s+(?:ARR|PSC|counter|time[- ]?base|frequency|period|prescaler)",
                 r"same\s+(?:timer|counter|time[- ]?base|(?:PWM\s+)?frequency|(?:PWM\s+)?period|ARR|auto[- ]?reload|clock source)",
                 r"single\s+(?:[\w-]+\s+){0,2}(?:frequency|period|counter|time[- ]?base|auto[- ]?reload|ARR|prescaler|PSC)",
                 r"(?:own|separate|independent|dedicated)\s+(?:[\w-]+\s+)?(?:time[- ]?base|counter|timer|ARR|auto[- ]?reload|period|frequency)",
                 r"one\s+(?:single\s+)?(?:frequency|period|time[- ]?base|auto[- ]?reload|ARR|counter)",
                 r"inherit\w*\s+(?:the\s+)?(?:\d+\s*\w+\s+)?(?:frequency|period)", r"per[- ]timer", r"common\s+to\s+(?:all|every|both)",
                 r"(?:ARR|PSC|prescaler|auto[- ]?reload|period|frequency)\b(?:[^.]|(?<=\d)\.(?=\d)){0,40}\b(?:every|all|both)\s+(?:the\s+)?channels?\b"],
        "hard": [r"(?:cannot|can't|can not|unable to)\s+(?:\w+\s+){0,3}(?:different|independent|separate|own)\s+(?:frequenc\w+|periods?|PSC|ARR)",
                 r"(?:can(?:'|no)t|cannot|can not)\s+coexist", r"(?:can(?:'|no)t|cannot|can not)\s+do\s+both",
                 r"can\s+only\s+(?:have|use|run|generate|output)\s+(?:one|a single)\b",
                 r"different\s+(?:PWM\s+)?(?:frequencies|periods)\s+(?:require|need)\s+(?:different|separate)\s+timers?",
                 r"must\s+(?:\w+\s+){0,3}same\s+(?:PWM\s+)?(?:frequency|period)"],
        "avoid": [],
    },
    "CLOCK_LIMIT": {
        "soft": [r"exceed\w*", r"above\s+(?:the\s+)?(?:allowed|permitted|rated|supported|specified|max\w*|limit|ceiling|170|150|344|26|16\b)", r"beyond", r"over\s+(?:the\s+)?(?:max\w*|limit|ceiling|170)", r"too\s+(?:high|fast)",
                 r"higher than (?:the\s+)?(?:max\w*|170)", r"(?:max(?:imum)?|highest|limit\w*|capped|ceiling)\b(?:[^.]|(?<=\d)\.(?=\d)){0,60}\d{2,3}(?:\.\d+)?\s*MHz", r"(?:specified|rated|guaranteed)\s+(?:only\s+)?(?:up\s+)?(?:to|at|for)\s+\d", r"out of (?:range|spec\w*)", r"violat\w+", r"outside\s+(?:the\s+)?(?:allowed|permitted|valid|supported|specified)"],
        "hard": [r"not\s+(?:possible|supported|allowed|achievable|reachable|valid|permitted)", r"incompatible", r"(?:isn't|is not)\s+valid",
                 r"caps?\s+(?:the\s+)?(?:core|clock|system clock)\s+at", r"tops?\s+out\s+at", r"top\s+speed", r"(?:can(?:'|no)t|cannot)\s+coexist",
                 r"only\s+(?:allows?|permits?|supports?|good for|rated|valid for|specified for)\s+(?:\w+\s+){0,3}(?:up to\s+)?\d{2,3}", r"\d{2,3}(?:\.\d+)?\s*MHz\s+or\s+(?:lower|less|below|under|slower)",
                 r"(?:at most|no more than|no higher than|not\s+(?:be\s+)?(?:higher|more|greater|faster)\s+than)\s+(?:\w+\s+){0,2}\d{2,3}", r"must\s+(?:stay|remain|be|lie|fall)\s+(?:with)?in\s+(?:the\s+)?(?:range\s+)?(?:of\s+)?\d",
                 r"can\s+only\s+(?:run|operate|work|go|be clocked)", r"(?:cannot|can't|can not)\s+(?:be\s+)?(?:set|reach|run|go|operate|exceed|use|be)",
                 r"\d{2,3}(?:\.\d+)?\s*MHz,?\s+(?:is\s+|as\s+)?(?:the\s+)?(?:max\w*|highest|limit\w*|ceiling|top|fastest)",
                 r"(?:highest|fastest|max(?:imum)?)\b\s+(?:[\w.-]+\s+){0,4}?(?:supports?|allows?|permits?|handles?|accepts?|supported|allowed)"],
        "avoid": [r"(?:clamped (?:to|from)|capped (?:to|at))\s+(?:\w+\s+){0,2}\d{2,3}(?:\.\d+)?\s*MHz"],
        "avoid_reasoned": [r"(?:rather than|instead of|reduced from|lowered from|scaled back from)\s+(?:\w+\s+){0,2}\d{2,3}(?:\.\d+)?\s*MHz"],
        # nêu thẳng con số MHz nên không cần từ chỉ khối clock trong câu ("The STM32G474 cannot run at 200 MHz")
        "free": [r"(?:cannot|can't|can not|unable to|won't)\s+(?:\w+\s+){0,3}(?:run|operate|be clocked|clock|reach|go|work)\s+(?:\w+\s+){0,2}(?:at|above|beyond|faster than|past)\s+\d{3}(?:\.\d+)?\s*MHz",
                 r"tops?\s+out\s+at\s+\d{3}", r"(?:limited|capped|restricted)\s+to\s+\d{3}(?:\.\d+)?\s*MHz", r"only\s+(?:run|operate|work|go)\s+(?:\w+\s+){0,2}(?:up to|at)\s+\d{3}", r"(?:at most|no more than)\s+\d{3}(?:\.\d+)?\s*MHz",
                 r"(?:can(?:'|no)t|cannot|unable to)\s+(?:\w+\s+){0,2}(?:set|use|select|choose|configure|program|reach|run)\s+(?:the\s+)?(?:\w+\s+){0,2}\d{3}(?:\.\d+)?\s*MHz", r"only\s+rated\s+(?:up\s+)?to\s+\d{3}"],
    },
}
_FAMILY_ALIASES = {"CLOCK_LIMIT": ("SYSCLK", "HCLK", "PCLK1", "PCLK2", "VCO", "PLL_IN", "HSE", "FLASH_WS", "PLLN")}


_WB = r"\b(?:"          # mọi mẫu từ vựng được bọc \b(?:…) để không khớp giữa từ ("own the counter" trong "down the counter")


def parse_code(code: str) -> tuple[str, str]:
    family, _, arg = code.partition(":")
    return family.strip().upper(), arg.strip()


def _entities(family: str, arg: str) -> list[re.Pattern]:
    """Danh sách mẫu định danh; MỌI mẫu phải khớp trong câu (voltage xử lý riêng)."""
    if family in ("PIN_CONFLICT", "NO_SUCH_AF", "INPUT_ONLY", "NOT_5V_TOLERANT"):
        return [re.compile(pin_re(arg), re.I)]
    if family == "TIMER_SHARED":
        return [re.compile(rf"(?<![A-Za-z0-9]){re.escape(arg)}(?![0-9])", re.I)]
    if family == "CLOCK_LIMIT":
        return [re.compile(rf"(?<![A-Za-z0-9_])(?:{_CLOCK_ENTITY.get(arg.upper(), re.escape(arg))})(?![A-Za-z0-9])", re.I)]
    return []


def _rails(arg: str) -> set[float]:
    """'1.8V-3.3V' -> {1.8, 3.3}."""
    return {round(float(x), 3) for x in re.findall(r"(\d+(?:\.\d+)?)\s*V", arg, re.I)}


def match_sentence(sentence: str, code: str) -> dict | None:
    """Câu này có nêu xung đột `code` không? -> {"cue", "kind"} hoặc None."""
    family, arg = parse_code(code)
    spec = _CUES.get(family)
    if spec is None:
        raise ValueError(f"unknown conflict family {family!r} in {code!r}")
    for pat in spec.get("free", []):
        m = re.search(_WB + pat + ")", sentence, re.I)
        if m and not negated(sentence, m.start()):
            return {"cue": m.group(0), "kind": "free"}
    weak_ok = True
    if family == "LEVEL_MISMATCH":
        need, have = _rails(arg), volts_in(sentence)
        if not need or not need & have:
            return None                                          # câu phải nêu ít nhất một trong hai mức áp
        weak_ok = need <= have                                   # từ vựng yếu (exceed, damage...) cần nêu đủ cả hai mức
        ents = []
    else:
        ents = _entities(family, arg)
        if not all(e.search(sentence) for e in ents):
            return None
    for kind in ("hard", "soft", "weak", "avoid", "avoid_reasoned"):
        if kind == "weak" and not weak_ok:
            continue
        if kind == "avoid_reasoned" and not _REASON.search(sentence):
            continue
        for pat in spec.get(kind, []):
            if kind == "avoid_reasoned":
                m = re.search(pat, sentence, re.I)
                if m:
                    return {"cue": m.group(0), "kind": "avoid"}
                continue
            if kind == "avoid":
                for e in ents:
                    for m in re.finditer(pat.replace("{E}", e.pattern), sentence, re.I):
                        return {"cue": m.group(0), "kind": "avoid"}
                    if _REASON.search(sentence):
                        for pat2 in _AVOID_SILENT if family != "CLOCK_LIMIT" else []:
                            for m in re.finditer(pat2.replace("{E}", e.pattern), sentence, re.I):
                                return {"cue": m.group(0), "kind": "avoid"}
                continue
            for m in re.finditer(_WB + pat + ")", sentence, re.I):
                if kind in ("soft", "weak"):
                    if negated(sentence, m.start()) or _NEG_AFTER.match(sentence[m.end():]) or _DENIAL.search(sentence):
                        continue
                    if family == "NOT_5V_TOLERANT" and re.search(pin_re(arg) + r"(?:[^.]|(?<=\d)\.(?=\d)){0,25}\b(?:is|are)\s+(?:also\s+)?5\s?V[- ]?tolerant", sentence, re.I):
                        continue                                         # "PC5 (TT_a) is 5 V tolerant": khẳng định NGƯỢC lại
                    if m.group(0).lower().startswith("conflict") and _NEUTRAL_AFTER.match(sentence[m.end():]):
                        continue
                return {"cue": m.group(0), "kind": kind}
    return None


def detect(text: str, code: str, window: int = 1) -> dict | None:
    """Câu đầu tiên của `text` nêu xung đột `code` -> {"sentence", "cue", "kind"}; không có -> None.
    `window` = số câu liên tiếp được xét như một đơn vị (mặc định 1 = D25 "cùng câu"; >1 chỉ để đo giả định "nếu nới", không dùng để chấm)."""
    sents = sentences(text)
    for i in range(len(sents)):
        unit = " ".join(sents[max(0, i - window + 1): i + 1])
        hit = match_sentence(unit, code)
        if hit:
            return {"sentence": unit, **hit}
    return None


# ------------------------------------------------------------------------------------------------ must_not: unsafe_connection
_UNSAFE_SOFT = [r"(?:connect|wire|attach|hook|tie|join|plug|link|solder)\w*\b(?:[^.]|(?<=\d)\.(?=\d)){0,40}\bdirectly", r"\bdirectly\s+(?:connect|wire|attach|to|into|on|with)",
                r"\bdirectly\s+compatible", r"\bstraight\s+(?:to|into|onto|on|through)\b", r"\bas[- ](?:is|it is)\b", r"\bjust\s+(?:connect|wire|plug|join)",
                r"\b(?:fine|ok|okay|safe)\s+(?:on|to connect|to wire)\b", r"\bno\s+(?:need\s+for\s+)?(?:an?\s+|any\s+)?(?:divider|resistor divider|conversion)"]
_UNSAFE_HARD = [r"\bno\s+need\s+for\s+(?:an?\s+|any\s+)?(?:\w+\s+(?:or|and)\s+)*(?:level[- ]?shift\w*|translat\w+|divider|shifters?|resistors?)",
                r"\bno\s+(?:need\s+for\s+)?(?:an?\s+)?(?:external\s+)?level[- ]?(?:shift|translat)\w*(?:\s+(?:is\s+)?(?:needed|required|necessary))?",
                r"level[- ]?(?:shift|translat)\w*\s+(?:is\s+|are\s+)?(?:not|isn't|aren't)\s+(?:strictly\s+|really\s+|actually\s+)?(?:needed|required|necessary)", r"(?:not|isn't|aren't)\s+(?:needed|required|necessary)(?:[^.]|(?<=\d)\.(?=\d)){0,20}level[- ]?shift",
                r"\b(?:don't|do not|doesn't|does not)\s+(?:really\s+|actually\s+)?(?:need|require)\s+(?:an?\s+|any\s+)?(?:external\s+)?(?:level[- ]?shift\w*|translat\w+|divider|shifters?|resistors?|conversion)",
                r"level[- ]?(?:shift|translat)\w*\s+(?:is|are)\s+optional",
                r"level[- ]?(?:shift|translat)\w*\s+(?:is\s+|would be\s+)?(?:overkill|unnecessary|superfluous)",
                r"(?:skip|omit|leave out|drop|forget|do without|go without)\s+(?:the\s+|a\s+|any\s+)?(?:[\w-]+\s+){0,2}(?:level[- ]?shift\w*|translat\w+|divider|resistors?|shifters?)",
                r"\bno\s+(?:extra|additional|external)\s+(?:parts?|components?|circuitry|hardware)\s+(?:is |are )?(?:needed|required|necessary)",
                r"5\s?v[- ]?tolerant(?:[^.]|(?<=\d)\.(?=\d)){0,20}\bso\b(?:[^.]|(?<=\d)\.(?=\d)){0,30}directly"]
# nghĩa tương đương nhưng thường nằm trong câu ĐIỀU KIỆN/cảnh báo ("Without a level shifter the MCU would overdrive...") nên bị bộ lọc cảnh báo chặn như cue mềm
_UNSAFE_COND = [r"\bwithout\s+(?:any\s+)?(?:level[- ]?shift\w*|translat\w+|extra\s+(?:components?|parts?|hardware))", r"\bno\s+(?:\w+\s+){0,2}(?:resistors?|shifting hardware|shifters?)\s+(?:in between|between)"]
_SAME_LEVEL = re.compile(r"\b(?:both|same|equal|identical|matching|match(?:es)?)\b", re.I)
_UNSAFE_NEG = {"instead", "rather", "unlike", "cannot", "can't", "dont", "don't", "avoid", "shouldn't", "mustn't", "unsafe", "unwise", "mistake", "wrong", "foolish", "wouldn't", "won't"}
_UNSAFE_WARN = re.compile(r"overstress\w*|damag\w+|exceed\w*|\brisk\w*|unsafe|danger\w*|\bharm\w*|burn\w*|destroy\w*|\bfry\b|latch-?up|over-?volt\w*|overdriv\w*|not safe|wouldn't|shouldn't|avoid\w*|not recommended|\bwrong\b|incorrect|bad idea|mistake|violat\w+|absolute max\w*|prohibit\w*|not allowed|forbidden", re.I)
_SHIFTER = re.compile(r"level[- ]?shift\w*|\bshifters?\b|translator|PCA9306|TXS0\d+|TXB0\d+", re.I)
_PIN_TOKEN = re.compile(r"\bP[A-G]\d{1,2}\b|\bGPIO\d+\b", re.I)


def _cue_pin(sentence: str, m: re.Match) -> str | None:
    """Chân mà cue nối-thẳng đang nói tới: chân đầu tiên SAU cue ("directly to PA3"), nếu không có thì chân cuối cùng TRƯỚC cue."""
    pins = list(_PIN_TOKEN.finditer(sentence))
    after = [p for p in pins if p.start() >= m.end()]
    before = [p for p in pins if p.end() <= m.start()]
    return (after[0] if after else before[-1] if before else None) and (after[0] if after else before[-1]).group(0)


_SUPPLY_ONLY = re.compile(r"pull[- ]?ups?|resistors?|capacitors?|decoupl\w+|\bsupply\b|\brail\b|VDDIO|\bVDD\b", re.I)
_SIGNAL_WORDS = re.compile(r"sensor|device|module|BME|MCU|STM32|SDA|SCL|\bpins?\b|signal|\blines?\b|GPS|\bTX\b|\bRX\b|\bP[A-G]\d+\b", re.I)


def detect_unsafe_connection(text: str, pin: str | None = None, rails: list[float] | None = None) -> dict | None:
    """Câu khuyến nghị nối TRỰC TIẾP / "không cần level shifter" ở miền không tương thích.
    `pin`: lời khuyên phải nói về chân đó — câu có tên chân, hoặc câu không nêu chân nào và câu liền trước nêu chân đó (nối thẳng vào chân FT KHÁC là an toàn). `rails`: các mức áp trong câu + câu
    liền trước phải đủ cả hai, hoặc không có mức áp nào (khi đó cue — "no level shifter is needed", "connect directly" — được hiểu theo ngữ cảnh lệch áp của task); nêu RIÊNG một mức kèm
    "both/same" ("both are 3V3 devices") thì bỏ qua; chỉ nêu MỘT mức duy nhất của task ("connect the sensor directly to the 3.3 V MCU") cũng bỏ qua, còn mức lạ kèm ("1.8 V sensor … 5 V tolerant") thì vẫn xét. Cue mềm bị loại nếu cùng câu có lời cảnh báo không bị phủ định ("directly ... can overstress the inputs") hoặc nối vào level shifter."""
    need = {round(float(r), 3) for r in rails or []}
    prev = ""
    for s in sentences(text):
        context = f"{prev} {s}"
        prev_s, prev = prev, s
        if pin:
            target = pin_re(pin)
            if not re.search(target, s, re.I) and (_PIN_TOKEN.search(s) or not re.search(target, prev_s, re.I)):
                continue                                                   # câu nói về chân KHÁC (hoặc không liên quan chân đang xét)
        have = volts_in(context)
        if need and have and not need <= have and (have <= need or _SAME_LEVEL.search(context)):
            continue                                                       # "both are 3V3 devices": không phải miền lệch áp đang xét
        if pin and re.search(r"(?:unlike|instead of|rather than|other than|not|except|than|away from|off)\s+(?:the\s+|pin\s+)*" + pin_re(pin), s, re.I):
            continue                                                       # chân đang xét được nêu để LOẠI TRỪ ("…directly to PA15, unlike PA3")
        for pat in _UNSAFE_HARD:
            m = re.search(_WB + pat + ")", s, re.I)
            if m and not negated(s, m.start(), extra=_UNSAFE_NEG, window=8):
                cp = _cue_pin(s, m) if pin else None
                if cp and cp.upper() != pin.upper():
                    continue                                               # "…moved RX to PA15, as PA15 is FT, there is no need for a level shifter": nói về chân khác
                return {"sentence": s, "cue": m.group(0)}
        if _SUPPLY_ONLY.search(s) and not _SIGNAL_WORDS.search(s):
            continue                                                       # "connect the pull-ups directly to the 1.8 V rail": nối nguồn, không phải nối tín hiệu
        if any(not negated(s, w.start()) for w in _UNSAFE_WARN.finditer(s)):
            continue                                                       # câu cảnh báo ("joining directly can overstress the inputs"), không phải khuyến nghị
        if any(not negated(s, w.start(), window=8) for w in _SHIFTER.finditer(s)) and not any(re.search(pat, s, re.I) for pat in _UNSAFE_COND):
            continue                                                       # "…directly to the shifter's high-voltage side": nối vào level shifter là cách làm ĐÚNG
        for pat in _UNSAFE_COND + _UNSAFE_SOFT:
            for m in re.finditer(_WB + pat + ")", s, re.I):
                if negated(s, m.start(), extra=_UNSAFE_NEG, window=8) or re.search(r"\b(?:do|does|did|should|must|can|could|would|will)\s+(?:not|n't)\b", s[: m.start()][-30:], re.I):
                    continue
                if pin:
                    cp = _cue_pin(s, m)
                    if cp and cp.upper() != pin.upper():
                        continue                                           # lời khuyên nối thẳng nói về chân KHÁC ("…moved RX to PA10, where it can be connected directly")
                return {"sentence": s, "cue": m.group(0)}
    return None
