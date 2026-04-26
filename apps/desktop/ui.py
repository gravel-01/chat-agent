from PyQt5.QtCore import Qt, QRect, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QGraphicsDropShadowEffect,
)

from .core import (
    clear_layout,
    extract_local_file_paths,
    filter_supported_document_paths,
    format_count,
    pixmap_to_png_bytes,
    truncate_text,
)


class CaptureWindow(QWidget):
    """全屏遮罩截图窗口"""
    shot_taken = pyqtSignal(bytes)
    capture_canceled = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setWindowState(Qt.WindowFullScreen)
        self.setWindowOpacity(0.4) # 稍微调亮一点遮罩，不至于太压抑
        self.setCursor(Qt.CrossCursor)

        self.start_pos = None
        self.end_pos = None
        self.is_drawing = False
        self.is_finished = False

    def paintEvent(self, event):
        if self.is_drawing and self.start_pos and self.end_pos:
            painter = QPainter(self)
            painter.setPen(QPen(QColor("#3b82f6"), 2, Qt.SolidLine)) # 截图框改为现代蓝色
            rect = QRect(self.start_pos, self.end_pos)
            painter.drawRect(rect)
            # 挖空选中区域
            painter.setBrush(QColor(255, 255, 255, 0))
            painter.drawRect(rect)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.start_pos = event.pos()
            self.is_drawing = True

    def mouseMoveEvent(self, event):
        if self.is_drawing:
            self.end_pos = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.end_pos = event.pos()
            self.is_drawing = False
            self.capture()

    def capture(self):
        if not self.start_pos or not self.end_pos:
            self.cancel_capture()
            return

        self.hide()
        x1, y1 = self.start_pos.x(), self.start_pos.y()
        x2, y2 = self.end_pos.x(), self.end_pos.y()
        rect = QRect(min(x1, x2), min(y1, y2), abs(x1 - x2), abs(y1 - y2))
        if rect.width() < 8 or rect.height() < 8:
            self.cancel_capture()
            return

        screen = QApplication.primaryScreen()
        pixmap = screen.grabWindow(0, rect.x(), rect.y(), rect.width(), rect.height())
        if pixmap.isNull():
            self.cancel_capture()
            return

        self.is_finished = True
        self.shot_taken.emit(pixmap_to_png_bytes(pixmap))
        self.close()

    def cancel_capture(self):
        if self.is_finished:
            return
        self.is_finished = True
        self.capture_canceled.emit()
        self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.cancel_capture()


