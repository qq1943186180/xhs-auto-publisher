"""
小红书提示词模板库
自然口吻：具体场景 + 真实细节 + 克制推荐

本模块集中管理所有 LLM 提示词模板，包括：
- 标题生成：TITLE_SYSTEM_PROMPT / TITLE_USER_TEMPLATE
- 文案生成：CONTENT_SYSTEM_PROMPT / CONTENT_USER_TEMPLATE（种草/测评/教程三种风格）
- 话题标签：TAGS_SYSTEM_PROMPT / TAGS_USER_TEMPLATE
- 小红书主图：XHS_IMAGE_PROMPTS（3种风格变体：博主风/纯白简约/氛围场景）
- 方向生成（第一轮）：DIRECTION_SYSTEM_PROMPT / DIRECTION_USER_TEMPLATE
- 方向扩写（第二轮）：DIRECTION_CONTENT_SYSTEM_PROMPT / DIRECTION_CONTENT_USER_TEMPLATE

辅助函数 get_*_prompt() 负责格式化模板，由各生成器模块调用。
"""

import re
from typing import Optional


# ============================================================
# 标题提示词模板
# ============================================================

TITLE_SYSTEM_PROMPT = """你是一个真的会发小红书的人。你的任务是给一篇真实分享起标题，不要像营销文案。

规则：
1. 标题 10-20 字，像发完笔记后自己顺手写下来的
2. 默认不要 emoji，也不要把 emoji 放在标题开头
3. 不要写夸张营销词：绝了、绝绝子、闭眼入、冲、天花板、被问爆、后悔没早买、救命、宝藏、谁用谁知道
4. 不要写成关键词堆砌，不要像“产品名+功效+人群+结论”的模板句
5. 优先写一个具体瞬间、搭配感受或细节观察，让人像在点开一篇真人笔记
6. 不要虚构数据、销量、好评率、功效承诺
7. 每次生成{count}个候选标题，每行一个，不要编号"""

TITLE_USER_TEMPLATE = """产品名称：{product_name}
产品描述：{description}
{extra_info}

请生成{count}个自然口吻的小红书标题。"""


# ============================================================
# 文案提示词模板
# ============================================================

CONTENT_SYSTEM_PROMPT = """你是一个真实的小红书用户，正在写一篇{style}风格的日常分享。

规则：
1. 正文 220-420 字即可，宁可短一点，也不要像长广告
2. 开头 1-2 句必须进入一个具体时刻，比如出门前、照镜子、收拾桌面、朋友来家里、试衣服、拆包裹，不要先讲结论
3. 全文要像在讲一个刚发生的小故事或一个新的发现，而不是总结产品卖点
4. 中间写清楚你为什么注意到它、为什么留下它、或者为什么愿意继续戴/用，带一点个人判断
5. 可以提优点，也可以轻描淡写写一个小缺点；不要全篇夸，也不要句句都满
6. 不要使用固定大纲标题，不要写“开头Hook/产品介绍/使用体验/购买建议/总结”
7. 不要虚构复购率、好评率、使用天数、功效数据，除非用户提供
8. 语言克制，避免夸张营销词：姐妹们、家人们、真的绝了、绝绝子、冲就对了、闭眼入、天花板、被问爆、后悔没早买、谁用谁知道、智商税
9. 不要写成客服、导购、宣传稿，也不要像“优点都列一遍”的测评清单
10. emoji 可不用；如果用，全文最多 1 个
11. 每段 1-3 句话，保留一点口语停顿，避免句句感叹号
12. 结尾停在一个自然的小判断、小犹豫或下一次想怎么搭，不要引导点赞收藏
13. 末尾附 3-5 个相关话题标签，格式：#标签1 #标签2 #标签3"""

STYLE_PROMPTS = {
    "种草": "第一人称故事型种草，像刚发生的一段日常记录，轻推荐，不强行安利",
    "测评": "真实体验型记录，重点写你观察到的细节和取舍，不用评分制",
    "教程": "经验分享型记录，像把自己摸索出来的小方法讲给朋友听",
}

