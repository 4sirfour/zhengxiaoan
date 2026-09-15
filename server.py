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


def search(query, k=4, include_internal=True):
    qt = tokenize(query)
    if not qt:
        return []
    scored = []
    for d in DOCS:
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
        scored.append((score, d))
    scored.sort(key=lambda x: -x[0])
    out = []
    for s, d in scored[:k]:
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
    n = (name or "").strip().split("·")[-1].strip()
    n = re.sub(r"^\d+[\.、]\s*", "", n)               # 去「17. 」「17、」
    n = re.sub(r"^[（(][^）)]*[）)]", "", n)          # 去「（美国护照申请）」等前缀括号
    n = re.sub(r"[（(][^）)]*[）)]", "", n)            # 去正文中的补充括号
    n = re.sub(r"^(涉外的?|国内的?)", "", n)          # 去高频通用前缀
    for s in SUFFIX_WORDS:
        n = n.replace(s, "")
    return n.strip(" 、，,-—")


def hit_is_relevant(query, items):
    """判断检索结果是否真正相关：必须命中「事项核心词」或该事项的「别名」。

    仅命中「公证/办理/材料」等通用词，或只命中「声明/协议」这类类型后缀，
    都不算命中，否则会把不相关事项的材料带出来。
    例外：若首位结果得分远超其余（强区分），且核心词与问题有 ≥3 字公共片段，
    也视为命中（应对「公众号主体迁移」vs「微信公众号主体迁移」这类近义表述）。
    """
    q = (query or "").strip()
    if not q:
        return False
    # 规则0：问题里出现某事项的别名（如「委托买房」→ 1 房屋车辆买卖委托），
    #        视为直接命中，这是最贴近用户口语的信号
    for alias, no in K.ALIAS_INDEX.items():
        if len(alias) >= 3 and alias in q:
            if any(d.get("no") == no for d in items):
                return True
    q_tokens = {t for t in tokenize(q) if len(t) >= 2 and t not in GENERIC_WORDS}
    for idx, d in enumerate(items):
        name = d.get("title", "")
        core = _core_subject(name)
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
    "在哪儿使用": ["在哪用", "哪里用", "使用地", "拿去", "用于哪个", "哪个国家", "出到", "用在"],
    "用途是什么": ["用途", "干什么用", "做什么用", "为了", "用来", "目的",
                   "卖给", "卖给谁", "赠与给", "过户给", "给亲戚", "给朋友", "给子女",
                   "给孩子", "给父母", "转给", "资助", "担保", "继承给", "留给孩子"],
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


