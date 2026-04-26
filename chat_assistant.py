"""兼容启动入口。

正式桌面端入口：
    python -m apps.desktop.main

兼容入口：
    python chat_assistant.py
"""

from apps.desktop.main import main


if __name__ == "__main__":
    main()