CONTENT_USER_TEMPLATE = """产品名称：{product_name}
产品描述：{description}
产品价格：{price}
核心卖点：{selling_points}
标题：{title}

请写一篇自然口吻的小红书笔记正文，并在末尾附上3-5个相关话题标签。"""


# ============================================================
# 话题标签提示词模板
# ============================================================

TAGS_SYSTEM_PROMPT = """你是一个小红书话题标签专家。根据产品信息推荐最相关的热门话题标签。

规则：
1. 生成3-5个话题标签
2. 优先精准、自然，避免堆太多泛标签
3. 可以包含 1 个大标签 + 2-4 个场景/风格/品类标签
4. 格式：每个标签以#开头，用空格分隔
5. 只输出标签，不要其他内容"""

TAGS_USER_TEMPLATE = """产品名称：{product_name}
产品类别：{category}
目标人群：{target_audience}
核心卖点：{selling_points}

请推荐相关话题标签。"""


# ============================================================
# 小红书主图提示词（3种风格变体）
# ============================================================

XHS_IMAGE_PROMPTS = {
    # 风格A：博主随手拍 - 模拟 iPhone 真实拍摄
    "style_a": """Using the product shown in the attached image, generate a new photo-realistic lifestyle image. The product must look EXACTLY the same — same color, same shape, same texture, same details. Do NOT alter the product itself. Only change the setting, lighting, and styling around it.

Product: {product_name}

New setting: A cozy home desk scene. Place the product on a warm light-wood desk surface, slightly off-center (rule of thirds). Include a half-drunk latte in a ceramic cup, a small dried flower bouquet in a glass vase, and maybe a paperback book with blurred cover. Background softly out of focus (portrait mode bokeh).

Lighting: Natural window light from the upper-left at ~45°, creating soft shadows. Slight lens flare or light leak on the left edge. Cloudy afternoon — diffused, not harsh.

Camera simulation (CRITICAL — must look like a real phone photo, NOT AI art):
- Shot on iPhone 15 Pro, 2x lens
- f/1.8 aperture with natural bokeh
- Slight noise/grain (ISO 400-800)
- Auto white balance with warm tint
- JPEG compression artifacts (not too clean)
- Slight barrel distortion at edges

Color: Warm beige/latte tones, slightly desaturated. Think VSCO A6 or C1 filter. Not oversaturated, not HDR-looking.

Imperfections (IMPORTANT for realism — do NOT skip):
- A small wrinkle on the tablecloth/fabric
- Maybe a fingerprint smudge on the desk surface
- Slight chromatic aberration on high-contrast edges
- Product should have tiny reflections/scratches if physical object

CRITICAL RULES:
- The product in the image MUST be identical to the attached photo — do not stylize, idealize, or reimagine it
- Do NOT add any text, watermark, logo, or UI overlay
- Must look like a real person casually snapped this with their phone
- If the attached image has a hand, jewelry, or specific angle, keep it the same""",

    # 风格B：买家秀风格 - 不是棚拍，是真实review图
    "style_b": """Using the product shown in the attached image, generate a new photo-realistic customer review photo. The product must look EXACTLY the same — same color, same shape, same texture, same details. Do NOT alter the product itself. Only change the setting and styling.

Product: {product_name}

New setting: A clean marble or light stone surface. Think: a real person's vanity table or desk. Maybe a blurred hand cream tube or small mirror at the edge of frame. Not perfectly arranged — slightly casual.

Lighting: Soft overhead natural light near a large window. Gentle shadows underneath. No harsh studio lighting — daytime indoor light.

Camera simulation (CRITICAL — must look like a real customer photo, NOT professional):
- Shot on Samsung Galaxy S24 or similar mid-range phone
- f/2.0, natural depth of field
- Auto HDR but not overdone
- Slight noise in shadow areas
- Realistic skin-tone white balance (slightly warm)
- JPEG artifacts, not RAW quality

Color: True-to-life colors. Slightly warm but accurate. No Instagram filter vibes.

Imperfections:
- Surface might have a tiny water spot or dust particle
- Product might be very slightly tilted (not perfectly level)
- Focus sharpest on front, back slightly soft

CRITICAL RULES:
- The product MUST be identical to the attached photo — do not stylize or idealize
- Do NOT add any text, watermark, logo, or overlay
- Must look like a real customer's unboxing/review photo""",

    # 风格C：生活随拍 - candid感，真实使用场景
    "style_c": """Using the product shown in the attached image, generate a new photo-realistic candid lifestyle photo. The product must look EXACTLY the same — same color, same shape, same texture, same details. Do NOT alter the product itself. Only change the context and setting.

Product: {product_name}

New setting: A natural lifestyle context — being worn/used, or placed in a real-life moment. Choose ONE:
- On a person's wrist/hand with casual clothing visible (sleeve slightly pushed up)
- On a bedside table next to a phone showing a blurred screen
- Held in a hand against a blurred outdoor background (cafe terrace, park bench)
- On a desk with a laptop, notebook, and pen nearby

Lighting: Golden hour or late afternoon light. Warm, directional, real shadows. Maybe dappled light through window blinds.

Camera simulation (CRITICAL — authenticity is everything):
- iPhone or Pixel phone camera
- Portrait mode with natural computational bokeh
- Slight motion blur on background elements
- Auto-exposure might slightly blow out highlights (realistic)
- ISO noise in darker areas
- Occasionally slightly out-of-focus

Color: Warm golden tones. Slightly faded, like a VSCO or Lightroom preset but not overdone.

Imperfections (CRITICAL — these make it look real):
- Background elements imperfect: messy bookshelf, crumpled napkin, charging cable
- Angle slightly Dutch (tilted)
- Maybe a finger partially visible at edge of frame
- Product might have a tiny reflection of the photographer

CRITICAL RULES:
- The product MUST be identical to the attached photo — do not stylize or idealize
- Do NOT add any text, watermark, logo, or overlay
- Must look like a real person's candid photo — authentic, lived-in, imperfect""",
}