# ==========================================
# 模块 D: 结果浮动窗口 UI
# ==========================================
class DockHandle(QWidget):
    """贴边浮窗把手"""
    capture_requested = pyqtSignal()
    paste_requested = pyqtSignal()
    reopen_requested = pyqtSignal()
    file_pick_requested = pyqtSignal()
    immersive_toggled = pyqtSignal(bool)
    files_dropped = pyqtSignal(list)
    dock_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.drag_offset = None
        self.dock_side = "right"
        self.init_ui()

    def init_ui(self):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground) # 开启透明背景以渲染外阴影
        self.setAcceptDrops(True)
        self.setFixedSize(156, 418)

        self.main_frame = QFrame(self)
        self.main_frame.setGeometry(12, 12, 132, 394)
        self.main_frame.setStyleSheet("""
            QFrame {
                background: rgba(255, 255, 255, 0.98);
                border: 1px solid #e2e8f0;
                border-radius: 20px; /* 更大的圆角呈现果冻感 */
            }
            QFrame#modeCard {
                background: #f8fafc;
                border: 1px solid #e2e8f0;
                border-radius: 14px;
            }
            QPushButton {
                background: #f8fafc;
                border: 1px solid #e2e8f0;
                border-radius: 12px;
                padding: 12px 0; /* 加大按钮垂直内边距 */
                color: #334155;
                font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
                font-size: 14px; /* 字体调大更清晰 */
                font-weight: 600;
            }
            QPushButton:hover { background: #f1f5f9; color: #0f172a; border-color: #cbd5e1; }
            QPushButton:pressed { background: #e2e8f0; }
            QPushButton#captureBtn { background: #3b82f6; border: none; color: white; }
            QPushButton#captureBtn:hover { background: #2563eb; }
            QPushButton#fileBtn { background: #10b981; border: none; color: white; }
            QPushButton#fileBtn:hover { background: #059669; }
            QPushButton#immersiveBtn {
                background: #e2e8f0;
                border: none;
                color: #334155;
                border-radius: 10px;
                padding: 8px 12px;
                font-size: 12px;
            }
            QPushButton#immersiveBtn:hover { background: #cbd5e1; }
            QPushButton#immersiveBtn:checked {
                background: #10b981;
                color: white;
            }
            QPushButton#immersiveBtn:checked:hover { background: #059669; }
            QLabel {
                font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
                color: #475569;
                font-size: 13px; /* 状态栏字号调大 */
                border: none;
                background: transparent;
            }
        """)

        # 更柔和的高级阴影
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(25)
        shadow.setColor(QColor(0, 0, 0, 30))
        shadow.setOffset(0, 8)
        self.main_frame.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self.main_frame)
        # 增加内容区的上下左右留白
        layout.setContentsMargins(16, 20, 16, 20)
        # 增加组件间距
        layout.setSpacing(12)

        self.status_dot = QLabel()
        self.status_dot.setFixedSize(10, 10)
        self.status_label = QLabel("就绪")
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignCenter)

        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(6)
        top_layout.addWidget(self.status_dot)
        top_layout.addWidget(self.status_label)
        top_layout.addStretch()

        capture_btn = QPushButton("截图")
        capture_btn.setObjectName("captureBtn")
        capture_btn.clicked.connect(self.capture_requested.emit)

        paste_btn = QPushButton("贴图")
        paste_btn.clicked.connect(self.paste_requested.emit)

        file_btn = QPushButton("文件")
        file_btn.setObjectName("fileBtn")
        file_btn.clicked.connect(self.file_pick_requested.emit)

        reopen_btn = QPushButton("上次")
        reopen_btn.clicked.connect(self.reopen_requested.emit)

        self.mode_card = QFrame()
        self.mode_card.setObjectName("modeCard")
        mode_layout = QVBoxLayout(self.mode_card)
        mode_layout.setContentsMargins(10, 10, 10, 10)
        mode_layout.setSpacing(8)
        mode_top = QHBoxLayout()
        mode_top.setContentsMargins(0, 0, 0, 0)
        mode_top.setSpacing(6)
        mode_title = QLabel("沉浸模式")
        mode_title.setStyleSheet("font-weight: 700; color: #0f172a; font-size: 12px;")
        self.immersive_btn = QPushButton("已关闭")
        self.immersive_btn.setObjectName("immersiveBtn")
        self.immersive_btn.setCheckable(True)
        self.immersive_btn.toggled.connect(self.immersive_toggled.emit)
        mode_top.addWidget(mode_title)
        mode_top.addStretch()
        mode_top.addWidget(self.immersive_btn)
        self.immersive_note = QLabel("关闭后热键将打开框选截图。")
        self.immersive_note.setWordWrap(True)
        self.immersive_note.setAlignment(Qt.AlignCenter)
        self.immersive_note.setStyleSheet("color: #64748b; font-size: 11px;")
        mode_layout.addLayout(mode_top)
        mode_layout.addWidget(self.immersive_note)

        layout.addLayout(top_layout)
        layout.addWidget(capture_btn)
        layout.addWidget(paste_btn)
        layout.addWidget(file_btn)
        layout.addWidget(reopen_btn)
        layout.addWidget(self.mode_card)
        layout.addStretch(1)

    def set_status(self, status_key, text):
        color = {
            "idle": "#10b981",
            "capturing": "#3b82f6",
            "ocr": "#3b82f6",
            "generating": "#8b5cf6",
            "ready": "#14b8a6",
            "error": "#ef4444",
        }.get(status_key, "#94a3b8")
        self.status_dot.setStyleSheet(f"background: {color}; border-radius: 5px;")

        display_text = text
        if len(text) > 5:
            if "就绪" in text:
                display_text = "就绪"
            elif "生成" in text:
                display_text = "生成中..."
            elif "识别" in text:
                display_text = "识别中..."
            elif "完成" in text:
                display_text = "完成"
        self.status_label.setText(display_text)
        self.setToolTip(text)

    def set_immersive_state(self, enabled, ready, detail):
        self.immersive_btn.blockSignals(True)
        self.immersive_btn.setChecked(bool(enabled))
        self.immersive_btn.blockSignals(False)

        if enabled and ready:
            button_text = "已开启"
        elif enabled:
            button_text = "预热中"
        else:
            button_text = "已关闭"

        info_text = (detail or "").strip() or "关闭后热键将打开框选截图。"
        self.immersive_btn.setText(button_text)
        self.immersive_btn.setToolTip(info_text)
        self.immersive_note.setText(info_text)
        self.immersive_note.setToolTip(info_text)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_offset = event.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self.drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self.drag_offset)

    def mouseReleaseEvent(self, event):
        self.drag_offset = None
        self.dock_changed.emit()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.reopen_requested.emit()

    def dragEnterEvent(self, event):
        paths = filter_supported_document_paths(extract_local_file_paths(event.mimeData()))
        if paths:
            event.acceptProposedAction()
            self.status_label.setText("松手导入")
            return
        event.ignore()

    def dropEvent(self, event):
        paths = filter_supported_document_paths(extract_local_file_paths(event.mimeData()))
        if not paths:
            event.ignore()
            return
        self.files_dropped.emit(paths)
        event.acceptProposedAction()

    def closeEvent(self, event):
        self.hide()
        event.ignore()


