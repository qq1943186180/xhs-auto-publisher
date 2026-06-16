"""
小红书页面选择器配置
每个关键元素提供 8-12 个备选选择器，用于 fallback
"""

# ============================================================
# 登录相关选择器
# ============================================================

# 登录状态检测 - 已登录的标志元素
LOGIN_INDICATORS = [
    'div.user-info',
    'img.user-avatar',
    'span.user-name',
    'div.side-bar .user',
    '.login-container .avatar',
    '[class*="user-info"]',
    '[class*="avatar"]',
    '.reds-avatar',
    'a[href*="user/profile"]',
    '.header-user',
]

# 未登录/需要登录的标志
NOT_LOGIN_INDICATORS = [
    'button:has-text("登录")',
    'a:has-text("登录")',
    '.login-btn',
    '[class*="login"]',
    'div.login-modal',
    '.qrcode-login',
    'button:has-text("Sign")',
    '[class*="sign-in"]',
]

# 二维码登录区域
QR_CODE_AREA = [
    '.qrcode-img',
    'img[class*="qrcode"]',
    'canvas.qrcode',
    'div[class*="qr"] img',
    '.login-qr img',
    '[class*="qrcode"] canvas',
    'div.login-box img',
    '.scan-login img',
]

# ============================================================
# 发布按钮选择器
# ============================================================

# 创作中心/发布入口按钮
CREATE_BUTTON = [
    'div.side-bar-icon:has-text("发布")',
    'button:has-text("发布笔记")',
    'a[href*="publish"]',
    '[class*="create-btn"]',
    '[class*="publish-btn"]',
    'div.creator-entry',
    'span:has-text("发布")',
    'button:has-text("创作")',
    '[class*="upload-btn"]',
    'a[href*="creator"]',
    'div.side-bar .create',
    'svg[class*="publish"]',
]

# ============================================================
# 图文发布页面选择器
# ============================================================

# 图片/视频 tab 切换
UPLOAD_TAB_IMAGE = [
    'div.creator-tab:has-text("图文")',
    'span:has-text("上传图文")',
    'div[class*="tab"]:has-text("图文")',
    'button:has-text("图文")',
    '[role="tab"]:has-text("图文")',
    'div.tab-item:has-text("图文")',
    'li:has-text("图文")',
    'span[class*="tab"]:has-text("图文")',
    'div.upload-tab:has-text("图文")',
    'a:has-text("图文")',
]

UPLOAD_TAB_VIDEO = [
    'div.creator-tab:has-text("视频")',
    'span:has-text("上传视频")',
    'div[class*="tab"]:has-text("视频")',
    'button:has-text("视频")',
    '[role="tab"]:has-text("视频")',
    'div.tab-item:has-text("视频")',
    'li:has-text("视频")',
    'span[class*="tab"]:has-text("视频")',
]

# 文件上传输入框（隐藏的 input[type=file]）
FILE_INPUT = [
    'input[type="file"]',
    'input[accept*="image"]',
    'input[accept*="video"]',
    'input[class*="upload"]',
    'input[name*="file"]',
    'input[name*="media"]',
    'div[class*="upload"] input[type="file"]',
    '.upload-input input[type="file"]',
    '[class*="file-input"] input',
    'input[accept*=".jpg"]',
    'input[accept*=".png"]',
]

# 图片上传区域（拖拽区域）
UPLOAD_AREA = [
    'div[class*="upload-container"]',
    'div[class*="drag-area"]',
    'div[class*="upload-area"]',
    'div.upload-wrapper',
    'div[class*="file-upload"]',
    'div[class*="dropzone"]',
    'div[class*="upload-drag"]',
    'div.upload-content',
]

# 上传进度/成功指示
UPLOAD_SUCCESS_INDICATOR = [
    'div[class*="upload-success"]',
    'div[class*="upload-done"]',
    'img[class*="preview"]',
    'div[class*="image-preview"]',
    'div[class*="thumbnail"]',
    'div[class*="upload-item"] img',
    'div[class*="uploaded"]',
    '.upload-list .item img',
]

# ============================================================
# 标题和正文输入
# ============================================================

# 标题输入框
TITLE_INPUT = [
    'input[placeholder*="标题"]',
    'input[class*="title"]',
    '#title',
    'input[name="title"]',
    'div[class*="title"] input',
    'input[placeholder*="填写标题"]',
    'input[class*="note-title"]',
    'input[maxlength="20"]',
    'input[placeholder*="title"]',
    'input[class*="titleInput"]',
    'div[contenteditable][class*="title"]',
    '[class*="title-input"] input',
]