# ============================================================
# 方向生成提示词（第一轮）
# ============================================================

DIRECTION_SYSTEM_PROMPT = """你是一个懂小红书内容的编辑。你的任务是为一个产品生成 3 个差异化的内容方向。

规则：
1. 每个方向必须有明确的定位差异（目标人群、内容角度、情感钩子不能重复）
2. 输出严格的 JSON 格式，不要添加任何额外文字
3. JSON 格式如下：
{
  "directions": [
    {
      "id": "A",
      "name": "方向名称（4-8字）",
      "target_audience": "目标人群描述",
      "angle": "内容角度（一句话）",
      "hook_type": "钩子类型（如：场景记录/选择过程/细节观察/搭配灵感）",
      "style_hint": "风格提示（如：克制分享/自然记录/具体测评/搭配思路）"
    }
  ]
}
4. 3 个方向之间差异要大，覆盖不同人群和场景
5. 方向名称和角度要像真人会写出来的笔记，不要像营销策划案"""

DIRECTION_USER_TEMPLATE = """产品名称：{product_name}
产品描述：{description}
产品价格：{price}
核心卖点：{selling_points}
本次文案风格偏好：{style_hint}

请为这个产品生成 3 个差异化的内容方向，输出 JSON。"""


# ============================================================
# 方向扩写提示词（第二轮）
# ============================================================