class SkillEditorWindow(QWidget):
    save_requested = pyqtSignal(dict)

    CATEGORY_LABELS = {
        "techniques": "技巧",
        "reply-styles": "回复风格",
        "language-styles": "语言风格",
    }

    def __init__(self):
        super().__init__()
        self.selected_category = "techniques"
        self.category_buttons = {}
        self.init_ui()

    def init_ui(self):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(620, 760)

        self.main_frame = QFrame(self)
        self.main_frame.setGeometry(16, 16, 588, 728)
        self.main_frame.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border-radius: 20px;
                border: 1px solid #e2e8f0;
                font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
            }
            QFrame#sectionCard {
                background-color: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 14px;
            }
            QPushButton {
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 10px;
                padding: 8px 14px;
                color: #334155;
                font-weight: 600;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #f8fafc;
                border-color: #94a3b8;
            }
            QPushButton#primaryAction {
                background-color: #3b82f6;
                color: white;
                border: none;
            }
            QPushButton#primaryAction:hover { background-color: #2563eb; }
            QPushButton#categoryChip:checked {
                background-color: #10b981;
                color: white;
                border: none;
            }
            QPushButton#categoryChip:checked:hover { background-color: #059669; }
            QLineEdit, QTextEdit {
                border: 1px solid #cbd5e1;
                border-radius: 10px;
                padding: 10px 12px;
                background: #f8fafc;
                color: #334155;
                font-size: 13px;
            }
            QLineEdit:focus, QTextEdit:focus {
                border: 1px solid #3b82f6;
                background: #ffffff;
            }
            QLabel {
                border: none;
                background: transparent;
                color: #475569;
            }
            QLabel#feedbackBox {
                border-radius: 10px;
                padding: 10px 12px;
                font-size: 12px;
            }
        """)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setColor(QColor(0, 0, 0, 35))
        shadow.setOffset(0, 10)
        self.main_frame.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self.main_frame)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(16)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        title = QLabel("本地 Skill 编辑器")
        title.setStyleSheet("font-weight: 700; font-size: 18px; color: #0f172a;")
        self.header_status = QLabel("创建模式")
        self.header_status.setStyleSheet("color: #047857; background: #d1fae5; border-radius: 6px; padding: 4px 10px; font-size: 12px; font-weight: 700;")
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet("""
            QPushButton { border: none; background: transparent; color: #94a3b8; font-size: 16px; border-radius: 14px; padding: 0; }
            QPushButton:hover { background: #f1f5f9; color: #0f172a; }
        """)
        close_btn.clicked.connect(self.hide)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.header_status)
        header.addWidget(close_btn)
        layout.addLayout(header)

        intro_card = QFrame()
        intro_card.setObjectName("sectionCard")
        intro_layout = QVBoxLayout(intro_card)
        intro_layout.setContentsMargins(16, 16, 16, 16)
        intro_layout.setSpacing(8)
        intro_title = QLabel("把你的经验沉淀成本地提示词")
        intro_title.setStyleSheet("font-weight: 700; color: #0f172a; font-size: 14px;")
        intro_text = QLabel("保存后会写入 skill-data/skills，并立即热重载到当前提示词组装器。")
        intro_text.setWordWrap(True)
        intro_text.setStyleSheet("color: #64748b; font-size: 12px;")
        intro_layout.addWidget(intro_title)
        intro_layout.addWidget(intro_text)
        layout.addWidget(intro_card)

        category_card = QFrame()
        category_card.setObjectName("sectionCard")
        category_layout = QVBoxLayout(category_card)
        category_layout.setContentsMargins(16, 16, 16, 16)
        category_layout.setSpacing(10)
        category_label = QLabel("分类")
        category_label.setStyleSheet("font-weight: 700; color: #0f172a; font-size: 13px;")
        chips = QHBoxLayout()
        chips.setContentsMargins(0, 0, 0, 0)
        chips.setSpacing(10)
        for category, label in self.CATEGORY_LABELS.items():
            button = QPushButton(label)
            button.setObjectName("categoryChip")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, value=category: self.set_category(value))
            self.category_buttons[category] = button
            chips.addWidget(button)
        chips.addStretch()
        category_layout.addWidget(category_label)
        category_layout.addLayout(chips)
        layout.addWidget(category_card)

        name_label = QLabel("名称")
        name_label.setStyleSheet("font-weight: 700; color: #0f172a; font-size: 13px;")
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("例如：steady-professional")
        layout.addWidget(name_label)
        layout.addWidget(self.name_input)

        description_label = QLabel("描述")
        description_label.setStyleSheet("font-weight: 700; color: #0f172a; font-size: 13px;")
        self.description_input = QLineEdit()
        self.description_input.setPlaceholderText("一句话说明这个 Skill 解决什么问题。")
        layout.addWidget(description_label)
        layout.addWidget(self.description_input)

        body_label = QLabel("Prompt Body")
        body_label.setStyleSheet("font-weight: 700; color: #0f172a; font-size: 13px;")
        self.body_input = QTextEdit()
        self.body_input.setPlaceholderText("写入你希望注入模型的提示词正文。")
        self.body_input.setMinimumHeight(280)
        layout.addWidget(body_label)
        layout.addWidget(self.body_input, 1)

        self.feedback_label = QLabel("")
        self.feedback_label.setObjectName("feedbackBox")
        self.feedback_label.setWordWrap(True)
        self.feedback_label.hide()
        layout.addWidget(self.feedback_label)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(10)
        reset_btn = QPushButton("重置")
        reset_btn.clicked.connect(self.reset_form)
        save_btn = QPushButton("保存 Skill")
        save_btn.setObjectName("primaryAction")
        save_btn.clicked.connect(self.emit_save)
        actions.addWidget(reset_btn)
        actions.addStretch()
        actions.addWidget(save_btn)
        layout.addLayout(actions)

        self.set_category(self.selected_category)

    def set_category(self, category):
        self.selected_category = category if category in self.CATEGORY_LABELS else "techniques"
        for current, button in self.category_buttons.items():
            button.blockSignals(True)
            button.setChecked(current == self.selected_category)
            button.blockSignals(False)

    def reset_form(self):
        self.set_category("techniques")
        self.name_input.clear()
        self.description_input.clear()
        self.body_input.clear()
        self.set_feedback("", error=False)
        self.header_status.setText("创建模式")

    def collect_payload(self):
        return {
            "category": self.selected_category,
            "name": self.name_input.text().strip(),
            "description": self.description_input.text().strip(),
            "body": self.body_input.toPlainText().strip(),
        }

    def emit_save(self):
        payload = self.collect_payload()
        if not payload["name"] or not payload["description"] or not payload["body"]:
            self.set_feedback("请完整填写名称、描述和 Prompt Body。", error=True)
            return
        self.header_status.setText("保存中")
        self.set_feedback("", error=False)
        self.save_requested.emit(payload)

    def set_feedback(self, message, error=False):
        text = str(message or "").strip()
        if not text:
            self.feedback_label.hide()
            return
        if error:
            self.feedback_label.setStyleSheet("background: #fef2f2; color: #dc2626; border: 1px solid #fecaca;")
            self.header_status.setText("需要修正")
        else:
            self.feedback_label.setStyleSheet("background: #ecfdf5; color: #047857; border: 1px solid #a7f3d0;")
            self.header_status.setText("已保存")
        self.feedback_label.setText(text)
        self.feedback_label.show()

    def closeEvent(self, event):
        self.hide()
        event.ignore()


class PersonaConfigWindow(QWidget):
    save_requested = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(560, 520)

        self.main_frame = QFrame(self)
        self.main_frame.setGeometry(16, 16, 528, 488)
        self.main_frame.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border-radius: 20px;
                border: 1px solid #e2e8f0;
                font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
            }
            QPushButton {
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 10px;
                padding: 8px 14px;
                color: #334155;
                font-weight: 600;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #f8fafc;
                border-color: #94a3b8;
            }
            QPushButton#primaryAction {
                background-color: #3b82f6;
                color: white;
                border: none;
            }
            QPushButton#primaryAction:hover { background-color: #2563eb; }
            QTextEdit {
                border: 1px solid #cbd5e1;
                border-radius: 10px;
                padding: 12px;
                background: #f8fafc;
                color: #334155;
                font-size: 13px;
            }
            QTextEdit:focus {
                border: 1px solid #3b82f6;
                background: #ffffff;
            }
            QLabel {
                border: none;
                background: transparent;
                color: #475569;
            }
        """)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setColor(QColor(0, 0, 0, 35))
        shadow.setOffset(0, 10)
        self.main_frame.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self.main_frame)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(16)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        title = QLabel("Persona Configuration")
        title.setStyleSheet("font-weight: 700; font-size: 18px; color: #0f172a;")
        self.header_status = QLabel("本地记忆")
        self.header_status.setStyleSheet("color: #1d4ed8; background: #dbeafe; border-radius: 6px; padding: 4px 10px; font-size: 12px; font-weight: 700;")
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet("""
            QPushButton { border: none; background: transparent; color: #94a3b8; font-size: 16px; border-radius: 14px; padding: 0; }
            QPushButton:hover { background: #f1f5f9; color: #0f172a; }
        """)
        close_btn.clicked.connect(self.hide)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.header_status)
        header.addWidget(close_btn)
        layout.addLayout(header)

        intro = QLabel("这里定义你希望模型长期保持的语气、人设和偏好。最近 10 次聊天生成记录会自动写入本地记忆。")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #64748b; font-size: 12px;")
        layout.addWidget(intro)

        self.persona_input = QTextEdit()
        self.persona_input.setPlaceholderText(
            "例如：\n- 我偏好稳重、简洁、克制的表达\n- 尽量先共情，再给建议\n- 避免过度热情或过度强硬"
        )
        layout.addWidget(self.persona_input, 1)

        self.feedback_label = QLabel("")
        self.feedback_label.setWordWrap(True)
        self.feedback_label.hide()
        layout.addWidget(self.feedback_label)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(10)
        close_action = QPushButton("关闭")
        close_action.clicked.connect(self.hide)
        save_btn = QPushButton("保存 Persona")
        save_btn.setObjectName("primaryAction")
        save_btn.clicked.connect(lambda: self.save_requested.emit(self.persona_input.toPlainText().strip()))
        actions.addWidget(close_action)
        actions.addStretch()
        actions.addWidget(save_btn)
        layout.addLayout(actions)

    def set_persona_text(self, text):
        self.persona_input.setPlainText(str(text or ""))

    def set_feedback(self, message, error=False):
        text = str(message or "").strip()
        if not text:
            self.feedback_label.hide()
            return
        if error:
            self.feedback_label.setStyleSheet("background: #fef2f2; color: #dc2626; border: 1px solid #fecaca; border-radius: 10px; padding: 10px 12px; font-size: 12px;")
            self.header_status.setText("需要修正")
        else:
            self.feedback_label.setStyleSheet("background: #ecfdf5; color: #047857; border: 1px solid #a7f3d0; border-radius: 10px; padding: 10px 12px; font-size: 12px;")
            self.header_status.setText("已保存")
        self.feedback_label.setText(text)
        self.feedback_label.show()

    def closeEvent(self, event):
        self.hide()
        event.ignore()


