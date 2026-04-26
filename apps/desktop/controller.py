import sys

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QApplication, QFileDialog

from .core import (
    AIWorker,
    BAIDU_ACCESS_TOKEN,
    DocumentParser,
    ERNIE_CHAT_ENDPOINT,
    ERNIE_MODEL,
    HOTKEY,
    HOTKEY_ENABLED,
    OCR_BACKEND,
    PADDLEOCR_API_URL,
    PROJECT_ROOT,
    PROMPT_ASSEMBLER,
    ScreenContextMonitor,
    SKILL_LIBRARY_ROOT,
    GlobalHotkeyManager,
    clamp,
    filter_supported_document_paths,
    pixmap_to_png_bytes,
    render_share_card_image,
)
from .ui import CaptureWindow, DockHandle, PersonaConfigWindow, ResultWindow, SkillEditorWindow


class ControllerSignals(QObject):
    hotkey_triggered = pyqtSignal()


class AppController:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        self.capture_window = None
        self.result_window = ResultWindow()
        self.skill_editor_window = SkillEditorWindow()
        self.persona_window = PersonaConfigWindow()
        self.handle_window = DockHandle()
        self.hotkey_manager = GlobalHotkeyManager(self.app)
        self.worker = None
        self.screen_context_monitor = None
        self.signals = ControllerSignals()
        self.state = {
            "ocr_text": "",
            "conversation": None,
            "replies": [],
            "source_type": "",
            "source_name": "",
            "document": None,
            "document_results": [],
            "question_text": "",
            "error": "",
            "status_key": "idle",
            "status_text": "就绪，点击截图或拖入文档开始。",
            "busy": False,
            "immersive_mode_enabled": False,
            "immersive_mode_ready": False,
            "immersive_mode_backend": "",
            "immersive_mode_note": "关闭后热键将打开框选截图。",
            "immersive_mode_error": "",
        }

        self.signals.hotkey_triggered.connect(self.handle_hotkey_trigger)

        self.handle_window.capture_requested.connect(self.start_capture)
        self.handle_window.paste_requested.connect(self.start_from_clipboard)
        self.handle_window.file_pick_requested.connect(self.pick_document)
        self.handle_window.files_dropped.connect(self.handle_dropped_files)
        self.handle_window.reopen_requested.connect(self.open_last_result)
        self.handle_window.immersive_toggled.connect(self.set_immersive_mode)
        self.handle_window.dock_changed.connect(self.snap_handle)

        self.result_window.regenerate_requested.connect(self.regenerate_replies)
        self.result_window.save_text_requested.connect(self.generate_from_text)
        self.result_window.rewrite_requested.connect(self.rewrite_reply)
        self.result_window.copy_requested.connect(self.copy_reply)
        self.result_window.share_requested.connect(self.share_reply_card)
        self.result_window.recapture_requested.connect(self.start_capture)
        self.result_window.file_pick_requested.connect(self.pick_document)
        self.result_window.files_dropped.connect(self.handle_dropped_files)
        self.result_window.document_summary_requested.connect(self.summarize_document)
        self.result_window.term_explain_requested.connect(self.explain_document_terms)
        self.result_window.document_extract_requested.connect(self.extract_document_info)
        self.result_window.resume_analysis_requested.connect(self.analyze_resume_document)
        self.result_window.contract_review_requested.connect(self.review_contract_document)
        self.result_window.document_question_requested.connect(self.ask_document_question)
        self.result_window.document_clear_requested.connect(self.clear_document)
        self.result_window.skill_editor_requested.connect(self.open_skill_editor)
        self.result_window.persona_settings_requested.connect(self.open_persona_settings)

        self.skill_editor_window.save_requested.connect(self.save_skill)
        self.persona_window.save_requested.connect(self.save_persona)

        self.app.aboutToQuit.connect(self.shutdown)
        self.restore_handle_position()
        self.setup_hotkey()

        self.handle_window.show()
        self.render_state()

        print("高情商回复助手已启动！")
        if HOTKEY_ENABLED:
            print(f"热键状态：{HOTKEY}")
        else:
            print("热键状态：未启用，主入口为贴边浮窗")
        if not BAIDU_ACCESS_TOKEN:
            print("警告：当前未检测到 .env 中的百度 Access Token，生成回复时会失败。")
        print(f"OCR 模式：{OCR_BACKEND}")
        if OCR_BACKEND == "api":
            print(f"OCR API 地址：{PADDLEOCR_API_URL}")
        print(f"文心模型：{ERNIE_MODEL}")
        print(f"文心接口地址：{ERNIE_CHAT_ENDPOINT}")
        if PROMPT_ASSEMBLER.has_skills():
            print(f"技能库状态：已加载 {PROMPT_ASSEMBLER.count_skills()} 个 skill")
        else:
            print(f"技能库状态：未加载到本地 skill，当前退回基础提示词。目录：{SKILL_LIBRARY_ROOT}")
        if PROMPT_ASSEMBLER.skill_library.load_errors:
            print("技能库警告：以下 skill 加载失败，将自动跳过。")
            for error in PROMPT_ASSEMBLER.skill_library.load_errors:
                print(f" - {error}")

    def render_state(self):
        self.handle_window.set_status(self.state["status_key"], self.state["status_text"])
        self.handle_window.set_immersive_state(
            self.state.get("immersive_mode_enabled", False),
            self.state.get("immersive_mode_ready", False),
            self.state.get("immersive_mode_note", ""),
        )
        self.result_window.show_state(self.state)
        if self.result_window.isVisible():
            self.position_result_window()

    def update_state(self, **changes):
        self.state.update(changes)
        self.render_state()

    def shutdown(self):
        self._stop_screen_context_monitor(update_state=False)

    def restore_handle_position(self):
        desktop = QApplication.desktop().availableGeometry()
        x = desktop.right() - self.handle_window.width() + 1
        y = desktop.center().y() - self.handle_window.height() // 2
        self.handle_window.move(x, y)
        self.handle_window.dock_side = "right"

    def setup_hotkey(self):
        if not HOTKEY_ENABLED:
            return
        try:
            self.hotkey_manager.register(HOTKEY, self.signals.hotkey_triggered.emit)
        except Exception as exc:
            print(f"热键不可用：{HOTKEY}，原因：{str(exc)}")

    def handle_hotkey_trigger(self):
        if self.state["busy"]:
            return
        if self.state.get("immersive_mode_enabled"):
            self.start_capture_from_screen_buffer()
            return
        self.start_capture()

    def set_status(self, status_key, status_text):
        self.state["status_key"] = status_key
        self.state["status_text"] = status_text
        self.render_state()

    def position_result_window(self):
        geometry = QApplication.desktop().availableGeometry(self.handle_window)
        side = self.handle_window.dock_side
        result_width = self.result_window.width()
        result_height = self.result_window.height()

        if side == "left":
            x = self.handle_window.x() + self.handle_window.width() + 12
        else:
            x = self.handle_window.x() - result_width - 12

        max_x = geometry.right() - result_width + 1
        x = clamp(x, geometry.left(), max_x)
        y = self.handle_window.y() + self.handle_window.height() // 2 - result_height // 2
        max_y = geometry.bottom() - result_height + 1
        y = clamp(y, geometry.top(), max_y)
        self.result_window.move(x, y)

    def position_skill_editor_window(self):
        geometry = QApplication.desktop().availableGeometry(self.handle_window)
        editor_width = self.skill_editor_window.width()
        editor_height = self.skill_editor_window.height()

        if self.result_window.isVisible():
            preferred_x = self.result_window.x() - editor_width - 16
            if preferred_x < geometry.left():
                preferred_x = self.result_window.x() + self.result_window.width() + 16
            preferred_y = self.result_window.y() + 20
        else:
            preferred_x = geometry.center().x() - editor_width // 2
            preferred_y = geometry.center().y() - editor_height // 2

        max_x = geometry.right() - editor_width + 1
        max_y = geometry.bottom() - editor_height + 1
        x = clamp(preferred_x, geometry.left(), max_x)
        y = clamp(preferred_y, geometry.top(), max_y)
        self.skill_editor_window.move(x, y)

    def position_persona_window(self):
        geometry = QApplication.desktop().availableGeometry(self.handle_window)
        window_width = self.persona_window.width()
        window_height = self.persona_window.height()

        if self.result_window.isVisible():
            preferred_x = self.result_window.x() - window_width - 16
            if preferred_x < geometry.left():
                preferred_x = self.result_window.x() + self.result_window.width() + 16
            preferred_y = self.result_window.y() + 40
        else:
            preferred_x = geometry.center().x() - window_width // 2
            preferred_y = geometry.center().y() - window_height // 2

        max_x = geometry.right() - window_width + 1
        max_y = geometry.bottom() - window_height + 1
        x = clamp(preferred_x, geometry.left(), max_x)
        y = clamp(preferred_y, geometry.top(), max_y)
        self.persona_window.move(x, y)

    def snap_handle(self):
        geometry = QApplication.desktop().availableGeometry(self.handle_window)
        center_x = self.handle_window.frameGeometry().center().x()
        side = "left" if center_x < geometry.center().x() else "right"
        y = clamp(
            self.handle_window.y(),
            geometry.top(),
            geometry.bottom() - self.handle_window.height() + 1,
        )
        if side == "left":
            x = geometry.left()
        else:
            x = geometry.right() - self.handle_window.width() + 1
        self.handle_window.move(x, y)
        self.handle_window.dock_side = side
        if self.result_window.isVisible():
            self.position_result_window()
        if self.skill_editor_window.isVisible():
            self.position_skill_editor_window()
        if self.persona_window.isVisible():
            self.position_persona_window()

    def _cleanup_capture_window(self):
        if self.capture_window is not None:
            self.capture_window.deleteLater()
            self.capture_window = None

    def open_skill_editor(self):
        self.skill_editor_window.show()
        self.position_skill_editor_window()
        self.skill_editor_window.raise_()
        self.skill_editor_window.activateWindow()

    def open_persona_settings(self):
        memory_manager = PROMPT_ASSEMBLER._get_memory_manager()
        self.persona_window.set_persona_text(memory_manager.get_persona())
        self.persona_window.set_feedback("", error=False)
        self.persona_window.show()
        self.position_persona_window()
        self.persona_window.raise_()
        self.persona_window.activateWindow()

    def save_skill(self, payload):
        payload = dict(payload or {})
        try:
            saved_meta = PROMPT_ASSEMBLER.skill_library.save_skill(
                payload.get("category"),
                payload.get("name"),
                payload.get("description"),
                payload.get("body"),
            )
            reload_meta = PROMPT_ASSEMBLER.reload_skills()
        except Exception as exc:
            self.skill_editor_window.set_feedback(f"保存失败：{str(exc)}", error=True)
            self.set_status("error", "Skill 保存失败。")
            return

        load_errors = reload_meta.get("load_errors", [])
        if load_errors:
            self.skill_editor_window.set_feedback(
                f"已写入 {saved_meta.get('slug', saved_meta.get('name', 'skill'))}，但热重载存在警告：{load_errors[0]}",
                error=True,
            )
            self.set_status("error", "Skill 已保存，重载有警告。")
            return

        message = (
            f"已保存到 {saved_meta.get('path', '')}。"
            f" 当前共加载 {reload_meta.get('skills_count', PROMPT_ASSEMBLER.count_skills())} 个 skill。"
        )
        self.skill_editor_window.set_feedback(message, error=False)
        self.update_state(error="")
        self.set_status("ready", "Skill 已保存并热更新。")

    def save_persona(self, persona_text):
        normalized = str(persona_text or "").strip()
        try:
            saved_value = PROMPT_ASSEMBLER._get_memory_manager().set_persona(normalized)
        except Exception as exc:
            self.persona_window.set_feedback(f"Persona 保存失败：{str(exc)}", error=True)
            self.set_status("error", "Persona 保存失败。")
            return

        if saved_value:
            self.persona_window.set_feedback("Persona 已保存，后续生成会自动参考这段长期偏好。", error=False)
            self.set_status("ready", "Persona 已更新。")
        else:
            self.persona_window.set_feedback("Persona 已清空，后续生成将不再注入长期偏好。", error=False)
            self.set_status("ready", "Persona 已清空。")

    def set_immersive_mode(self, enabled):
        if enabled:
            self._start_screen_context_monitor()
            return
        self._stop_screen_context_monitor()

    def _start_screen_context_monitor(self):
        monitor = self.screen_context_monitor
        if monitor is not None and monitor.isRunning():
            self.update_state(
                immersive_mode_enabled=True,
                immersive_mode_note=self.state.get("immersive_mode_note") or "正在缓存屏幕上下文...",
                immersive_mode_error="",
            )
            return

        monitor = ScreenContextMonitor(fps=1.0)
        monitor.frame_updated.connect(self._handle_screen_context_frame)
        monitor.status_changed.connect(self._handle_screen_context_status)
        monitor.error_occurred.connect(self._handle_screen_context_error)
        self.screen_context_monitor = monitor
        self.update_state(
            immersive_mode_enabled=True,
            immersive_mode_ready=False,
            immersive_mode_backend="",
            immersive_mode_note="正在以 1 FPS 缓存屏幕，等待首帧...",
            immersive_mode_error="",
        )
        monitor.start_monitoring()

    def _stop_screen_context_monitor(self, update_state=True):
        monitor = self.screen_context_monitor
        self.screen_context_monitor = None
        if monitor is not None:
            try:
                monitor.stop_monitoring()
            finally:
                monitor.deleteLater()

        if update_state:
            self.update_state(
                immersive_mode_enabled=False,
                immersive_mode_ready=False,
                immersive_mode_backend="",
                immersive_mode_note="关闭后热键将打开框选截图。",
                immersive_mode_error="",
            )

    def _handle_screen_context_frame(self, payload):
        if not self.state.get("immersive_mode_enabled"):
            return

        backend = str(payload.get("backend", "") or "").strip()
        ready = self.state.get("immersive_mode_ready", False)
        current_backend = self.state.get("immersive_mode_backend", "")
        if ready and backend == current_backend:
            return

        note = "实时屏幕上下文已就绪，热键将直接识别当前屏幕。"
        if backend:
            note = f"实时屏幕上下文已就绪 · {backend.upper()} · 热键直接识别。"
        self.update_state(
            immersive_mode_ready=True,
            immersive_mode_backend=backend,
            immersive_mode_note=note,
            immersive_mode_error="",
        )

    def _handle_screen_context_status(self, status):
        if status == "screen_monitor_already_running":
            return

        if status.startswith("screen_monitor_running:"):
            backend = status.split(":", 1)[1].strip()
            note = "正在缓存屏幕上下文，等待首帧..."
            if backend:
                note = f"正在缓存屏幕上下文 · {backend.upper()} · 等待首帧..."
            self.update_state(
                immersive_mode_enabled=True,
                immersive_mode_ready=False,
                immersive_mode_backend=backend,
                immersive_mode_note=note,
            )
            return

        if status == "screen_monitor_unavailable":
            self.update_state(
                immersive_mode_enabled=False,
                immersive_mode_ready=False,
                immersive_mode_backend="",
                immersive_mode_note="缺少 mss 或 Pillow，沉浸模式不可用。",
            )
            return

        if status == "screen_monitor_stopped" and not self.state.get("immersive_mode_enabled"):
            self.update_state(
                immersive_mode_ready=False,
                immersive_mode_backend="",
                immersive_mode_note="关闭后热键将打开框选截图。",
                immersive_mode_error="",
            )

    def _handle_screen_context_error(self, message):
        text = str(message or "").strip()
        if not text:
            return

        if "未检测到可用截图后端" in text or "不可用" in text:
            self.update_state(
                immersive_mode_enabled=False,
                immersive_mode_ready=False,
                immersive_mode_backend="",
                immersive_mode_note="缺少 mss 或 Pillow，沉浸模式不可用。",
                immersive_mode_error=text,
            )
            return

        self.update_state(
            immersive_mode_ready=False,
            immersive_mode_note="屏幕采集中断，正在自动重试...",
            immersive_mode_error=text,
        )

    def start_capture(self):
        if self.state["busy"]:
            return

        self.handle_window.show()
        self.handle_window.hide()
        self.result_window.hide()
        self.set_status("capturing", "请框选聊天区域。")

        self.capture_window = CaptureWindow()
        self.capture_window.shot_taken.connect(self._handle_capture_taken)
        self.capture_window.capture_canceled.connect(self._handle_capture_canceled)
        self.capture_window.show()

    def _handle_capture_canceled(self):
        self._cleanup_capture_window()
        self.handle_window.show()
        self.set_status("idle", "已取消截图。")

    def _handle_capture_taken(self, image_data):
        self._cleanup_capture_window()
        self.handle_window.show()
        self.open_last_result()
        self._start_worker(
            "bundle",
            status_key="ocr",
            status_text="正在识别并生成回复...",
            image_data=image_data,
        )

    def start_capture_from_screen_buffer(self):
        if self.state["busy"]:
            return

        monitor = self.screen_context_monitor
        if monitor is None or not self.state.get("immersive_mode_enabled"):
            self.start_capture()
            return

        image_data = monitor.get_latest_frame_bytes()
        if not image_data:
            self.update_state(error="沉浸模式还在预热，暂时没有可识别的屏幕缓冲。")
            self.set_status("error", "沉浸模式未就绪。")
            self.open_last_result()
            return

        self.open_last_result()
        self._start_worker(
            "bundle",
            status_key="ocr",
            status_text="正在识别实时屏幕上下文...",
            image_data=image_data,
        )

    def start_from_clipboard(self):
        if self.state["busy"]:
            return

        clipboard = self.app.clipboard()
        pixmap = clipboard.pixmap()
        if pixmap.isNull():
            image = clipboard.image()
            if not image.isNull():
                pixmap = QPixmap.fromImage(image)

        if pixmap.isNull():
            self.update_state(error="剪贴板里没有可用图片，请先复制截图。")
            self.set_status("error", "剪贴板里没有可用图片。")
            self.open_last_result()
            return

        self.open_last_result()
        self._start_worker(
            "bundle",
            status_key="ocr",
            status_text="正在识别剪贴板图片...",
            image_data=pixmap_to_png_bytes(pixmap),
        )

    def pick_document(self):
        if self.state["busy"]:
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self.result_window,
            "选择文件",
            str(PROJECT_ROOT),
            "Documents (*.pdf *.docx *.md *.markdown *.txt);;All Files (*.*)",
        )
        if file_path:
            self.handle_dropped_files([file_path])

    def handle_dropped_files(self, paths):
        if self.state["busy"]:
            return

        supported_paths = filter_supported_document_paths(paths)
        if not supported_paths:
            self.update_state(error="当前仅支持 PDF、DOCX、Markdown、TXT 文件。")
            self.set_status("error", "文件格式不支持。")
            self.open_last_result()
            return

        self.open_last_result()
        self._start_worker(
            "document_load",
            status_key="generating",
            status_text="正在解析文件...",
            file_path=supported_paths[0],
        )

    def open_last_result(self):
        self.result_window.show()
        self.position_result_window()
        self.result_window.raise_()
        self.result_window.activateWindow()
        self.render_state()

    def clear_document(self):
        self.update_state(
            ocr_text="",
            conversation=None,
            replies=[],
            source_type="",
            document=None,
            document_results=[],
            question_text="",
            error="",
            busy=False,
        )
        self.set_status("idle", "已清空当前文件。")

    def generate_from_text(self, text):
        normalized_text = (text or "").strip()
        if not normalized_text:
            self.update_state(error="请先输入或保留可用文字，再生成回复。")
            self.set_status("error", "没有可生成的文字。")
            self.open_last_result()
            return

        self.state["ocr_text"] = normalized_text
        self.state["source_type"] = "chat"
        self.open_last_result()
        self._start_worker(
            "bundle",
            status_key="generating",
            status_text="正在根据编辑后的文字生成回复...",
            text=normalized_text,
            conversation=self.state.get("conversation"),
        )

    def regenerate_replies(self, instruction):
        text = (self.state.get("ocr_text") or "").strip()
        if not text:
            self.update_state(error="当前没有可重生成的聊天内容。")
            self.set_status("error", "没有可重生成的内容。")
            self.open_last_result()
            return

        self.open_last_result()
        self._start_worker(
            "bundle",
            status_key="generating",
            status_text="正在生成新一轮回复...",
            text=text,
            instruction=instruction,
            conversation=self.state.get("conversation"),
        )

    def rewrite_reply(self, index, style, current_reply):
        text = (self.state.get("ocr_text") or "").strip()
        if not text:
            self.update_state(error="当前没有可改写的聊天内容。")
            self.set_status("error", "没有可改写的内容。")
            self.open_last_result()
            return

        self.open_last_result()
        self._start_worker(
            "rewrite",
            status_key="generating",
            status_text="正在重写回复...",
            text=text,
            style=style,
            current_reply=current_reply,
            index=index,
            conversation=self.state.get("conversation"),
        )

    def summarize_document(self):
        if not self.state.get("document"):
            self.update_state(error="请先载入文件。")
            self.set_status("error", "当前没有可概括的文件。")
            self.open_last_result()
            return

        self.open_last_result()
        self._start_worker(
            "document_summary",
            status_key="generating",
            status_text="正在概括文件...",
            document=self.state.get("document"),
        )

    def explain_document_terms(self):
        if not self.state.get("document"):
            self.update_state(error="请先载入文件。")
            self.set_status("error", "当前没有可解释的文件。")
            self.open_last_result()
            return

        self.open_last_result()
        self._start_worker(
            "document_terms",
            status_key="generating",
            status_text="正在提取术语解释...",
            document=self.state.get("document"),
        )

    def extract_document_info(self):
        if not self.state.get("document"):
            self.update_state(error="请先载入文件。")
            self.set_status("error", "当前没有可提取的信息文件。")
            self.open_last_result()
            return

        self.open_last_result()
        self._start_worker(
            "document_extract",
            status_key="generating",
            status_text="正在提取关键信息...",
            document=self.state.get("document"),
        )

    def analyze_resume_document(self):
        if not self.state.get("document"):
            self.update_state(error="请先载入简历文件。")
            self.set_status("error", "当前没有可分析的简历。")
            self.open_last_result()
            return

        self.open_last_result()
        self._start_worker(
            "document_resume_analysis",
            status_key="generating",
            status_text="正在分析简历...",
            document=self.state.get("document"),
        )

    def review_contract_document(self):
        if not self.state.get("document"):
            self.update_state(error="请先载入合同文件。")
            self.set_status("error", "当前没有可审查的合同。")
            self.open_last_result()
            return

        self.open_last_result()
        self._start_worker(
            "document_contract_review",
            status_key="generating",
            status_text="正在审查合同风险...",
            document=self.state.get("document"),
        )

    def ask_document_question(self, question):
        normalized_question = (question or "").strip()
        if not self.state.get("document"):
            self.update_state(error="请先载入文件。")
            self.set_status("error", "当前没有可提问的文件。")
            self.open_last_result()
            return
        if not normalized_question:
            self.update_state(error="请输入问题后再提问。")
            self.set_status("error", "请输入问题。")
            self.open_last_result()
            return

        self.state["question_text"] = normalized_question
        self.open_last_result()
        self._start_worker(
            "document_question",
            status_key="generating",
            status_text="正在回答问题...",
            document=self.state.get("document"),
            question=normalized_question,
        )

    def copy_reply(self, text):
        value = str(text or "").strip()
        if not value:
            return
        self.app.clipboard().setText(value)
        self.update_state(error="")
        self.set_status("ready", "已复制到剪贴板。")

    def share_reply_card(self, payload):
        payload = dict(payload or {})
        reply_text = str(payload.get("reply_text") or payload.get("text") or "").strip()
        reply_style = str(payload.get("reply_style") or payload.get("style") or "").strip()
        if not reply_text:
            self.update_state(error="当前没有可分享的回复内容。")
            self.set_status("error", "分享失败。")
            self.open_last_result()
            return

        try:
            image = render_share_card_image(
                {
                    "reply_index": payload.get("reply_index", payload.get("index", -1)),
                    "reply_style": reply_style or "AI 推荐回复",
                    "reply_text": reply_text,
                    "ocr_text_snapshot": (self.state.get("ocr_text") or payload.get("ocr_text") or "").strip(),
                    "source_type": self.state.get("source_type") or payload.get("source_type") or "chat",
                    "source_name": payload.get("source_name") or self.state.get("source_name") or "",
                    "brand": "高情商聊天回复助手",
                }
            )
        except Exception as exc:
            self.update_state(error=f"分享卡生成失败：{str(exc)}")
            self.set_status("error", "分享失败。")
            self.open_last_result()
            return

        self.app.clipboard().setPixmap(QPixmap.fromImage(image))
        self.update_state(error="")
        self.set_status("ready", "分享卡已复制到剪贴板。")

    def _start_worker(self, mode, status_key, status_text, **kwargs):
        if self.worker is not None and self.worker.isRunning():
            return

        self.state["busy"] = True
        self.state["error"] = ""
        self.set_status(status_key, status_text)

        self.worker = AIWorker(mode=mode, **kwargs)
        self.worker.finished.connect(self._handle_worker_finished)
        self.worker.start()

    def _handle_worker_finished(self, result):
        worker = self.worker
        self.worker = None
        if worker is not None:
            worker.deleteLater()

        mode = result.get("mode", "")
        if mode == "rewrite":
            self._handle_rewrite_result(result)
            return
        if mode == "document_load":
            self._handle_document_load_result(result)
            return
        if mode in {
            "document_summary",
            "document_terms",
            "document_extract",
            "document_resume_analysis",
            "document_contract_review",
            "document_question",
        }:
            self._handle_document_action_result(result)
            return
        self._handle_bundle_result(result)

    def _handle_bundle_result(self, result):
        replies = result.get("replies", []) if isinstance(result.get("replies"), list) else []
        ocr_text = str(result.get("ocr_text", "") or "").strip()
        error = str(result.get("error", "") or "").strip()
        conversation = result.get("conversation")

        self.update_state(
            ocr_text=ocr_text,
            conversation=conversation,
            replies=replies,
            source_type="chat" if ocr_text else "",
            document=None,
            document_results=[],
            question_text="",
            error=error,
            busy=False,
        )
        if error:
            self.set_status("error", error)
        else:
            assistant_memory = "\n".join(
                f"{item.get('style', '回复')}：{str(item.get('text', '')).strip()}"
                for item in replies
                if str(item.get("text", "")).strip()
            ).strip()
            if ocr_text and assistant_memory:
                PROMPT_ASSEMBLER._get_memory_manager().append_exchange(ocr_text, assistant_memory)
            self.set_status("ready", f"已生成 {len(replies)} 条回复。")
        self.open_last_result()

    def _handle_rewrite_result(self, result):
        error = str(result.get("error", "") or "").strip()
        replies = list(self.state.get("replies") or [])
        index = result.get("index", -1)
        reply = result.get("reply") or {}

        if not error and 0 <= index < len(replies):
            replies[index] = {
                "style": reply.get("style", replies[index].get("style", "")),
                "text": reply.get("text", replies[index].get("text", "")),
            }

        self.update_state(
            replies=replies,
            error=error,
            busy=False,
        )
        if error:
            self.set_status("error", error)
        else:
            self.set_status("ready", f"已更新第 {index + 1} 条回复。")
        self.open_last_result()

    def _handle_document_load_result(self, result):
        error = str(result.get("error", "") or "").strip()
        document = result.get("document")

        if error or not isinstance(document, dict):
            self.update_state(
                error=error or "文件载入失败。",
                busy=False,
            )
            self.set_status("error", self.state["error"])
            self.open_last_result()
            return

        self.update_state(
            ocr_text="",
            conversation=None,
            replies=[],
            source_type="document",
            document=document,
            document_results=[],
            question_text="",
            error="",
            busy=False,
        )
        self.set_status("ready", "文件已载入，可以开始概括或提问。")
        self.open_last_result()

    def _handle_document_action_result(self, result):
        error = str(result.get("error", "") or "").strip()
        document = result.get("document") or self.state.get("document")
        cards = result.get("cards", []) if isinstance(result.get("cards"), list) else []
        mode = result.get("mode", "")
        question = str(result.get("question", "") or "").strip()

        self.update_state(
            source_type="document",
            document=document,
            document_results=cards if not error else self.state.get("document_results", []),
            question_text=question or self.state.get("question_text", ""),
            error=error,
            busy=False,
        )

        if error:
            self.set_status("error", error)
        else:
            message_map = {
                "document_summary": "文件概括已生成。",
                "document_terms": "术语解释已生成。",
                "document_extract": "关键信息已提取。",
                "document_resume_analysis": "简历分析已生成。",
                "document_contract_review": "合同审查已生成。",
                "document_question": "文档问答结果已生成。",
            }
            self.set_status("ready", message_map.get(mode, "文件处理完成。"))
        self.open_last_result()

    def run(self):
        return self.app.exec_()