# 正文输入框（通常是 contenteditable div）
CONTENT_INPUT = [
    'div[contenteditable="true"][class*="content"]',
    'div[contenteditable="true"][class*="post"]',
    'div[contenteditable="true"][class*="editor"]',
    'div[contenteditable="true"][class*="note"]',
    '#post-textarea',
    'div[contenteditable="true"][class*="ql-editor"]',
    'div[class*="editor"] div[contenteditable]',
    'div[contenteditable="true"]',
    'textarea[placeholder*="正文"]',
    'textarea[class*="content"]',
    'div[class*="ql-editor"]',
    'div[class*="ProseMirror"]',
]

# ============================================================
# 话题标签选择器
# ============================================================

# 话题按钮/入口
TOPIC_BUTTON = [
    'div[class*="tag-btn"]:has-text("#")',
    'span:has-text("#添加话题")',
    'button:has-text("添加话题")',
    'div[class*="topic"] button',
    '[class*="add-topic"]',
    '[class*="tag-btn"]',
    'span[class*="topic"]',
    'div[class*="hash-tag"]',
    'button:has-text("话题")',
    'div[class*="addTag"]',
    'span:has-text("# 话题")',
]

# 话题搜索框
TOPIC_SEARCH_INPUT = [
    'input[placeholder*="搜索话题"]',
    'input[class*="topic"] input',
    'input[placeholder*="话题"]',
    'div[class*="topic-search"] input',
    'input[class*="search-input"]',
    'input[name*="topic"]',
    'div[class*="search"] input[type="text"]',
]

# 话题搜索结果项
TOPIC_SEARCH_RESULT = [
    'div[class*="topic-item"]',
    'div[class*="search-result"] div[class*="item"]',
    'li[class*="topic"]',
    'div[class*="suggest"] div[class*="item"]',
    'div[class*="result-list"] > div',
    'div[class*="topic-list"] > div',
]

# 已添加的话题标签
TOPIC_TAG = [
    'span[class*="topic-tag"]',
    'div[class*="tag-item"]',
    'span[class*="hashtag"]',
    'div[class*="selected-topic"]',
]

# ============================================================
# 发布按钮
# ============================================================

PUBLISH_BUTTON = [
    'button:has-text("发布")',
    'div[class*="publish"] button',
    'button[class*="publish"]',
    'button[class*="submit"]',
    'span:has-text("发布笔记")',
    'button:has-text("发布笔记")',
    '[class*="publishBtn"]',
    'div[class*="footer"] button:has-text("发布")',
    'button.btn-publish',
    'div[class*="action"] button:has-text("发布")',
]

# 发布成功标志
PUBLISH_SUCCESS_INDICATOR = [
    'div[class*="success"]',
    'div:has-text("发布成功")',
    'span:has-text("发布成功")',
    'div[class*="publish-success"]',
    '.toast-success',
    '[class*="success-toast"]',
]

# ============================================================
# 通用
# ============================================================

# 关闭弹窗/遮罩
CLOSE_POPUP = [
    'div[class*="close"]',
    'button[class*="close"]',
    'span[class*="close"]',
    'svg[class*="close"]',
    '[class*="modal-close"]',
    'div[class*="mask"]',
    'div[class*="overlay"]',
]

# 加载中指示器
LOADING_INDICATOR = [
    'div[class*="loading"]',
    'div[class*="spinner"]',
    'div[class*="skeleton"]',
    '.ant-spin',
]

# 错误提示
ERROR_INDICATOR = [
    'div[class*="error"]',
    'div[class*="toast-error"]',
    'span[class*="error"]',
    '.toast-error',
    '[class*="fail"]',
]


def get_selectors(name: str) -> list[str]:
    """根据名称获取选择器列表"""
    all_selectors = {
        "login_indicators": LOGIN_INDICATORS,
        "not_login_indicators": NOT_LOGIN_INDICATORS,
        "qr_code_area": QR_CODE_AREA,
        "create_button": CREATE_BUTTON,
        "upload_tab_image": UPLOAD_TAB_IMAGE,
        "upload_tab_video": UPLOAD_TAB_VIDEO,
        "file_input": FILE_INPUT,
        "upload_area": UPLOAD_AREA,
        "upload_success": UPLOAD_SUCCESS_INDICATOR,
        "title_input": TITLE_INPUT,
        "content_input": CONTENT_INPUT,
        "topic_button": TOPIC_BUTTON,
        "topic_search_input": TOPIC_SEARCH_INPUT,
        "topic_search_result": TOPIC_SEARCH_RESULT,
        "topic_tag": TOPIC_TAG,
        "publish_button": PUBLISH_BUTTON,
        "publish_success": PUBLISH_SUCCESS_INDICATOR,
        "close_popup": CLOSE_POPUP,
        "loading": LOADING_INDICATOR,
        "error": ERROR_INDICATOR,
    }
    return all_selectors.get(name, [])