class ResultWindow(QWidget):
    """显示 AI 建议的侧边结果面板"""
    regenerate_requested = pyqtSignal(str)
    save_text_requested = pyqtSignal(str)
    rewrite_requested = pyqtSignal(int, str, str)
    copy_requested = pyqtSignal(str)
    share_requested = pyqtSignal(dict)
    recapture_requested = pyqtSignal()
    file_pick_requested = pyqtSignal()
    files_dropped = pyqtSignal(list)
    skill_editor_requested = pyqtSignal()
    persona_settings_requested = pyqtSignal()
    document_summary_requested = pyqtSignal()
    term_explain_requested = pyqtSignal()
    document_extract_requested = pyqtSignal()
    resume_analysis_requested = pyqtSignal()
    contract_review_requested = pyqtSignal()
    document_question_requested = pyqtSignal(str)
    document_clear_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.current_ocr_text = ""
        self.current_document = None
        self.current_source_type = ""
        self.init_ui()

    def init_ui(self):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAcceptDrops(True)
        self.setFixedSize(510, 750) # 为阴影留出边距

        self.main_frame = QFrame(self)
        self.main_frame.setGeometry(15, 15, 480, 720)
        self.main_frame.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border-radius: 20px;
                border: 1px solid #e2e8f0;
                font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
            }
            QFrame#panelCard {
                background-color: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 12px;
            }
            QFrame#panelCard:hover {
                border: 1px solid #cbd5e1;
            }
            QFrame#dropZone {
                background-color: #f8fafc;
                border: 2px dashed #cbd5e1;
                border-radius: 12px;
            }
            QLabel {
                border: none;
                background: transparent;
            }
            QLabel#sourceChip {
                background-color: #eff6ff;
                color: #2563eb;
                border: 1px solid #bfdbfe;
                border-radius: 6px;
                padding: 4px 8px;
                font-weight: 600;
                font-size: 12px;
            }
            QLabel#summaryBox {
                background-color: #f8fafc;
                border: 1px solid #e2e8f0;
                border-radius: 10px;
                padding: 12px;
                color: #334155;
                font-size: 13px;
                line-height: 1.5;
            }
            QLabel#errorBox {
                background-color: #fef2f2;
                color: #dc2626;
                border: 1px solid #fecaca;
                border-radius: 10px;
                padding: 12px;
                font-size: 13px;
            }
            QPushButton {
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                padding: 6px 12px;
                color: #334155;
                font-weight: 600;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #f8fafc;
                color: #0f172a;
                border-color: #94a3b8;
            }
            QPushButton:pressed { background-color: #e2e8f0; }
            QPushButton#primaryAction {
                background-color: #3b82f6;
                color: white;
                border: none;
            }
            QPushButton#primaryAction:hover { background-color: #2563eb; }
            QPushButton#accentAction {
                background-color: #10b981;
                color: white;
                border: none;
            }
            QPushButton#accentAction:hover { background-color: #059669; }
            QPushButton#dangerAction {
                color: #ef4444;
                border: 1px solid #fca5a5;
            }
            QPushButton#dangerAction:hover {
                background-color: #fef2f2;
                border: 1px solid #ef4444;
            }
            QTextEdit {
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                padding: 8px;
                background: #f8fafc;
                color: #334155;
                font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
                font-size: 13px;
            }
            QTextEdit:focus {
                border: 1px solid #3b82f6;
                background: #ffffff;
            }
            QLineEdit {
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                padding: 8px 12px;
                background: #f8fafc;
                color: #334155;
                font-size: 13px;
            }
            QLineEdit:focus {
                border: 1px solid #3b82f6;
                background: #ffffff;
            }
            /* 滚动条美化 */
            QScrollBar:vertical {
                border: none;
                background: transparent;
                width: 6px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: #cbd5e1;
                min-height: 30px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical:hover {
                background: #94a3b8;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
        """)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(25)
        shadow.setColor(QColor(0, 0, 0, 35))
        shadow.setOffset(0, 8)
        self.main_frame.setGraphicsEffect(shadow)

        self.layout = QVBoxLayout(self.main_frame)
        self.layout.setContentsMargins(20, 20, 20, 20)
        self.layout.setSpacing(14)

        # 头部标题
        title_layout = QHBoxLayout()
        title_label = QLabel("聊天与文档助手")
        title_label.setStyleSheet("font-weight: bold; font-size: 18px; color: #0f172a; border: none;")
        skill_btn = QPushButton("技能库")
        skill_btn.clicked.connect(self.skill_editor_requested.emit)
        settings_btn = QPushButton("设置")
        settings_btn.clicked.connect(self.persona_settings_requested.emit)
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("color: #059669; background: #d1fae5; border-radius: 6px; padding: 4px 10px; font-size: 12px; font-weight: bold; border: none;")
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet("""
            QPushButton { border: none; background: transparent; color: #94a3b8; font-size: 16px; border-radius: 14px; padding: 0; }
            QPushButton:hover { background: #f1f5f9; color: #0f172a; }
        """)
        close_btn.clicked.connect(self.hide)

        title_layout.addWidget(title_label)
        title_layout.addStretch()
        title_layout.addWidget(skill_btn)
        title_layout.addWidget(settings_btn)
        title_layout.addWidget(self.status_label)
        title_layout.addWidget(close_btn)
        self.layout.addLayout(title_layout)

        # 来源信息卡片
        self.source_card = QFrame()
        self.source_card.setObjectName("panelCard")
        source_layout = QVBoxLayout(self.source_card)
        source_layout.setContentsMargins(14, 14, 14, 14)
        source_layout.setSpacing(10)
        source_top = QHBoxLayout()
        self.source_type_label = QLabel("待输入")
        self.source_type_label.setObjectName("sourceChip")
        self.source_name_label = QLabel("截图聊天，或拖入文档开始。")
        self.source_name_label.setWordWrap(True)
        self.source_name_label.setStyleSheet("font-weight: bold; color: #1e293b; border: none; font-size: 14px;")
        source_top.addWidget(self.source_type_label)
        source_top.addWidget(self.source_name_label, 1)
        self.open_file_btn = QPushButton("打开文件")
        self.open_file_btn.setObjectName("accentAction")
        self.open_file_btn.clicked.connect(self.file_pick_requested.emit)
        self.edit_btn = QPushButton("改文字")
        self.edit_btn.clicked.connect(self.toggle_editor)
        self.clear_doc_btn = QPushButton("清空文件")
        self.clear_doc_btn.setObjectName("dangerAction")
        self.clear_doc_btn.clicked.connect(self.document_clear_requested.emit)
        source_top.addWidget(self.open_file_btn)
        source_top.addWidget(self.edit_btn)
        source_top.addWidget(self.clear_doc_btn)
        source_layout.addLayout(source_top)
        self.source_meta_label = QLabel("支持 PDF / DOCX / Markdown / TXT")
        self.source_meta_label.setWordWrap(True)
        self.source_meta_label.setStyleSheet("color: #64748b; border: none; font-size: 12px;")
        source_layout.addWidget(self.source_meta_label)
        self.layout.addWidget(self.source_card)

        # 拖拽提示区
        self.drop_zone = QFrame()
        self.drop_zone.setObjectName("dropZone")
        drop_layout = QVBoxLayout(self.drop_zone)
        drop_layout.setContentsMargins(16, 16, 16, 16)
        drop_layout.setSpacing(6)
        self.drop_zone_title = QLabel("拖入 PDF / DOCX / Markdown")
        self.drop_zone_title.setStyleSheet("font-weight: bold; color: #0f172a; border: none; font-size: 14px;")
        self.drop_zone_title.setAlignment(Qt.AlignCenter)
        self.drop_zone_note = QLabel("也可以点击“打开文件”。支持 .pdf / .docx / .md / .txt")
        self.drop_zone_note.setWordWrap(True)
        self.drop_zone_note.setAlignment(Qt.AlignCenter)
        self.drop_zone_note.setStyleSheet("color: #64748b; border: none; font-size: 12px;")
        drop_layout.addWidget(self.drop_zone_title)
        drop_layout.addWidget(self.drop_zone_note)
        self.layout.addWidget(self.drop_zone)

        # 预览头
        preview_head = QHBoxLayout()
        self.preview_title = QLabel("内容预览")
        self.preview_title.setStyleSheet("font-weight: bold; color: #1e293b; border: none; font-size: 15px;")
        preview_head.addWidget(self.preview_title)
        preview_head.addStretch()
        self.layout.addLayout(preview_head)

        # 内容摘要
        self.summary_label = QLabel("还没有识别内容")
        self.summary_label.setObjectName("summaryBox")
        self.summary_label.setWordWrap(True)
        self.layout.addWidget(self.summary_label)

        # 文本编辑器
        self.editor_wrapper = QFrame()
        editor_layout = QVBoxLayout(self.editor_wrapper)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(8)
        self.editor = QTextEdit()
        self.editor.setFixedHeight(100)
        editor_layout.addWidget(self.editor)
        editor_btns = QHBoxLayout()
        editor_cancel = QPushButton("取消")
        editor_cancel.clicked.connect(lambda: self.toggle_editor(False))
        editor_save = QPushButton("保存并重生成")
        editor_save.setObjectName("primaryAction")
        editor_save.clicked.connect(lambda: self.save_text_requested.emit(self.editor.toPlainText().strip()))
        editor_btns.addWidget(editor_cancel)
        editor_btns.addStretch()
        editor_btns.addWidget(editor_save)
        editor_layout.addLayout(editor_btns)
        self.editor_wrapper.hide()
        self.layout.addWidget(self.editor_wrapper)

        # 文档操作按钮组
        self.document_actions_frame = QFrame()
        doc_actions_layout = QVBoxLayout(self.document_actions_frame)
        doc_actions_layout.setContentsMargins(0, 0, 0, 0)
        doc_actions_layout.setSpacing(10)
        doc_actions_top = QHBoxLayout()
        doc_actions_top.setContentsMargins(0, 0, 0, 0)
        doc_actions_top.setSpacing(10)
        doc_actions_bottom = QHBoxLayout()
        doc_actions_bottom.setContentsMargins(0, 0, 0, 0)
        doc_actions_bottom.setSpacing(10)
        self.summary_btn = QPushButton("概括文件")
        self.summary_btn.clicked.connect(self.document_summary_requested.emit)
        self.terms_btn = QPushButton("术语解释")
        self.terms_btn.clicked.connect(self.term_explain_requested.emit)
        self.extract_btn = QPushButton("提取信息")
        self.extract_btn.clicked.connect(self.document_extract_requested.emit)
        self.resume_btn = QPushButton("分析简历")
        self.resume_btn.clicked.connect(self.resume_analysis_requested.emit)
        self.contract_btn = QPushButton("审查合同")
        self.contract_btn.clicked.connect(self.contract_review_requested.emit)
        for btn in [self.summary_btn, self.terms_btn, self.extract_btn, self.resume_btn, self.contract_btn]:
            btn.setSizePolicy(btn.sizePolicy().Expanding, btn.sizePolicy().Fixed)
        doc_actions_top.addWidget(self.summary_btn)
        doc_actions_top.addWidget(self.terms_btn)
        doc_actions_top.addWidget(self.extract_btn)
        doc_actions_bottom.addWidget(self.resume_btn)
        doc_actions_bottom.addWidget(self.contract_btn)
        doc_actions_layout.addLayout(doc_actions_top)
        doc_actions_layout.addLayout(doc_actions_bottom)
        self.layout.addWidget(self.document_actions_frame)

        # 文档提问
        self.document_question_frame = QFrame()
        question_layout = QHBoxLayout(self.document_question_frame)
        question_layout.setContentsMargins(0, 0, 0, 0)
        question_layout.setSpacing(8)
        self.document_question_input = QLineEdit()
        self.document_question_input.setPlaceholderText("向文档提问，如：提取合同违约责任...")
        self.document_question_input.returnPressed.connect(self.emit_document_question)
        self.ask_btn = QPushButton("发送")
        self.ask_btn.setObjectName("primaryAction")
        self.ask_btn.clicked.connect(self.emit_document_question)
        question_layout.addWidget(self.document_question_input, 1)
        question_layout.addWidget(self.ask_btn)
        self.layout.addWidget(self.document_question_frame)

        # 错误提示框
        self.error_label = QLabel("")
        self.error_label.setObjectName("errorBox")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        self.layout.addWidget(self.error_label)

        # 滚动区域 (卡片容器)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setStyleSheet("background: transparent;")
        self.scroll_content = QWidget()
        self.scroll_content.setStyleSheet("background: transparent;")
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(2, 2, 8, 2)
        self.scroll_layout.setSpacing(12)
        self.scroll_area.setWidget(self.scroll_content)
        self.layout.addWidget(self.scroll_area, 1)

        # 聊天底部操作栏
        self.chat_actions_frame = QFrame()
        bottom_actions = QHBoxLayout(self.chat_actions_frame)
        bottom_actions.setContentsMargins(0, 8, 0, 0)
        bottom_actions.setSpacing(10)
        more_btn = QPushButton("换一换")
        more_btn.clicked.connect(lambda: self.regenerate_requested.emit("请换一组新的表达，尽量不要重复上一轮的措辞。"))
        polite_btn = QPushButton("更稳妥")
        polite_btn.clicked.connect(lambda: self.regenerate_requested.emit("请把 3 条回复整体写得更礼貌、更稳妥，适合职场聊天。"))
        short_btn = QPushButton("更简短")
        short_btn.clicked.connect(lambda: self.regenerate_requested.emit("请把 3 条回复写得更简短，优先一句话就能发出。"))
        capture_btn = QPushButton("重新截图")
        capture_btn.setObjectName("primaryAction")
        capture_btn.clicked.connect(self.recapture_requested.emit)
        for btn in [more_btn, polite_btn, short_btn]:
            btn.setSizePolicy(btn.sizePolicy().Expanding, btn.sizePolicy().Fixed)
            bottom_actions.addWidget(btn)
        bottom_actions.addWidget(capture_btn)
        self.layout.addWidget(self.chat_actions_frame)

        self.clear_doc_btn.hide()
        self.document_actions_frame.hide()
        self.document_question_frame.hide()

    def closeEvent(self, event):
        self.hide()
        event.ignore()

    def toggle_editor(self, visible=None):
        if self.current_source_type == "document":
            return
        should_show = not self.editor_wrapper.isVisible() if visible is None else visible
        self.editor_wrapper.setVisible(should_show)
        if should_show:
            self.editor.setPlainText(self.current_ocr_text)

    def emit_document_question(self):
        self.document_question_requested.emit(self.document_question_input.text().strip())

    def set_document_controls_enabled(self, enabled):
        for widget in (
            self.summary_btn,
            self.terms_btn,
            self.extract_btn,
            self.resume_btn,
            self.contract_btn,
            self.document_question_input,
            self.ask_btn,
        ):
            widget.setEnabled(enabled)

    def render_source_card(self, state):
        document = state.get("document")
        source_type = state.get("source_type") or ("document" if document else "chat" if state.get("ocr_text") else "")

        self.current_document = document
        self.current_source_type = source_type

        if source_type == "document" and document:
            self.source_type_label.setText("文档")
            self.source_name_label.setText(document.get("file_name", "未命名文件"))
            self.source_meta_label.setText(document.get("meta_text", ""))
            self.preview_title.setText("文档预览")
            self.summary_label.setText(document.get("preview", "") or "文档已载入。")
            self.edit_btn.hide()
            self.clear_doc_btn.show()
            self.document_actions_frame.show()
            self.document_question_frame.show()
            self.chat_actions_frame.hide()
            self.drop_zone_title.setText("继续拖入文件可替换当前文档")
            self.drop_zone_note.setText("可以概括文件、解释专有名词，或直接向文档提问。")
            self.editor_wrapper.hide()
            return

        if state.get("ocr_text"):
            self.source_type_label.setText("聊天截图")
            self.source_name_label.setText("当前聊天 OCR 内容")
            message_count = len((state.get("conversation") or {}).get("messages") or [])
            meta_text = f"已识别 {format_count(len(state.get('ocr_text', '')))} 字"
            if message_count:
                meta_text += f" · {message_count} 条消息"
            self.source_meta_label.setText(meta_text)
            self.preview_title.setText("识别文字")
            self.summary_label.setText(truncate_text(state.get("ocr_text", ""), 220) or "还没有识别内容")
            self.edit_btn.show()
            self.clear_doc_btn.hide()
            self.document_actions_frame.hide()
            self.document_question_frame.hide()
            self.chat_actions_frame.show()
            self.drop_zone_title.setText("也可以拖入文件切换到文档模式")
            self.drop_zone_note.setText("支持 PDF / DOCX / Markdown / TXT。")
            return

        self.source_type_label.setText("待输入")
        self.source_name_label.setText("截图聊天，或拖入文档开始。")
        self.source_meta_label.setText("支持 PDF / DOCX / Markdown / TXT")
        self.preview_title.setText("内容预览")
        self.summary_label.setText("还没有可处理的内容。可以先截图聊天，也可以直接拖入文档。")
        self.edit_btn.hide()
        self.clear_doc_btn.hide()
        self.document_actions_frame.hide()
        self.document_question_frame.hide()
        self.chat_actions_frame.show()

    def render_reply_cards(self, replies):
        for index, reply in enumerate(replies):
            card = QFrame()
            card.setObjectName("panelCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 14, 14, 14)
            card_layout.setSpacing(10)

            top = QHBoxLayout()
            tag = QLabel(reply["style"])
            tag.setStyleSheet("background:#eff6ff;color:#2563eb;border-radius:6px;padding:4px 8px;font-weight:bold;font-size:12px;border:none;")

            rewrite_btn = QPushButton("重写")
            rewrite_btn.clicked.connect(lambda checked=False, i=index, s=reply["style"], t=reply["text"]: self.rewrite_requested.emit(i, s, t))

            share_btn = QPushButton("分享")
            share_btn.setObjectName("accentAction")
            share_btn.clicked.connect(
                lambda checked=False, i=index, s=reply["style"], t=reply["text"]: self.share_requested.emit(
                    {
                        "index": i,
                        "style": s,
                        "reply_text": t,
                        "ocr_text": self.current_ocr_text,
                        "source_type": self.current_source_type,
                        "source_name": (self.current_document or {}).get("file_name", ""),
                    }
                )
            )

            copy_btn = QPushButton("复制")
            copy_btn.setObjectName("primaryAction") # 强调动作
            copy_btn.clicked.connect(lambda checked=False, t=reply["text"]: self.copy_requested.emit(t))

            top.addWidget(tag)
            top.addStretch()
            top.addWidget(rewrite_btn)
            top.addWidget(share_btn)
            top.addWidget(copy_btn)

            content = QLabel(reply["text"])
            content.setWordWrap(True)
            content.setTextInteractionFlags(Qt.TextSelectableByMouse)
            content.setStyleSheet("color: #334155; font-size: 14px; line-height: 1.5; border: none;")

            card_layout.addLayout(top)
            card_layout.addWidget(content)
            self.scroll_layout.addWidget(card)

    def render_document_cards(self, cards):
        for item in cards:
            card = QFrame()
            card.setObjectName("panelCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 14, 14, 14)
            card_layout.setSpacing(10)

            top = QHBoxLayout()
            title = QLabel(str(item.get("title", "结果")).strip() or "结果")
            title.setStyleSheet("font-weight:bold;color:#0f172a;font-size:15px;border:none;")

            copy_btn = QPushButton("复制")
            copy_btn.clicked.connect(lambda checked=False, t=item.get("text", ""): self.copy_requested.emit(str(t)))

            top.addWidget(title)
            top.addStretch()
            top.addWidget(copy_btn)

            content = QLabel(str(item.get("text", "")).strip())
            content.setWordWrap(True)
            content.setTextInteractionFlags(Qt.TextSelectableByMouse)
            content.setStyleSheet("color: #475569; font-size: 14px; line-height: 1.5; border: none;")

            card_layout.addLayout(top)
            card_layout.addWidget(content)
            self.scroll_layout.addWidget(card)

    def dragEnterEvent(self, event):
        paths = filter_supported_document_paths(extract_local_file_paths(event.mimeData()))
        if paths:
            event.acceptProposedAction()
            self.drop_zone_title.setText("松手即可导入文件")
            return
        event.ignore()

    def dropEvent(self, event):
        paths = filter_supported_document_paths(extract_local_file_paths(event.mimeData()))
        if not paths:
            event.ignore()
            return
        self.files_dropped.emit(paths)
        self.drop_zone_title.setText("正在准备导入文件...")
        event.acceptProposedAction()

    def show_state(self, state):
        self.current_ocr_text = state["ocr_text"]
        self.status_label.setText(state["status_text"])
        self.render_source_card(state)

        if self.current_source_type != "document" and not self.editor_wrapper.isVisible():
            self.editor.setPlainText(state["ocr_text"])

        if self.current_source_type == "document":
            self.document_question_input.setText(state.get("question_text", ""))

        self.set_document_controls_enabled(bool(state.get("document")) and not state["busy"])

        if not self.editor_wrapper.isVisible():
            self.editor.setPlainText(state["ocr_text"])

        self.error_label.setVisible(bool(state["error"]))
        self.error_label.setText(state["error"])

        clear_layout(self.scroll_layout)

        if state["busy"]:
            loading = QLabel(state["status_text"])
            loading.setWordWrap(True)
            loading.setAlignment(Qt.AlignCenter)
            loading.setStyleSheet("color: #64748b; font-size: 14px; font-weight: bold; margin-top: 20px;")
            self.scroll_layout.addWidget(loading)
            self.scroll_layout.addStretch(1)
            return

        if self.current_source_type == "document":
            cards = state.get("document_results", [])
            if not cards:
                empty = QLabel(state["error"] or ("文件已载入，可以先点击“概括文件”或直接提问。" if state.get("document") else "拖入文档开始。"))
                empty.setWordWrap(True)
                empty.setAlignment(Qt.AlignCenter)
                empty.setStyleSheet("color: #94a3b8; font-size: 13px; margin-top: 20px;")
                self.scroll_layout.addWidget(empty)
                self.scroll_layout.addStretch(1)
                return
            self.render_document_cards(cards)
            self.scroll_layout.addStretch(1)
            return

        replies = state["replies"]
        if not replies:
            empty = QLabel(state["error"] or "点击贴边浮窗上的截图开始，或拖入文件。")
            empty.setWordWrap(True)
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet("color: #94a3b8; font-size: 13px; margin-top: 20px;")
            self.scroll_layout.addWidget(empty)
            self.scroll_layout.addStretch(1)
            return

        self.render_reply_cards(replies)
        self.scroll_layout.addStretch(1)
