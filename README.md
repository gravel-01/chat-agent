# 高情商聊天回复助手

一个本地桌面端 AI 聊天回复助手。

当前主流程是：

贴边浮窗截图 -> OCR API 提取文字 -> 调用文心生成回复 -> 在结果侧板中复制或重写。

这里的运行方式就是本地虚拟环境直接运行，不需要额外的 Web 服务，也不需要别的启动器。

## 当前结构

```text
高情商聊天回复助手/
├─ apps/
│  └─ desktop/            # 桌面端主线
├─ chat_assistant.py      # 兼容启动入口
├─ doc/                   # 文档
├─ skill-data/README.md   # 本地 skill 数据说明，实际数据默认不提交
├─ .env.example           # 环境变量模板
├─ requirements.txt       # Python 依赖
└─ README.md
```

## 本地运行

如果你已经激活了自己的虚拟环境或 conda 环境，直接在项目根目录执行下面两步就行。

### 1. 安装依赖

```powershell
python -m pip install -r requirements.txt
```

### 2. 创建配置

```powershell
Copy-Item .env.example .env
```

至少填写：

```env
BAIDU_ACCESS_TOKEN="你的_ACCESS_TOKEN"
ERNIE_MODEL="ernie-5.0-thinking-preview"
OCR_BACKEND="api"
PADDLEOCR_API_URL="https://你的-aistudio-app/layout-parsing"
PADDLEOCR_TOKEN="你的_PADDLEOCR_TOKEN"
REQUEST_TIMEOUT="60"
HOTKEY="ctrl+alt+q"
HOTKEY_ENABLED="false"
```

### 3. 启动

正式命令：

```powershell
python -m apps.desktop.main
```

兼容命令：

```powershell
python chat_assistant.py
```

## 为什么之前会报错

之前你在正确环境里运行仍然报错，不是环境问题，而是代码问题：

- `apps/desktop/controller.py` 在整理过程中变成了残缺文件
- `AppController` 里缺少 `start_capture` 等方法
- 所以即使依赖正确，也会在启动时直接抛 `AttributeError`

这个问题现在已经修回到至少可导入、可启动链路校验通过的状态。

## 当前依赖策略

你现在走的是 `OCR_BACKEND="api"`，所以默认不需要本地 OCR 依赖。

`requirements.txt` 目前按 API OCR 路径收敛为最小依赖，主要包含：

- `PyQt5`
- `requests`
- `pypdf`

如果以后你改成 `OCR_BACKEND="local"`，再额外安装：

```powershell
python -m pip install paddlepaddle paddleocr Pillow numpy
```

## 脱敏说明

仓库默认不会提交以下本地内容：

- `.env` 和 `.env.*` 中的真实访问令牌、接口地址和本地开关。
- `skill-data/` 下除 `README.md` 之外的本地 skill、persona 记忆、聊天历史和第三方语料。
- `__pycache__`、虚拟环境、IDE 配置、构建产物和日志。

首次运行时可以按需创建或导入本地 `skill-data/skills`；程序保存 persona 或 skill 时会自动创建对应目录。

## 常见问题

### 1. 已经在本地环境里，能不能直接跑？

可以。

只要你已经激活了目标环境，并且装好了 `requirements.txt`，直接在项目根目录执行：

```powershell
python -m apps.desktop.main
```

### 2. 截图后没有结果

优先检查：

- `.env` 中的 `BAIDU_ACCESS_TOKEN`
- `.env` 中的 `PADDLEOCR_API_URL`
- `.env` 中的 `PADDLEOCR_TOKEN`
- 当前网络是否能访问 OCR API 和文心接口

### 3. 热键没有反应

当前默认入口是贴边浮窗，不依赖热键。

如果你主动开启了热键，再检查：

- `HOTKEY_ENABLED` 是否设为 `true`
- `HOTKEY` 是否和其他软件冲突

## 当前状态

当前仓库已经收敛成纯桌面项目，不再包含 Web 端说明和文件。
