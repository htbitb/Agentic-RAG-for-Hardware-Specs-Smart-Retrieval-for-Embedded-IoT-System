"""Central project configuration loaded from .env in project root."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _load_dotenv() -> None:
    """Load environment variables from .env (and .env.txt) in project root."""
    for candidate in (ROOT / ".env", ROOT / ".env.txt"):
        if not candidate.is_file():
            continue
        for raw_line in candidate.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                val = val[1:-1]
            elif " #" in val:
                val = val.split(" #", 1)[0].strip()
            if key and (key not in os.environ or (not os.environ[key] and val)):
                os.environ[key] = val


_load_dotenv()


def _resolve_path(env_key: str, default_rel: str) -> Path:
    raw = os.getenv(env_key, "").strip()
    p = Path(raw) if raw else (ROOT / default_rel)
    return p if p.is_absolute() else (ROOT / p)


# Directories & persistence paths
DATA_DIR = ROOT / "data"
LOGS_DIR = ROOT / "logs"
AUDIT_LOG = _resolve_path("AUDIT_LOG", "logs/audit.jsonl")
SANDBOX_DIR = _resolve_path("SANDBOX_DIR", "workspace_out")
MEMORY_DB = _resolve_path("MEMORY_DB", "data/memory.sqlite")

AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
MEMORY_DB.parent.mkdir(parents=True, exist_ok=True)

# LLM configuration
LLM_API_KEY = (
    os.getenv("LLM_API_KEY", "").strip()
    or os.getenv("OPENAI_API_KEY", "").strip()
    or os.getenv("GEMINI_API_KEY", "").strip()
)
LLM_BASE_URL = (
    os.getenv("LLM_BASE_URL", "").strip()
    or os.getenv("OPENAI_BASE_URL", "").strip()
    or ("https://generativelanguage.googleapis.com/v1beta/openai/" if os.getenv("GEMINI_API_KEY", "").strip() else None)
)
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-3.5-flash-lite").strip() or "gemini-3.5-flash-lite"
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.0") or 0.0)

# Token pricing (USD per 1M tokens)
PRICE_IN_PER_M = float(os.getenv("PRICE_IN_PER_M", "0.075") or 0.075)
PRICE_OUT_PER_M = float(os.getenv("PRICE_OUT_PER_M", "0.30") or 0.30)

# Agent, retrieval & MCP runtime parameters
TOP_K = int(os.getenv("TOP_K", "5") or 5)
MCP_TRANSPORT = os.getenv("MCP_TRANSPORT", "inproc").strip() or "inproc"
MAX_STEPS = int(os.getenv("MAX_STEPS", "8") or 8)
TOOL_TIMEOUT_S = float(os.getenv("TOOL_TIMEOUT_S", "30.0") or 30.0)
TOOL_RETRIES = int(os.getenv("TOOL_RETRIES", "2") or 2)
PORT = int(os.getenv("PORT", "8000") or 8000)

# Dữ liệu thật (P1): SVD/pin/giới hạn trong SQLite, text index hybrid (BM25 + embedding)
HW_DB = _resolve_path("HW_SPECS_DB", "data/hw_specs.sqlite")
TEXT_INDEX_DB = _resolve_path("TEXT_INDEX_DB", "data/text_index.sqlite")
TEXT_INDEX_EMB = _resolve_path("TEXT_INDEX_EMB", "data/text_index.npy")
