import os
import sys
import json
import base64
import ctypes
import html
import re
import time
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree as ET
import requests
from io import BytesIO
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QTextEdit, QFrame, QMessageBox,
                             QScrollArea, QFileDialog, QLineEdit)
from PyQt5.QtCore import Qt, pyqtSignal, QThread, QPoint, QRect, QRectF, QAbstractNativeEventFilter, QByteArray, QBuffer, QIODevice
from PyQt5.QtGui import QPainter, QPen, QColor, QCursor, QPixmap, QImage, QLinearGradient, QFont, QFontMetricsF

def find_project_root():
    current = Path(__file__).resolve().parent
    for candidate in (current, *current.parents):
        if (candidate / ".env.example").exists():
            return candidate
    return Path(__file__).resolve().parents[2]


PROJECT_ROOT = find_project_root()
SKILL_LIBRARY_ROOT = PROJECT_ROOT / "skill-data" / "skills"
MEMORY_STORE_PATH = PROJECT_ROOT / "skill-data" / "memory" / "persona_memory.json"

# ==========================================
# 配置区域
# ==========================================
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

            # 已存在的系统环境变量优先级更高
            os.environ.setdefault(key, value)


load_env_file()

BAIDU_ACCESS_TOKEN = os.getenv("BAIDU_ACCESS_TOKEN", "").strip()
ERNIE_BASE_URL = os.getenv(
    "ERNIE_BASE_URL",
    "https://aistudio.baidu.com/llm/lmapi/v3"
).strip().rstrip("/")
ERNIE_CHAT_ENDPOINT = (
    os.getenv("ERNIE_CHAT_ENDPOINT", "").strip()
    or f"{ERNIE_BASE_URL}/chat/completions"
)
ERNIE_MODEL = os.getenv(
    "ERNIE_MODEL",
    "ernie-5.0-thinking-preview"
).strip() or "ernie-5.0-thinking-preview"
OCR_BACKEND = os.getenv("OCR_BACKEND", "local").strip().lower() or "local"
PADDLEOCR_API_URL = os.getenv("PADDLEOCR_API_URL", "").strip()
PADDLEOCR_TOKEN = os.getenv("PADDLEOCR_TOKEN", "").strip()

# 全局热键设置
HOTKEY = os.getenv("HOTKEY", "ctrl+alt+q").strip() or "ctrl+alt+q"


def get_request_timeout():
    """读取请求超时时间"""
    raw_value = os.getenv("REQUEST_TIMEOUT", "60").strip()
    try:
        return max(5, int(raw_value))
    except ValueError:
        return 60


REQUEST_TIMEOUT = get_request_timeout()


def get_bool_env(name, default=False):
    """读取布尔型环境变量"""
    raw_value = os.getenv(name, str(default)).strip().lower()
    return raw_value in {"1", "true", "yes", "on"}


def pixmap_to_png_bytes(pixmap):
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    pixmap.save(buffer, "PNG")
    return bytes(data)


def truncate_text(text, limit=140):
    value = (text or "").strip().replace("\r", " ")
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def format_count(value):
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "0"


def clamp(value, minimum, maximum):
    if maximum < minimum:
        return minimum
    return max(minimum, min(value, maximum))


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child_layout = item.layout()
        if widget is not None:
            widget.deleteLater()
        elif child_layout is not None:
            clear_layout(child_layout)


def extract_local_file_paths(mime_data):
    if mime_data is None or not mime_data.hasUrls():
        return []
    paths = []
    for url in mime_data.urls():
        if not url.isLocalFile():
            continue
        local_path = url.toLocalFile()
        if local_path:
            paths.append(local_path)
    return paths


def filter_supported_document_paths(paths):
    return [path for path in paths if Path(path).suffix.lower() in DOCUMENT_DROP_EXTENSIONS]


def measure_wrapped_text_height(text, font, width, flags):
    metrics = QFontMetricsF(font)
    rect = metrics.boundingRect(QRectF(0, 0, float(max(1, width)), 10000.0), int(flags), str(text or ""))
    return max(metrics.height(), rect.height())


def render_share_card_image(payload):
    """将回复内容渲染成适合分享到剪贴板的图片。"""
    payload = dict(payload or {})
    reply_style = str(payload.get("reply_style") or payload.get("style") or "AI 发言人").strip() or "AI 发言人"
    reply_text = str(payload.get("reply_text") or payload.get("text") or "").strip()
    source_text = str(
        payload.get("ocr_text_snapshot")
        or payload.get("ocr_text")
        or payload.get("source_text")
        or ""
    ).strip()
    brand = str(payload.get("brand") or "高情商聊天回复助手").strip() or "高情商聊天回复助手"

    if not reply_text:
        raise ValueError("分享卡缺少可用回复内容。")

    source_excerpt = truncate_text(source_text.replace("\r", " ").replace("\n", " "), 260)
    if not source_excerpt:
        source_excerpt = "未提供原始 OCR 文本"

    width = 1080
    outer_padding = 48
    card_padding = 56
    content_width = width - (outer_padding * 2) - (card_padding * 2)
    text_flags = Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap

    eyebrow_font = QFont("Microsoft YaHei", 18)
    eyebrow_font.setBold(True)
    section_font = QFont("Microsoft YaHei", 18)
    section_font.setBold(True)
    source_font = QFont("Microsoft YaHei", 19)
    reply_font = QFont("Microsoft YaHei", 32)
    reply_font.setBold(True)
    watermark_font = QFont("Microsoft YaHei", 15)

    source_height = measure_wrapped_text_height(source_excerpt, source_font, content_width - 32, text_flags)
    reply_height = measure_wrapped_text_height(reply_text, reply_font, content_width - 48, text_flags)
    minimum_reply_height = QFontMetricsF(reply_font).lineSpacing() * 3.2
    reply_height = max(reply_height, minimum_reply_height)

    source_box_height = 92 + source_height
    reply_box_height = 100 + reply_height
    height = int(max(820, outer_padding * 2 + 120 + source_box_height + reply_box_height + 120))

    device_pixel_ratio = 2.0
    image = QImage(
        int(width * device_pixel_ratio),
        int(height * device_pixel_ratio),
        QImage.Format_ARGB32_Premultiplied,
    )
    image.setDevicePixelRatio(device_pixel_ratio)
    image.fill(Qt.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

    background = QLinearGradient(0, 0, width, height)
    background.setColorAt(0.0, QColor("#eff6ff"))
    background.setColorAt(0.55, QColor("#f8fafc"))
    background.setColorAt(1.0, QColor("#ecfdf5"))
    painter.fillRect(0, 0, width, height, background)

    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(59, 130, 246, 26))
    painter.drawEllipse(-80, -40, 360, 240)
    painter.setBrush(QColor(16, 185, 129, 24))
    painter.drawEllipse(width - 310, height - 250, 360, 280)

    card_x = outer_padding
    card_y = outer_padding
    card_w = width - outer_padding * 2
    card_h = height - outer_padding * 2
    painter.setBrush(QColor(255, 255, 255, 238))
    painter.setPen(QPen(QColor("#dbeafe"), 1))
    painter.drawRoundedRect(card_x, card_y, card_w, card_h, 28, 28)

    inner_x = card_x + card_padding
    inner_y = card_y + card_padding
    inner_w = card_w - card_padding * 2

    pill_text = f"AI 发言人卡 · {reply_style}"
    painter.setFont(eyebrow_font)
    pill_width = int(QFontMetricsF(eyebrow_font).horizontalAdvance(pill_text) + 34)
    painter.setBrush(QColor("#dbeafe"))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(inner_x, inner_y, pill_width, 40, 20, 20)
    painter.setPen(QColor("#1d4ed8"))
    painter.drawText(inner_x + 18, inner_y + 27, pill_text)

    source_box_y = inner_y + 66
    painter.setBrush(QColor("#f8fafc"))
    painter.setPen(QPen(QColor("#e2e8f0"), 1))
    painter.drawRoundedRect(inner_x, int(source_box_y), inner_w, int(source_box_height), 22, 22)
    painter.setFont(section_font)
    painter.setPen(QColor("#334155"))
    painter.drawText(inner_x + 18, source_box_y + 30, "原始 OCR 文本")
    painter.setFont(source_font)
    painter.setPen(QColor("#64748b"))
    source_rect = QRect(inner_x + 18, source_box_y + 44, inner_w - 36, int(source_height + 20))
    painter.drawText(source_rect, int(text_flags), source_excerpt)

    reply_box_y = int(source_box_y + source_box_height + 24)
    painter.setBrush(QColor("#ecfdf5"))
    painter.setPen(QPen(QColor("#a7f3d0"), 1))
    painter.drawRoundedRect(inner_x, reply_box_y, inner_w, int(reply_box_height), 24, 24)
    painter.fillRect(inner_x + 22, reply_box_y + 22, 6, int(reply_box_height - 44), QColor("#10b981"))
    painter.setFont(section_font)
    painter.setPen(QColor("#047857"))
    painter.drawText(inner_x + 42, reply_box_y + 34, "AI 推荐回复")
    painter.setFont(reply_font)
    painter.setPen(QColor("#0f172a"))
    reply_rect = QRect(inner_x + 42, reply_box_y + 52, inner_w - 70, int(reply_height + 20))
    painter.drawText(reply_rect, int(text_flags), reply_text)

    watermark_y = int(reply_box_y + reply_box_height + 44)
    painter.setFont(watermark_font)
    painter.setPen(QColor("#94a3b8"))
    watermark_text = html.unescape(f"{brand} · 分享自 AI Spokesperson")
    painter.drawText(QRect(inner_x, watermark_y, inner_w, 28), int(Qt.AlignCenter), watermark_text)

    painter.end()
    return image


ERNIE_WEB_SEARCH_ENABLED = get_bool_env("ERNIE_WEB_SEARCH_ENABLED", True)
HOTKEY_ENABLED = get_bool_env("HOTKEY_ENABLED", False)
DOCUMENT_DROP_EXTENSIONS = {".pdf", ".docx", ".doc", ".md", ".markdown", ".txt"}


