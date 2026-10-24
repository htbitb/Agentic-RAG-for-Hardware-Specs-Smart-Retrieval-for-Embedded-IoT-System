#!/usr/bin/env python3
"""Vẽ sơ đồ kiến trúc kiểu draw.io bằng Pillow ở độ phân giải cao (2600x1220)
với đường nối vuông góc (orthogonal connectors) đi trong hành lang, không cắt ngang chữ,
xuất ra cả PNG và PDF để nhúng vào LaTeX và PowerPoint.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
ASSETS.mkdir(parents=True, exist_ok=True)

W, H = 2600, 1240
FONT_REG = "/System/Library/Fonts/Supplemental/Arial.ttf"
FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
FONT_ITALIC = "/System/Library/Fonts/Supplemental/Arial Italic.ttf"
FONT_MONO = "/System/Library/Fonts/Supplemental/Courier New Bold.ttf"

def fnt(size, bold=False, italic=False, mono=False):
    path = FONT_MONO if mono else (FONT_BOLD if bold else (FONT_ITALIC if italic else FONT_REG))
    return ImageFont.truetype(path, size)

# Bảng màu chuẩn draw.io engineering
C = {
    "bg": "#FFFFFF",
    "grid": "#F1F5F9",
    "border": "#CBD5E1",
    "navy": "#164B78",
    "navy_fill": "#EBF3FA",
    "teal": "#146C60",
    "teal_fill": "#E6F4F1",
    "amber": "#B45309",
    "amber_fill": "#FEF6E7",
    "slate": "#475569",
    "slate_fill": "#F8FAFC",
    "ink": "#0F172A",
    "sub": "#334155",
    "muted": "#64748B",
    "white": "#FFFFFF",
}

base = Image.new("RGBA", (W, H), C["bg"])
draw = ImageDraw.Draw(base)

# Lưới nền draw.io
for x in range(20, W - 20, 28):
    draw.line([(x, 16), (x, H - 16)], fill=C["grid"], width=1)
for y in range(16, H - 16, 28):
    draw.line([(16, y), (W - 16, y)], fill=C["grid"], width=1)
draw.rounded_rectangle((12, 12, W - 12, H - 12), radius=16, outline=C["border"], width=3)

def shadow_card(x1, y1, x2, y2, radius=14, fill="#FFFFFF", outline="#164B78", width=3, dashed=False):
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sh)
    sd.rounded_rectangle((x1 + 3, y1 + 5, x2 + 3, y2 + 5), radius=radius, fill=(15, 23, 42, 22))
    sh = sh.filter(ImageFilter.GaussianBlur(5))
    base.alpha_composite(sh)
    d = ImageDraw.Draw(base)
    d.rounded_rectangle((x1, y1, x2, y2), radius=radius, fill=fill, outline=None if dashed else outline, width=width)
    if dashed:
        dash_rect(d, x1, y1, x2, y2, outline, width=width, dash=14, gap=8, radius=radius)

def dash_line(d, p1, p2, color, width=3, dash=12, gap=8):
    x1, y1 = p1
    x2, y2 = p2
    dx, dy = x2 - x1, y2 - y1
    dist = max(1, int((dx * dx + dy * dy) ** 0.5))
    step = dash + gap
    for s in range(0, dist, step):
        e = min(dist, s + dash)
        sx, sy = x1 + dx * s / dist, y1 + dy * s / dist
        ex, ey = x1 + dx * e / dist, y1 + dy * e / dist
        d.line([(sx, sy), (ex, ey)], fill=color, width=width)

def dash_rect(d, x1, y1, x2, y2, color, width=3, dash=12, gap=8, radius=10):
    dash_line(d, (x1 + radius, y1), (x2 - radius, y1), color, width, dash, gap)
    dash_line(d, (x2, y1 + radius), (x2, y2 - radius), color, width, dash, gap)
    dash_line(d, (x2 - radius, y2), (x1 + radius, y2), color, width, dash, gap)
    dash_line(d, (x1, y2 - radius), (x1, y1 + radius), color, width, dash, gap)

def lane_container(x1, y1, x2, y2, title, color):
    shadow_card(x1, y1, x2, y2, radius=14, fill="#FFFFFF", outline=color, width=3)
    d = ImageDraw.Draw(base)
    d.rounded_rectangle((x1, y1, x2, y1 + 54), radius=14, fill=color)
    d.rectangle((x1, y1 + 28, x2, y1 + 54), fill=color)
    d.text(((x1 + x2) / 2, y1 + 27), title, font=fnt(24, bold=True), fill="#FFFFFF", anchor="mm")

def node_box(x1, y1, x2, y2, title, lines, fill=C["navy_fill"], outline=C["navy"], badge=None, badge_color=None, dashed=False, footer=None):
    shadow_card(x1, y1, x2, y2, radius=11, fill=fill, outline=outline, width=3, dashed=dashed)
    d = ImageDraw.Draw(base)
    ty = y1 + 24
    if badge:
        bc = badge_color or outline
        bw = d.textlength(badge, font=fnt(16, bold=True)) + 22
        d.rounded_rectangle((x1 + 16, y1 + 12, x1 + 16 + bw, y1 + 40), radius=6, fill=bc)
        d.text((x1 + 16 + bw / 2, y1 + 26), badge, font=fnt(16, bold=True), fill="#FFFFFF", anchor="mm")
        d.text((x1 + 26 + bw, y1 + 26), title, font=fnt(22, bold=True), fill=C["ink"], anchor="lm")
        ty = y1 + 58
    else:
        d.text(((x1 + x2) / 2, y1 + 25), title, font=fnt(22, bold=True), fill=outline if dashed else C["ink"], anchor="mm")
        d.line([(x1 + 14, y1 + 44), (x2 - 14, y1 + 44)], fill=outline, width=1)
        ty = y1 + 64
    for line in lines:
        if badge:
            d.text((x1 + 18, ty), line, font=fnt(19), fill=C["sub"], anchor="lm")
        else:
            d.text(((x1 + x2) / 2, ty), line, font=fnt(19), fill=C["sub"], anchor="mm")
        ty += 27
    if footer:
        d.text(((x1 + x2) / 2, y2 - 17), footer, font=fnt(17, italic=True), fill=C["muted"], anchor="mm")

def draw_arrow_head(d, p_from, p_to, color, size=11):
    x1, y1 = p_from
    x2, y2 = p_to
    dx, dy = x2 - x1, y2 - y1
    if abs(dx) >= abs(dy):
        s = 1 if dx >= 0 else -1
        pts = [(x2, y2), (x2 - s * size * 1.35, y2 - size * 0.75), (x2 - s * size * 1.35, y2 + size * 0.75)]
    else:
        s = 1 if dy >= 0 else -1
        pts = [(x2, y2), (x2 - size * 0.75, y2 - s * size * 1.35), (x2 + size * 0.75, y2 - s * size * 1.35)]
    d.polygon(pts, fill=color)

def ortho_arrow(pts, color=C["navy"], width=4, both=False, dashed=False, label=None, label_pos=None):
    d = ImageDraw.Draw(base)
    for a, b in zip(pts[:-1], pts[1:]):
        if dashed:
            dash_line(d, a, b, color, width=width, dash=10, gap=6)
        else:
            d.line([a, b], fill=color, width=width)
    draw_arrow_head(d, pts[-2], pts[-1], color)
    if both:
        draw_arrow_head(d, pts[1], pts[0], color)
    if label and label_pos:
        lx, ly = label_pos
        f = fnt(17, bold=True)
        tw = d.textlength(label, font=f)
        d.rounded_rectangle((lx - tw / 2 - 8, ly - 13, lx + tw / 2 + 8, ly + 13), radius=5, fill="#FFFFFF", outline=color, width=2)
        d.text((lx, ly), label, font=f, fill=color, anchor="mm")

# 0. Top Legend Bar
shadow_card(34, 24, W - 34, 92, radius=10, fill=C["slate_fill"], outline=C["border"], width=2)
draw = ImageDraw.Draw(base)
draw.text((58, 58), "Kiến trúc Hardware Co-Design Agent v2 (Bản cài đặt S3@P5)", font=fnt(26, bold=True), fill=C["navy"], anchor="lm")

# Legend items
draw.rounded_rectangle((1140, 42, 1178, 74), radius=5, fill=C["navy_fill"], outline=C["navy"], width=3)
draw.text((1190, 58), "Đang chạy từ đầu đến cuối (P0–P5)", font=fnt(20, bold=True), fill=C["ink"], anchor="lm")

draw.rounded_rectangle((1605, 42, 1643, 74), radius=5, fill=C["teal_fill"], outline=C["teal"], width=3)
draw.text((1655, 58), "Cổng kiểm chứng / Kho dữ liệu & SQLite", font=fnt(20, bold=True), fill=C["ink"], anchor="lm")

draw.rounded_rectangle((2110, 42, 2148, 74), radius=5, fill=C["amber_fill"], outline=None, width=3)
dash_rect(draw, 2110, 42, 2148, 74, C["amber"], width=3, dash=8, gap=5, radius=5)
draw.text((2160, 58), "Kế hoạch tiếp theo (P6–P8)", font=fnt(20, bold=True), fill=C["amber"], anchor="lm")
# 1. LANE 1: NGƯỜI DÙNG & GIAO TIẾP
lane_container(34, 114, 434, 900, "1. Giao tiếp & Phiên chạy", C["navy"])
node_box(58, 190, 410, 340, "Kỹ sư Nhúng / IoT", [
    "Đặt mục tiêu thiết kế / câu hỏi",
    "Phê duyệt ghi file (Approve/Reject)",
    "Trả lời làm rõ (Clarify / Choice)",
], fill=C["navy_fill"], outline=C["navy"])

node_box(58, 396, 410, 576, "CLI & Run API (HTTP / SSE)", [
    "POST /api/runs • GET /events",
    "POST /api/runs/{id}/resume",
    "Tuần tự hoá & khôi phục phiên",
], fill=C["navy_fill"], outline=C["navy"], footer="Đang chạy (P4–P5)")

node_box(58, 632, 410, 872, "Web UI v2 Panels (P8)", [
    "• Plan & Replan Diff Panel",
    "• Board Pin / Clock / Power View",
    "• Timeline & Interrupt Cards",
    "• Lesson & Budget Monitor",
], fill=C["amber_fill"], outline=C["amber"], dashed=True, footer="Kế hoạch P8 (UI hiện tại là v1)")

# 2. LANE 2: AGENT RUNTIME V2
lane_container(494, 114, 1504, 900, "2. Agent Runtime v2 — State Machine có Checkpoint & Verification Gate", C["navy"])

node_box(524, 190, 974, 355, "INTAKE & Guardrail v1", [
    "Chặn prompt injection / quá áp đầu vào",
    "Nạp BoardState, kế hoạch & lịch sử phiên",
    "Trích trạng thái clock khởi đầu",
], fill=C["navy_fill"], outline=C["navy"])

node_box(1024, 190, 1474, 355, "PLAN & LLM Policy", [
    "Model: ag/gemini-3.8-flash-medium",
    "Lập / cập nhật kế hoạch (update_plan)",
    "Tự chủ chọn công cụ & sinh mã C CMSIS",
], fill=C["navy_fill"], outline=C["navy"])

node_box(524, 405, 974, 585, "ACT <-> OBSERVE", [
    "Gọi công cụ qua ToolHub / Local Controls",
    "Lưu observation đầy đủ cho Gate",
    "Ngân sách: 40 bước • 1,5M token • 600s",
], fill=C["navy_fill"], outline=C["navy"])

node_box(1024, 405, 1474, 585, "CHECK & FINISH_GATE (G1–G5)", [
    "G1 Provenance • G2 Functional Sim",
    "G3 Board DRC (8 luật) • G4 Safety",
    "G5 Clang ARM -fsyntax-only",
], fill=C["teal_fill"], outline=C["teal"], footer="Lỗi cục bộ → tự sửa | Lỗi cấu trúc → Replan")

node_box(524, 635, 974, 780, "INTERRUPTED <-> RESUME", [
    "ask_human (clarify / choice, tối đa 3 lần)",
    "write_config_file (cổng duyệt ghi file)",
    "Checkpoint SQLite bền qua kill tiến trình",
], fill=C["navy_fill"], outline=C["navy"])

node_box(1024, 635, 1474, 780, "Trạng thái kết thúc (Terminal)", [
    "DONE: Gate chấp nhận (answered)",
    "REFUSED: chặn an toàn / injection",
    "ESCALATED: hết ngân sách / lặp lỗi > 3 lần",
], fill=C["slate_fill"], outline=C["slate"])

node_box(524, 800, 1474, 882, "Action Policy Engine & Taint Tracking trước mọi lệnh gọi công cụ (Kế hoạch P6)", [
    "Kiểm tham số quá áp / chân không FT trước khi sửa BoardState; chặn dữ liệu dính cờ injection ghi file",
], fill=C["amber_fill"], outline=C["amber"], dashed=True)

# 3. LANE 3: MCP TOOLHUB & 32 TOOLS
lane_container(1564, 114, 2566, 900, "3. MCP ToolHub (inproc) & 32 Công cụ theo mức quyền", C["navy"])

node_box(1592, 186, 2538, 286, "ToolHub Dispatcher: Allowlist • Project Scope • Sanitize • Audit JSONL", [
    "Chỉ retry công cụ read-only • Tự gắn project_id • 3 công cụ điều khiển cục bộ: update_plan, ask_human, finish",
], fill=C["navy_fill"], outline=C["navy"])

node_box(1592, 314, 2052, 494, "text-manual (3 tools)", [
    "• search_manual (BM25 + MiniLM)",
    "• get_chunk_context (chunk lân cận)",
    "• list_documents (metadata)",
    "• (naive_search ẩn cho baseline)",
], fill=C["navy_fill"], outline=C["navy"], badge="READ-ONLY", badge_color=C["navy"])

node_box(2078, 314, 2538, 494, "hw-knowledge (8 tools)", [
    "• query_pin_af • find_pins_for_signal",
    "• get_register_bitfields • search_regs",
    "• get_electrical_specs • clock_limits",
    "• check_logic_compat • list_chips",
], fill=C["navy_fill"], outline=C["navy"], badge="READ-ONLY", badge_color=C["navy"])

node_box(1592, 520, 2052, 710, "board-state (13 tools)", [
    "• 4 đọc: state, power, run_drc, diff",
    "• 9 ghi hoàn tác: set_target, reqs,",
    "  allocate/release_pin, clock_config,",
    "  add_device, connect, decision, rollback",
], fill=C["teal_fill"], outline=C["teal"], badge="STATE-MUTATING", badge_color=C["teal"])

node_box(2078, 520, 2538, 710, "hw-sandbox (4 tools)", [
    "• solve_timer_config (PSC/ARR/CCR)",
    "• analyze_c_code (parse C → ops)",
    "• simulate_register_writes (mô phỏng)",
    "• compile_check (clang -fsyntax-only)",
], fill=C["teal_fill"], outline=C["teal"], badge="SANDBOXED-EXEC", badge_color=C["teal"])

node_box(1592, 736, 2538, 876, "write_config_file (1 tool)", [
    "• Kiểm tên file, đuôi (.c/.h/.txt/.json/.md), kích thước ≤ 20 KB, chống path traversal ngoài workspace_out/",
    "• Bắt buộc tạo interrupt approval; chỉ ghi sau khi người dùng Approve và kiểm tra lại đường dẫn lúc ghi",
], fill=C["amber_fill"], outline=C["amber"], badge="IRREVERSIBLE-WRITE", badge_color=C["amber"])

# 4. BOTTOM LANE: DATA & MEMORY
lane_container(34, 946, 2566, 1212, "4. Tầng Dữ liệu Kỹ thuật Thật (Corpus chung với Baseline) & Bộ nhớ Bền vững (SQLite)", C["teal"])

node_box(58, 1016, 668, 1190, "hw_specs.sqlite (Dữ liệu cấu trúc SVD & Datasheet)", [
    "3 chip (STM32G474, ESP32, nRF52840) • 210 peripheral",
    "6.338 thanh ghi • 27.186 field • 189 chân / 1.045 AF • 104 giới hạn",
], fill=C["teal_fill"], outline=C["teal"])

node_box(694, 1016, 1304, 1190, "text_index.sqlite + .npy (Hybrid Retrieval)", [
    "6 PDF chính hãng (4.520 trang) → 9.583 chunk theo tiêu đề",
    "BM25 (SQLite FTS5) + MiniLM 384 chiều, trộn Reciprocal Rank Fusion",
], fill=C["teal_fill"], outline=C["teal"])

node_box(1330, 1016, 1940, 1190, "checkpoints.sqlite & board_state.sqlite", [
    "Lưu AgentState sau mỗi bước, lịch sử phiên (session history)",
    "BoardState event-sourced theo project_id (hỗ trợ diff & rollback)",
], fill=C["navy_fill"], outline=C["navy"])

node_box(1966, 1016, 2542, 1190, "Lesson & Project Memory xuyên phiên (P7)", [
    "Chỉ ghi bài học sửa lỗi sau khi simulator xác nhận pass",
    "Truy hồi theo chip / peripheral / mã lỗi ở bước INTAKE",
], fill=C["amber_fill"], outline=C["amber"], dashed=True)
# 5. ORTHOGONAL CONNECTORS (đi trong hành lang, không đè chữ)
# User <-> CLI/Run API
ortho_arrow([(234, 340), (234, 396)], color=C["navy"], both=True)
# CLI/Run API -> INTAKE
ortho_arrow([(410, 448), (464, 448), (464, 272), (524, 272)], color=C["navy"], label="Goal", label_pos=(464, 355))
# CLI/Run API <-> INTERRUPTED
ortho_arrow([(410, 528), (464, 528), (464, 708), (524, 708)], color=C["navy"], both=True, label="Interrupt / Resume", label_pos=(464, 616))
# INTAKE -> PLAN
ortho_arrow([(974, 272), (1024, 272)], color=C["navy"])
# PLAN <-> ACT
ortho_arrow([(1140, 355), (1140, 380), (749, 380), (749, 405)], color=C["navy"], both=True)
# ACT -> CHECK/GATE
ortho_arrow([(974, 480), (1024, 480)], color=C["teal"])
# CHECK/GATE -> ACT (local error feedback)
ortho_arrow([(1024, 535), (974, 535)], color=C["amber"], label="Sửa lỗi", label_pos=(999, 558))
# CHECK/GATE -> PLAN (structural error replan)
ortho_arrow([(1474, 450), (1492, 450), (1492, 272), (1474, 272)], color=C["amber"])
# ACT <-> INTERRUPTED
ortho_arrow([(749, 585), (749, 635)], color=C["navy"], both=True)
# CHECK/GATE -> Terminal DONE
ortho_arrow([(1249, 585), (1249, 635)], color=C["teal"], label="Pass", label_pos=(1249, 610))
# ACT <-> ToolHub Dispatcher (qua hành lang trên y=162)
ortho_arrow([(749, 405), (749, 380), (1534, 380), (1534, 236), (1592, 236)], color=C["navy"], both=True, label="Tool Call", label_pos=(1534, 308))
# Runtime & ToolHub <-> Data Layer (nối vuông góc tới viền trên container 4 tại y=946)
ortho_arrow([(2065, 900), (2065, 946)], color=C["teal"], both=True)
ortho_arrow([(1635, 900), (1635, 946)], color=C["navy"], both=True)
ortho_arrow([(999, 900), (999, 946)], color=C["navy"], both=True)

rgb_img = base.convert("RGB")
png_path = ASSETS / "architecture_drawio.png"
pdf_path = ASSETS / "architecture_drawio.pdf"
rgb_img.save(png_path, quality=95)
rgb_img.save(pdf_path, "PDF", resolution=300.0)
print("Saved crisp draw.io architecture diagram:", png_path, pdf_path)
