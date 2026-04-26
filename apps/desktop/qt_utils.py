from pathlib import Path

from PyQt5.QtCore import QByteArray, QBuffer, QIODevice

from backend.app.infrastructure.config import DOCUMENT_DROP_EXTENSIONS


def pixmap_to_png_bytes(pixmap):
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    pixmap.save(buffer, "PNG")
    return bytes(data)


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