class DocumentParser:
    """解析拖入的文档内容，优先使用标准库，按能力降级"""

    TEXT_EXTENSIONS = {".txt", ".md", ".markdown"}
    DOCX_EXTENSIONS = {".docx"}
    PDF_EXTENSIONS = {".pdf"}
    LEGACY_WORD_EXTENSIONS = {".doc"}

    @classmethod
    def is_supported_path(cls, file_path):
        suffix = Path(file_path).suffix.lower()
        return suffix in DOCUMENT_DROP_EXTENSIONS

    @classmethod
    def parse_file(cls, file_path):
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在：{path}")

        suffix = path.suffix.lower()
        if suffix in cls.TEXT_EXTENSIONS:
            text = cls.parse_text_file(path)
            parser_name = "plain-text"
            source_type = "markdown" if suffix in {".md", ".markdown"} else "text"
            meta = {"encoding": "auto"}
        elif suffix in cls.DOCX_EXTENSIONS:
            text = cls.parse_docx_file(path)
            parser_name = "stdlib-docx"
            source_type = "docx"
            meta = {"paragraph_count": len([line for line in text.splitlines() if line.strip()])}
        elif suffix in cls.PDF_EXTENSIONS:
            text, parser_name, meta = cls.parse_pdf_file(path)
            source_type = "pdf"
        elif suffix in cls.LEGACY_WORD_EXTENSIONS:
            raise ValueError("旧版 .doc 暂不支持，请先另存为 .docx 后再拖入。")
        else:
            raise ValueError("当前仅支持 PDF、DOCX、Markdown、TXT 文件。")

        normalized_text = cls.normalize_document_text(text)
        if not normalized_text:
            raise ValueError("文件解析成功，但没有提取到可用文本。")

        return cls.build_document_payload(
            path,
            normalized_text,
            source_type=source_type,
            parser_name=parser_name,
            extra_meta=meta,
        )

    @classmethod
    def parse_text_file(cls, file_path):
        return cls.read_text_with_fallback_encodings(file_path)

    @classmethod
    def parse_docx_file(cls, file_path):
        try:
            with zipfile.ZipFile(file_path, "r") as archive:
                xml_data = archive.read("word/document.xml")
        except KeyError as exc:
            raise ValueError("DOCX 文件缺少 word/document.xml，可能已损坏。") from exc
        except zipfile.BadZipFile as exc:
            raise ValueError("DOCX 文件无法读取，可能不是合法的 Office 文档。") from exc

        namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        root = ET.fromstring(xml_data)
        paragraphs = []

        for paragraph in root.iterfind(".//w:p", namespace):
            parts = []
            for node in paragraph.iter():
                tag = node.tag.rsplit("}", 1)[-1]
                if tag == "t" and node.text:
                    parts.append(node.text)
                elif tag == "tab":
                    parts.append("\t")
                elif tag in {"br", "cr"}:
                    parts.append("\n")
            paragraph_text = "".join(parts).strip()
            if paragraph_text:
                paragraphs.append(paragraph_text)

        return "\n".join(paragraphs)

    @classmethod
    def parse_pdf_file(cls, file_path):
        backends = (
            ("pypdf", cls._extract_pdf_with_pypdf),
            ("PyPDF2", cls._extract_pdf_with_pypdf2),
            ("pdfplumber", cls._extract_pdf_with_pdfplumber),
            ("fitz", cls._extract_pdf_with_pymupdf),
        )

        import_errors = []
        for backend_name, extractor in backends:
            try:
                return extractor(file_path)
            except ModuleNotFoundError:
                import_errors.append(backend_name)
            except Exception as exc:
                raise ValueError(f"PDF 解析失败（{backend_name}）：{str(exc)}") from exc

        raise ValueError(
            "当前环境缺少 PDF 解析库，建议先安装 pypdf：pip install pypdf"
        )

    @staticmethod
    def _extract_pdf_with_pypdf(file_path):
        from pypdf import PdfReader

        reader = PdfReader(str(file_path))
        pages = []
        for page in reader.pages:
            pages.append((page.extract_text() or "").strip())
        return "\n\n".join(part for part in pages if part), "pypdf", {"page_count": len(reader.pages)}

    @staticmethod
    def _extract_pdf_with_pypdf2(file_path):
        from PyPDF2 import PdfReader

        reader = PdfReader(str(file_path))
        pages = []
        for page in reader.pages:
            pages.append((page.extract_text() or "").strip())
        return "\n\n".join(part for part in pages if part), "PyPDF2", {"page_count": len(reader.pages)}

    @staticmethod
    def _extract_pdf_with_pdfplumber(file_path):
        import pdfplumber

        pages = []
        with pdfplumber.open(str(file_path)) as pdf:
            for page in pdf.pages:
                pages.append((page.extract_text() or "").strip())
            page_count = len(pdf.pages)
        return "\n\n".join(part for part in pages if part), "pdfplumber", {"page_count": page_count}

    @staticmethod
    def _extract_pdf_with_pymupdf(file_path):
        import fitz

        document = fitz.open(str(file_path))
        try:
            pages = []
            for page_index in range(document.page_count):
                pages.append((document.load_page(page_index).get_text("text") or "").strip())
            return "\n\n".join(part for part in pages if part), "PyMuPDF", {"page_count": document.page_count}
        finally:
            document.close()

    @staticmethod
    def read_text_with_fallback_encodings(file_path):
        encodings = ("utf-8", "utf-8-sig", "gb18030", "gbk")
        last_error = None
        for encoding in encodings:
            try:
                return Path(file_path).read_text(encoding=encoding)
            except UnicodeDecodeError as exc:
                last_error = exc
        raise ValueError(f"文件编码无法识别：{str(last_error)}") from last_error

    @staticmethod
    def normalize_document_text(text):
        value = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
        value = re.sub(r"\n{3,}", "\n\n", value)
        value = re.sub(r"[ \t]{2,}", " ", value)
        return value.strip()

    @classmethod
    def build_document_payload(cls, file_path, text, source_type, parser_name="", extra_meta=None):
        path = Path(file_path)
        meta = dict(extra_meta or {})
        char_count = len(text)
        line_count = len([line for line in text.splitlines() if line.strip()])
        preview = truncate_text(text.replace("\n", " "), 220)
        meta_text_parts = [
            f"类型：{source_type.upper()}",
            f"解析：{parser_name or 'auto'}",
            f"字数：{format_count(char_count)}",
        ]
        if meta.get("page_count"):
            meta_text_parts.append(f"页数：{meta['page_count']}")
        if meta.get("paragraph_count"):
            meta_text_parts.append(f"段落：{format_count(meta['paragraph_count'])}")

        return {
            "file_path": str(path),
            "file_name": path.name,
            "file_type": source_type,
            "parser": parser_name or "auto",
            "text": text,
            "preview": preview,
            "char_count": char_count,
            "line_count": line_count,
            "meta_text": " · ".join(meta_text_parts),
            "meta": meta,
        }


class GlobalHotkeyManager:
    """优先使用 Windows 原生全局热键，避免依赖第三方 keyboard 包"""

    def __init__(self, app):
        self.app = app
        self.hotkey_filter = None

    def register(self, hotkey, callback):
        if sys.platform == "win32":
            self.hotkey_filter = WindowsHotkeyFilter()
            self.app.installNativeEventFilter(self.hotkey_filter)
            self.hotkey_filter.register(hotkey, callback)
            self.app.aboutToQuit.connect(self.hotkey_filter.unregister_all)
            return

        try:
            import keyboard
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "当前平台需要安装 keyboard 库才能使用全局热键，请执行：pip install keyboard"
            ) from exc

        keyboard.add_hotkey(hotkey, callback)


if sys.platform == "win32":
    from ctypes import wintypes

    WM_HOTKEY = 0x0312
    MOD_ALT = 0x0001
    MOD_CONTROL = 0x0002
    MOD_SHIFT = 0x0004
    MOD_WIN = 0x0008
    MOD_NOREPEAT = 0x4000

    WINDOWS_MODIFIERS = {
        "alt": MOD_ALT,
        "ctrl": MOD_CONTROL,
        "control": MOD_CONTROL,
        "shift": MOD_SHIFT,
        "win": MOD_WIN,
        "windows": MOD_WIN,
        "meta": MOD_WIN,
    }

    WINDOWS_KEY_CODES = {
        "space": 0x20,
        "tab": 0x09,
        "enter": 0x0D,
        "return": 0x0D,
        "esc": 0x1B,
        "escape": 0x1B,
        "left": 0x25,
        "up": 0x26,
        "right": 0x27,
        "down": 0x28,
        "delete": 0x2E,
        "del": 0x2E,
        "insert": 0x2D,
        "ins": 0x2D,
        "home": 0x24,
        "end": 0x23,
        "pageup": 0x21,
        "pagedown": 0x22,
    }

    def parse_windows_hotkey(hotkey):
        """把类似 ctrl+alt+q 的字符串转换为 Windows 热键参数"""
        parts = [part.strip().lower() for part in hotkey.split("+") if part.strip()]
        if len(parts) < 2:
            raise ValueError("热键格式无效，请使用类似 ctrl+alt+q 的格式")

        modifiers = 0
        for token in parts[:-1]:
            if token not in WINDOWS_MODIFIERS:
                raise ValueError(f"不支持的修饰键：{token}")
            modifiers |= WINDOWS_MODIFIERS[token]

        key_token = parts[-1]
        if len(key_token) == 1 and key_token.isalpha():
            key_code = ord(key_token.upper())
        elif len(key_token) == 1 and key_token.isdigit():
            key_code = ord(key_token)
        elif key_token.startswith("f") and key_token[1:].isdigit():
            fn_number = int(key_token[1:])
            if 1 <= fn_number <= 24:
                key_code = 0x70 + fn_number - 1
            else:
                raise ValueError(f"不支持的功能键：{key_token}")
        elif key_token in WINDOWS_KEY_CODES:
            key_code = WINDOWS_KEY_CODES[key_token]
        else:
            raise ValueError(f"不支持的主按键：{key_token}")

        return modifiers | MOD_NOREPEAT, key_code


    class WindowsHotkeyFilter(QAbstractNativeEventFilter):
        """监听 WM_HOTKEY，实现系统级全局热键"""

        def __init__(self):
            super().__init__()
            self.user32 = ctypes.windll.user32
            self.hotkeys = {}
            self.next_hotkey_id = 1

        def register(self, hotkey, callback):
            modifiers, key_code = parse_windows_hotkey(hotkey)
            hotkey_id = self.next_hotkey_id
            self.next_hotkey_id += 1

            if not self.user32.RegisterHotKey(None, hotkey_id, modifiers, key_code):
                raise RuntimeError(
                    f"注册全局热键失败：{hotkey}。请确认热键没有被其他程序占用。"
                )

            self.hotkeys[hotkey_id] = callback

        def unregister_all(self):
            for hotkey_id in list(self.hotkeys):
                self.user32.UnregisterHotKey(None, hotkey_id)
                self.hotkeys.pop(hotkey_id, None)

        def nativeEventFilter(self, event_type, message):
            if event_type not in {"windows_generic_MSG", "windows_dispatcher_MSG"}:
                return False, 0

            msg = wintypes.MSG.from_address(int(message))
            if msg.message != WM_HOTKEY:
                return False, 0

            callback = self.hotkeys.get(int(msg.wParam))
            if callback is None:
                return False, 0

            callback()
            return True, 0