DIRECTION_CONTENT_SYSTEM_PROMPT = """你是一个真实的小红书用户。根据给定的内容方向，为产品生成 3 篇自然、不像广告的笔记文案。

规则：
1. 每篇 220-420 字
2. 三篇都要像在讲不同的小故事或小观察，不能只是换几句同义词
3. 三篇必须有明显区别：
   - 篇1：从一个具体场景切入，比如出门前、照镜子、临时换衣服、朋友见面、桌边随手拍
   - 篇2：写选择它、送人、搭配它、留下它的过程，要有一点个人判断，不要煽情
   - 篇3：写细节观察，像你戴了一会儿之后才注意到的东西，不要编数据
4. 每篇开头都要出现一个明确动作或画面，不要一上来就下结论
5. 不要使用固定小标题，不要写“总结一下/优点/缺点/购买建议”
6. 语言像真人记录，允许一点不完美表达；不要每句都很满，不要像客服或导购
7. 禁用词：姐妹们、家人们、绝了、绝绝子、闭眼入、冲、天花板、被问爆、后悔没早买、救命、宝藏、谁用谁知道、智商税、复购率、好评率
8. 标题不要用 emoji，不要写成模板化口号；更像“那天出门前我顺手戴了它”这种真人标题
9. emoji 可不用；如果用，每篇正文最多 1 个
10. 每篇末尾附 3-5 个话题标签（#标签 格式）
11. 输出严格的 JSON 格式，不要添加任何额外文字

JSON 格式：
{
  "posts": [
    {
      "index": 1,
      "hook_style": "日常场景",
      "title": "标题（12-22字，自然，可不含emoji）",
      "content": "正文内容...",
      "tags": ["#标签1", "#标签2"]
    }
  ]
}"""

DIRECTION_CONTENT_USER_TEMPLATE = """产品名称：{product_name}
产品描述：{description}
产品价格：{price}
核心卖点：{selling_points}
本次文案风格偏好：{style_hint_user}

内容方向：
- 方向名称：{direction_name}
- 目标人群：{target_audience}
- 内容角度：{angle}
- 钩子类型：{hook_type}
- 风格提示：{style_hint}

请按方向生成 3 篇差异化文案，输出 JSON。"""


STYLE_ALIASES = {
    "种草": "种草",
    "种草推荐": "种草",
    "产品测评": "测评",
    "测评": "测评",
    "使用教程": "教程",
    "教程": "教程",
}


