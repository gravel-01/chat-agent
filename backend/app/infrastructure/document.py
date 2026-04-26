import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from backend.app.infrastructure.config import DOCUMENT_DROP_EXTENSIONS
from backend.app.shared.text import format_count, truncate_text


def filter_supported_document_paths(paths):
    return [path for path in paths if Path(path).suffix.lower() in DOCUMENT_DROP_EXTENSIONS]


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

        for backend_name, extractor in backends:
            try:
                return extractor(file_path)
            except ModuleNotFoundError:
                continue
            except Exception as exc:
                raise ValueError(f"PDF 解析失败（{backend_name}）：{str(exc)}") from exc

        raise ValueError("当前环境缺少 PDF 解析库，建议先安装 pypdf：pip install pypdf")

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
