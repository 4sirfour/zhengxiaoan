# -*- coding: utf-8 -*-
"""
证小安 · 公证知识库问答服务
- 知识库检索 + 四要素分析型问答
- 多模型可选（右上角选择器）
- 对外 / 对内权限控制
"""
import os, json, re, math, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import kb_data as K
import kb_official as O
import hague_data as HG

# ==================== 模型注册表 ====================
# 每组含：id / 名称 / 供应商 / 模型名 / 默认端点 / 是否免费 / 说明
MODELS = [
    {
        "id": "deepseek-chat",
        "label": "DeepSeek Chat",
        "desc": "免费额度 · 通用问答，性价比高",
        "provider": "deepseek",
        "base": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "free": True,
        "tier": "fast",
    },
    {
        "id": "deepseek-reasoner",
        "label": "DeepSeek Reasoner",
        "desc": "免费额度 · 强推理，适合多方案比较",
        "provider": "deepseek",
        "base": "https://api.deepseek.com/v1",
        "model": "deepseek-reasoner",
        "free": True,
        "tier": "smart",
    },
    {
        "id": "doubao-lite",
        "label": "豆包 Lite",
        "desc": "火山方舟 · 免费额度 · 快速应答",
        "provider": "doubao",
        "base": "https://ark.cn-beijing.volces.com/api/v3",
        "model": "doubao-lite-32k",
        "free": True,
        "tier": "fast",
    },
    {
        "id": "doubao-pro",
        "label": "豆包 Pro",
        "desc": "火山方舟 · 免费额度 · 智能分析",
        "provider": "doubao",
        "base": "https://ark.cn-beijing.volces.com/api/v3",
        "model": "doubao-pro-32k",
        "free": True,
        "tier": "smart",
    },
    {
        "id": "glm-4-flash",
        "label": "智谱 GLM-4-Flash",
        "desc": "智谱 · 完全免费 · 快速应答",
        "provider": "glm",
        "base": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
        "free": True,
        "tier": "fast",
    },
    {
        "id": "qwen-plus",
        "label": "通义千问 Plus",
        "desc": "阿里云百炼 · 免费额度",
        "provider": "qwen",
        "base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "free": True,
        "tier": "smart",
    },
    {
        "id": "kb-only",
        "label": "仅知识库检索",
        "desc": "不调用大模型，直接返回知识库条目（无需 API Key）",
        "provider": "none",
        "base": "",
        "model": "",
        "free": True,
        "tier": "off",
    },
]

ENV_KEYS = {
    "deepseek": ["DEEPSEEK_API_KEY"],
    "doubao": ["ARK_API_KEY", "DOUBAO_API_KEY"],
    "glm": ["GLM_API_KEY", "ZHIPU_API_KEY"],
    "qwen": ["QWEN_API_KEY", "DASHSCOPE_API_KEY"],
}