IMAGE_PRODUCT_PROFILES = [
    {
        "category": "jewelry or wearable accessory",
        "keywords": ["手串", "手链", "项链", "吊坠", "挂件", "戒指", "耳环", "耳饰", "耳钉", "玉", "翡翠", "玛瑙", "水晶", "珍珠", "银饰", "配饰"],
        "usage": "worn on the wrist, neck, finger, bag strap, or placed near outfit fabrics",
        "props": "soft linen sleeve, jewelry tray, small mirror, muted textile, tea cup, clean hand pose",
        "avoid": "oversized studio jewelry ads, fantasy glow, changing the stone color or bead arrangement",
        "scenes": [
            "a real outfit-check moment near a window, the accessory worn naturally with a sleeve slightly pushed up",
            "a quiet dressing-table detail shot, the accessory resting near fabric folds and a small mirror",
            "a casual cafe or tea-table moment, the accessory visible while the hand is reaching for a cup",
        ],
    },
    {
        "category": "clothing, shoes, or bag",
        "keywords": ["衣", "裙", "裤", "鞋", "包", "帽", "外套", "毛衣", "卫衣", "衬衫", "汉服", "吊带"],
        "usage": "worn in a full or half-body styling moment",
        "props": "mirror, doorway, simple room background, tote bag, neutral floor, natural outfit layers",
        "avoid": "runway poses, catalog-white background unless specifically requested, changing fabric cut or print",
        "scenes": [
            "a mirror outfit check before going out, with natural room clutter kept subtle",
            "a street or cafe doorway candid shot, focused on how the item sits on the body",
            "a flat-lay styling scene with shoes, bag, and folded layers arranged casually",
        ],
    },
    {
        "category": "beauty or personal care product",
        "keywords": ["口红", "唇", "面霜", "精华", "护肤", "香水", "彩妆", "粉底", "洗发", "沐浴", "面膜", "防晒"],
        "usage": "used on a vanity, bathroom shelf, or makeup routine scene",
        "props": "small towel, mirror edge, cotton pad, water droplets, warm bathroom light, clean vanity",
        "avoid": "medical claims, fake before-after results, changing packaging label shape",
        "scenes": [
            "a morning vanity routine with the product just picked up by hand",
            "a bathroom shelf detail shot with water droplets and a folded towel nearby",
            "a small bag or makeup pouch scene, as if the product is carried for the day",
        ],
    },
    {
        "category": "home object or decor",
        "keywords": ["杯", "碗", "盘", "壶", "花瓶", "摆件", "香薰", "灯", "收纳", "枕", "毯", "家居", "桌布"],
        "usage": "placed in a lived-in home corner or tabletop scene",
        "props": "wood table, soft curtain light, plant leaf, book, tray, fabric texture, everyday household details",
        "avoid": "empty showroom scenes, perfect render-like symmetry, changing material texture",
        "scenes": [
            "a lived-in dining or desk corner with the object already in use",
            "a soft afternoon home scene with curtains, plant shadows, and real tabletop marks",
            "a close detail shot showing texture and scale beside ordinary home items",
        ],
    },
    {
        "category": "food, tea, coffee, or snack",
        "keywords": ["茶", "咖啡", "零食", "饼", "糖", "果", "酒", "饮", "蜂蜜", "糕", "坚果", "牛奶"],
        "usage": "shown as something being opened, poured, tasted, or shared",
        "props": "plate, cup, napkin, wooden tray, kitchen counter, crumbs, afternoon light",
        "avoid": "fake nutrition claims, plastic-looking food, changing package design",
        "scenes": [
            "an opening-and-tasting moment on a kitchen counter with natural small mess",
            "an afternoon snack table with one portion served and packaging still visible",
            "a close-up of texture beside a cup or plate, with realistic crumbs or condensation",
        ],
    },
    {
        "category": "digital accessory or small device",
        "keywords": ["手机", "耳机", "键盘", "鼠标", "充电", "平板", "相机", "支架", "数据线", "音箱"],
        "usage": "used on a real desk, commute, charging, or setup scene",
        "props": "laptop, notebook, cable, desk lamp, bag pocket, soft screen glow, practical workspace",
        "avoid": "futuristic sci-fi effects, changing ports/buttons, unreadable fake UI text",
        "scenes": [
            "a real desk setup during work, with cables and notebook arranged naturally",
            "a bag or commute detail shot showing how the item is carried",
            "a close functional shot while the item is being plugged in, held, or adjusted",
        ],
    },
    {
        "category": "stationery or creative tool",
        "keywords": ["笔", "本", "贴纸", "手账", "文具", "印章", "便签", "画笔", "胶带"],
        "usage": "used in journaling, note-taking, planning, or craft moments",
        "props": "open notebook, paper scraps, pen marks, washi tape, desk lamp, soft shadow",
        "avoid": "perfectly sterile office stock photo, fake readable text, changing product pattern",
        "scenes": [
            "a real desk note-taking moment with the item mid-use",
            "a journaling flat-lay with paper layers and small imperfect alignment",
            "a close-up of texture, tip, paper edge, or storage detail in warm light",
        ],
    },
]

DEFAULT_IMAGE_PROFILE = {
    "category": "small lifestyle product",
    "usage": "placed or used in a believable daily-life moment",
    "props": "simple real-life props that match the product, natural textures, hands only if useful",
    "avoid": "generic stock-photo composition, changing the product identity, fake text or logos",
    "scenes": [
        "a first-use moment in a real home or desk setting that naturally fits this exact product",
        "a detail review photo showing material, scale, and how it sits with nearby daily items",
        "a candid lifestyle scene where the product is being carried, touched, placed, or used",
    ],
}


def _clean_product_name(product_name: str) -> str:
    text = re.sub(r"\s+", " ", product_name or "").strip()
    return text[:120] or "the product"


