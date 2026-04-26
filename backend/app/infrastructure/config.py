import os
from pathlib import Path


def find_project_root():
    current = Path(__file__).resolve().parent
    for candidate in (current, *current.parents):
        if (candidate / ".env.example").exists():
            return candidate
    return Path(__file__).resolve().parents[3]


PROJECT_ROOT = find_project_root()
SKILL_LIBRARY_ROOT = PROJECT_ROOT / "skill-data" / "skills"


def load_env_file(env_path=None):
    """从项目根目录加载 .env 文件，不依赖额外库"""
    if env_path is None:
        env_path = PROJECT_ROOT / ".env"

    if not os.path.exists(env_path):
        return

    with open(env_path, "r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'\"")
            os.environ.setdefault(key, value)


load_env_file()


def get_request_timeout():
    raw_value = os.getenv("REQUEST_TIMEOUT", "60").strip()
    try:
        return max(5, int(raw_value))
    except ValueError:
        return 60


def get_bool_env(name, default=False):
    raw_value = os.getenv(name, str(default)).strip().lower()
    return raw_value in {"1", "true", "yes", "on"}


BAIDU_ACCESS_TOKEN = os.getenv("BAIDU_ACCESS_TOKEN", "").strip()
ERNIE_BASE_URL = os.getenv(
    "ERNIE_BASE_URL",
    "https://aistudio.baidu.com/llm/lmapi/v3",
).strip().rstrip("/")
ERNIE_CHAT_ENDPOINT = (
    os.getenv("ERNIE_CHAT_ENDPOINT", "").strip()
    or f"{ERNIE_BASE_URL}/chat/completions"
)
ERNIE_MODEL = os.getenv(
    "ERNIE_MODEL",
    "ernie-5.0-thinking-preview",
).strip() or "ernie-5.0-thinking-preview"
OCR_BACKEND = os.getenv("OCR_BACKEND", "local").strip().lower() or "local"
PADDLEOCR_API_URL = os.getenv("PADDLEOCR_API_URL", "").strip()
PADDLEOCR_TOKEN = os.getenv("PADDLEOCR_TOKEN", "").strip()
HOTKEY = os.getenv("HOTKEY", "ctrl+alt+q").strip() or "ctrl+alt+q"
REQUEST_TIMEOUT = get_request_timeout()
ERNIE_WEB_SEARCH_ENABLED = get_bool_env("ERNIE_WEB_SEARCH_ENABLED", True)
HOTKEY_ENABLED = get_bool_env("HOTKEY_ENABLED", False)
DOCUMENT_DROP_EXTENSIONS = {".pdf", ".docx", ".doc", ".md", ".markdown", ".txt"}
