import ctypes
import sys

from PyQt5.QtCore import QAbstractNativeEventFilter


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
                raise RuntimeError(f"注册全局热键失败：{hotkey}。请确认热键没有被其他程序占用。")

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