def _infer_image_profile(product_name: str) -> dict:
    text = product_name or ""
    for profile in IMAGE_PRODUCT_PROFILES:
        if any(keyword in text for keyword in profile["keywords"]):
            return profile
    return DEFAULT_IMAGE_PROFILE


def _extra_visual_cues(product_name: str, product_context: str = "") -> str:
    text = f"{product_name} {product_context}"
    cues = []
    cue_rules = [
        (["夏", "清凉"], "fresh summer light, breathable fabrics, airy composition"),
        (["显白"], "skin-tone friendly natural light, but no artificial skin whitening"),
        (["中式", "国风", "汉服"], "subtle Chinese-style textile or tea-table detail, modern and restrained"),
        (["原创", "手作", "手工"], "small designer-handmade feeling, tactile imperfections, no factory catalog look"),
        (["绿", "翡翠", "碧玉"], "soft green-adjacent props, avoid changing the actual product color"),
        (["粉"], "gentle pink or blush accent props only if they match the product"),
        (["黑"], "clean contrast with off-white or gray props, keep highlights controlled"),
        (["儿童", "宝宝"], "safe, soft, parent-friendly daily scene, no exaggerated claims"),
        (["通勤", "上班"], "commute or workday scene, practical and calm"),
        (["礼物", "送"], "gift-opening moment, subtle ribbon or box detail, no readable greeting text"),
    ]
    for keywords, cue in cue_rules:
        if any(keyword in text for keyword in keywords):
            cues.append(cue)
    return "; ".join(cues) if cues else "infer color, material, scale, and usage details from the attached image"


def _build_dynamic_image_prompt(
    product_name: str,
    style: str,
    scene_index: int,
    product_context: str = "",
) -> str:
    product = _clean_product_name(product_name)
    profile = _infer_image_profile(product)
    scenes = profile["scenes"]
    scene = scenes[scene_index % len(scenes)]
    visual_cues = _extra_visual_cues(product, product_context)
    context_line = f"\nAdditional product/context notes: {product_context[:500]}" if product_context else ""

    style_guides = {
        "style_a": (
            "Real user lifestyle photo. The moment should feel like someone just noticed the product in daily life, "
            "not a planned advertisement."
        ),
        "style_b": (
            "Detail review photo. Emphasize material, size, texture, finish, and how the product looks in ordinary light."
        ),
        "style_c": (
            "Candid usage scene. Show a small story around the product: being worn, held, opened, placed, or used."
        ),
    }
    camera_guides = [
        "phone camera, natural depth of field, slight handheld imperfection, realistic shadows",
        "close but not macro-only, true-to-life color, small dust/fabric/water/desk details where appropriate",
        "warm natural light or soft indoor light, not HDR, not CGI, not studio-perfect",
    ]

    return f"""Use the attached product image as the visual reference. Generate ONE new photo-realistic Xiaohongshu-style product image.

Product title: {product}
Inferred product type: {profile["category"]}
Natural use case: {profile["usage"]}
Scene idea for this product: {scene}
Product-specific visual cues: {visual_cues}
Useful nearby props: {profile["props"]}
Avoid for this product: {profile["avoid"]}{context_line}

Style direction: {style_guides.get(style, style_guides["style_a"])}
Camera and realism: {camera_guides[scene_index % len(camera_guides)]}.

Critical reference rules:
- The product itself must stay visually identical to the attached image: same shape, color, material, pattern, bead order, package shape, labels, and proportions.
- Do not invent a different product, do not redesign it, and do not turn it into an illustration.
- Pick props, background, hand pose, and angle that naturally match this exact product type and title.
- Do not add readable text, watermark, logo, UI overlay, before-after claims, or exaggerated commercial slogans.
- The final image should look like a real Xiaohongshu note photo taken by a normal user with a phone."""


# ============================================================
# 辅助函数
# ============================================================