class OCRClient:
    """统一封装本地 OCR 和远程 OCR API"""

    _shared_local_ocr = None

    def __init__(self):
        self.backend = OCR_BACKEND
        self.ocr = None

        if self.backend == "local":
            from paddleocr import PaddleOCR

            if OCRClient._shared_local_ocr is None:
                OCRClient._shared_local_ocr = PaddleOCR(
                    use_angle_cls=True,
                    lang="ch",
                    show_log=False,
                )
            self.ocr = OCRClient._shared_local_ocr
        elif self.backend == "api":
            if not PADDLEOCR_API_URL:
                raise ValueError("当 OCR_BACKEND=api 时，必须在 .env 中配置 PADDLEOCR_API_URL")
            if not PADDLEOCR_TOKEN:
                raise ValueError("当 OCR_BACKEND=api 时，必须在 .env 中配置 PADDLEOCR_TOKEN")
        else:
            raise ValueError("OCR_BACKEND 仅支持 local 或 api")

    def extract_text(self, image_data):
        """兼容旧接口：只返回最终拼接文本"""
        return self.extract_conversation(image_data).get("transcript", "")

    def extract_conversation(self, image_data):
        """根据配置选择 OCR 实现，并返回带坐标和左右归类的结构化结果"""
        if self.backend == "api":
            return self.extract_conversation_by_api(image_data)
        return self.extract_conversation_by_local(image_data)

    def extract_conversation_by_local(self, image_data):
        """使用本地 PaddleOCR 识别图片文字和坐标"""
        import numpy as np
        from PIL import Image

        image = Image.open(BytesIO(image_data)).convert("RGB")
        image_width, image_height = image.size
        result = self.ocr.ocr(np.array(image), cls=True)
        line_items = []

        if result and result[0]:
            for line in result[0]:
                if not isinstance(line, (list, tuple)) or len(line) < 2:
                    continue

                bbox = self.normalize_bbox(line[0])
                content = line[1] if len(line) > 1 else None
                text = ""
                confidence = None

                if isinstance(content, (list, tuple)) and content:
                    text = str(content[0]).strip()
                    if len(content) > 1:
                        try:
                            confidence = float(content[1])
                        except (TypeError, ValueError):
                            confidence = None
                elif isinstance(content, str):
                    text = content.strip()

                if not text:
                    continue

                line_items.append({
                    "text": text,
                    "bbox": bbox,
                    "confidence": confidence,
                })

        return self.build_conversation_payload(line_items, image_width, image_height)

    def extract_conversation_by_api(self, image_data):
        """调用远程 OCR API，尽量提取文字和坐标"""
        payload = {
            "file": base64.b64encode(image_data).decode("ascii"),
            "fileType": 1,
            "useDocOrientationClassify": False,
            "useDocUnwarping": False,
            "useChartRecognition": False,
        }
        headers = {
            "Authorization": f"token {PADDLEOCR_TOKEN}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                PADDLEOCR_API_URL,
                json=payload,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
        except Exception as e:
            raise RuntimeError(self.describe_api_request_error(e)) from e

        try:
            result = response.json()
        except Exception as e:
            raise RuntimeError(f"OCR API 返回的不是合法 JSON: {str(e)}") from e

        image_width, image_height = self.extract_image_size(result)
        line_items = self.collect_text_items(result)
        if line_items and image_width <= 0:
            image_width = max(int(item["bbox"][2]) for item in line_items if item.get("bbox")) + 1
        if line_items and image_height <= 0:
            image_height = max(int(item["bbox"][3]) for item in line_items if item.get("bbox")) + 1

        if line_items:
            return self.build_conversation_payload(line_items, image_width, image_height)

        texts = self.collect_texts(result)
        transcript = "\n".join(texts).strip()
        messages = []
        if transcript:
            messages.append({
                "sender": "unknown",
                "text": transcript,
                "bbox": None,
                "line_count": len(texts),
                "source": "fallback",
            })
        return {
            "transcript": transcript,
            "plain_text": transcript,
            "messages": messages,
            "lines": [],
            "image_width": image_width,
            "image_height": image_height,
        }

    @staticmethod
    def describe_api_request_error(exc):
        endpoint = (PADDLEOCR_API_URL or "").strip()
        host = urlparse(endpoint).netloc or endpoint or "未配置"

        if isinstance(exc, requests.exceptions.SSLError):
            return (
                "调用 OCR API 失败: 与 OCR 服务建立 HTTPS 连接时被对端中断。"
                f" 当前地址: {host}。"
                " 这通常表示 AI Studio OCR 应用未启动、域名已失效或已更换、服务端 HTTPS 配置异常，"
                "或本地代理/安全软件拦截了连接。请先在浏览器中直接打开该地址确认服务是否在线；"
                "如果 OCR 服务刚重新部署过，请同步更新 .env 里的 PADDLEOCR_API_URL。"
            )

        if isinstance(exc, requests.exceptions.Timeout):
            return (
                "调用 OCR API 失败: 请求超时。"
                f" 当前地址: {host}。"
                " 请确认 OCR 服务仍在运行，或适当增大 .env 中的 REQUEST_TIMEOUT。"
            )

        if isinstance(exc, requests.exceptions.ConnectionError):
            return (
                "调用 OCR API 失败: 无法与 OCR 服务建立连接。"
                f" 当前地址: {host}。"
                " 请确认域名和 443 端口可访问，并检查本机网络、代理、防火墙或杀毒软件是否拦截。"
            )

        if isinstance(exc, requests.exceptions.HTTPError):
            status_code = exc.response.status_code if exc.response is not None else "unknown"
            response_preview = ""
            if exc.response is not None:
                response_preview = (exc.response.text or "").strip().replace("\r", " ").replace("\n", " ")
                if len(response_preview) > 180:
                    response_preview = response_preview[:177].rstrip() + "..."
            message = f"调用 OCR API 失败: 服务返回 HTTP {status_code}。当前地址: {host}。"
            if response_preview:
                message += f" 响应内容: {response_preview}"
            return message

        return f"调用 OCR API 失败: {str(exc)}"

    @staticmethod
    def normalize_bbox(raw_bbox):
        """把常见 bbox/polygon 结构统一成 [x1, y1, x2, y2]"""
        if raw_bbox is None:
            return None

        if isinstance(raw_bbox, dict):
            if {"x1", "y1", "x2", "y2"}.issubset(raw_bbox):
                return OCRClient.normalize_bbox([
                    raw_bbox.get("x1"),
                    raw_bbox.get("y1"),
                    raw_bbox.get("x2"),
                    raw_bbox.get("y2"),
                ])
            if {"left", "top", "right", "bottom"}.issubset(raw_bbox):
                return OCRClient.normalize_bbox([
                    raw_bbox.get("left"),
                    raw_bbox.get("top"),
                    raw_bbox.get("right"),
                    raw_bbox.get("bottom"),
                ])
            if {"x", "y", "width", "height"}.issubset(raw_bbox):
                x = raw_bbox.get("x")
                y = raw_bbox.get("y")
                width = raw_bbox.get("width")
                height = raw_bbox.get("height")
                return OCRClient.normalize_bbox([x, y, x + width, y + height])
            if {"x", "y", "w", "h"}.issubset(raw_bbox):
                x = raw_bbox.get("x")
                y = raw_bbox.get("y")
                width = raw_bbox.get("w")
                height = raw_bbox.get("h")
                return OCRClient.normalize_bbox([x, y, x + width, y + height])
            for key in ("bbox", "box", "boundingBox", "bounding_box", "polygon", "points", "quad", "quadrilateral"):
                bbox = OCRClient.normalize_bbox(raw_bbox.get(key))
                if bbox:
                    return bbox
            return None

        if isinstance(raw_bbox, (list, tuple)):
            if len(raw_bbox) == 4 and all(isinstance(value, (int, float)) for value in raw_bbox):
                x1, y1, x2, y2 = raw_bbox
                return [
                    int(min(x1, x2)),
                    int(min(y1, y2)),
                    int(max(x1, x2)),
                    int(max(y1, y2)),
                ]

            if len(raw_bbox) == 8 and all(isinstance(value, (int, float)) for value in raw_bbox):
                points = list(zip(raw_bbox[::2], raw_bbox[1::2]))
                return OCRClient.normalize_bbox(points)

            point_candidates = []
            for item in raw_bbox:
                if isinstance(item, dict) and {"x", "y"}.issubset(item):
                    point_candidates.append((item.get("x"), item.get("y")))
                elif isinstance(item, (list, tuple)) and len(item) >= 2:
                    point_candidates.append((item[0], item[1]))

            if point_candidates:
                xs = [float(point[0]) for point in point_candidates]
                ys = [float(point[1]) for point in point_candidates]
                return [
                    int(min(xs)),
                    int(min(ys)),
                    int(max(xs)),
                    int(max(ys)),
                ]

        return None

    @staticmethod
    def classify_sender(bbox, image_width):
        if not bbox or image_width <= 0:
            return "unknown"

        center_x = (bbox[0] + bbox[2]) / 2
        middle_x = image_width / 2
        dead_zone = max(20, image_width * 0.08)

        if center_x < middle_x - dead_zone:
            return "other"
        if center_x > middle_x + dead_zone:
            return "self"
        return "system"

    @classmethod
    def build_conversation_payload(cls, line_items, image_width=0, image_height=0):
        prepared_lines = []
        for item in line_items:
            text = str(item.get("text", "")).strip()
            bbox = cls.normalize_bbox(item.get("bbox"))
            if not text:
                continue

            center_x = None
            center_y = None
            height = None
            if bbox:
                center_x = round((bbox[0] + bbox[2]) / 2, 2)
                center_y = round((bbox[1] + bbox[3]) / 2, 2)
                height = bbox[3] - bbox[1]

            prepared_lines.append({
                "text": text,
                "bbox": bbox,
                "confidence": item.get("confidence"),
                "center_x": center_x,
                "center_y": center_y,
                "height": height,
                "sender": cls.classify_sender(bbox, image_width),
            })

        prepared_lines.sort(key=lambda item: (
            item["bbox"][1] if item["bbox"] else 10**9,
            item["bbox"][0] if item["bbox"] else 10**9,
        ))

        messages = cls.group_lines_into_messages(prepared_lines, image_width)
        plain_text = "\n".join(item["text"] for item in prepared_lines).strip()
        transcript = cls.messages_to_transcript(messages).strip() or plain_text

        return {
            "transcript": transcript,
            "plain_text": plain_text,
            "messages": messages,
            "lines": prepared_lines,
            "image_width": image_width,
            "image_height": image_height,
        }

    @classmethod
    def group_lines_into_messages(cls, lines, image_width=0):
        messages = []
        for line in lines:
            if not messages:
                messages.append(cls._start_message(line))
                continue

            previous = messages[-1]
            if cls.should_merge_line(previous, line, image_width):
                previous["text_parts"].append(line["text"])
                previous["line_count"] += 1
                previous["bbox"] = cls.merge_bbox(previous.get("bbox"), line.get("bbox"))
                previous["source_lines"].append(line)
            else:
                messages.append(cls._start_message(line))

        for message in messages:
            message["text"] = "\n".join(part for part in message.pop("text_parts", []) if part).strip()

        return messages

    @staticmethod
    def _start_message(line):
        return {
            "sender": line.get("sender", "unknown"),
            "text_parts": [line.get("text", "")],
            "bbox": line.get("bbox"),
            "line_count": 1,
            "source_lines": [line],
        }

    @staticmethod
    def should_merge_line(previous_message, current_line, image_width):
        if previous_message.get("sender") != current_line.get("sender"):
            return False

        previous_bbox = previous_message.get("bbox")
        current_bbox = current_line.get("bbox")
        if not previous_bbox or not current_bbox:
            return False

        vertical_gap = current_bbox[1] - previous_bbox[3]
        current_height = max(12, current_bbox[3] - current_bbox[1])
        gap_limit = max(16, min(42, int(current_height * 1.6)))

        previous_center_x = (previous_bbox[0] + previous_bbox[2]) / 2
        current_center_x = (current_bbox[0] + current_bbox[2]) / 2
        center_delta = abs(previous_center_x - current_center_x)
        column_limit = max(50, image_width * 0.18) if image_width > 0 else 60

        return vertical_gap <= gap_limit and center_delta <= column_limit

    @staticmethod
    def merge_bbox(first_bbox, second_bbox):
        if not first_bbox:
            return second_bbox
        if not second_bbox:
            return first_bbox
        return [
            min(first_bbox[0], second_bbox[0]),
            min(first_bbox[1], second_bbox[1]),
            max(first_bbox[2], second_bbox[2]),
            max(first_bbox[3], second_bbox[3]),
        ]

    @staticmethod
    def messages_to_transcript(messages):
        label_map = {
            "other": "对方",
            "self": "我",
            "system": "系统",
            "unknown": "未分类",
        }
        lines = []
        for message in messages:
            text = str(message.get("text", "")).strip()
            if not text:
                continue
            label = label_map.get(message.get("sender", "unknown"), "未分类")
            lines.append(f"[{label}] {text}")
        return "\n".join(lines)

    @classmethod
    def collect_text_items(cls, data):
        items = []
        cls._walk_text_items(data, items)

        deduped = []
        seen = set()
        for item in items:
            bbox = tuple(item["bbox"]) if item.get("bbox") else None
            key = (item.get("text", "").strip(), bbox)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    @classmethod
    def _walk_text_items(cls, data, items):
        if isinstance(data, dict):
            bbox = cls.normalize_bbox(data)
            text = cls.extract_candidate_text(data)
            if bbox and text:
                items.append({"text": text, "bbox": bbox})

            for key, value in data.items():
                if key in {"images", "outputImages"}:
                    continue
                cls._walk_text_items(value, items)
            return

        if isinstance(data, list):
            for item in data:
                cls._walk_text_items(item, items)

    @staticmethod
    def extract_candidate_text(data):
        if not isinstance(data, dict):
            return ""

        for key in ("text", "rec_text", "transcription", "content", "value"):
            value = data.get(key)
            if (
                isinstance(value, str)
                and value.strip()
                and not value.strip().startswith(("http://", "https://"))
            ):
                return value.strip()
        return ""

    @classmethod
    def extract_image_size(cls, data):
        size = cls._walk_for_image_size(data)
        if size:
            return size
        return 0, 0

    @classmethod
    def collect_texts(cls, data):
        """从常见 OCR API 返回结构中尽量提取文字"""
        texts = []

        if isinstance(data, dict):
            result = data.get("result")
            if isinstance(result, dict):
                layout_results = result.get("layoutParsingResults")
                if isinstance(layout_results, list):
                    for item in layout_results:
                        markdown = item.get("markdown", {})
                        if not isinstance(markdown, dict):
                            continue
                        text = markdown.get("text", "")
                        if isinstance(text, str) and text.strip():
                            texts.append(text.strip())
                    if texts:
                        return texts

        cls._walk_texts(data, texts)
        # 去掉空值并保留顺序
        return [item.strip() for item in texts if isinstance(item, str) and item.strip()]

    @classmethod
    def _walk_for_image_size(cls, data):
        if isinstance(data, dict):
            width = data.get("width")
            height = data.get("height")
            if isinstance(width, (int, float)) and isinstance(height, (int, float)) and width > 0 and height > 0:
                return int(width), int(height)
            for value in data.values():
                found = cls._walk_for_image_size(value)
                if found:
                    return found
            return None

        if isinstance(data, list):
            for item in data:
                found = cls._walk_for_image_size(item)
                if found:
                    return found
        return None

    @classmethod
    def _walk_texts(cls, data, texts):
        if isinstance(data, dict):
            preferred_keys = [
                "text",
                "rec_text",
                "transcription",
                "content",
                "value",
            ]

            for key in preferred_keys:
                value = data.get(key)
                if (
                    isinstance(value, str)
                    and value.strip()
                    and not value.strip().startswith(("http://", "https://"))
                ):
                    texts.append(value)

            for key, value in data.items():
                if key in {"images", "outputImages"}:
                    continue
                cls._walk_texts(value, texts)
            return

        if isinstance(data, list):
            for item in data:
                cls._walk_texts(item, texts)
            return

        if (
            isinstance(data, str)
            and data.strip()
            and not data.strip().startswith(("http://", "https://"))
        ):
            texts.append(data)


@dataclass
class SkillDefinition:
    category: str
    name: str
    description: str
    body: str
    path: str


class SkillLibrary:
    """从本地 skill 目录加载提示词技能定义"""

    CATEGORY_NAMES = ("techniques", "reply-styles", "language-styles")

    def __init__(self, root_dir):
        self.root_dir = Path(root_dir)
        self.skills = {category: {} for category in self.CATEGORY_NAMES}
        self.load_errors = []
        self.load()

    @staticmethod
    def _normalize_line_text(value, field_name):
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field_name} 不能为空")
        return " ".join(text.replace("\r", "\n").splitlines()).strip()

    @staticmethod
    def _slugify(name):
        candidate = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", str(name or "").strip().lower())
        candidate = re.sub(r"-{2,}", "-", candidate).strip("-")
        if not candidate:
            raise ValueError("name 无法生成有效目录名")
        return candidate

    def load(self):
        self.skills = {category: {} for category in self.CATEGORY_NAMES}
        self.load_errors = []

        if not self.root_dir.exists():
            return

        for category in self.CATEGORY_NAMES:
            category_dir = self.root_dir / category
            if not category_dir.exists():
                continue

            for skill_dir in sorted(path for path in category_dir.iterdir() if path.is_dir()):
                skill_md_path = skill_dir / "SKILL.md"
                if not skill_md_path.exists():
                    continue

                try:
                    skill = self._parse_skill(skill_md_path, category)
                except Exception as exc:
                    self.load_errors.append(f"{skill_md_path}: {str(exc)}")
                    continue

                if skill is not None:
                    self.skills[category][skill.name] = skill

    def reload(self):
        self.load()
        return {
            "skills_count": self.count_skills(),
            "load_errors": list(self.load_errors),
        }

    def save_skill(self, category, name, description, body):
        category_name = str(category or "").strip()
        if category_name not in self.CATEGORY_NAMES:
            valid_categories = ", ".join(self.CATEGORY_NAMES)
            raise ValueError(f"category 非法：{category_name}，可选值：{valid_categories}")

        skill_name = self._normalize_line_text(name, "name")
        skill_description = self._normalize_line_text(description, "description")
        skill_body = str(body or "").strip()
        if not skill_body:
            raise ValueError("body 不能为空")

        slug = self._slugify(skill_name)
        skill_dir = self.root_dir / category_name / slug
        skill_path = skill_dir / "SKILL.md"
        existed_before = skill_path.exists()

        skill_dir.mkdir(parents=True, exist_ok=True)
        frontmatter_lines = [
            "---",
            f"name: {skill_name}",
            f"description: {skill_description}",
            "---",
            "",
            skill_body,
            "",
        ]
        skill_path.write_text("\n".join(frontmatter_lines), encoding="utf-8")

        return {
            "category": category_name,
            "name": skill_name,
            "description": skill_description,
            "slug": slug,
            "path": str(skill_path),
            "created": not existed_before,
            "updated": existed_before,
        }

    def count_skills(self):
        return sum(len(items) for items in self.skills.values())

    def has_skills(self):
        return self.count_skills() > 0

    def get(self, category, name):
        return self.skills.get(category, {}).get(name)

    @staticmethod
    def _parse_skill(skill_md_path, category):
        content = skill_md_path.read_text(encoding="utf-8").strip()
        lines = content.splitlines()
        if len(lines) < 3 or lines[0].strip() != "---":
            raise ValueError("SKILL.md 缺少合法 frontmatter")

        closing_index = None
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                closing_index = index
                break

        if closing_index is None:
            raise ValueError("SKILL.md frontmatter 未正确闭合")

        metadata = {}
        for line in lines[1:closing_index]:
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            metadata[key.strip()] = value.strip().strip("'\"")

        name = metadata.get("name", "").strip()
        description = metadata.get("description", "").strip()
        body = "\n".join(lines[closing_index + 1:]).strip()

        if not name:
            raise ValueError("缺少 name")
        if not description:
            raise ValueError("缺少 description")
        if not body:
            raise ValueError("缺少 body")

        return SkillDefinition(
            category=category,
            name=name,
            description=description,
            body=body,
            path=str(skill_md_path),
        )


