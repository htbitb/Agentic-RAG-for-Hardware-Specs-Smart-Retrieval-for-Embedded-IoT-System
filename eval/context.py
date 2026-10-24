"""GradeContext: dữ liệu tham chiếu cho graders (manifest, text từng trang, prompt hệ thống, bí mật)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "corpus"


def _key(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


@dataclass
class GradeContext:
    manifest: list[dict]
    pages: dict = field(default_factory=dict)               # doc_id -> [text trang PDF 1, 2, ...]
    pages_dir: Path | None = None                           # nạp lười từ corpus/.cache/pages
    system_prompts: dict = field(default_factory=dict)      # system ("S0"/"S1"/"S2") -> prompt thật
    secrets: list = field(default_factory=list)             # giá trị bí mật thật (chỉ so khớp, không bao giờ in)

    def __post_init__(self):
        self._by_key: dict[str, dict] = {}
        for e in self.manifest:
            names = [e["doc_id"], *e.get("aliases", [])]
            if e.get("file"):
                names += [Path(e["file"]).name, Path(e["file"]).stem]
            for n in names:
                self._by_key.setdefault(_key(n), e)

    @classmethod
    def load(cls, system_prompts=None, secrets=None, corpus: Path = CORPUS) -> "GradeContext":
        manifest = yaml.safe_load((corpus / "manifest.yaml").read_text(encoding="utf-8"))
        return cls(manifest=manifest, pages_dir=corpus / ".cache" / "pages",
                   system_prompts=system_prompts or {}, secrets=secrets or [])

    def resolve_doc(self, name: str) -> dict | None:
        """Khớp đúng khoá (doc_id / alias / tên file); nếu không, alias dài nhất (>= 6 ký tự) nằm trong cụm văn bản,
        vd 'nRF52840 Product Specification v1.8' ⊃ alias 'nRF52840 Product Specification'."""
        k = _key(name)
        if k in self._by_key:
            return self._by_key[k]
        best = max((a for a in self._by_key if len(a) >= 6 and a in k), key=len, default=None)
        return self._by_key[best] if best else None

    def entry(self, doc_id: str) -> dict | None:
        return next((e for e in self.manifest if e["doc_id"] == doc_id), None)

    def page_text(self, doc_id: str, pdf_page: int) -> str | None:
        if doc_id not in self.pages and self.pages_dir is not None:
            path = self.pages_dir / f"{doc_id}.jsonl"
            if path.is_file():
                self.pages[doc_id] = [json.loads(l)["text"] for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        texts = self.pages.get(doc_id)
        if texts is None or not (1 <= pdf_page <= len(texts)):
            return None
        return texts[pdf_page - 1]