def get_title_prompt(
    product_name: str,
    description: str,
    count: int = 5,
    extra_info: Optional[str] = None,
) -> tuple[str, str]:
    """获取标题生成的系统提示和用户提示"""
    system = TITLE_SYSTEM_PROMPT.format(count=count)
    extra = f"补充信息：{extra_info}" if extra_info else ""
    user = TITLE_USER_TEMPLATE.format(
        product_name=product_name,
        description=description,
        extra_info=extra,
        count=count,
    )
    return system, user


def get_content_prompt(
    product_name: str,
    description: str,
    title: str,
    price: str = "未知",
    selling_points: str = "",
    style: str = "种草",
) -> tuple[str, str]:
    """获取文案生成的系统提示和用户提示"""
    style_key = STYLE_ALIASES.get(style, "种草")
    style_desc = STYLE_PROMPTS.get(style_key, STYLE_PROMPTS["种草"])
    system = CONTENT_SYSTEM_PROMPT.format(style=style_desc)
    user = CONTENT_USER_TEMPLATE.format(
        product_name=product_name,
        description=description,
        price=price,
        selling_points=selling_points or "待补充",
        title=title,
    )
    return system, user


def get_tags_prompt(
    product_name: str,
    category: str = "",
    target_audience: str = "",
    selling_points: str = "",
) -> tuple[str, str]:
    """获取话题标签生成的系统提示和用户提示"""
    user = TAGS_USER_TEMPLATE.format(
        product_name=product_name,
        category=category or "通用",
        target_audience=target_audience or "年轻女性",
        selling_points=selling_points or "品质好、性价比高",
    )
    return TAGS_SYSTEM_PROMPT, user


def get_image_prompt(
    product_name: str,
    style: str = "style_a",
    product_context: str = "",
) -> str:
    """获取小红书主图生成提示词（3种风格）"""
    style_order = ["style_a", "style_b", "style_c"]
    scene_index = style_order.index(style) if style in style_order else 0
    return _build_dynamic_image_prompt(
        product_name=product_name,
        style=style,
        scene_index=scene_index,
        product_context=product_context,
    )


def get_all_image_prompts(product_name: str, product_context: str = "") -> list[str]:
    """获取全部3种风格的提示词"""
    return [
        get_image_prompt(product_name, "style_a", product_context=product_context),
        get_image_prompt(product_name, "style_b", product_context=product_context),
        get_image_prompt(product_name, "style_c", product_context=product_context),
    ]


def get_direction_prompt(
    product_name: str,
    description: str,
    price: str = "未知",
    selling_points: str = "",
    style: str = "种草推荐",
) -> tuple[str, str]:
    """获取方向生成（第一轮）的系统提示和用户提示"""
    style_key = STYLE_ALIASES.get(style, "种草")
    style_hint = STYLE_PROMPTS.get(style_key, STYLE_PROMPTS["种草"])
    user = DIRECTION_USER_TEMPLATE.format(
        product_name=product_name,
        description=description,
        price=price,
        selling_points=selling_points or "待补充",
        style_hint=style_hint,
    )
    return DIRECTION_SYSTEM_PROMPT, user


def get_direction_content_prompt(
    product_name: str,
    description: str,
    price: str,
    selling_points: str,
    direction: dict,
    style: str = "种草推荐",
) -> tuple[str, str]:
    """获取方向扩写（第二轮）的系统提示和用户提示"""
    style_key = STYLE_ALIASES.get(style, "种草")
    style_hint = STYLE_PROMPTS.get(style_key, STYLE_PROMPTS["种草"])
    user = DIRECTION_CONTENT_USER_TEMPLATE.format(
        product_name=product_name,
        description=description,
        price=price,
        selling_points=selling_points or "待补充",
        style_hint_user=style_hint,
        direction_name=direction.get("name", ""),
        target_audience=direction.get("target_audience", ""),
        angle=direction.get("angle", ""),
        hook_type=direction.get("hook_type", ""),
        style_hint=direction.get("style_hint", ""),
    )
    return DIRECTION_CONTENT_SYSTEM_PROMPT, user