class MemoryManager:
    """本地 JSON 记忆管理器：持久化 Persona 与最近对话。"""

    DEFAULT_PERSONA = ""
    MAX_EXCHANGES = 10

    def __init__(self, store_path=MEMORY_STORE_PATH, max_exchanges=MAX_EXCHANGES):
        self.store_path = Path(store_path)
        self.max_exchanges = max(1, int(max_exchanges or self.MAX_EXCHANGES))
        self._lock = threading.RLock()
        self._data = {
            "persona": self.DEFAULT_PERSONA,
            "history": [],
        }
        self._load_from_disk()

    @staticmethod
    def _normalize_text(value):
        return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()

    def _normalize_exchange(self, exchange):
        if not isinstance(exchange, dict):
            return None

        user_text = self._normalize_text(
            exchange.get("user", exchange.get("user_text", exchange.get("input", "")))
        )
        assistant_text = self._normalize_text(
            exchange.get("assistant", exchange.get("assistant_text", exchange.get("output", "")))
        )
        if not user_text and not assistant_text:
            return None

        try:
            timestamp = int(exchange.get("timestamp", time.time()))
        except (TypeError, ValueError):
            timestamp = int(time.time())

        return {
            "timestamp": timestamp,
            "user": user_text,
            "assistant": assistant_text,
        }

    def _normalize_snapshot(self, raw_data):
        if not isinstance(raw_data, dict):
            return {
                "persona": self.DEFAULT_PERSONA,
                "history": [],
            }

        persona = self._normalize_text(raw_data.get("persona", self.DEFAULT_PERSONA))
        history = []
        for item in raw_data.get("history", []):
            normalized_item = self._normalize_exchange(item)
            if normalized_item is not None:
                history.append(normalized_item)

        if len(history) > self.max_exchanges:
            history = history[-self.max_exchanges:]

        return {
            "persona": persona,
            "history": history,
        }

    def _write_to_disk_unlocked(self):
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.store_path.with_suffix(self.store_path.suffix + ".tmp")
        payload = json.dumps(self._data, ensure_ascii=False, indent=2)
        temp_path.write_text(payload, encoding="utf-8")
        os.replace(temp_path, self.store_path)

    def _load_from_disk(self):
        with self._lock:
            if not self.store_path.exists():
                self._data = {
                    "persona": self.DEFAULT_PERSONA,
                    "history": [],
                }
                return

            try:
                raw = json.loads(self.store_path.read_text(encoding="utf-8"))
            except Exception:
                raw = {}

            self._data = self._normalize_snapshot(raw)

    def get_snapshot(self):
        with self._lock:
            return {
                "persona": self._data.get("persona", self.DEFAULT_PERSONA),
                "history": [dict(item) for item in self._data.get("history", [])],
            }

    def get_persona(self):
        with self._lock:
            return self._data.get("persona", self.DEFAULT_PERSONA)

    def set_persona(self, persona):
        with self._lock:
            self._data["persona"] = self._normalize_text(persona)
            self._write_to_disk_unlocked()
            return self._data["persona"]

    def get_history(self):
        with self._lock:
            return [dict(item) for item in self._data.get("history", [])]

    def replace_history(self, history):
        with self._lock:
            normalized = []
            for item in history or []:
                normalized_item = self._normalize_exchange(item)
                if normalized_item is not None:
                    normalized.append(normalized_item)
            if len(normalized) > self.max_exchanges:
                normalized = normalized[-self.max_exchanges:]
            self._data["history"] = normalized
            self._write_to_disk_unlocked()
            return [dict(item) for item in self._data["history"]]

    def append_exchange(self, user_text, assistant_text):
        with self._lock:
            exchange = self._normalize_exchange(
                {
                    "timestamp": int(time.time()),
                    "user": user_text,
                    "assistant": assistant_text,
                }
            )
            if exchange is None:
                return [dict(item) for item in self._data.get("history", [])]

            history = list(self._data.get("history", []))
            history.append(exchange)
            if len(history) > self.max_exchanges:
                history = history[-self.max_exchanges:]
            self._data["history"] = history
            self._write_to_disk_unlocked()
            return [dict(item) for item in history]

    def clear(self):
        with self._lock:
            self._data = {
                "persona": self.DEFAULT_PERSONA,
                "history": [],
            }
            self._write_to_disk_unlocked()


