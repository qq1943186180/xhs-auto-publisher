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

## 环境要求

- Windows 10/11
- Python 3.9+
- Chrome 或 Edge
- 小红书创作者中心账号
- 如需 AI 文案：配置可用的大模型 API Key
- 如需 AI 图片：确保 Kimi WebBridge / 浏览器自动化服务可用，并保持对应网站登录状态

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
python cli.py login
python cli.py publish --title "标题" --content "正文" --images "C:\path\to\image1.jpg" "C:\path\to\image2.jpg"
```

CLI 只会接收真实存在的本地图片路径。发布前 UI 会过滤缺失图片，避免把失效路径传给发布流程。

## 项目结构

```text
xhs-auto-publisher/
├─ main.py                  # 桌面应用入口
├─ cli.py                   # 小红书发布 CLI
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
   ├─ publisher/            # 小红书发布流程
   └─ utils/                # 日志等工具
```

## 本地数据与安全

仓库不会保存账号、Cookie、API Key、浏览器会话、采集图片或生成图片。这些内容都应该留在本机的 `~/.xhs-publisher` 目录里，不要提交到 GitHub。

`.env.example` 只提供字段示例。实际使用时复制成 `.env` 后再填写自己的配置。

## 开发

```powershell
python -m py_compile main.py cli.py build_exe.py
python -m py_compile src\ai\image_generator.py src\gui\main_window.py src\gui\pages\ai_generate_page.py src\gui\pages\publish_page.py src\gui\pages\task_list_page.py src\gui\pages\settings_page.py
```

打包为 Windows 可执行文件：

```powershell
python build_exe.py
```

## 状态说明

这是一个本地自动化工具，仍在持续迭代。不同账号、浏览器版本、小红书页面改版和 AI 网站交互变化，都可能影响采集、生成或发布流程。建议先小批量测试，再批量使用。

## License

MIT