# ==================== 提示词 ====================
SYSTEM = """你是「证小安」公证业务知识库助手。你的职责不是检索资料，而是做四要素分析型问答。

【铁律】回答任何公证问题，必须围绕四个要素展开：
① 办什么公证  ② 户籍在哪儿  ③ 在哪儿使用  ④ 用途是什么

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

【依据来源优先级】
1. 优先用「知识库检索到的相关条目」作答，标注条目编号。
2. 知识库未收录该事项时，用「司法部官方证明材料清单」作答，标注来源为司法部官方清单；这是权威口径。
3. 官方清单也没有时，用「网络检索结果」作答，并明确标注来自网络检索、仅供参考、须以使用地公证处口径为准。
4. 以上都没有时，才说明「当前知识库未提供」，并建议补充文档或联系负责人确认。

【严禁跨条目挪用材料】
- 材料清单只能取自：①当事人所问事项对应的知识库条目；②司法部官方清单中同一事项；③网络检索结果中同一事项。
- 严禁把 A 事项的材料（如户口本公证、亲属关系公证、房屋委托公证的材料）安到 B 事项上。
- 若所列来源均无该事项材料，必须明确说「该项材料暂未收录」，不得凭常识编造，也不得用其他事项材料凑数。

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


# ==================== 网络检索兜底 ====================
WEB_CACHE = {}
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def _bing_parse(html, limit=5):
    """解析必应搜索结果（标题 + 摘要）"""
    items = re.findall(r'<li class="b_algo".*?</li>', html, re.S)
    out = []
    for it in items[:limit]:
        mt = re.search(r'<h2[^>]*>(.*?)</h2>', it, re.S)
        mc = re.search(r'<p[^>]*>(.*?)</p>', it, re.S)
        t = re.sub(r"<[^>]+>", "", mt.group(1)).strip() if mt else ""
        c = re.sub(r"<[^>]+>", "", mc.group(1)).strip() if mc else ""
        c = c.replace("&quot;", '"').replace("&amp;", "&").replace("&ensp;", " ")
        if t and len(t) > 4:
            out.append({"title": t, "snippet": c})
    return out


def official_lookup(query):
    """知识库未收录时，查司法部官方《公证事项证明材料清单》底库。
    返回 (文本, 是否命中)。这是权威来源，优先于网络检索。"""
    q = (query or "").strip()
    if not q:
        return "", False
    # 先在官方底库中按关键词匹配（取最长命中）
    hit = None
    for key in sorted(O.OFFICIAL.keys(), key=len, reverse=True):
        if key in q:
            hit = O.OFFICIAL[key]
            break
    if not hit:
        hit = O.lookup(q)
    if not hit:
        return "", False
    mats = "\n".join(f"  {i}. {m}" for i, m in enumerate(hit["materials"], 1))
    return (f"【司法部官方证明材料清单 · {hit['name']}】\n{mats}"), True


def web_search(query, limit=5, timeout=9):
    """网络检索补充（必应中文）。返回 (文本, 是否成功)"""
    q = (query or "").strip()
    if not q:
        return "", False
    if q in WEB_CACHE:
        return WEB_CACHE[q], bool(WEB_CACHE[q])
    try:
        import urllib.parse
        url = ("https://cn.bing.com/search?q=" + urllib.parse.quote(q)
               + "&setlang=zh-CN&ensearch=0")
        req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                   "Accept-Language": "zh-CN,zh;q=0.9"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            html = r.read().decode("utf-8", "ignore")
        res = _bing_parse(html, limit)
        # 质量过滤：剔除词典/翻译类噪声结果
        noise = ("词典", "翻译", "读音", "的意思", "百科", "是什么意思", "音标", "例句")
        res = [x for x in res if not any(n in x["title"] for n in noise)]
        if not res:
            WEB_CACHE[q] = ""
            return "", False
        lines = []
        for i, it in enumerate(res, 1):
            lines.append(f"{i}. {it['title']}")
            if it["snippet"]:
                lines.append(f"   摘要：{it['snippet'][:180]}")
        txt = ("【网络检索结果 · 仅供参考，最终以使用地公证处口径为准】\n"
               + "\n".join(lines))
        WEB_CACHE[q] = txt
        return txt, True
    except Exception as e:
        WEB_CACHE[q] = ""
        return f"（网络检索未成功：{e}）", False


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

    def do_GET(self):
        p = urlparse(self.path).path
        cfg = load_cfg()
        if p in ("/", "/index.html"):
            f = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
            if os.path.exists(f):
                return self._send(200, open(f, encoding="utf-8").read(), "text/html; charset=utf-8")
            return self._send(404, "index.html not found", "text/plain; charset=utf-8")

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

        if p == "/api/ask":
            q = (b.get("q") or "").strip()
            model = b.get("model") or cfg["defaultModel"]
            internal_view = bool(b.get("internalView"))
            # 对话历史：[{role:"user"|"assistant", text:"..."}]
            hist = [h for h in (b.get("history") or [])
                    if isinstance(h, dict) and isinstance(h.get("text"), str) and h["text"].strip()]
            hist = hist[-8:]  # 最多保留最近 4 轮
            if not q:
                return self._send(400, {"error": "请输入问题"})

            # ---- 四要素：当前问题 + 历史用户消息 合并判断 ----
            # 某一要素只要在任何一轮中明确过，后续就不再追问
            four = extract_four(q)
            hist_user_texts = [h["text"].strip() for h in hist if h.get("role") == "user"]
            for t in hist_user_texts:
                hf = extract_four(t)
                for k, v in hf.items():
                    four[k] = four[k] or v
            missing = [k for k, v in four.items() if not v]

            # ---- 检索：当前问题 + 最近两轮用户输入，提升上下文命中率 ----
            search_q = " ".join(hist_user_texts[-2:] + [q])
            topk = int(b.get("k") or cfg.get("topK", 4))
            hits = search(search_q, k=topk, include_internal=internal_view)
            # 相关度判定：必须命中「事项级特征词」才算知识库有对应条目，
            # 否则视为未收录 → 走官方底库/网络兜底，避免挪用其他事项材料
            strong_hits = [h for h in hits if h.get("_score", 0) >= 1.0]
            kb_ok = bool(hits) and hit_is_relevant(q, hits) and bool(strong_hits)
            if not kb_ok:
                # 二次召回：默认 topK 偏小，像「身份证、户口本、护照…」这类
                # 多主题条目容易被挤出。扩大召回范围后再判一次，避免误判为未收录。
                # 但必须要求「宽召回的首位」本身相关且得分足够，否则会把
                # 弱相关条目（如「公司」→「公司股权协议」）也当成本事项目。
                wider = search(search_q, k=max(topk * 6, 24), include_internal=internal_view)
                w_strong = [h for h in wider if h.get("_score", 0) >= 1.0]
                if (w_strong and hit_is_relevant(q, w_strong[:2])
                        and w_strong[0].get("_score", 0) >= 2.0):
                    hits = w_strong[:topk]
                    strong_hits = hits
                    kb_ok = True
            off_txt, off_ok = "", False
            web_txt, web_ok = "", False
            if not kb_ok:
                # 知识库无对应条目 → 先查司法部官方材料底库，再补网络检索；
                # 严禁挪用其他条目的材料
                hits = []
                off_txt, off_ok = official_lookup(q)
                web_txt, web_ok = web_search(f"{q} 公证 所需材料 办理", limit=4)
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

            # ---- 仅知识库检索模式 ----
            m = next((x for x in MODELS if x["id"] == model), None)
            if m and m["provider"] == "none":
                if not hits:
                    if off_ok or web_ok:
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
                if missing:
                    lines.append("——\n提示：四要素尚缺「" + "、".join(missing) +
                                 "」，补齐后可给出更精准的判断（右上角切换到模型分析可获得完整解读）。")
                return self._send(200, {"answer": "\n".join(lines), "four": four,
                                        "missing": missing,
                                        "hits": [{"title": h["title"], "ok": h.get("ok", True), "no": h["no"]} for h in hits],
                                        "model": model, "mode": "kb"})

            # ---- 模型分析模式 ----
            have = [k for k, v in four.items() if v]
            blocks = []
            if off_ok:
                blocks.append(off_txt)
            if web_ok:
                blocks.append(web_txt)
            if not kb_ok and not blocks:
                blocks.append("（知识库无对应条目，官方底库与网络检索也未取得有效结果）")
            web_block = ("\n\n" + "\n\n".join(blocks)) if blocks else ""
            if missing:
                ask = "、".join(missing)
                user = (f"当事人提问：{q}\n\n"
                        f"知识库检索到的相关条目：\n{build_context(hits)}{web_block}\n\n"
                        f"【知识库全部事项目录】\n{kb_catalog()}\n\n"
                        f"【四要素核对结果】\n"
                        f"- 当事人已明确：{'、'.join(have) if have else '（无）'}\n"
                        f"- 仍缺失：{ask}\n\n"
                        f"请「边答边问」，严格按以下顺序回答：\n"
                        f"1. 先基于已明确的要素，对照检索条目与事项目录，把当前能确定的分析直接给出来"
                        f"（可能适用的事项、价格、材料、限制条件、已可下的初步结论）；\n"
                        f"2. 若缺失的要素会导向不同结论，用「若…则…」简要分情况说明；\n"
                        f"3. 最后用一两句话请当事人补充仍缺失的要素（{ask}），不要展开长篇追问。\n"
                        f"注意：材料清单只能取自当事人所问事项对应的条目，严禁挪用其他事项的材料；"
                        f"该事项无材料信息时，明说「知识库暂未收录」，可引用网络结果并标注来源。")
            else:
                user = (f"当事人提问：{q}\n\n"
                        f"知识库检索到的相关条目：\n{build_context(hits)}{web_block}\n\n"
                        f"【四要素核对结果】\n办什么公证、户籍在哪儿、在哪儿使用、用途是什么 —— 四项均已明确。\n\n"
                        f"请直接按「结论 → 依据 → 办理要素 → 材料清单 → 价格与时长 → 下一步」"
                        f"的结构给出完整分析，不要再追问任何要素。若涉及涉外，说明是否需要海牙认证。")

            if internal_view:
                user += "\n\n（当前为管理员视图，可参考完整结论与内部报价。）"

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
                elif off_ok:
                    lines.append(off_txt + "\n")
                    if web_ok: lines.append(web_txt + "\n")
                elif web_ok:
                    lines.append(web_txt + "\n")
                else:
                    lines.append("知识库、官方底库与网络检索均未取得有效结果，建议补充文档或联系负责人确认。\n")
                if missing:
                    lines.append("——\n提示：四要素尚缺「" + "、".join(missing) + "」。")
                return self._send(200, {"answer": "\n".join(lines), "four": four,
                                        "missing": missing, "degraded": True,
                                        "official": (not hits and off_ok), "web": (not hits and web_ok),
                                        "hits": [{"title": h["title"], "ok": h.get("ok", True), "no": h["no"]} for h in hits],
                                        "model": model, "mode": "fallback"})

            return self._send(200, {"answer": ans, "four": four, "missing": missing,
                                    "official": (not hits and off_ok), "web": (not hits and web_ok),
                                    "hits": [{"title": h["title"], "ok": h.get("ok", True), "no": h["no"]} for h in hits],
                                    "model": model, "mode": "llm"})

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