class PromptAssembler:
    """将技巧、回复风格、语言风格组合成最终提示词"""

    DEFAULT_REPLY_STYLES = ("稳妥版", "自然版", "加分版")
    DOCUMENT_CONTEXT_LIMIT = 14000
    STYLE_PRESET_MAP = {
        "稳妥版": {
            "technique": "workplace-bluf-reply",
            "reply_style": "steady-professional",
            "language_style": "clear-structured-zh",
        },
        "自然版": {
            "technique": "empathy-first-response",
            "reply_style": "warm-supportive",
            "language_style": "concise-wechat-zh",
        },
        "加分版": {
            "technique": "empathy-first-response",
            "reply_style": "light-humor",
            "language_style": "lively-natural-zh",
        },
    }
    _memory_manager = None

    def __init__(self, skill_library, memory_manager=None):
        self.skill_library = skill_library
        if memory_manager is not None:
            self.__class__._memory_manager = memory_manager

    @classmethod
    def _get_memory_manager(cls):
        if cls._memory_manager is None:
            cls._memory_manager = MemoryManager()
        return cls._memory_manager

    @classmethod
    def _format_memory_context(cls):
        memory_manager = cls._get_memory_manager()
        snapshot = memory_manager.get_snapshot()
        persona = str(snapshot.get("persona", "")).strip()
        history = snapshot.get("history") or []
        lines = []

        if persona:
            lines.append("【用户 Persona】")
            lines.append(persona)

        if history:
            lines.append("【最近对话记忆】")
            for index, exchange in enumerate(history[-memory_manager.max_exchanges:], start=1):
                user_text = str(exchange.get("user", "")).strip()
                assistant_text = str(exchange.get("assistant", "")).strip()
                if user_text:
                    lines.append(f"{index}. 用户：{user_text}")
                if assistant_text:
                    lines.append(f"{index}. 助手：{assistant_text}")

        if not lines:
            return ""

        return "以下是长期上下文，请在满足任务要求前提下参考：\n" + "\n".join(lines)

    @classmethod
    def prepend_memory_context(cls, system_prompt):
        memory_context = cls._format_memory_context()
        prompt_text = str(system_prompt or "").strip()
        if not memory_context:
            return prompt_text
        if not prompt_text:
            return memory_context
        return f"{memory_context}\n\n{prompt_text}"

    def has_skills(self):
        return self.skill_library.has_skills()

    def count_skills(self):
        return self.skill_library.count_skills()

    def reload_skills(self):
        return self.skill_library.reload()

    @classmethod
    def resolve_style_name(cls, style_name):
        raw_style = (style_name or "").strip()
        if raw_style in cls.STYLE_PRESET_MAP:
            return raw_style
        if any(token in raw_style for token in ("稳", "礼貌", "正式")):
            return "稳妥版"
        if any(token in raw_style for token in ("加分", "幽默", "亮点")):
            return "加分版"
        return "自然版"

    def _resolve_preset(self, style_name):
        return self.STYLE_PRESET_MAP[self.resolve_style_name(style_name)]

    def _skill_section(self, title, category, name):
        skill = self.skill_library.get(category, name)
        if skill is None:
            return f"### {title}\n未找到 {category}/{name}，请保持原有中文高情商回复标准。"

        return (
            f"### {title}\n"
            f"名称：{skill.name}\n"
            f"用途：{skill.description}\n"
            f"{skill.body}"
        )

    def _style_instruction_block(self, style_name):
        preset = self._resolve_preset(style_name)
        sections = [
            self._skill_section("会话技巧", "techniques", preset["technique"]),
            self._skill_section("回复风格", "reply-styles", preset["reply_style"]),
            self._skill_section("语言风格", "language-styles", preset["language_style"]),
        ]
        return f"## {style_name}\n" + "\n\n".join(sections)

    @staticmethod
    def format_conversation_context(conversation):
        if not isinstance(conversation, dict):
            return ""

        messages = conversation.get("messages") or []
        if not messages:
            return ""

        label_map = {
            "other": "对方",
            "self": "我",
            "system": "系统",
            "unknown": "未分类",
        }

        lines = []
        for index, message in enumerate(messages, start=1):
            text = str(message.get("text", "")).strip()
            if not text:
                continue
            label = label_map.get(message.get("sender", "unknown"), "未分类")
            lines.append(f"{index}. {label}: {text}")

        if not lines:
            return ""

        return (
            "聊天结构如下。`对方/我/系统` 标签是基于 OCR 文本框坐标做出的左右归类推断；"
            "优先参考这个结构来理解谁说了什么，再结合原始 OCR 文本修正细节。\n"
            + "\n".join(lines)
        )

    @staticmethod
    def extract_focus_terms(text):
        raw_tokens = re.findall(r"[A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", (text or "").lower())
        stopwords = {
            "请", "帮我", "一下", "这个", "那个", "哪些", "什么", "怎么", "以及", "然后",
            "文件", "文档", "内容", "信息", "提取", "总结", "概括", "说明", "解释", "看看",
        }
        focus_terms = []
        for token in raw_tokens:
            token = token.strip()
            if not token or token in stopwords or token in focus_terms:
                continue
            focus_terms.append(token)
            if len(focus_terms) >= 10:
                break
        return focus_terms

    @classmethod
    def select_document_context(cls, document, focus="", max_chars=None):
        if not isinstance(document, dict):
            return ""

        text = str(document.get("text", "")).strip()
        if not text:
            return ""

        limit = max_chars or cls.DOCUMENT_CONTEXT_LIMIT
        if len(text) <= limit:
            return text

        chunks = [chunk.strip() for chunk in re.split(r"\n{2,}", text) if chunk.strip()]
        if not chunks:
            return text[:limit].strip()

        focus_terms = cls.extract_focus_terms(focus)
        scored = []
        for index, chunk in enumerate(chunks):
            lowered = chunk.lower()
            score = 0
            for term in focus_terms:
                score += lowered.count(term) * 3
            if index < 2:
                score += 2
            if index == len(chunks) - 1:
                score += 1
            scored.append((score, index, chunk))

        ordered_indices = []
        seen = set()
        for preferred in (0, 1, len(chunks) - 1):
            if 0 <= preferred < len(chunks) and preferred not in seen:
                ordered_indices.append(preferred)
                seen.add(preferred)

        for _, index, _ in sorted(scored, key=lambda item: (-item[0], item[1])):
            if index in seen:
                continue
            ordered_indices.append(index)
            seen.add(index)

        selected_chunks = []
        total_length = 0
        for index in sorted(ordered_indices):
            chunk = chunks[index]
            next_length = total_length + len(chunk) + (2 if selected_chunks else 0)
            if selected_chunks and next_length > limit:
                continue
            selected_chunks.append(chunk)
            total_length = next_length
            if total_length >= limit:
                break

        context = "\n\n".join(selected_chunks).strip()
        if len(context) < len(text):
            context += "\n\n[提示] 文档过长，以上为与任务最相关的节选。"
        return context

    @classmethod
    def format_document_context(cls, document, focus=""):
        if not isinstance(document, dict):
            return ""

        excerpt = cls.select_document_context(document, focus=focus)
        if not excerpt:
            return ""

        file_name = document.get("file_name", "未命名文件")
        meta_text = document.get("meta_text", "")
        sections = [f"文件名：{file_name}"]
        if meta_text:
            sections.append(meta_text)
        sections.append("文档内容如下：")
        sections.append(excerpt)
        return "\n".join(sections)

    @classmethod
    def build_document_summary_messages(cls, document):
        document_context = cls.format_document_context(document, focus="概括 总结 核心 内容")
        system_prompt = (
            "你是一位中文文档阅读助手。\n"
            "请基于提供的文档内容输出 3 到 4 张卡片，帮助用户快速理解文件。\n"
            "卡片标题尽量覆盖：一句话概括、核心内容、关键细节、后续行动/风险。\n"
            "不要输出 Markdown，不要解释过程，不要编造文档里没有出现的信息。\n"
            '必须严格返回 JSON：{"cards":[{"title":"标题","text":"内容"}]}'
        )
        system_prompt = cls.prepend_memory_context(system_prompt)
        user_prompt = (
            f"{document_context}\n\n"
            "请输出适合直接展示在浮窗里的文件概括卡片。"
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    @classmethod
    def build_document_terms_messages(cls, document):
        document_context = cls.format_document_context(document, focus="术语 专有名词 名词解释 缩写 概念")
        system_prompt = (
            "你是一位中文文档阅读助手。\n"
            "请从文档中挑选 4 到 6 个最值得解释的专有名词、缩写或专业概念。\n"
            "每张卡片的 title 直接写术语名称，text 用 1 到 2 句话解释它在当前文档里的含义、作用或上下文。\n"
            "如果文档明显没有专业术语，就挑选最关键的关键词，不要编造背景知识。\n"
            '必须严格返回 JSON：{"cards":[{"title":"术语名","text":"解释"}]}'
        )
        system_prompt = cls.prepend_memory_context(system_prompt)
        user_prompt = (
            f"{document_context}\n\n"
            "请输出适合直接展示的术语解释卡片。"
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    @classmethod
    def build_document_extract_messages(cls, document):
        document_context = cls.format_document_context(document, focus="提取 关键信息 时间 金额 责任 交付 结论 行动项")
        system_prompt = (
            "你是一位中文文档阅读助手。\n"
            "请从文档中提取最值得直接拿走使用的关键信息。\n"
            "优先整理：关键结论、时间/金额/数量、责任与交付、需要跟进的事项；没有的项目不要编造。\n"
            "每张卡片都要简洁、可执行。\n"
            '必须严格返回 JSON：{"cards":[{"title":"标题","text":"内容"}]}'
        )
        system_prompt = cls.prepend_memory_context(system_prompt)
        user_prompt = (
            f"{document_context}\n\n"
            "请输出 3 到 5 张关键提取卡片。"
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    @classmethod
    def build_document_question_messages(cls, document, question):
        normalized_question = (question or "").strip()
        document_context = cls.format_document_context(document, focus=normalized_question)
        system_prompt = (
            "你是一位中文文档问答助手。\n"
            "请只基于提供的文档内容回答用户问题；如果文档里没有明确答案，直接说明未提及。\n"
            "返回 2 到 3 张卡片，至少包含：问题回答、定位依据；必要时补充后续建议。\n"
            "不要输出 Markdown，不要编造。\n"
            '必须严格返回 JSON：{"cards":[{"title":"标题","text":"内容"}]}'
        )
        system_prompt = cls.prepend_memory_context(system_prompt)
        user_prompt = (
            f"{document_context}\n\n"
            f"用户问题：{normalized_question}\n"
            "请直接给出可展示的回答卡片。"
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    @classmethod
    def build_resume_analysis_messages(cls, document):
        document_context = cls.format_document_context(
            document,
            focus="简历 候选人 经历 项目 技能 业绩 亮点 风险 面试"
        )
        system_prompt = (
            "你是一位资深招聘顾问与面试官。\n"
            "请只基于简历内容，输出 4 到 6 张可直接用于评估候选人的卡片。\n"
            "优先覆盖：候选人画像、核心优势、岗位匹配度、潜在风险/疑问、面试追问建议、简历优化建议。\n"
            "若文档信息不足，请明确写出“信息不足”而不是编造。\n"
            "不要输出 Markdown，不要解释过程。\n"
            '必须严格返回 JSON：{"cards":[{"title":"标题","text":"内容"}]}'
        )
        system_prompt = cls.prepend_memory_context(system_prompt)
        user_prompt = (
            f"{document_context}\n\n"
            "请输出简历分析卡片。"
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    @classmethod
    def build_contract_risk_messages(cls, document):
        document_context = cls.format_document_context(
            document,
            focus="合同 条款 风险 违约 付款 交付 保密 知识产权 争议 解除 责任"
        )
        system_prompt = (
            "你是一位合同审阅助手。\n"
            "请只基于提供的合同内容，输出 4 到 6 张风险审阅卡片。\n"
            "优先覆盖：关键风险点、触发条件、可能影响、建议动作/补充条款。\n"
            "若文档未提及某类风险，请直接写“文档未提及”，不要编造。\n"
            "不要输出 Markdown，不要给法律结论性建议，只做文本风险提示。\n"
            '必须严格返回 JSON：{"cards":[{"title":"标题","text":"内容"}]}'
        )
        system_prompt = cls.prepend_memory_context(system_prompt)
        user_prompt = (
            f"{document_context}\n\n"
            "请输出合同风险审阅卡片。"
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def build_reply_messages(self, text, instruction="", conversation=None):
        if not self.has_skills():
            return self.build_legacy_reply_messages(text, instruction, conversation)

        style_blocks = [
            self._style_instruction_block(style_name)
            for style_name in self.DEFAULT_REPLY_STYLES
        ]
        conversation_context = self.format_conversation_context(conversation)
        system_prompt = (
            "你是一位高情商中文聊天助手。\n"
            "请基于同一段聊天内容，生成 3 条可以直接发送的中文回复。\n"
            "3 条回复的 style 必须固定为：稳妥版、自然版、加分版。\n"
            "每个 style 只输出 1 条回复，且三条回复的表达不要互相重复。\n"
            "默认把最近一条来自“对方”的消息视为待回复目标；如果上下文明显表明应回复更早内容，再自行调整。\n"
            "如果技能说明与额外要求之间存在张力，优先保证安全、清晰、关系维护，再尽量吸收额外要求。\n"
            "不要解释，不要分析，不要使用 Markdown，不要输出 JSON 之外的内容。\n"
            "必须严格按照以下 JSON 格式返回："
            '{"replies": [{"style": "稳妥版", "text": "内容..."}, {"style": "自然版", "text": "内容..."}, {"style": "加分版", "text": "内容..."}]}'
            "\n\n下面是 3 个 style 的技能约束，请分别遵守：\n\n"
            + "\n\n".join(style_blocks)
        )
        system_prompt = self.prepend_memory_context(system_prompt)
        user_sections = []
        if conversation_context:
            user_sections.append(conversation_context)
        user_sections.append(f"原始 OCR 文本如下：\n{text}")
        user_sections.append(
            f"额外要求：{instruction or '默认输出自然、可直接发送的中文回复。'}"
        )
        user_sections.append("请只返回 JSON。")
        user_content = "\n\n".join(user_sections)
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

    def build_rewrite_messages(self, text, style, current_reply, conversation=None):
        if not self.has_skills():
            return self.build_legacy_rewrite_messages(text, style, current_reply, conversation)

        normalized_style = self.resolve_style_name(style)
        conversation_context = self.format_conversation_context(conversation)
        system_prompt = (
            "你是一位高情商中文聊天助手。\n"
            f"请把当前回复改写成一个新的版本，并保持 style 固定为：{normalized_style}。\n"
            "新版本必须保留原回复的核心意图、场景适配性和可直接发送性，但要明显换一种自然表达。\n"
            "如果聊天结构中区分了“对方”和“我”，请继续以“对方”的最新消息为回复对象理解上下文。\n"
            "不要解释，不要分析，不要使用 Markdown，不要输出 JSON 之外的内容。\n"
            f'必须严格按照以下 JSON 格式返回：{{"reply": {{"style": "{normalized_style}", "text": "内容..."}}}}'
            "\n\n下面是这条回复必须遵守的技能约束：\n\n"
            + self._style_instruction_block(normalized_style)
        )
        system_prompt = self.prepend_memory_context(system_prompt)
        user_sections = []
        if conversation_context:
            user_sections.append(conversation_context)
        user_sections.append(f"原始 OCR 文本如下：\n{text}")
        user_sections.append(f"目标 style：{normalized_style}")
        user_sections.append(f"当前回复：{current_reply}")
        user_sections.append("请在不改变核心立场的前提下，重写成新的版本。")
        user_content = "\n\n".join(user_sections)
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

    @staticmethod
    def build_legacy_reply_messages(text, instruction="", conversation=None):
        conversation_context = PromptAssembler.format_conversation_context(conversation)
        system_prompt = (
            "你是一位高情商中文聊天助手。"
            "请根据用户提供的聊天内容，输出 3 条可以直接发送的中文回复。"
            "3 条回复的 style 必须固定为：稳妥版、自然版、加分版。"
            "不要解释，不要分析，不要使用 Markdown。"
            "必须严格按照以下 JSON 格式返回："
            '{"replies": [{"style": "稳妥版", "text": "内容..."}, {"style": "自然版", "text": "内容..."}, {"style": "加分版", "text": "内容..."}]}'
        )
        system_prompt = PromptAssembler.prepend_memory_context(system_prompt)
        user_sections = []
        if conversation_context:
            user_sections.append(conversation_context)
        user_sections.append(f"聊天背景文字如下：\n{text}")
        user_sections.append(
            f"额外要求：{instruction or '默认输出自然、可直接发送的中文回复。'}"
        )
        user_sections.append("请只返回 JSON。")
        return [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": "\n\n".join(user_sections),
            },
        ]

    @staticmethod
    def build_legacy_rewrite_messages(text, style, current_reply, conversation=None):
        conversation_context = PromptAssembler.format_conversation_context(conversation)
        system_prompt = (
            "你是一位高情商中文聊天助手。"
            "请把当前回复改写成一个新的版本，保留同样的 style。"
            "不要解释，不要分析，不要使用 Markdown。"
            "必须严格按照以下 JSON 格式返回："
            '{"reply": {"style": "稳妥版", "text": "内容..."}}'
        )
        system_prompt = PromptAssembler.prepend_memory_context(system_prompt)
        user_sections = []
        if conversation_context:
            user_sections.append(conversation_context)
        user_sections.append(f"聊天背景文字如下：\n{text}")
        user_sections.append(f"目标风格：{style}")
        user_sections.append(f"当前回复：{current_reply}")
        user_sections.append("请改写成新的版本。")
        return [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": "\n\n".join(user_sections),
            },
        ]


PROMPT_ASSEMBLER = PromptAssembler(
    SkillLibrary(SKILL_LIBRARY_ROOT),
    memory_manager=MemoryManager(),
)

# ==========================================
# 模块 B0: 常驻屏幕上下文监控线程
# ==========================================
class ScreenContextMonitor(QThread):
    """后台轮询全屏截图，维护最新一帧 PNG 二进制缓冲。"""

    frame_updated = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)

    def __init__(self, fps=1.0, parent=None):
        super().__init__(parent)
        safe_fps = float(fps) if fps else 1.0
        if safe_fps <= 0:
            safe_fps = 1.0
        self._interval_seconds = 1.0 / safe_fps
        self._stop_event = threading.Event()
        self._frame_lock = threading.Lock()
        self._latest_frame_png = b""
        self._latest_frame_meta = {
            "backend": "",
            "frame_width": 0,
            "frame_height": 0,
            "captured_at": 0.0,
            "ready": False,
            "frame_size_bytes": 0,
        }
        self._backend = ""
        self._backend_error = ""

    def start_monitoring(self):
        """主线程安全调用：启动监控线程（若未运行）。"""
        if self.isRunning():
            return False
        self._stop_event.clear()
        self.start()
        return True

    def stop(self, timeout_ms=1500):
        """请求线程停止并等待退出。"""
        self._stop_event.set()
        if not self.isRunning():
            return True
        return self.wait(timeout_ms)

    def stop_monitoring(self, wait_ms=2000):
        """兼容旧接口。"""
        return self.stop(timeout_ms=wait_ms)

    def latest_frame_bytes(self):
        """同步读取最新 PNG 帧（bytes），用于主线程按需消费。"""
        with self._frame_lock:
            if not self._latest_frame_png:
                return b""
            return bytes(self._latest_frame_png)

    def get_latest_frame_bytes(self):
        """兼容旧接口。"""
        return self.latest_frame_bytes()

    def latest_frame_meta(self):
        """读取最新帧元数据，不触发任何 UI 变更。"""
        with self._frame_lock:
            return dict(self._latest_frame_meta)

    def get_latest_frame_meta(self):
        """兼容旧接口。"""
        return self.latest_frame_meta()

    def clear_buffer(self):
        """清空最近一帧缓存。"""
        with self._frame_lock:
            self._latest_frame_png = b""
            self._latest_frame_meta = {
                "backend": self._backend,
                "frame_width": 0,
                "frame_height": 0,
                "captured_at": 0.0,
                "ready": False,
                "frame_size_bytes": 0,
            }

    def get_backend_status(self):
        return {
            "backend": self._backend,
            "error": self._backend_error,
            "available": bool(self._backend),
        }

    def run(self):
        backend_name = self._detect_backend()
        if not backend_name:
            self.error_occurred.emit(
                self._backend_error
                or "未检测到可用截图后端（mss 或 Pillow.ImageGrab）。"
            )
            return

        try:
            if backend_name == "mss":
                self._run_mss_loop()
            elif backend_name == "pil":
                self._run_pil_loop()
        except Exception as exc:
            self.error_occurred.emit(f"屏幕监控线程异常: {str(exc)}")

    def _capture_and_publish(self, capture_func):
        while not self._stop_event.is_set():
            try:
                frame_png, frame_width, frame_height = capture_func()
                if frame_png:
                    captured_at = time.time()
                    payload = {
                        "backend": self._backend,
                        "frame_width": int(frame_width or 0),
                        "frame_height": int(frame_height or 0),
                        "captured_at": float(captured_at),
                        "ready": True,
                        "frame_size_bytes": len(frame_png),
                    }
                    with self._frame_lock:
                        self._latest_frame_png = frame_png
                        self._latest_frame_meta = dict(payload)
                    self.frame_updated.emit(payload)
            except Exception as exc:
                self.error_occurred.emit(f"屏幕采集失败: {str(exc)}")
            if self._stop_event.wait(self._interval_seconds):
                break

    def _run_mss_loop(self):
        import mss
        import mss.tools

        self._backend = "mss"
        with mss.mss() as sct:
            monitor = sct.monitors[0]

            def capture_once():
                shot = sct.grab(monitor)
                frame_width, frame_height = shot.size
                frame_png = mss.tools.to_png(shot.rgb, shot.size)
                return frame_png, frame_width, frame_height

            self._capture_and_publish(capture_once)

    def _run_pil_loop(self):
        from PIL import ImageGrab

        self._backend = "pil"

        def capture_once():
            image = ImageGrab.grab(all_screens=True)
            buffer = BytesIO()
            image.save(buffer, format="PNG")
            frame_width, frame_height = image.size
            return buffer.getvalue(), frame_width, frame_height

        self._capture_and_publish(capture_once)

    def _detect_backend(self):
        self._backend = ""
        self._backend_error = ""
        errors = []

        try:
            import mss  # noqa: F401
            import mss.tools  # noqa: F401

            self._backend = "mss"
            return "mss"
        except Exception as exc:
            errors.append(f"mss 不可用: {str(exc)}")

        try:
            from PIL import ImageGrab  # noqa: F401

            self._backend = "pil"
            return "pil"
        except Exception as exc:
            errors.append(f"Pillow.ImageGrab 不可用: {str(exc)}")

        self._backend_error = "；".join(errors)
        return ""

# ==========================================
# 模块 C: 文心一言 API 调用逻辑
# ==========================================
class ERNIEBotClient:
    @staticmethod
    def extract_content(response_data):
        """从 OpenAI 兼容返回结构中提取文本内容"""
        choices = response_data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("模型返回中缺少 choices")

        message = choices[0].get("message", {})
        content = message.get("content", "")

        if isinstance(content, list):
            text_parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text = item.get("text", "")
                    if text:
                        text_parts.append(text)
            content = "".join(text_parts)

        if not isinstance(content, str) or not content.strip():
            raise ValueError("模型未返回有效内容")

        return content.strip()

    @staticmethod
    def parse_json_reply(content):
        """清洗并解析模型返回的 JSON"""
        clean_content = content.replace("```json", "").replace("```", "").strip()

        try:
            return json.loads(clean_content)
        except json.JSONDecodeError:
            start = clean_content.find("{")
            end = clean_content.rfind("}")
            if start == -1 or end == -1 or end <= start:
                raise
            return json.loads(clean_content[start:end + 1])

    @staticmethod
    def post_messages(messages):
        if not BAIDU_ACCESS_TOKEN:
            return {
                "error": "缺少百度 Access Token，请在 .env 文件中填写 BAIDU_ACCESS_TOKEN"
            }

        payload = {
            "model": ERNIE_MODEL,
            "messages": messages,
            "web_search": {
                "enable": ERNIE_WEB_SEARCH_ENABLED
            },
            "max_completion_tokens": 4096,
        }

        try:
            response = requests.post(
                ERNIE_CHAT_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {BAIDU_ACCESS_TOKEN}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            result = response.json()
            content = ERNIEBotClient.extract_content(result)
            return ERNIEBotClient.parse_json_reply(content)
        except Exception as e:
            return {"error": f"API 调用或解析失败: {str(e)}"}

    @staticmethod
    def normalize_cards(result, fallback_title="结果"):
        raw_cards = result.get("cards", [])
        cards = []
        if isinstance(raw_cards, list):
            for index, item in enumerate(raw_cards, start=1):
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title", "")).strip() or f"{fallback_title} {index}"
                text = str(item.get("text", "")).strip()
                if not text:
                    continue
                cards.append({"title": title, "text": text})

        if cards:
            return cards

        for field_name, field_title in (
            ("answer", "问题回答"),
            ("summary", "文件概括"),
            ("content", fallback_title),
            ("text", fallback_title),
        ):
            text_value = str(result.get(field_name, "")).strip()
            if text_value:
                return [{"title": field_title, "text": text_value}]

        return []

    @staticmethod
    def get_replies(text, instruction="", conversation=None):
        """调用文心一言生成回复建议"""
        result = ERNIEBotClient.post_messages(
            PROMPT_ASSEMBLER.build_reply_messages(text, instruction, conversation)
        )
        if "error" in result:
            return result

        raw_replies = result.get("replies", [])
        replies = []
        default_styles = ["稳妥版", "自然版", "加分版"]
        for index, item in enumerate(raw_replies[:3]):
            if not isinstance(item, dict):
                continue
            text_value = str(item.get("text", "")).strip()
            if not text_value:
                continue
            style_value = default_styles[index]
            replies.append({"style": style_value, "text": text_value})

        if not replies:
            return {"error": "模型没有返回可用的回复结果，请重试。"}
        return {"replies": replies}

    @staticmethod
    def rewrite_reply(text, style, current_reply, conversation=None):
        result = ERNIEBotClient.post_messages(
            PROMPT_ASSEMBLER.build_rewrite_messages(text, style, current_reply, conversation)
        )
        if "error" in result:
            return result

        reply = result.get("reply", {})
        text_value = str(reply.get("text", "")).strip()
        if not text_value:
            return {"error": "模型没有返回可用的单条改写结果，请重试。"}
        return {
            "reply": {
                "style": style,
                "text": text_value,
            }
        }

    @staticmethod
    def summarize_document(document):
        result = ERNIEBotClient.post_messages(
            PROMPT_ASSEMBLER.build_document_summary_messages(document)
        )
        if "error" in result:
            return result

        cards = ERNIEBotClient.normalize_cards(result, fallback_title="文件概括")
        if not cards:
            return {"error": "模型没有返回可用的文件概括结果，请重试。"}
        return {"cards": cards}

    @staticmethod
    def explain_document_terms(document):
        result = ERNIEBotClient.post_messages(
            PROMPT_ASSEMBLER.build_document_terms_messages(document)
        )
        if "error" in result:
            return result

        cards = ERNIEBotClient.normalize_cards(result, fallback_title="术语解释")
        if not cards:
            return {"error": "模型没有返回可用的术语解释结果，请重试。"}
        return {"cards": cards}

    @staticmethod
    def extract_document_info(document):
        result = ERNIEBotClient.post_messages(
            PROMPT_ASSEMBLER.build_document_extract_messages(document)
        )
        if "error" in result:
            return result

        cards = ERNIEBotClient.normalize_cards(result, fallback_title="关键信息")
        if not cards:
            return {"error": "模型没有返回可用的关键信息提取结果，请重试。"}
        return {"cards": cards}

    def answer_document_question(document, question):
        result = ERNIEBotClient.post_messages(
            PROMPT_ASSEMBLER.build_document_question_messages(document, question)
        )
        if "error" in result:
            return result

        cards = ERNIEBotClient.normalize_cards(result, fallback_title="文档问答")
        if not cards:
            return {"error": "模型没有返回可用的问答结果，请重试。"}
        return {"cards": cards}

    @staticmethod
    def analyze_resume_document(document):
        result = ERNIEBotClient.post_messages(
            PROMPT_ASSEMBLER.build_resume_analysis_messages(document)
        )
        if "error" in result:
            return result

        cards = ERNIEBotClient.normalize_cards(result, fallback_title="简历分析")
        if not cards:
            return {"error": "模型没有返回可用的简历分析结果，请重试。"}
        return {"cards": cards}

    @staticmethod
    def review_contract_risks(document):
        result = ERNIEBotClient.post_messages(
            PROMPT_ASSEMBLER.build_contract_risk_messages(document)
        )
        if "error" in result:
            return result

        cards = ERNIEBotClient.normalize_cards(result, fallback_title="合同风险")
        if not cards:
            return {"error": "模型没有返回可用的合同风险审阅结果，请重试。"}
        return {"cards": cards}

# ==========================================
# 模块 B & C: 后台处理线程 (OCR + LLM)
# ==========================================
class AIWorker(QThread):
    """异步处理 OCR 和 AI 调用，避免主线程卡死"""
    finished = pyqtSignal(dict)

    def __init__(self, image_data=None, text="", instruction="", mode="bundle",
                 style="", current_reply="", index=-1, conversation=None,
                 file_path="", question="", document=None):
        super().__init__()
        self.image_data = image_data
        self.text = text
        self.instruction = instruction
        self.mode = mode
        self.style = style
        self.current_reply = current_reply
        self.index = index
        self.conversation = conversation
        self.file_path = file_path
        self.question = question
        self.document = document

    def resolve_document(self):
        if isinstance(self.document, dict) and self.document.get("text"):
            return self.document
        if not self.file_path:
            raise ValueError("当前没有可用的文档。")
        return DocumentParser.parse_file(self.file_path)

    def run(self):
        try:
            if self.mode == "rewrite":
                rewrite_result = ERNIEBotClient.rewrite_reply(
                    self.text,
                    self.style,
                    self.current_reply,
                    self.conversation,
                )
                rewrite_result["mode"] = "rewrite"
                rewrite_result["index"] = self.index
                self.finished.emit(rewrite_result)
                return

            if self.mode == "document_load":
                document = self.resolve_document()
                self.finished.emit({
                    "mode": "document_load",
                    "document": document,
                })
                return

            if self.mode == "document_summary":
                document = self.resolve_document()
                result = ERNIEBotClient.summarize_document(document)
                result["mode"] = "document_summary"
                result["document"] = document
                self.finished.emit(result)
                return

            if self.mode == "document_terms":
                document = self.resolve_document()
                result = ERNIEBotClient.explain_document_terms(document)
                result["mode"] = "document_terms"
                result["document"] = document
                self.finished.emit(result)
                return

            if self.mode == "document_extract":
                document = self.resolve_document()
                result = ERNIEBotClient.extract_document_info(document)
                result["mode"] = "document_extract"
                result["document"] = document
                self.finished.emit(result)
                return

            if self.mode == "document_question":
                document = self.resolve_document()
                question = (self.question or "").strip()
                if not question:
                    raise ValueError("请输入问题后再提问。")
                result = ERNIEBotClient.answer_document_question(document, question)
                result["mode"] = "document_question"
                result["document"] = document
                result["question"] = question
                self.finished.emit(result)
                return

            if self.mode in {"document_resume_analysis", "resume_analysis"}:
                document = self.resolve_document()
                result = ERNIEBotClient.analyze_resume_document(document)
                result["mode"] = "document_resume_analysis"
                result["document"] = document
                self.finished.emit(result)
                return

            if self.mode in {
                "document_contract_review",
                "document_contract_risk",
                "contract_review",
                "contract_risk",
            }:
                document = self.resolve_document()
                result = ERNIEBotClient.review_contract_risks(document)
                result["mode"] = "document_contract_review"
                result["document"] = document
                self.finished.emit(result)
                return

            ocr_text = (self.text or "").strip()
            conversation = self.conversation if isinstance(self.conversation, dict) else None
            if self.image_data is not None:
                ocr_client = OCRClient()
                conversation = ocr_client.extract_conversation(self.image_data)
                ocr_text = str(conversation.get("transcript", "")).strip()

            if not ocr_text:
                self.finished.emit({
                    "mode": "bundle",
                    "error": "没有识别到可用文字，请重新截图、贴图，或手动输入文字。",
                    "ocr_text": "",
                    "replies": [],
                    "conversation": conversation,
                })
                return

            ai_result = ERNIEBotClient.get_replies(ocr_text, self.instruction, conversation)
            ai_result["mode"] = "bundle"
            ai_result["ocr_text"] = ocr_text
            ai_result["conversation"] = conversation
            self.finished.emit(ai_result)
        except Exception as e:
            self.finished.emit({
                "mode": self.mode,
                "error": f"后台处理出错: {str(e)}",
                "ocr_text": self.text,
                "replies": [],
                "index": self.index,
                "conversation": self.conversation,
                "document": self.document,
            })

# ==========================================
# 模块 A: 截图工具 (遮罩层)
# ==========================================