# 图片识图模型（多模态）：按 provider 指定可用的视觉模型。
# 优先用免费且效果稳定的 glm-4v-flash；未配置对应 Key 时前端会提示无法识图。
VISION_MODELS = {
    "glm": {"model": "glm-4v-flash", "base": "https://open.bigmodel.cn/api/paas/v4"},
    "qwen": {"model": "qwen-vl-plus", "base": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
}

CFG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def load_cfg():
    cfg = {"keys": {}, "defaultModel": "deepseek-chat", "topK": 4,
           "adminPass": "zx2026"}
    # 环境变量优先
    for prov, names in ENV_KEYS.items():
        for n in names:
            if os.environ.get(n):
                cfg["keys"][prov] = os.environ[n]
                break
    if os.path.exists(CFG_PATH):
        try:
            saved = json.load(open(CFG_PATH, encoding="utf-8"))
            cfg["keys"].update({k: v for k, v in saved.get("keys", {}).items() if v})
            cfg["defaultModel"] = saved.get("defaultModel", cfg["defaultModel"])
            cfg["topK"] = saved.get("topK", cfg["topK"])
            if saved.get("adminPass"):
                cfg["adminPass"] = saved["adminPass"]
        except Exception:
            pass
    return cfg


def save_cfg(cfg):
    json.dump(cfg, open(CFG_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


# ==================== 检索 ====================
STOP = set("的了是什么呢吗和与或在有个我要请问一下这那可以能办公证")


def tokenize(s):
    s = s.lower()
    toks = set()
    for w in re.findall(r"[a-z0-9]+", s):
        toks.add(w)
    cn = re.findall(r"[\u4e00-\u9fa5]+", s)
    for seg in cn:
        for i in range(len(seg)):
            for L in (2, 3, 4):
                if i + L <= len(seg):
                    t = seg[i:i + L]
                    if not all(c in STOP for c in t):
                        toks.add(t)
    return toks


DOCS = K.flatten_for_index()
for d in DOCS:
    d["_tk"] = tokenize(d["title"] + " " + d["content"])


def _doc_weight(d):
    """文档类型权重：具体事项条目 > 案例 > 平台类（总表/简介等）。
    避免「收费标准总表」这类泛化长文档抢占具体条目的排序位。"""
    i = d.get("id", "")
    if i.startswith("item-"):
        return 1.0
    if i.startswith("case-"):
        return 0.92
    return 0.72  # plat-* / fee


PRICE_WORDS = ("价格", "价钱", "多少钱", "费用", "收费", "报价", "怎么收", "多少", "价位", "贵不贵")
# 明确的「问价」信号：出现其一即认为用户在问价格（「多少」单独也算，
# 因为中文口语问价基本都带「多少」；配合「收费总表已被召回」双重约束使用）
_STRONG_PRICE_WORDS = ("价格", "价钱", "多少钱", "费用", "收费", "报价", "怎么收", "价位", "贵不贵")


def _is_price_q(q):
    """是否为价格类问法。"""
    q = q or ""
    return any(w in q for w in _STRONG_PRICE_WORDS) or ("多少" in q)


# 周期/时长类问法：「要几天」「多久能拿」等。各省报价表里有公证周期
# （period）与公证+认证周期（periodAuth）字段，问周期时必须把该数据
# 注入回答，否则会出现「问了几天不答几天」的硬伤。
PERIOD_WORDS = ("几天", "多久", "多长时间", "多少天", "几个工作日", "周期",
                "多久能拿", "什么时候能拿", "多快", "用时", "时长", "多长时间能好")


def _is_period_q(q):
    q = q or ""
    return any(w in q for w in PERIOD_WORDS)


# 红线校验：提问/识图内容触碰到知识库明确禁止项、而模型回答未给出禁止结论时，
# 由系统在答案末尾强制补充警示（不依赖模型自觉，杜绝漏说）
# (触发词, 回答中应出现的结论句, 补充文案)
REDLINE_NOTES = [
    ("代收", "不能代收", "卖房款项不能代收（知识库条目 1「房屋、车辆买卖委托」要求）"),
]


def redline_notes(text, ans):
    """返回需要系统强制补充的红线提示列表。"""
    t = text or ""
    out = []
    for kw, must, note in REDLINE_NOTES:
        if kw in t and must not in (ans or ""):
            out.append(f"您咨询的内容涉及「{kw}房款」：按知识库口径，{note}。"
                       f"请以办理公证处最终口径为准。")
    return out


def period_note():
    """从各省报价表汇总办理周期说明（属知识库内容，对所有人开放）。

    周期不是价格，不属内部成本信息，普通用户问「要几天」时应如实回答。
    """
    if not K.QUOTES:
        return ""
    fmt = lambda s: (s or "").replace("工", " 个工作日").strip()
    pers = sorted({fmt(q.get("period")) for q in K.QUOTES if (q.get("period") or "").strip()})
    auths = sorted({fmt(q.get("periodAuth")) for q in K.QUOTES if (q.get("periodAuth") or "").strip()})
    lines = []
    if pers:
        lines.append(f"公证出具周期：{' / '.join(pers)}（知识库覆盖的 25 省口径一致）")
    if auths:
        lines.append(f"若使用地要求海牙/领事认证：公证+认证合计周期 {' / '.join(auths)}")
    if not lines:
        return ""
    return "【办理周期 · 来源：知识库各省报价表】\n- " + "\n- ".join(lines)


# ==================== 涉外国家判定（单号/双号 · 是否必须海牙） ====================
# 用户问「去某国的公证」时，需回答两件事：
#   ① 该国通常做单号还是双号；② 是否必须办海牙认证（Apostille）。
# 知识库未收录「国家→单双号/海牙」对照表（用户已确认走联网检索判断），
# 因此这里负责：识别国家 → 生成判定检索式 → 交给联网检索 → 组装带来源与不确定性的结论。
COUNTRY_EXTRA = [
    "申根", "申根国", "欧盟", "美国", "加拿大", "澳大利亚", "澳洲", "新西兰", "英国",
    "爱尔兰", "日本", "韩国", "朝鲜", "新加坡", "马来西亚", "泰国", "越南", "菲律宾",
    "印度尼西亚", "印尼", "柬埔寨", "老挝", "缅甸", "文莱", "印度", "巴基斯坦",
    "孟加拉", "斯里兰卡", "尼泊尔", "哈萨克斯坦", "乌兹别克斯坦", "吉尔吉斯斯坦",
    "塔吉克斯坦", "土库曼斯坦", "蒙古", "阿联酋", "迪拜", "沙特", "卡塔尔", "科威特",
    "阿曼", "巴林", "以色列", "土耳其", "伊朗", "伊拉克", "约旦", "黎巴嫩", "叙利亚",
    "德国", "法国", "意大利", "西班牙", "葡萄牙", "荷兰", "比利时", "卢森堡", "瑞士",
    "奥地利", "瑞典", "挪威", "丹麦", "芬兰", "冰島", "冰岛", "波兰", "捷克", "斯洛伐克",
    "匈牙利", "罗马尼亚", "保加利亚", "希腊", "克罗地亚", "斯洛文尼亚", "塞尔维亚",
    "俄罗斯", "俄国", "乌克兰", "白俄罗斯", "立陶宛", "拉脱维亚", "爱沙尼亚", "格鲁吉亚",
    "亚美尼亚", "阿塞拜疆", "埃及", "南非", "尼日利亚", "肯尼亚", "埃塞俄比亚",
    "摩洛哥", "阿尔及利亚", "突尼斯", "利比亚", "坦桑尼亚", "乌干达", "加纳",
    "巴西", "阿根廷", "智利", "秘鲁", "哥伦比亚", "委内瑞拉", "厄瓜多尔", "玻利维亚",
    "乌拉圭", "巴拉圭", "墨西哥", "巴拿马", "哥斯达黎加", "古巴", "牙买加",
]

# 判定「是否属海牙公约适用范围」的权威名单见 hague_data（外交部《公约》缔约国名单）。
# 这里的 COUNTRY_EXTRA 仅负责「从提问里识别出国家名」。


def find_countries(text):
    """从提问中识别使用地国家（含「申根」这类区域）。按出现位置去重排序。"""
    t = text or ""
    found = []
    for c in COUNTRY_EXTRA:
        i = t.find(c)
        if i >= 0 and c not in found:
            found.append((i, c))
    found.sort()
    out = []
    for _i, c in found:
        # 「申根国」「冰岛 / 冰島」等归一化，避免重复计数
        n = {"申根国": "申根", "冰島": "冰岛", "俄国": "俄罗斯", "澳洲": "澳大利亚",
             "印尼": "印度尼西亚", "迪拜": "阿联酋"}.get(c, c)
        if n not in out:
            out.append(n)
    return out


def is_overseas_q(text, countries=()):
    """判断是否涉外问题：显式提到国外/涉外，或识别到具体国家。"""
    t = text or ""
    if countries:
        return True
    return any(w in t for w in ["国外", "境外", "外国", "出国", "涉外", "海牙",
                                "领事认证", "使馆认证", "双认证", "单号", "双号",
                                "签证", "留学", "移民", "出国游", "定居"])



def _is_platform_doc(d):
    i = d.get("id", "")
    return i.startswith("plat-") or i == "fee"


def search(query, k=4, include_internal=True):
    qt = tokenize(query)
    if not qt:
        return []
    # 平台类文档（收费标准总表、平台简介、办理流程）聚合了全部子项名，
    # 命中词多、得分虚高，容易抢占具体事项条目的排序位。
    # 因此仅在问题涉及「价格/费用」时才纳入平台类文档。
    allow_platform = any(w in (query or "") for w in PRICE_WORDS)
    price_q = _is_price_q(query)
    scored = []
    for d in DOCS:
        if _is_platform_doc(d) and not allow_platform:
            continue
        dt = d["_tk"]
        hit = qt & dt
        if not hit:
            continue
        # TF-IDF 近似
        score = sum(1.0 / (1 + math.log(1 + len(DOCS) / (1 + sum(1 for x in DOCS if t in x["_tk"]))))
                    * (len(t) ** 0.5) for t in hit)
        score *= (1 + 0.35 * len(hit) / max(1, len(qt)))
        # 中文全串命中加权
        for t in hit:
            if len(t) >= 4 and t in d["content"]:
                score *= 1.25
        # 文档类型权重：具体条目优先于平台类泛化文档
        score *= _doc_weight(d)
        # 价格类问法下，收费总表是知识库的价格索引，给一个温和加权（+15%），
        # 使其在「涉外公证多少钱」这类品类级问价中能与具体条目竞争。
        raw = score  # 记录未加权总分，供后续「具体事项优先」校正比较
        if price_q and d.get("id") == "fee":
            score *= 1.15
        scored.append((score, d, raw))
    scored.sort(key=lambda x: -x[0])
    # 价格类问法二次校正：
    # (a) 若首位具体条目的「事项核心词」根本没出现在问题里（如问「涉外公证
    #     多少钱」，「涉外」是类目词而非标的，首位却是「涉外赠与协议」），
    #     说明它是被类目词误召回的噪声，此时应由收费总表接管；
    # (b) 否则若具体条目原始得分不低于总表原始得分的 8 成，说明用户在问某个
    #     具体事项的价格，把总表压到该条目之后即可。
    if price_q:
        _fee_i = next((i for i, x in enumerate(scored) if x[1].get("id") == "fee"), None)
        _item = next(((i, x) for i, x in enumerate(scored)
                      if x[1].get("id", "").startswith("item-")), None)
        if _fee_i is not None:
            _core_absent = False
            if _item and _item[0] == 0:
                _c = _core_subject(_item[1][1].get("title", ""))
                _core_absent = (len(_c) >= 2 and _c not in query
                                and not any(len(f) >= 2 and f in query
                                            for f in re.split(r"[、，,/\s]+", _c)))
            if _core_absent and scored[_fee_i][2] >= 1.0:
                _fe = scored.pop(_fee_i)
                scored.insert(0, _fe)
            elif _item and _item[0] > 0 and _item[1][2] >= scored[_fee_i][2] * 0.8:
                _fe = scored.pop(_fee_i)
                scored.insert(_item[0], _fe)
    out = []
    for s, d, _raw in scored[:k]:
        d2 = dict(d)
        d2["_score"] = s
        out.append(d2)
    return out


GENERIC_WORDS = {
    "公证", "办理", "申请", "需要", "什么", "材料", "如何", "怎么", "可以", "是否",
    "请问", "我想", "我要", "户籍", "使用", "用途", "用于", "国内", "国外", "境外",
}

# 事项名中常见但无区分度的「类型后缀」：剥离后剩下的才是事项的「核心业务词」。
# 若只命中这些后缀（如「声明」「协议」），不能算知识库收录了该事项。
SUFFIX_WORDS = (
    "公证", "证明", "声明", "协议", "合同", "书", "文件", "事项", "服务",
)


def _core_subject(name):
    """取事项名的核心业务词：去掉编号、大类前缀与类型后缀。"""
    n = (name or "").strip()
    # 先剥离所有括号内容：括号里可能含「·」（如「（婚内购买·单独所有）」），
    # 若先按「·」切分会把括号内的碎片当成事项名。
    n = re.sub(r"[（(][^）)]*[）)]", "", n)
    n = n.split("·")[-1].strip()                       # 去大类前缀
    n = re.sub(r"^\d+[\.、]\s*", "", n)               # 去「17. 」「17、」
    n = re.sub(r"^(涉外的?|国内的?)", "", n)          # 去高频通用前缀
    for s in SUFFIX_WORDS:
        n = n.replace(s, "")
    return n.strip(" 、，,-—")


def _is_catchall(d):
    """是否为「兜底桶」事项（如「声明类公证（其他）」）。

    兜底桶本身没有具体标的，不能靠别名或模糊匹配单独认定相关，
    否则会把不相关事项的材料带出来；必须由具体事项来背书。
    """
    nm = (d.get("title") or "").split("·")[-1]
    return ("其他" in nm) or ("一般" in nm)


def hit_is_relevant(query, items):
    """判断检索结果是否真正相关：必须命中「事项核心词」或该事项的「别名」。

    仅命中「公证/办理/材料」等通用词，或只命中「声明/协议」这类类型后缀，
    都不算命中，否则会把不相关事项的材料带出来。
    例外：若首位结果得分远超其余（强区分），且核心词与问题有 ≥3 字公共片段，
    也视为命中（应对「公众号主体迁移」vs「微信公众号主体迁移」这类近义表述）。
    注意：兜底桶事项（其他/一般）不参与独立认定，需由具体事项背书。
    """
    q = (query or "").strip()
    if not q:
        return False
    # 规则P：价格类问法命中「收费总表」，且总表就是首位结果时，
    #        视总表为该问法的权威答案，直接认定相关（总表是知识库的价格索引）。
    #        要求总表排首位，避免「公司章程公证多少钱」这类问题因为总表被
    #        顺带召回，而把「转让股权」这种无关事项的材料带出来。
    if (_is_price_q(q) and items and items[0].get("id") == "fee"
            and items[0].get("_score", 0) >= 1.0):
        return True
    # 规则0：问题里出现某事项的别名（如「委托买房」→ 1 房屋车辆买卖委托），
    #        视为直接命中，这是最贴近用户口语的信号。
    #        兜底桶不在此列——避免用泛化别名抢走具体/官方事项的路由。
    for alias, no in K.ALIAS_INDEX.items():
        if len(alias) >= 3 and alias in q:
            for d in items:
                if d.get("no") == no and not _is_catchall(d):
                    return True
    q_tokens = {t for t in tokenize(q) if len(t) >= 2 and t not in GENERIC_WORDS}
    for idx, d in enumerate(items):
        name = d.get("title", "")
        core = _core_subject(name)
        # 兜底桶：核心词无实质含义（如「类」），跳过其独立认定
        if _is_catchall(d):
            continue
        if len(core) < 2:
            continue
        # 规则0.5：该事项有别名被问题直接命中
        for alias in K.ALIAS.get(d.get("no"), []):
            if len(alias) >= 3 and alias in q:
                return True
        # 规则1：事项核心词整体出现在问题里（最强信号）
        if core in q:
            return True
        # 规则2：核心词被拆成 ≥2 字的片段，片段出现在问题里，
        #        且该片段本身不是通用词/类型后缀
        frags = [s for s in re.split(r"[、，,/\s]+", core) if len(s) >= 2]
        if any(f in q for f in frags):
            return True
        # 规则3：问题中的 token 命中核心词，且该 token 覆盖核心词 ≥60%，
        #        或 token 长度 ≥3 且为核心词开头。
        #        长度门槛用于过滤「公司」「转让」这类 2 字泛词造成的跨界误判
        #        （如「公司章程」命中「公司股权协议」、「国有土地转让」命中「转让股权」）。
        for t in q_tokens:
            if len(t) < 2 or t not in core:
                continue
            if len(t) * 5 >= len(core) * 3:
                return True
            if len(t) >= 3 and core.startswith(t):
                return True
        # 规则4：首位结果得分压倒性领先，且核心词与问题存在 ≥3 字公共子串
        #        （应对「公众号主体迁移」vs「微信公众号主体迁移」这类近义表述；
        #        要求 ≥3 字是为了避免「转让」这种 2 字泛词误判成同一事项）
        if idx == 0 and len(items) > 1:
            top = items[0].get("_score", 0)
            nxt = max((x.get("_score", 0) for x in items[1:]), default=0)
            if top >= 5.0 and top >= nxt * 8:
                for i in range(len(core) - 2):
                    seg = core[i:i + 3]
                    if seg in q and seg not in GENERIC_WORDS:
                        return True
    return False


# ==================== 四要素抽取 ====================
FOUR = {
    "办什么公证": ["办什么", "什么公证", "办理什么", "想办", "要办", "我想做", "办理", "申请"],
    "户籍在哪儿": ["户籍", "户口", "籍贯", "老家", "户籍地", "哪里的户口", "户口本"],
    "在哪儿使用": ["在哪用", "哪里用", "使用地", "拿去", "用于哪个", "哪个国家", "出到", "用在",
                   "申根"],
    "用途是什么": ["用途", "干什么用", "做什么用", "为了", "用来", "目的",
                   "卖给", "卖给谁", "赠与给", "过户给", "给亲戚", "给朋友", "给子女",
                   "给孩子", "给父母", "转给", "资助", "担保", "继承给", "留给孩子",
                   "申根", "签证", "认证用", "落户", "上学", "入学"],
}

PROVINCES = [q["prov"] for q in K.QUOTES] + ["香港", "澳门", "台湾"]
COUNTRIES = ["美国", "加拿大", "澳大利亚", "英国", "日本", "韩国", "新加坡", "新西兰",
             "德国", "法国", "意大利", "西班牙", "荷兰", "马来西亚", "泰国", "越南",
             "菲律宾", "阿联酋", "俄罗斯", "巴西", "南非", "印度", "印尼"]

# 事项名词典：提到即认为「办什么公证」已明确
ITEM_WORDS = [
    "委托", "声明", "协议", "合同", "签字", "印鉴", "继承", "遗嘱", "出生", "学历", "学位",
    "成绩单", "毕业证", "抚养权", "监护", "亲属关系", "结婚证", "离婚", "死亡证明",
    "身份证", "户口本", "护照", "曾用名", "财产约定", "赠与", "赠予", "过户", "注销抵押",
    "结按", "股权", "分红", "出国留学", "随行", "不随行", "出行同意", "海牙", "公证",
]


def extract_four(text):
    """从提问中判断四要素哪些已明确、哪些缺失"""
    got = {}
    for slot, kws in FOUR.items():
        got[slot] = any(k in text for k in kws)
    # 办什么公证：出现具体事项名词即算明确
    if not got["办什么公证"] and any(w in text for w in ITEM_WORDS):
        got["办什么公证"] = True
    # 户籍：提到省份即认为已明确
    if not got["户籍在哪儿"] and any(p in text for p in PROVINCES):
        got["户籍在哪儿"] = True
    # 使用地：提到国家/国外字样即认为已明确
    if not got["在哪儿使用"]:
        if any(c in text for c in COUNTRIES):
            got["在哪儿使用"] = True
        elif any(w in text for w in ["国内使用", "国内用", "国外", "境外", "外国", "出国",
                                     "涉外", "海牙", "留学", "移民", "签证", "用于"]):
            got["在哪儿使用"] = True
    return got


def is_overseas(text):
    return any(w in text for w in ["国外", "境外", "外国", "出国", "涉外", "海牙",
                                   "留学", "移民", "签证"] + COUNTRIES)


# ==================== 大模型调用 ====================
def call_llm(model_id, messages, cfg, timeout=90):
    m = next((x for x in MODELS if x["id"] == model_id), None)
    if not m or m["provider"] == "none":
        return None, "该模式不使用大模型"
    key = cfg["keys"].get(m["provider"], "")
    if not key:
        return None, f"未配置 {m['provider']} 的 API Key，请点击右上角「配置」填入"
    base = cfg.get("customBase", {}).get(m["provider"], m["base"]).rstrip("/")
    url = base + "/chat/completions"
    body = json.dumps({
        "model": m["model"],
        "messages": messages,
        "temperature": cfg.get("temperature", 0.2),
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + key,
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"], None
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:300]
        return None, f"模型调用失败 HTTP {e.code}：{detail}"
    except Exception as e:
        return None, f"模型调用失败：{e}"


# ==================== 图片识图 ====================
# 识别图片内容并抽取「公证业务需求」。三类图片都要能读：
# ①证件/材料照片（不动产权证、房产证、户口本、公证书…）
# ②聊天/需求截图（微信里别人发的需求、代办描述）
# ③卷宗/文书扫描件（委托书、声明书、卷宗页）
VISION_PROMPT = """你是公证业务的需求识别助手。请阅读用户上传的图片，抽取其中与「公证办理」相关的业务信息。

【第一步 · 判断图片类型】
正证照 / 材料照片 / 聊天需求截图 / 卷宗文书 / 与公证无关 / 无法辨认

【第二步 · 按下面格式输出结构化结果】
图片类型：（上面六选一）
业务需求：（用一句话概括当事人到底想办什么公证。截图里若有多条需求，逐条列出）
涉及事项：（对应公证事项名，如 房屋买卖委托、结婚证公证、亲属关系公证、无犯罪记录公证；不确定就写「不确定」）
省份/户籍：（能看出的省份或城市；看不出写「未提及」）
使用地：（国内 / 具体国家 / 涉外；看不出写「未提及」）
用途：（留学、签证、移民、过户、诉讼、继承等；看不出写「未提及」）
关键信息：（证件号、产权证号、姓名等可见要点，涉及敏感号码用「已隐去」代替，不要完整复述）
能否判断：（能判断 / 信息不足）

【硬性要求】
1. 只描述图片里真实可见的内容，严禁脑补和推测图片外的信息。
2. 涉及身份证号、手机号、银行卡号等敏感信息，只写「已隐去」，不要抄录。
3. 图片与公证业务无关时，明确说「图片内容与公证业务无关」，不要强行编造需求。
4. 图片模糊无法辨认时，明确说「图片模糊，无法辨认」，并指出哪部分看不清。
5. 不要给出「能不能办」「多少钱」的结论——这一步只做识别，后续由业务系统判定。
"""


def vision_analyze(images, cfg, note="", provider=None, timeout=90):
    """用视觉模型识别图片内容。images 为 dataURL 或 http 地址列表。

    返回 (识别文本, 错误信息)。
    """
    if not images:
        return None, "未提供图片"
    # 选一个已配置 Key 的视觉模型
    provs = [provider] if provider else list(VISION_MODELS.keys())
    picked = None
    for p in provs:
        if p in VISION_MODELS and cfg["keys"].get(p):
            picked = p
            break
    if not picked:
        return None, ("图片识别需要视觉模型（智谱 GLM-4V / 通义千问 VL）。"
                      "请在右上角「配置」里填入智谱或通义的 API Key 后重试。")
    vm = VISION_MODELS[picked]
    base = cfg.get("customBase", {}).get(picked, vm["base"]).rstrip("/")
    content = [{"type": "text", "text": VISION_PROMPT}]
    for im in images[:4]:                      # 单次最多识别 4 张
        content.append({"type": "image_url", "image_url": {"url": im}})
    if note:
        content.append({"type": "text", "text": f"（用户补充说明：{note}）"})
    body = json.dumps({
        "model": vm["model"],
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.1,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(base + "/chat/completions", data=body, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + cfg["keys"][picked]})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"], None
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:300]
        return None, f"图片识别失败 HTTP {e.code}：{detail}"
    except Exception as e:
        return None, f"图片识别失败：{e}"


# 从识别文本中抽取检索用关键词
def vision_keywords(vtext):
    """把识图结果压成一句可用于检索的查询串（事项词 + 省份 + 用途）。"""
    parts = []
    for line in (vtext or "").split("\n"):
        if "：" not in line:
            continue
        k, v = line.split("：", 1)
        k, v = k.strip().lstrip("-* ").strip(), v.strip()
        if k.startswith("业务需求") or k.startswith("涉及事项"):
            parts.insert(0, v)
        elif k.startswith("省份") or k.startswith("户籍") or k.startswith("用途"):
            if v and v not in ("未提及", "—", "-"):
                parts.append(v)
    return " ".join(p for p in parts if p)[:300]


# ==================== 提示词 ====================
SYSTEM = """你是「证小安」公证业务知识库助手。你的职责不是检索资料，而是做四要素分析型问答。

【铁律】回答任何公证问题，必须围绕四个要素展开：
① 办什么公证  ② 户籍在哪儿  ③ 在哪儿使用  ④ 用途是什么

【最高优先级 · 有问必答】
当事人明确问到的每个子问题，都必须在回答中正面、直接地给出答案，严禁跳过：
- 问「要几天/多久」→ 必须给出办理周期（上下文中的「办理周期」数据就是答案）
- 问「多少钱/费用」→ 必须给出价格
- 问「需要什么材料」→ 必须给出材料清单（或明确说明未收录）
- 问「能不能办」→ 必须给出可办性结论
- 提到特定用途/场景（如「申根签」「出国留学」）→ 必须针对该场景给出说明与要求
先答完所有被问到的问题，再谈要素补齐；禁止用「还缺信息」把没答的问题糊弄过去。

【工作步骤】
1. 边答边问，禁止只追问不给内容：
   - 拿「当事人已明确的要素」先匹配知识库，把当前能确定的分析直接说出来：
     可能适用的事项条目（编号、价格、关键材料、受理限制），以及已经可以确定的结论
   - 若缺失的要素会导致不同结论，用「若…则…」简要分情况说明
   - 全部分析给完之后，最后用一两句话请当事人补充仍缺的要素，不要展开长篇追问
2. 四要素齐全后做完整分析：
   - 归类：归入具体的公证事项条目
   - 校验：逐项核对地域限制、产权性质限制、线上可办性、涉外可认可性
   - 冲突识别：四要素与知识库限制冲突时，直接指出冲突点
   - 方案比较：存在多种路径时（如车辆过户可选协议公证或赠与公证），比较并推荐
   - 风险提示：主动提示不被认可的风险
3. 输出结构：结论 → 依据（标注条目编号）→ 办理要素 → 材料清单 → 价格与时长 → 下一步
   （要素不全时先给「初步判断」，可用的结构类似，但必须有实质内容和依据）

【办理状态口径】
知识库每条事项都标注了办理状态：☑ 可办理（能受理）、☐ 不能办理（线上不受理或受限）。
- 命中 ☑ 事项：给出结论、依据、办理要素、材料清单、价格、下一步
- 命中 ☐ 事项：明确告知不能办理及原因，并指出替代方案（如继承公证线上办不了，可做放弃继承或委托继承）
- 禁止把 ☐ 不能办理的事项说成可以办理

【办理周期口径 · 严禁编造】
- 上下文给出「办理周期 · 来源：知识库各省报价表」时，**只能**引用该数据
  （公证出具 3-5 个工作日；公证+认证 10-15 个工作日）。
- 未给出该数据时，不得说出任何具体周期数字（如「5-7 个工作日」），
  只能说明「以公证处实际受理进度为准」。
- 严禁把行业常见值当成我司口径。

【依据来源优先级】
1. 优先用「知识库检索到的相关条目」作答，标注条目编号。
2. 「办理周期 · 来源：知识库各省报价表」属于知识库内容，问周期时直接引用。
3. 知识库未收录该事项时，用「司法部官方证明材料清单」作答，标注来源为司法部官方清单；这是权威口径。
4. 官方清单也没有时，用「网络检索结果」作答，并明确标注来自网络检索、仅供参考、须以使用地公证处口径为准。
5. 以上都没有时，才说明「当前知识库未提供」，并建议补充文档或联系负责人确认。

【未完全匹配 · 展示相关知识点（重要）】
当事人问的事项在知识库里**没有完全匹配的条目**时（上下文会出现
「相关知识点 · 知识库暂无与提问完全匹配的条目」块），必须遵守：
1. **不得直接套用相近条目的结论**。例如相近条目说「监护权变更不能公证」，
   不能据此把当事人问的「意定监护公证」判为不可办理——两者是不同事项，
   意定监护恰恰是《民法典》允许的书面约定。相近条目只能作为背景参考并标注差异。
2. **不得猜价格、不得编造材料清单**。禁止「可能 699 元起」「建议准备以下可能
   需要的材料」这类模糊编造；未收录就说未收录。
3. **必须展示相关知识点**（这是当事人明确要求的行为），组织为：
   ① 概念与法律依据：这个事项是什么、哪部法律哪一条规定（可引用上下文中的
      官方清单相关事项、联网检索结果；不得虚构条款号）；
   ② 办理要求与限制：官方清单相关事项的材料清单、相近条目中的限制口径
      （标注条目号，并说明与所问事项的差异）；
   ③ 常见用途与场景：这类公证通常用在哪；
   ④ 明确说明「知识库暂无该具体事项条目，以下为相关知识点整理」，
      最终以办理公证处口径为准。
4. 上下文有「司法部官方清单 · 相关事项」的，材料部分引用它（标注来源），
   而不是自行罗列。
5. 上下文有联网检索结果时引用并标注「来自网络检索」；没有时不得虚构来源。

【涉外公证 · 国家判定（必须回答）】
当事人的公证用于境外、且提到了具体国家/地区（如「美国」「韩国」「申根」「马来西亚」）时，
除常规分析外，**必须正面回答以下两件事，缺一不可**：
1. **单号还是双号**：说明该国通常建议做单号还是双号公证，并解释区别
   ——单号＝仅公证中文原件；双号＝中文原件＋译文均做公证（境外认可度更高，涉外一般建议双号）。
2. **是否必须海牙认证**：说明该国是否属《取消外国公文书认证要求的公约》（海牙公约）适用范围：
   - 属海牙公约国 → 通常办海牙认证（Apostille）即可，无需领事认证；
   - 非海牙公约国 → 通常需领事认证（使馆认证，即「双认证」）。
3. 知识库**没有「国家→单双号/海牙」对照表**。若上下文给出了「涉外国家判定」段与
   相关「网络检索结果」，按其作答；检索未果时，如实说明**未能确认**，
   给出较可能的判断方向，并提示**以使用地收件机构及公证处最终口径为准**。
4. 严禁因为知识库没有收录就跳过这两点不答，也不得编造确定性的结论。

【知识库内容 vs 补充内容 · 必须区分标注】
- 命中知识库时，知识库已有内容作为主答案，标注条目编号。
- 若知识库条目本身缺少提问所需的内容（如「材料」字段为空），而系统补充提供了
  「网络检索结果」，则这部分内容属于**非现有知识库内容，仅做参考**。
- 引用补充内容时，必须单独起一段，以「（以下为非现有知识库内容，仅做参考）」
  开头，明确说明知识库未收录、内容来自网络检索、须以使用地公证处口径为准。
- 严禁把补充内容与知识库内容混在一起不加区分，也不得让补充内容看起来像知识库结论。
- 【严禁虚构来源】上下文中**没有**「网络检索结果」块时，绝不可在回答里写
  「根据网络检索」「据检索结果」「官方清单显示」等字样——本次并未取得这些来源。
  此时只能如实说明「该项暂未收录」，可用一般常识谨慎解释，不得声称有来源。

【严禁跨条目挪用材料】
- 材料清单只能取自：①当事人所问事项对应的知识库条目；②司法部官方清单中同一事项；③网络检索结果中同一事项。
- 严禁把 A 事项的材料（如户口本公证、亲属关系公证、房屋委托公证的材料）安到 B 事项上。
- 若所列来源均无该事项材料，必须明确说「该项材料暂未收录」，不得凭常识编造，也不得用其他事项材料凑数。
- 【最容易犯的错误】当检索结果里同时出现多个条目时，材料必须严格对应到「当事人实际所问的那一个事项」。
  例如问「遗嘱公证」，而检索结果里另有「委托继承」条目，**绝不能**把「委托继承」的材料
  （委托人身份证、与被继承人关系证明、被继承人死亡证明、受托人身份证等）写成遗嘱公证的材料。
  当事人所问事项的材料为空时，就直接说该事项材料暂未收录，宁可留白也不得挪用。
- 【高风险事项 · 材料为空时禁止推测】以下事项在知识库里没有材料字段，属人身关系/形式要件类，
  仅凭常识极易编错：遗嘱公证、继承公证、转让股权、公司股权协议、孩子监护、涉及人身关系的公证、
  委托涉及矿产类、出国随行/不随行公证。对这类事项，材料部分一律写明「知识库暂未收录」，
  可附网络检索结果并标注「仅做参考」，不得自行罗列通用材料充数。

【禁止】
- 禁止只抛出追问、不给任何实质性分析内容
- 禁止仅摘抄知识库原文片段作为回答
- 禁止编造价格、材料清单、受理结论
- 禁止追问当事人已经明确说过的要素

【语气】专业、直接、给结论，不绕弯。"""


def build_context(hits):
    if not hits:
        return "（知识库未检索到相关条目）"
    parts = []
    for h in hits:
        tag = "【☑ 可办理】" if h.get("ok", True) else "【☐ 不能办理】"
        parts.append(f"--- {tag} {h['title']} ---\n{h['content']}")
    return "\n\n".join(parts)


# 知识库条目中「属于实质缺口」的字段：这些字段为空时，
# 说明该条目的回答不完整，需要补充联网查询。
_GAP_FIELDS = ("材料", "价格", "要求", "户籍在哪儿", "在哪儿使用", "用途是什么")

# 「附加主题」词表：问题里问到了、但知识库条目内容可能完全没覆盖的知识主题
# （如「申根签的要求/时间」）。若问题含某主题而所有命中条目都未提到该词，
# 视为主题缺口 → 补充联网检索并按「非现有知识库内容」标注。
TOPIC_WORDS = ("申根", "双认证", "领事认证", "使馆认证", "海牙", "翻译", "译文", "公证词")


def kb_gaps(hits):
    """找出知识库命中条目相对提问的内容缺口。

    返回 [(类型, 标识, 条目), ...]，类型为 "field"（字段为空）或 "topic"（主题未覆盖）：
    - ("field", "材料", <遗嘱公证条目>)   ：条目「材料」字段为空
    - ("topic", "申根", <top1 条目>)      ：问题问申根而条目内容均未提及
    收费总表等平台类文档不参与「字段为空」判定。
    """
    out = []
    seen = set()
    for h in hits:
        if str(h.get("id", "")).startswith("case-"):
            continue
        body = h.get("content") or ""
        # 解析「字段：值」结构；值可能为空（形如「材料：」行尾）
        for line in body.split("\n"):
            if "：" not in line:
                continue
            k, v = line.split("：", 1)
            k = k.strip()
            if k in _GAP_FIELDS and not v.strip() and (k, h.get("id")) not in seen:
                seen.add((k, h.get("id")))
                out.append(("field", k, h))
    return out


def topic_gaps(q, hits):
    """问题中提到、但命中条目内容完全未覆盖的「附加主题」。"""
    qt = q or ""
    return [t for t in TOPIC_WORDS
            if t in qt and not any(t in (h.get("content") or "") for h in hits)]


def _gap_subject(gaps, hits):
    """从缺口条目或首位命中里取事项主体词（剥类目前缀与编号）。"""
    cands = [h for _k, _t, h in gaps if h] or list(hits or [])
    for h in cands:
        t = (h.get("title") or "").split("·")[-1].strip()
        t = re.sub(r"^\d+\s*[\.、]\s*", "", t).strip()
        if t and not (("其他" in t) or ("一般" in t)):
            return t
    return ""


def gap_web_search(q, gaps, topics=(), user_q=""):
    """针对知识库缺口（字段空缺 / 主题未覆盖）补充联网查询。

    只在确有缺口时触发，避免命中知识库后仍无条件联网。
    - 主题缺口（如问「申根签」而条目未提）→ 检索「{事项} 公证 申根签证 要求 办理时间」
    - 字段缺口（如「材料」为空）→ 沿用「{问题词} {事项} 公证处 需要什么材料」
    返回 (文本, 是否成功)。
    """
    if not gaps and not topics:
        return "", False
    base = re.sub(r"(怎么|如何|需要|什么|哪些|办理|流程|材料|资料|要|吗|\?|？|。|，|,|\s)+", " ",
                  (user_q or q or "")).strip()
    queries = []          # (检索式, 主题校验词；空=按公证相关性过滤)
    if topics:
        # 主题查询用纯主题词（不带事项前缀——组合长查询会被搜索引擎错误
        # 分词，混入「结婚/抖音」类完全无关的结果）；「申根」补全为「申根签证」
        tlabels = [("申根签证" if t == "申根" else t) for t in topics]
        tq = " ".join(tlabels)
        queries.append((f"{tq} 公证 认证 要求", tuple(tlabels)))
        queries.append((f"{tq} 办理流程 材料 时间", tuple(tlabels)))
    subj = _gap_subject(gaps, [])
    if any(k == "field" for k, _t, _h in gaps) and subj:
        queries.append((f"{base} {subj} 公证处 需要什么材料", ()))
    for query, must in queries:
        txt, ok = web_search(query, limit=4, require_notary=not must,
                             must_contain=must)
        if ok:
            return txt, True
    return "", False


# ==================== 涉外国家判定：单号/双号 · 是否必须海牙 ====================
def country_rule_search(country, item="", timeout=9):
    """取某国涉外公证的「单双号 / 海牙认证」要求依据。

    判定主干为外交部《公约》缔约国名单（权威，见 hague_data），
    本函数只负责补充联网佐证。注意：必应对「国家名 + 公证」类长查询
    分词效果差（常返回国别百科），因此检索式刻意避开长组合，
    并用机制类查询（Apostille / 附加证明书）提高命中质量。
    返回 (检索文本, 是否成功)。
    """
    if not country:
        return "", False
    is_member, norm = HG.is_hague_member(country)
    queries = []
    if is_member:
        queries.append((f"附加证明书 Apostille 办理流程 公证书", ("公证", "证明书")))
        queries.append((f"{norm} 海牙认证 公证书 使用", ("公证",)))
    else:
        queries.append((f"{norm} 领事认证 公证书 办理", ("公证", "认证")))
        queries.append((f"{norm} 公证 双认证 使馆认证", ("公证",)))
    for qs, must in queries:
        txt, ok = web_search(qs, limit=4, require_notary=True, must_contain=must,
                             timeout=timeout)
        if ok:
            return txt, True
    return "", False


def country_ruling_note(countries, item="", user_q="", web_txt="", web_ok=False):
    """组装涉外国家的「单号/双号 · 是否必须海牙」判定结论段。

    是否属海牙公约适用范围：以中国领事服务网（外交部）《公约》缔约国名单
    为权威依据（hague_data），联网检索作为补充佐证。
    """
    if not countries:
        return ""
    lines = ["【涉外国家判定 · 单号/双号与海牙认证】"]
    for c in countries:
        is_member, norm = HG.is_hague_member(c)
        lines.append(f"● {c}：")
        # ① 单号 / 双号
        lines.append("  - 单号 / 双号：涉外场景**通常建议做双号**"
                     "（双号＝中文原件＋译文均做公证，境外机构对译文效力认可度更高）；"
                     "若使用地机构明确只要求中文文件，可做单号。最终以使用地要求为准。")
        # ② 是否必须海牙（依据官方缔约国名单）
        if is_member:
            lines.append(f"  - 是否必须海牙认证：{c} 属《取消外国公文书认证要求的公约》"
                         "（海牙公约）缔约国，**通常办海牙认证（附加证明书 / Apostille）即可**，"
                         "无需再办领事认证（双认证）。"
                         "但仍需确认具体收件机构是否另有要求（少数机构会额外要求翻译件公证）。")
        else:
            lines.append(f"  - 是否必须海牙认证：{c} **不在**外交部公布的《公约》缔约国名单内，"
                         "通常**需要办领事认证（使馆认证，即「双认证」）**，"
                         "即「公证 → 外交部/地方外办认证 → 使用国驻华使领馆认证」。"
                         "若该国近期已加入公约或收件机构另有规定，请以使用地机构口径为准。")
    lines.append("")
    lines.append(f"（判定依据：{HG.hague_source_note()}。"
                 "缔约国名单为外交部官方口径；个别收件机构可能有额外要求，"
                 "办理前请与使用地机构或办理公证处最终确认。）")
    if web_ok and web_txt:
        lines.append("")
        lines.append("（以下为联网检索到的相关信息，属非现有知识库内容，仅供参考）")
        lines.append(web_txt)
    # 价格：知识库有单双号与「+海牙」分档 → 提示可据此报价
    if K.QUOTES:
        lines.append("")
        lines.append("（价格提示：知识库各省报价表已按「单号公证 / 双号公证 / "
                     "单号公证+海牙 / 双号公证+海牙」四档分列，可结合户籍所在省报价。）")
    return "\n".join(lines)



# ==================== 网络检索兜底 ====================
WEB_CACHE = {}
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def _bing_parse(html, limit=5):
    """解析必应搜索结果（标题 + 摘要）"""
    import html as _html
    items = re.findall(r'<li class="b_algo".*?</li>', html, re.S)
    out = []
    for it in items[:limit]:
        mt = re.search(r'<h2[^>]*>(.*?)</h2>', it, re.S)
        mc = re.search(r'<p[^>]*>(.*?)</p>', it, re.S)
        t = re.sub(r"<[^>]+>", "", mt.group(1)).strip() if mt else ""
        c = re.sub(r"<[^>]+>", "", mc.group(1)).strip() if mc else ""
        # 还原全部 HTML 实体（&nbsp; &#0183; &quot; 等）
        t = _html.unescape(t).replace("\u00a0", " ")
        c = _html.unescape(c).replace("\u00a0", " ")
        if t and len(t) > 4:
            out.append({"title": t, "snippet": c})
    return out


# 口语事项名 → 司法部官方清单用词
# 用户口语常与官方清单用词不一致（口语「转让股权」vs 官方「股权转让协议」），
# 直接匹配不到会造成「官方清单明明有、却答不出来」。
_OFFICIAL_SYNONYM = {
    "转让股权": "股权转让协议",
    "股权转让": "股权转让协议",
    "股权公证": "股权转让协议",
    "遗嘱": "处理事务的遗嘱",
    "遗嘱公证": "处理事务的遗嘱",
    "公司股权协议": "股权转让协议",
    "意向监护": "意定监护",
    "意向监护公证": "意定监护",
    "意定监护公证": "意定监护",
    "监护公证": "法定监护",
    "监护权公证": "法定监护",
}

# 2 字片段黑名单：这些片段太通用，不作为「相关条目」的判定依据
_GENERIC_SEGS = {"公证", "证明", "办理", "书证", "证公", "明书", "件复", "复印",
                 "委托书", "声明书", "事项", "问题", "怎么", "什么", "需要",
                 "可以", "能否", "是不是", "多少", "哪里", "哪个"}


def _core_segs(text):
    """抽问句中的 2 字汉字片段（用于相关主题匹配）。"""
    t = text or ""
    out = set()
    for i in range(len(t) - 1):
        seg = t[i:i + 2]
        if re.match(r"^[\u4e00-\u9fa5]{2}$", seg) and seg not in _GENERIC_SEGS:
            out.add(seg)
    return out


def official_related(query, limit=3):
    """官方清单中与问句主题**相关**的条目（非精确匹配）。

    匹配方式：问句与官方键名共享有意义的 2 字片段（如「意向监护公证」
    与「意定监护」共享「监护」）。用于知识库未完全命中时展示相关知识点。
    返回 [(key, info), ...] 按共享度降序。
    """
    qsegs = _core_segs(query)
    if not qsegs:
        return []
    scored = []
    for key, info in O.OFFICIAL.items():
        ksegs = _core_segs(key)
        common = qsegs & ksegs
        if common:
            scored.append((len(common), key, info))
    scored.sort(key=lambda x: (-x[0], len(x[1])))
    return [(k, info) for _s, k, info in scored[:limit]]


def _normalize_topic_words(q):
    """口语 → 官方/规范术语替换（用于联网检索），返回 (规范词列表, 是否发生替换)。"""
    words = []
    hit = False
    for spoken, formal in _OFFICIAL_SYNONYM.items():
        if spoken in (q or ""):
            words.append(formal)
            hit = True
    return words, hit


def related_knowledge_note(q, kb_hits=(), official_hit=False, want_web=True):
    """组装「相关知识点」块：知识库无完全匹配条目时，把相关知识展示给当事人。

    用户明确要求：库里没有时，不要只回「未收录 + 猜测」，而要把相关的
    知识点、办理要求、限制等展示出来。本函数收集三类素材：
      ① 官方清单相关事项（材料参考）——权威；
      ② 知识库相关条目（标注「非完全匹配」，突出限制/要求字段）；
      ③ 联网检索（用规范术语，如「意向监护」→「意定监护」）。
    返回 (文本, 联网文本, 联网是否成功)。
    """
    rel_off = official_related(q)
    rel_off = [(k, info) for k, info in rel_off] if not official_hit else []
    kb_rel = [h for h in (kb_hits or []) if h.get("_score", 0) >= 0.5][:3]

    web_txt, web_ok = "", False
    if want_web:
        norm_words, replaced = _normalize_topic_words(q)
        queries = []
        if replaced:
            queries.append(" ".join(norm_words) + " 公证 办理要求 法律规定")
        base = re.sub(r"(怎么|如何|需要|什么|哪些|办理|流程|材料|资料|吗|\?|？|。|，|,|\s)+",
                      " ", q).strip()
        queries.append(f"{base} 公证 办理要求 限制")
        for qs in queries:
            t, ok = web_search(qs, limit=4, require_notary=True)
            if ok:
                web_txt, web_ok = t, ok
                break

    if not rel_off and not kb_rel and not web_ok:
        return "", web_txt, web_ok

    lines = ["【相关知识点 · 知识库暂无与提问完全匹配的条目】"]
    if rel_off:
        lines.append("")
        lines.append("一、司法部官方清单中的相关事项（材料参考，注意区分具体事项）：")
        for k, info in rel_off:
            mats = "\n".join(f"    {i}. {m}" for i, m in enumerate(info["materials"], 1))
            lines.append(f"  ◦ {info.get('name') or k}：")
            lines.append(mats)
    if kb_rel:
        lines.append("")
        lines.append("二、知识库中的相关条目（与所问事项相近，但**不是同一事项**，注意区分）：")
        for h in kb_rel:
            tag = "☑ 可办理" if h.get("ok", True) else "☐ 不能办理"
            lines.append(f"  ◦ 条目 {h['no']} {h['title'].split('·')[-1].strip()}［{tag}］")
            body = h.get("content") or ""
            keep = [l for l in body.split("\n")
                    if any(l.startswith(f"{f}：") for f in ("结论", "要求", "办什么公证", "用途是什么"))
                    and l.split("：", 1)[-1].strip()]
            for l in keep[:3]:
                lines.append(f"      {l}")
    if web_ok and web_txt:
        lines.append("")
        lines.append("三、联网检索 · 该主题的法律依据与办理要求：")
        lines.append(web_txt)
    lines.append("")
    lines.append("（以上为相关知识点的整理，并非对所问事项的最终结论；"
                 "具体能否办理、材料与费用，以办理公证处口径为准。）")
    return "\n".join(lines), web_txt, web_ok


def official_lookup(query, extra_keys=None):
    """知识库未收录时，查司法部官方《公证事项证明材料清单》底库。
    返回 (文本, 是否命中)。这是权威来源，优先于网络检索。

    extra_keys：候补检索词（如知识库条目名、常见同义写法）。
    用户口语常与官方清单用词不一致（如口语「转让股权」vs 官方「股权转让协议」），
    直接用语原句匹配不到，因此再用候补词逐个尝试。
    """
    q = (query or "").strip()
    if not q and not extra_keys:
        return "", False
    hit = None
    # 先在官方底库中按关键词匹配（取最长命中）
    for key in sorted(O.OFFICIAL.keys(), key=len, reverse=True):
        if key in q:
            hit = O.OFFICIAL[key]
            break
    # 口语词形预替换：问句含 _OFFICIAL_SYNONYM 的口语键时，用其规范词再匹配一轮
    # （如口语「意向监护」→ 官方术语「意定监护」，字面不同导致直接匹配漏检）
    if not hit:
        for spoken, formal in _OFFICIAL_SYNONYM.items():
            if spoken in q:
                for key in sorted(O.OFFICIAL.keys(), key=len, reverse=True):
                    if key == formal or key in formal or formal in key:
                        hit = O.OFFICIAL[key]
                        break
            if hit:
                break
    if not hit:
        hit = O.lookup(q)
    # 候选词逐个尝试：候补词本身 + 口语→官方用词的同义映射
    if not hit:
        cands = []
        for k in (extra_keys or []):
            k = (k or "").strip()
            if len(k) < 2:
                continue
            cands.append(k)
            if k in _OFFICIAL_SYNONYM:
                cands.append(_OFFICIAL_SYNONYM[k])
        for k in cands:
            k = k.strip()
            if len(k) < 2:
                continue
            for key in sorted(O.OFFICIAL.keys(), key=len, reverse=True):
                if key in k or k in key:
                    hit = O.OFFICIAL[key]
                    break
            if not hit:
                hit = O.lookup(k)
            if hit:
                break
    if not hit:
        return "", False
    mats = "\n".join(f"  {i}. {m}" for i, m in enumerate(hit["materials"], 1))
    return (f"【司法部官方证明材料清单 · {hit['name']}】\n{mats}"), True


def _bing_fetch(q, ensearch=0, timeout=9):
    """请求必应搜索页。ensearch=0 中文版 / 1 国际版。

    中文版对部分组合词（如「申根签证」）存在分词故障——会把「申根」拆成单字
    「申」并返回字典类噪声，此时需要回退到国际版重查。
    """
    import urllib.parse
    url = ("https://cn.bing.com/search?q=" + urllib.parse.quote(q)
           + f"&setlang=zh-CN&ensearch={ensearch}")
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Language": "zh-CN,zh;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def _bing_pick(html, limit, require_notary=True, must_contain=()):
    """解析并过滤必应结果。
    - require_notary=False 时放宽「公证」相关性强制，用于主题缺口查询
      （如问「申根签证」主题本身，结果与主题相关即可）；
    - must_contain 非空时，结果标题/摘要必须包含其中之一（主题词二次校验，
      防止组合词被搜索引擎错误分词后混入完全无关的「结婚/抖音」类结果）。"""
    res = _bing_parse(html, limit * 3)
    # 噪声过滤：词典/翻译/百科类，以及纯词条解释
    noise = ("词典", "翻译", "读音", "的意思", "是什么意思", "音标", "例句",
             "百度百科", "_百度百科", "MBA智库", "维基百科", "百科 _")
    res = [x for x in res if not any(n in x["title"] for n in noise)]
    if must_contain:
        res = [x for x in res
               if any(m in (x["title"] + x["snippet"]) for m in must_contain)]
    if require_notary:
        # 相关性过滤：结果需与「公证」相关（标题或摘要出现公证/公证书/公证处）
        _kw = ("公证", "公证书", "公证处", "涉外公证", "司法")
        res = [x for x in res if any(k in (x["title"] + x["snippet"]) for k in _kw)]
    return res[:limit]


def web_search(query, limit=5, timeout=9, require_notary=True, must_contain=()):
    """网络检索补充（必应中文，失败自动回退必应国际版）。返回 (文本, 是否成功)

    对结果做相关性过滤：进入本函数的问题基本都带「公证」语境，
    因此要求结果标题/摘要必须与「公证」相关，否则视为未取得有效结果，
    避免把百科、物流、服装批发这类明显无关的搜索结果带进答案。
    主题类查询（require_notary=False）只做噪声过滤与主题词校验。
    """
    q = (query or "").strip()
    if not q:
        return "", False
    cache_key = f"{q}|{int(require_notary)}|{','.join(must_contain)}"
    if cache_key in WEB_CACHE:
        return WEB_CACHE[cache_key], bool(WEB_CACHE[cache_key])
    res = []
    err = None
    try:
        # 先中文版；中文版无有效结果（含分词故障场景）再回退国际版
        for ens in (0, 1):
            html = _bing_fetch(q, ensearch=ens, timeout=timeout)
            res = _bing_pick(html, limit, require_notary=require_notary,
                             must_contain=must_contain)
            if res:
                break
    except Exception as e:
        err = e
    if not res:
        WEB_CACHE[cache_key] = ""
        return (f"（网络检索未成功：{err}）" if err else ""), False
    lines = []
    for i, it in enumerate(res, 1):
        lines.append(f"{i}. {it['title']}")
        if it["snippet"]:
            lines.append(f"   摘要：{it['snippet'][:180]}")
    txt = ("【网络检索结果 · 仅供参考，最终以使用地公证处口径为准】\n"
           + "\n".join(lines))
    WEB_CACHE[cache_key] = txt
    return txt, True


def kb_catalog(include_internal=False):
    """知识库全部事项目录（按类目分组，含编号与价格），供模型在要素不全时给出可能方向"""
    seen = {}
    order = []
    for it in K.all_items():
        if it["cat"] not in seen:
            seen[it["cat"]] = []
            order.append(it["cat"])
        price = (it.get("price") or "").split("（")[0]
        flag = "☑" if it["ok"] else "☐"
        seen[it["cat"]].append(f"{flag}{it['no']}.{it['name']}" + (f"（{price}）" if price else ""))
    return "\n".join(f"{cat}：" + "；".join(seen[cat]) for cat in order)


# ==================== HTTP 服务 ====================
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, data, ctype="application/json; charset=utf-8"):
        if isinstance(data, (dict, list)):
            data = json.dumps(data, ensure_ascii=False).encode("utf-8")
        elif isinstance(data, str):
            data = data.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    def do_OPTIONS(self):
        # CORS 预检：Pages 等跨域前端发 JSON POST 前会先发 OPTIONS
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self):
        # HEAD 探测支持（此前未实现返回 501，部分客户端健康检查会失败）
        p = urlparse(self.path).path
        name = {"/": "full.html", "/full.html": "full.html",
                "/index.html": "index.html",
                "/weixin.html": "weixin.html"}.get(p)
        f = os.path.join(os.path.dirname(os.path.abspath(__file__)), name) if name else ""
        if f and os.path.exists(f):
            n = len(open(f, "rb").read())
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(n))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        p = urlparse(self.path).path
        cfg = load_cfg()
        # 完整版（含模型选择/图片识别，调用 /api/*）
        if p in ("/", "/full.html"):
            f = os.path.join(os.path.dirname(os.path.abspath(__file__)), "full.html")
            if os.path.exists(f):
                return self._send(200, open(f, encoding="utf-8").read(), "text/html; charset=utf-8")
            return self._send(404, "full.html not found", "text/plain; charset=utf-8")

        # 静态版（与 GitHub Pages 一致，零后端依赖）
        if p == "/index.html":
            f = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
            if os.path.exists(f):
                return self._send(200, open(f, encoding="utf-8").read(), "text/html; charset=utf-8")
            return self._send(404, "index.html not found", "text/plain; charset=utf-8")

        # 微信精简版（自包含单页，零跨域请求）
        if p == "/weixin.html":
            f = os.path.join(os.path.dirname(os.path.abspath(__file__)), "weixin.html")
            if os.path.exists(f):
                return self._send(200, open(f, encoding="utf-8").read(), "text/html; charset=utf-8")
            return self._send(404, "weixin.html not found", "text/plain; charset=utf-8")

        if p == "/api/models":
            out = []
            for m in MODELS:
                ok = (m["provider"] == "none") or bool(cfg["keys"].get(m["provider"]))
                out.append({"id": m["id"], "label": m["label"], "desc": m["desc"],
                            "free": m["free"], "tier": m["tier"], "ready": ok})
            return self._send(200, {"models": out, "default": cfg["defaultModel"]})

        if p == "/api/kb":
            # 权限控制：目录与条目详情对所有人可见；
            # 仅「各省报价表」为内部信息，需管理员密码；收费总表对外可见（无价格留空）
            qs = parse_qs(urlparse(self.path).query)
            internal = qs.get("internal", ["0"])[0] in ("1", "true")
            rows = [r[:2] if len(r) > 2 else r for r in K.FEE_TABLE] if internal else K.FEE_TABLE
            base = {"kb": K.KB, "platform": K.PLATFORM,
                    "feeTable": rows, "cases": K.CASES, "limited": K.LIMITED,
                    "quoteHeaders": [], "quoteNotes": [], "quotes": [], "blocked": K.BLOCKED,
                    "admin": False,
                    "stats": {"total": len(K.all_items()),
                              "ok": len(K.ok_items()),
                              "no": len(K.blocked_items())}}
            if internal:
                passed = qs.get("pass", [""])[0] == cfg.get("adminPass")
                if not passed:
                    return self._send(401, {"error": "管理员密码错误"})
                base.update({"quotes": K.QUOTES, "quoteHeaders": K.QUOTE_HEADERS,
                             "quoteNotes": K.QUOTE_NOTES, "admin": True})
            return self._send(200, base)

        if p == "/api/config":
            provs = {}
            for prov in ENV_KEYS:
                k = cfg["keys"].get(prov, "")
                provs[prov] = {"set": bool(k), "mask": (k[:4] + "****" + k[-4:]) if len(k) > 8 else ("****" if k else "")}
            return self._send(200, {"providers": provs, "defaultModel": cfg["defaultModel"],
                                    "topK": cfg.get("topK", 4), "temperature": cfg.get("temperature", 0.2)})

        if p == "/api/health":
            return self._send(200, {"ok": True, "models": len(MODELS), "docs": len(DOCS)})

        return self._send(404, {"error": "not found"})

    def do_POST(self):
        p = urlparse(self.path).path
        cfg = load_cfg()
        b = self._body()

        if p == "/api/search":
            q = (b.get("q") or "").strip()
            hits = search(q, k=int(b.get("k") or cfg.get("topK", 4)),
                          include_internal=b.get("includeInternal", True))
            return self._send(200, {"hits": [{"title": h["title"], "ok": h.get("ok", True), "no": h["no"]} for h in hits]})

        if p == "/api/vision":
            # 图片识别：读图 → 抽取业务需求 → 复用 /api/ask 的检索判定链路
            images = [x for x in (b.get("images") or []) if isinstance(x, str) and x]
            note = (b.get("note") or "").strip()
            if not images:
                return self._send(400, {"error": "请先选择图片"})
            if len(images) > 4:
                images = images[:4]
            vtxt, verr = vision_analyze(images, cfg, note)
            if verr:
                return self._send(200, {"ok": False, "error": verr,
                                        "answer": f"⚠️ {verr}"})
            return self._send(200, {"ok": True, "vision": vtxt,
                                    "query": vision_keywords(vtxt)})

        if p == "/api/ask":
            q = (b.get("q") or "").strip()
            model = b.get("model") or cfg["defaultModel"]
            internal_view = bool(b.get("internalView"))
            # 对话历史：[{role:"user"|"assistant", text:"..."}]
            hist = [h for h in (b.get("history") or [])
                    if isinstance(h, dict) and isinstance(h.get("text"), str) and h["text"].strip()]
            hist = hist[-8:]  # 最多保留最近 4 轮
            # 识图结果（由 /api/vision 得到后随提问一起提交）：
            # 作为补充材料注入，并在答案开头回显「我读到了什么」
            vision_ctx = (b.get("vision") or "").strip()
            if not q and not vision_ctx:
                return self._send(400, {"error": "请输入问题或上传图片"})
            if not q and vision_ctx:
                q = vision_keywords(vision_ctx) or "图片中的公证需求"

            # ---- 四要素：当前问题 + 历史用户消息 + 识图结果 合并判断 ----
            # 某一要素只要在任何一轮中明确过，后续就不再追问
            four = extract_four(q)
            hist_user_texts = [h["text"].strip() for h in hist if h.get("role") == "user"]
            for t in hist_user_texts:
                hf = extract_four(t)
                for k, v in hf.items():
                    four[k] = four[k] or v
            if vision_ctx:
                # 图片里读到的省份/用途/使用地也算已明确；
                # 但「未提及」的字段行要剔除，否则「户籍：未提及」会被误判为已明确
                vtext_for_four = "\n".join(l for l in vision_ctx.split("\n")
                                           if "未提及" not in l and "无法辨认" not in l)
                for k, v in extract_four(vtext_for_four).items():
                    four[k] = four[k] or v
            missing = [k for k, v in four.items() if not v]

            # ---- 检索：识图关键词 + 当前问题 + 最近两轮用户输入 ----
            search_q = " ".join(hist_user_texts[-2:] + [q])
            if vision_ctx:
                # 识图出的事项词是检索主信号（"这个能办吗"这类问题本身无事项词）
                vk = vision_keywords(vision_ctx)
                if vk:
                    search_q = vk + " " + search_q
            # 相关性判定同样要用检索串：识图场景下用户问题常是「能办吗」这类
            # 无事项词的问法，用原句判定会误判为「知识库未收录」
            rel_q = search_q if vision_ctx else q
            topk = int(b.get("k") or cfg.get("topK", 4))
            hits = search(search_q, k=topk, include_internal=internal_view)
            # 相关度判定：必须命中「事项级特征词」才算知识库有对应条目，
            # 否则视为未收录 → 走官方底库/网络兜底，避免挪用其他事项材料
            strong_hits = [h for h in hits if h.get("_score", 0) >= 1.0]
            kb_ok = bool(hits) and hit_is_relevant(rel_q, hits) and bool(strong_hits)
            if not kb_ok:
                # 二次召回：默认 topK 偏小，像「身份证、户口本、护照…」这类
                # 多主题条目容易被挤出。扩大召回范围后再判一次，避免误判为未收录。
                # 但必须要求「宽召回的首位」本身相关且得分足够，否则会把
                # 弱相关条目（如「公司」→「公司股权协议」）也当成本事项目。
                wider = search(search_q, k=max(topk * 6, 24), include_internal=internal_view)
                w_strong = [h for h in wider if h.get("_score", 0) >= 1.0]
                if (w_strong and hit_is_relevant(rel_q, w_strong[:2])
                        and w_strong[0].get("_score", 0) >= 2.0):
                    hits = w_strong[:topk]
                    strong_hits = hits
                    kb_ok = True
            # 口语词形检测：问句含 _OFFICIAL_SYNONYM 的口语键（如「意向监护」），
            # 说明问句用词与知识库/官方条目的规范术语存在差异——即使 KB 命中，
            # 命中条目也可能只是「相关背景」而非同一事项，需要提醒模型辨别。
            spoken_forms = [(sp, _OFFICIAL_SYNONYM[sp]) for sp in _OFFICIAL_SYNONYM
                            if sp in q and len(sp) >= 3]
            mismatch_note = ""
            off_txt, off_ok = "", False
            web_txt, web_ok = "", False
            gaps = []
            rel_note = ""
            if not kb_ok:
                # 知识库无对应条目 → 先查司法部官方材料底库，再补网络检索；
                # 严禁挪用其他条目的材料
                hits = []
                off_txt, off_ok = official_lookup(q)
                web_txt, web_ok = web_search(f"{q} 公证 所需材料 办理", limit=4)
                # 相关知识点：库里没有完全匹配时，把官方清单相关事项、
                # 知识库相近条目、联网检索到的法律依据/办理要求展示给当事人
                # （已取得官方精确命中或已联网成功时不再重复检索）
                rel_note, rel_web, rel_web_ok = related_knowledge_note(
                    q, kb_hits=wider, official_hit=off_ok,
                    want_web=not web_ok)
                if rel_web_ok and not web_ok:
                    web_txt, web_ok = rel_web, True
            elif spoken_forms:
                # KB 有命中、但问句含口语词形（如「意向监护」≠规范术语「意定监护」）：
                # 官方清单按同义词替换匹配规范事项 + 相关知识点素材 + 匹配度提醒，
                # 防止模型把相近条目结论直接套到所问事项上
                off_txt, off_ok = official_lookup(q)
                rel_note, rel_web, rel_web_ok = related_knowledge_note(
                    q, kb_hits=strong_hits, official_hit=off_ok,
                    want_web=True)
                if rel_web_ok:
                    web_txt, web_ok = (web_txt + "\n\n" + rel_web) if web_ok else rel_web, True
                sp, formal = spoken_forms[0]
                first_name = (strong_hits[0]["title"].split("·")[-1].strip()
                              if strong_hits else "")
                mismatch_note = (
                    f"【匹配度提醒 · 必须先展示相关知识点】当事人提问中的「{sp}」是口语写法，"
                    f"对应官方规范术语「{formal}」——这**大概率就是当事人要办的事项**"
                    f"（司法部官方清单已收录「{formal}」，材料清单见下方官方清单块）。\n"
                    f"检索命中的条目「{first_name}」针对的是**其他监护事项**（监护权变更、"
                    f"过继、收养等法定监护问题），与「{formal}」**不是同一事项**，"
                    f"其「不可办理」结论**不适用于**当事人的问题。\n"
                    f"请严格按以下结构回答（不要等当事人补充信息才给内容）：\n"
                    f"1. 先讲「{formal}」是什么：法律允许当事人以书面协议预先确定监护人"
                    f"（如上下文联网检索有法律依据则引用并标注，没有则用通用表述、"
                    f"不虚构条款号）；\n"
                    f"2. 完整展示官方清单「{formal}」的材料清单（逐条列出，标注"
                    f"「来源：司法部官方证明材料清单」）；\n"
                    f"3. 说明相近条目「{first_name}」与「{formal}」的区别"
                    f"（条目针对监护权变更/过继/收养，声明无效不能公证；"
                    f"而{formal}是法律允许的协议安排），让当事人对号入座；\n"
                    f"4. 最后再请当事人补充户籍、用途等要素；\n"
                    f"5. **不得给出「{formal}」的具体价格**——知识库没有该规范事项的定价，"
                    f"相近条目的价格不适用；若确需提及价格区间，必须标注"
                    f"「为相近事项参考价，以公证处报价为准」。")
            else:
                hits = strong_hits
                # 若命中的只是「其他/一般」这类兜底桶，而司法部官方清单里
                # 有该事项的专门条目，则优先采用官方专门条目（更权威、更具体），
                # 同时保留桶条目作为背景参考。
                # 注意只检查条目名本身（「·」之后），避免「九、其他」这类类目名误触发。
                def _is_bucket(h):
                    nm = h["title"].split("·")[-1]
                    return "其他" in nm or "一般" in nm
                if any(_is_bucket(h) for h in hits[:1]):
                    o_txt, o_ok = official_lookup(q)
                    if o_ok:
                        off_txt, off_ok = o_txt, o_ok
                # 命中知识库之后，若条目本身存在内容缺口（如「材料」为空），
                # 或问题问到了条目未覆盖的主题（如「申根签」），针对缺口补充查询：
                # 先用司法部官方清单（权威，优先），官方清单未收录时再联网检索。
                gaps = kb_gaps(hits)
                field_gaps = [g for g in gaps if g[0] == "field"]
                topics = topic_gaps(q, hits)
                for t in topics:
                    gaps.append(("topic", t, hits[0] if hits else None))
                if field_gaps:
                    if not off_ok:
                        keys = []
                        for _k, _t, h in field_gaps:
                            t = (h.get("title") or "").split("·")[-1].strip()
                            t = re.sub(r"^\d+\s*[\.、]\s*", "", t).strip()
                            if t:
                                keys.append(t)
                        o_txt, o_ok = official_lookup(q, extra_keys=keys)
                        if o_ok:
                            off_txt, off_ok = o_txt, o_ok
                if gaps:
                    g_txt, g_ok = gap_web_search(q, gaps, topics, search_q)
                    if g_ok:
                        web_txt, web_ok = g_txt, g_ok

            # ---- 涉外国家判定：单号/双号 · 是否必须海牙 ----
            # 用户要求：涉外且提供了国家名称时，须回答该国做单号还是双号、
            # 是否必须海牙认证；知识库若无收录则联网搜索作答（知识库暂无该对照表）。
            q_all = " ".join(hist_user_texts[-2:] + [q, vision_ctx])
            countries = find_countries(q_all)
            overseas = is_overseas_q(q_all, countries)
            country_note = ""
            # 口语词形检测：问句含 _OFFICIAL_SYNONYM 的口语键（如「意向监护」），
            # 说明问句用词与知识库/官方条目的规范术语存在差异——即使 KB 命中，
            # 命中条目也可能只是「相关背景」而非同一事项，需要提醒模型辨别。
            if countries and overseas:
                # 事项主体（用于把检索式聚焦到具体公证类型）
                _subj = ""
                for h in (hits or []):
                    nm = (h.get("title") or "").split("·")[-1]
                    nm = re.sub(r"^\d+\s*[\.、]\s*", "", nm).strip()
                    if nm and "其他" not in nm and "一般" not in nm:
                        _subj = nm
                        break
                c_txt, c_ok = country_rule_search(countries[0], item=_subj)
                country_note = country_ruling_note(countries, item=_subj, user_q=q,
                                                   web_txt=c_txt, web_ok=c_ok)
                # 联网结果并入 web 块，保证「非知识库内容」标注链路一致
                if c_ok:
                    web_txt = (web_txt + "\n\n" + c_txt) if web_ok else c_txt
                    web_ok = True
                    if not gaps:
                        gaps.append(("topic", "涉外国家要求",
                                     hits[0] if hits else None))
            # 问「要几天/多久」→ 注入各省报价表中的办理周期（知识库内容）；
            # 识图场景一律注入，避免模型就周期自行编造常见值。
            # 涉外/未命中知识库场景也注入：周期是跨事项通用的知识库数据，
            # 模型没有它就容易编出「5-7 个工作日」这类不存在的值。
            _need_period = (_is_period_q(q) or vision_ctx or countries
                            or not kb_ok)
            pn = period_note() if _need_period else ""
            gap_labels = "、".join(sorted({t for _k, t, _h in gaps})) if gaps else ""

            # ---- 仅知识库检索模式 ----
            m = next((x for x in MODELS if x["id"] == model), None)
            if m and m["provider"] == "none":
                if not hits:
                    if country_note:
                        # 涉外国家判定优先展示（用户明确要求的回答项）
                        parts = ["【仅知识库检索 · 未启用模型分析】\n", country_note + "\n"]
                        if rel_note:
                            parts.append(rel_note + "\n")
                        if off_ok or web_ok:
                            parts.append("以下是权威/网络检索到的相关信息：\n")
                            if off_ok: parts.append(off_txt + "\n")
                            if web_ok and web_txt and web_txt not in country_note and web_txt not in rel_note:
                                parts.append(web_txt + "\n")
                        parts.append("如需完整分析，请右上角切换到模型分析；"
                                     "或从下方目录指出想办的事项。\n\n"
                                     "【知识库全部事项目录】\n" + kb_catalog())
                        ans = "\n".join(parts)
                    elif rel_note:
                        # 相关知识点：官方清单相关事项 + 知识库相近条目 + 联网法律依据
                        parts = ["【仅知识库检索 · 未启用模型分析】\n", rel_note + "\n"]
                        if off_ok: parts.append(off_txt + "\n")
                        if web_ok and web_txt and web_txt not in rel_note:
                            parts.append(web_txt + "\n")
                        parts.append("如需完整分析，请右上角切换到模型分析；"
                                     "或从下方目录指出想办的事项。\n\n"
                                     "【知识库全部事项目录】\n" + kb_catalog())
                        ans = "\n".join(parts)
                    elif off_ok or web_ok:
                        parts = ["【仅知识库检索 · 未启用模型分析】\n",
                                 "当前知识库未收录该事项，以下是权威/网络检索到的相关信息：\n"]
                        if off_ok: parts.append(off_txt + "\n")
                        if web_ok: parts.append(web_txt + "\n")
                        parts.append("如需完整分析，请右上角切换到模型分析；"
                                     "或从下方目录指出想办的事项。\n\n"
                                     "【知识库全部事项目录】\n" + kb_catalog())
                        ans = "\n".join(parts)
                    else:
                        ans = ("当前知识库未检索到与提问直接相关的条目，官方底库与网络检索也未取得有效结果。\n\n"
                               "【知识库全部事项目录】\n" + kb_catalog() +
                               "\n\n您可以从中指出想办的事项，或补充更多信息后再次提问。")
                    return self._send(200, {
                        "answer": ans, "four": four, "missing": missing,
                        "hits": [], "model": model, "mode": "kb",
                        "official": off_ok, "web": web_ok})
                lines = ["【仅知识库检索 · 未启用模型分析】", ""]
                if vision_ctx:
                    # 回显读图结果，让当事人核对识别准确性
                    lines.append("【我读到的图片内容】\n" + vision_ctx + "\n")
                for h in hits:
                    tag = "☑ 可办理" if h.get("ok", True) else "☐ 不能办理"
                    if h.get("id") == "fee":
                        # 收费总表内容过长，仅知识库模式下只给概览，不整表铺开
                        lines.append(f"■ {h['title']}［{tag}］\n"
                                     "（收费总表内容较多，此处仅列概览；"
                                     "切换到模型分析可获取与您问题相关的具体价格）\n"
                                     + "\n".join(l.split("；明细：")[0]
                                                 for l in h["content"].split("\n")) + "\n")
                        continue
                    lines.append(f"■ {h['title']}［{tag}］\n{h['content']}\n")
                if pn:
                    lines.append(pn + "\n")
                if country_note:
                    # 涉外国家判定（单号/双号 · 是否必须海牙）
                    lines.append(country_note + "\n")
                if mismatch_note:
                    # 口语词形提示：命中的条目可能是相关背景而非同一事项
                    sp0, formal0 = spoken_forms[0]
                    lines.append(
                        f"——\n⚠️ 提示：您问的「{sp0}」是口语写法，官方规范术语为「{formal0}」。"
                        f"上方条目为**相近事项**（不一定是同一事项），其结论不能直接套用。\n"
                        + (f"规范术语对应的官方清单材料如下：\n{off_txt}\n" if off_ok
                           else f"（官方清单按「{formal0}」未取得材料清单，可切换模型分析联网核实。）\n"))
                if missing:
                    lines.append("——\n提示：四要素尚缺「" + "、".join(missing) +
                                 "」，补齐后可给出更精准的判断（右上角切换到模型分析可获得完整解读）。")
                # 命中知识库但条目存在材料/主题缺口时，附上联网补充并明确标注
                if web_ok:
                    lines.append("\n——\n（以下为非现有知识库内容，仅做参考）\n"
                                 f"知识库条目中「{gap_labels}」暂无收录，"
                                 "以下为联网补充检索信息：\n" + web_txt)
                for _rl in redline_notes(q + " " + vision_ctx, "\n".join(lines)):
                    lines.append("\n——\n⚠️ " + _rl)
                return self._send(200, {"answer": "\n".join(lines), "four": four,
                                        "missing": missing,
                                        "hits": [{"title": h["title"], "ok": h.get("ok", True), "no": h["no"]} for h in hits],
                                        "model": model, "mode": "kb",
                                        "official": off_ok, "web": web_ok,
                                        "vision": vision_ctx, "countries": countries})

            # ---- 模型分析模式 ----
            have = [k for k, v in four.items() if v]
            blocks = []
            if off_ok:
                blocks.append(off_txt)
            if web_ok:
                blocks.append(web_txt)
            if not kb_ok and not blocks:
                blocks.append("（知识库无对应条目，官方底库与网络检索也未取得有效结果。"
                              "⚠️ 严禁称「根据网络检索」「据检索结果」——本次并未取得任何检索结果；"
                              "只能说明该事项暂未收录，可用一般常识谨慎说明，"
                              "但不得给出具体价格与办理周期的承诺值。）")
            web_block = ("\n\n" + "\n\n".join(blocks)) if blocks else ""
            # 相关知识点块：知识库无完全匹配时，把官方清单相关事项、相近条目、
            # 联网法律依据注入上下文，供模型组织「相关知识点」展示
            rel_block = ("\n\n" + rel_note) if rel_note else ""
            # 匹配度提醒块：口语词形与规范术语有差异时，防止模型套用相近条目结论
            mismatch_block = ("\n\n" + mismatch_note) if mismatch_note else ""
            # 问「要几天/多久」时把各省报价表的周期数据注入上下文（知识库内容）
            pn_block = ("\n\n" + pn) if pn else ""
            # 涉外国家判定：注入结论段 + 强制要求模型必须回答这两项
            country_block = ("\n\n" + country_note) if country_note else ""
            country_req = ""
            if country_note:
                country_req = ("\n\n【涉外国家判定 · 必须回答】当事人提问涉及境外使用地"
                               f"（{'、'.join(countries)}）。回答中必须明确给出两点：\n"
                               "1. 该国通常做【单号】还是【双号】公证，并解释两者区别"
                               "（单号＝仅公证中文原件；双号＝中文原件＋译文均公证）；\n"
                               "2. 该国【是否必须办海牙认证（Apostille）】，"
                               "还是需要领事认证（双认证）。\n"
                               "以上两点若知识库未收录，须按下方「涉外国家判定」与"
                               "网络检索结果作答，并明确标注为非知识库内容、"
                               "以使用地机构及公证处最终口径为准；"
                               "不得因知识库无此项而略过不答。")
            # 命中知识库、但条目存在内容缺口（字段空缺或问题提到的主题未覆盖）时，
            # 明确要求模型把「知识库没有、仅来自网络」的内容单独标注出来。
            gap_note = ""
            if kb_ok and gaps:
                gap_note = (f"\n\n【重要 · 补充内容标注】知识库条目中「{gap_labels}」暂无收录。"
                            + ("下方「网络检索结果」为补充查询所得，属**非现有知识库内容，仅做参考**。\n"
                               "回答时对这部分内容单独用一段，该段必须以「（以下为非现有知识库内容，仅做参考）」开头，"
                               "概述网络检索到的相关信息；不得把这部分内容写成知识库结论。"
                               if web_ok else
                               "联网补充也未检索到有效结果。可另起一段以「（以下为非现有知识库内容，仅做参考）」开头，"
                               "用一般行业常识简要做答，不得给出具体数字承诺。\n")
                            + "【严禁挪用】不得用检索结果中其他事项的内容填补缺口，如实说明未收录。")
            if missing:
                ask = "、".join(missing)
                user = (f"当事人提问：{q}\n\n"
                        f"知识库检索到的相关条目：\n{build_context(hits)}{pn_block}{country_block}{rel_block}{mismatch_block}{web_block}\n\n"
                        f"【知识库全部事项目录】\n{kb_catalog()}\n\n"
                        f"【四要素核对结果】\n"
                        f"- 当事人已明确：{'、'.join(have) if have else '（无）'}\n"
                        f"- 仍缺失：{ask}\n\n"
                        f"请「边答边问」，严格按以下顺序回答：\n"
                        f"1. 先基于已明确的要素，对照检索条目与事项目录，把当前能确定的分析直接给出来"
                        f"（可能适用的事项、价格、材料、限制条件、办理周期、已可下的初步结论）；\n"
                        f"2. 若缺失的要素会导向不同结论，用「若…则…」简要分情况说明；\n"
                        f"3. 最后用一两句话请当事人补充仍缺失的要素（{ask}），不要展开长篇追问。\n"
                        f"注意：材料清单只能取自当事人所问事项对应的条目，严禁挪用其他事项的材料；"
                        f"该事项无材料信息时，明说「知识库暂未收录」，可引用网络结果并标注来源。"
                        f"{country_req}"
                        f"{gap_note}")
            else:
                user = (f"当事人提问：{q}\n\n"
                        f"知识库检索到的相关条目：\n{build_context(hits)}{pn_block}{country_block}{rel_block}{mismatch_block}{web_block}\n\n"
                        f"【四要素核对结果】\n办什么公证、户籍在哪儿、在哪儿使用、用途是什么 —— 四项均已明确。\n\n"
                        f"请直接按「结论 → 依据 → 办理要素 → 材料清单 → 价格与时长 → 下一步」"
                        f"的结构给出完整分析，不要再追问任何要素。若涉及涉外，说明是否需要海牙认证。"
                        f"{country_req}"
                        f"{gap_note}")

            if internal_view:
                user += "\n\n（当前为管理员视图，可参考完整结论与内部报价。）"
            # 识图结果作为事实材料注入：要求模型先回显识别内容，再据此判定
            if vision_ctx:
                user += (f"\n\n【当事人上传图片的识别结果 · 作为事实依据】\n{vision_ctx}\n\n"
                         "以上为系统读图所得，请按此作答：\n"
                         "1. 先用一小段回显「我读到的内容」（事项、省份、用途等关键信息），"
                         "让当事人核对识别是否准确；\n"
                         "2. 再据此给出「能不能办」的明确结论，并附依据、材料、价格、周期；\n"
                         "3. 识别结果中标注「未提及」的要素（如户籍、用途），按四要素规则继续追问；\n"
                         "4. 若识别结果显示图片与公证业务无关或无法辨认，直接说明并请当事人改用文字描述，"
                         "不得硬凑一个公证事项；\n"
                         "5. 识别出的需求若与知识库条目的限制冲突（如需求含「代收房款」"
                         "而条目「要求」写明「卖房款项不能代收」），必须明确指出该冲突："
                         "冲突部分不能办，其余可办部分正常分析，不得回避。")
            if kb_ok and gaps and web_ok:
                # 尾部强提醒：轻量模型对长提示词中部的指令容易忽略，
                # 在消息末尾再强调一次标注要求
                user += (f"\n\n【再次提醒】知识库未收录：{gap_labels}。"
                         "回答中必须有一段以「（以下为非现有知识库内容，仅做参考）」"
                         "开头的内容，概述网络检索到的相关信息。")

            # 组装消息：system + 历史轮次 + 当前提问（模型可看到之前说过的要素）
            msgs = [{"role": "system", "content": SYSTEM}]
            for h in hist:
                role = "user" if h.get("role") == "user" else "assistant"
                txt = h["text"].strip()
                if role == "assistant" and len(txt) > 600:
                    txt = txt[:600] + "…（已截断）"
                if txt:
                    msgs.append({"role": role, "content": txt})
            msgs.append({"role": "user", "content": user})

            ans, err = call_llm(model, msgs, cfg)
            if err:
                # 模型不可用时降级为知识库检索 / 网络检索，保证服务可用
                lines = [f"⚠️ {err}", "", "已自动降级为检索结果：", ""]
                if hits:
                    for h in hits:
                        tag = "☑ 可办理" if h.get("ok", True) else "☐ 不能办理"
                        lines.append(f"■ {h['title']}［{tag}］\n{h['content']}\n")
                    if pn:
                        lines.append(pn + "\n")
                elif off_ok:
                    lines.append(off_txt + "\n")
                    if web_ok: lines.append(web_txt + "\n")
                elif web_ok:
                    lines.append(web_txt + "\n")
                else:
                    lines.append("知识库、官方底库与网络检索均未取得有效结果，建议补充文档或联系负责人确认。\n")
                if country_note:
                    lines.append("\n" + country_note + "\n")
                if kb_ok and gaps and web_ok:
                    # 降级路径同样保证「非知识库内容」标注存在
                    lines.append("\n——\n（以下为非现有知识库内容，仅做参考）\n"
                                 f"知识库条目中「{gap_labels}」暂无收录，"
                                 "以下为联网补充检索信息：\n" + web_txt)
                if missing:
                    lines.append("——\n提示：四要素尚缺「" + "、".join(missing) + "」。")
                for _rl in redline_notes(q + " " + vision_ctx, "\n".join(lines)):
                    lines.append("\n——\n⚠️ " + _rl)
                return self._send(200, {"answer": "\n".join(lines), "four": four,
                                        "missing": missing, "degraded": True,
                                        "official": off_ok, "web": web_ok,
                                        "hits": [{"title": h["title"], "ok": h.get("ok", True), "no": h["no"]} for h in hits],
                                        "model": model, "mode": "fallback",
                                        "vision": vision_ctx})

            # 兜底标注：模型（尤其轻量模型）未按提示词要求单独标注缺口内容时，
            # 由系统在答案末尾自动补上，确保「非现有知识库内容，仅做参考」一定出现
            if kb_ok and gaps and web_ok and "非现有知识库内容" not in ans:
                ans += (f"\n\n——\n（以下为非现有知识库内容，仅做参考）\n"
                        f"知识库条目中「{gap_labels}」暂无收录，"
                        f"以上回答中涉及该部分的内容与以下信息均来自联网检索，仅供参考：\n{web_txt}")

            # 涉外判定的确定性兜底：用户明确要求「涉外 + 给了国家」时必须回答
            # 「单号/双号」与「是否必须海牙」。模型若漏答（未同时出现单号/双号
            # 与海牙相关表述），由系统强制补上判定段，不依赖模型自觉。
            if country_note and not ("海牙" in ans or "Apostille" in ans
                                     or "领事认证" in ans or "双认证" in ans):
                ans += "\n\n——\n" + country_note

            # 虚假来源兜底：本次并未取得任何检索结果（无官方清单、无网络结果）时，
            # 模型若仍写了「根据网络检索/检索结果显示」等，属虚构来源，系统补正说明。
            if not web_ok and not off_ok and not kb_ok:
                if any(k in ans for k in ("网络检索", "检索结果", "联网搜索",
                                          "官方清单", "司法部清单")):
                    ans += ("\n\n——\n（说明：本次未从知识库、官方清单或网络检索中"
                            "取得该事项的有效资料，上文中所述内容为一般性说明，"
                            "具体以公证处口径为准。）")

            # 口语词形场景的价格兜底：规范事项在知识库无定价，模型给出的价格
            # 可能来自相近条目——强制补充来源说明，避免误认为是准确报价
            if mismatch_note and re.search(r"\d+(?:\.\d+)?\s*元", ans):
                _f0 = spoken_forms[0][1]
                ans += (f"\n\n——\n（价格说明：知识库暂无「{_f0}」的专门定价，上文中出现的价格"
                        f"为相近事项的价格档，仅供参考；实际费用以办理公证处对「{_f0}」"
                        f"的报价为准。）")

            # 红线校验：模型回答若漏掉了知识库明确禁止项，系统强制补充
            rl = redline_notes(q + " " + vision_ctx, ans)
            if rl:
                ans += "\n\n——\n⚠️ " + " ".join(rl)

            return self._send(200, {"answer": ans, "four": four, "missing": missing,
                                    "official": off_ok, "web": web_ok,
                                    "hits": [{"title": h["title"], "ok": h.get("ok", True), "no": h["no"]} for h in hits],
                                    "model": model, "mode": "llm",
                                    "vision": vision_ctx, "countries": countries})

        if p == "/api/admin/login":
            ok = (b.get("pass") or "") == cfg.get("adminPass")
            return self._send(200 if ok else 401, {"ok": ok})

        if p == "/api/config":
            if "keys" in b:
                for prov, v in b["keys"].items():
                    if v and "****" not in v:
                        cfg["keys"][prov] = v.strip()
            if b.get("adminPass", "").strip():
                cfg["adminPass"] = b["adminPass"].strip()
            for k in ("defaultModel", "topK", "temperature"):
                if k in b:
                    cfg[k] = b[k]
            save_cfg(cfg)
            return self._send(200, {"ok": True})

        return self._send(404, {"error": "not found"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print(f"证小安知识库服务启动：http://0.0.0.0:{port}")
    print(f"知识库 {len(DOCS)} 条索引 | 模型 {len(MODELS)} 个可选")
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
