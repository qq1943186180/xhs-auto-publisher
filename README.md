# 小红书自动发布系统

一个面向小红书内容运营的本地桌面工具，用来采集商品素材、生成种草笔记、生成或管理配图，并把待发布内容集中到发布管理里。

项目代码和运行数据是分开的：

- 代码目录：`xhs-auto-publisher`
- 运行数据：`~/.xhs-publisher`
- 采集商品：`~/.xhs-publisher/collected/products_simple.json`
- 生成笔记：`~/.xhs-publisher/generated_notes.json`
- AI 图片：`~/.xhs-publisher/generated_images/`
- 浏览器会话：`~/.xhs-publisher/browser-data/`

## 功能概览

- 商品采集：从商家后台采集商品标题和本地图，每个商品默认最多采集 5 张图。
- AI 文案：围绕一个商品生成 9 个候选文案版本，用于挑选，而不是重复创建 9 条发布记录。
- 种草笔记编辑：标题、正文、话题标签和图片可以在发布前继续修改。
- AI 图片：支持直接生成图片，也支持只生成提示词后让用户自己生图。
- 图片管理：支持本地上传、图片预览、缺图重试和发布前过滤不存在的文件。
- 发布管理：集中查看草稿、发布选中、全部发布、删除单条或全部清理。
- 设置页：管理账号/API、浏览器、采集数量和发布相关配置。

## AI 图片说明

当前图片生成主要走网页自动化流程：

- GPT 网页生图：通过浏览器打开 ChatGPT 网页生成图片。实际使用时，ChatGPT Plus / Pro 或其他支持图片生成的账号更稳定；普通账号可能因为额度、排队、功能限制导致失败或速度变慢。
- Kimi WebBridge：用于控制本机真实浏览器会话，也可以配合 Playwright 做浏览器自动化，完成打开网页、上传产品图、填写提示词、等待生成结果和下载图片。
- 自己生成模式：应用可以只给出图片提示词，用户在自己常用的生图工具里生成，再回到发布管理里上传本地图片。

## 环境要求

- Windows 10/11
- Python 3.9+
- Chrome 或 Edge
- 小红书创作者中心账号
- 如需 AI 文案：配置可用的大模型 API Key
- 如需 AI 图片：确保 Kimi WebBridge / Playwright 浏览器自动化服务可用，并保持 ChatGPT、Kimi 等对应网站登录状态

## 快速开始

```powershell
git clone https://github.com/qq1943186180/xhs-auto-publisher.git
cd xhs-auto-publisher

python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
python -m playwright install chromium

copy .env.example .env
python main.py
```

第一次发布前建议先在应用里完成：

1. 在设置页填写 API 与浏览器相关配置。
2. 打开采集页，采集商品素材。
3. 到 AI 生成页生成文案和图片，确认只保存当前选中的 1 篇笔记。
4. 到发布管理页检查图片数量、标题、正文和话题标签。
5. 使用发布按钮前，确认浏览器里已经登录小红书创作者中心。

## 命令行发布

GUI 内部会调用发布能力，也可以直接用 CLI 测试：

```powershell
python -m src.publisher.cli_publisher --title "标题" --content "正文" --images "C:\path\to\image1.jpg" "C:\path\to\image2.jpg"
python -m src.publisher.cli_publisher --title "标题" --content "正文" --images "C:\path\to\image1.jpg" --auto --json
```

CLI 只会接收真实存在的本地图片路径。发布前 UI 会过滤缺失图片，避免把失效路径传给发布流程。

## 项目结构

```text
xhs-auto-publisher/
├─ main.py                  # 桌面应用入口
├─ build_exe.py             # PyInstaller 打包脚本
├─ requirements.txt         # Python 依赖
├─ .env.example             # 环境变量示例
├─ examples/
│  └─ publish_example.py
└─ src/
   ├─ ai/                   # 文案、方向、标题和图片生成
   ├─ collector/            # 商品采集与浏览器管理
   ├─ config/               # 配置管理
   ├─ database/             # 本地数据存储
   ├─ gui/                  # PyQt/qfluentwidgets 桌面界面
   ├─ models/               # 数据模型
   ├─ publisher/            # 小红书发布流程与 CLI
   └─ utils/                # 日志等工具
```

## 本地数据与安全

仓库不会保存账号、Cookie、API Key、浏览器会话、采集图片或生成图片。这些内容都应该留在本机的 `~/.xhs-publisher` 目录里，不要提交到 GitHub。

`.env.example` 只提供字段示例。实际使用时复制成 `.env` 后再填写自己的配置。

## 开发

```powershell
python -m py_compile main.py build_exe.py
python -m py_compile src\ai\image_generator.py src\gui\main_window.py src\gui\pages\ai_generate_page.py src\gui\pages\publish_page.py src\gui\pages\task_list_page.py src\gui\pages\settings_page.py
```

打包为 Windows 可执行文件：

```powershell
python build_exe.py
```

## 常见问题（FAQ）

### Q: Kimi WebBridge 连接不上？
A: 确保以下几点：
1. Chrome/Edge 浏览器已打开
2. Kimi WebBridge 浏览器扩展已安装并启用
3. 扩展连接状态为"已连接"（扩展图标显示绿色）
4. 默认地址 `http://127.0.0.1:10086`，可通过环境变量 `KIMI_WEBBRIDGE_URL` 修改

### Q: AI 文案生成失败，提示"没有可用的 API Key"？
A: 检查以下配置（任选一种）：
1. 在应用设置页添加 API Key
2. 设置环境变量：`XHS_OPENAI_KEY`、`XHS_KIMI_KEY` 或 `XHS_QWEN_KEY`
3. 支持的提供商：OpenAI、Kimi（Moonshot）、通义千问

### Q: 图片生成超时？
A: ChatGPT DALL-E 生图通常需要 30-60 秒。如果持续超时：
1. 检查网络连接
2. 确认 ChatGPT 账号有图片生成权限（Plus/Pro 更稳定）
3. 尝试减少并行生成数量（默认最多 3 张）

### Q: 打包 EXE 失败？
A: 常见原因：
1. 缺少依赖：确保 `pip install -r requirements.txt` 和 `pip install pyinstaller` 已执行
2. 杀毒软件拦截：将项目目录加入白名单
3. 路径过长：将项目移到短路径下（如 `C:\dev\xhs-auto-publisher`）

### Q: 小红书发布失败？
A: 发布前请确认：
1. 浏览器已登录小红书创作者中心
2. 标题不超过 20 字，正文不超过 1000 字
3. 图片已上传且路径有效（发布前会自动过滤缺失图片）
4. 话题标签格式正确（#标签名）

### Q: 如何自定义图片生成提示词？
A: 在 AI 图片生成页，选择"自定义提示词"模式，可以为每个风格（博主风/纯白简约/氛围场景）单独编辑提示词。

### Q: 数据存储在哪里？
A: 所有运行数据保存在 `~/.xhs-publisher` 目录：
- `collected/products_simple.json` — 采集的商品
- `generated_notes.json` — 生成的笔记
- `generated_images/` — AI 生成的图片
- `browser-data/` — 浏览器会话
- `keys.enc` — 加密存储的 API Key

### Q: 如何清除所有数据重新开始？
A: 删除 `~/.xhs-publisher` 目录即可。注意这会清除所有 API Key、采集数据和生成记录。

## 状态说明

这是一个本地自动化工具，仍在持续迭代。不同账号、浏览器版本、小红书页面改版和 AI 网站交互变化，都可能影响采集、生成或发布流程。建议先小批量测试，再批量使用。

## License

MIT
