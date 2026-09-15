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
        if not include_internal and d["mark"] == "int":
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
        scored.append((score, d))
    scored.sort(key=lambda x: -x[0])
    return [d for _, d in scored[:k]]


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

【禁止】
- 禁止只抛出追问、不给任何实质性分析内容
- 禁止仅摘抄知识库原文片段作为回答
- 禁止编造价格、材料清单、受理结论
- 禁止把「对内/仅管理员」的事项当作可对外办理事项答复给当事人
- 禁止追问当事人已经明确说过的要素
- 知识库无依据时，必须明说「当前知识库未提供」，并建议补充文档或找负责人确认

【语气】专业、直接、给结论，不绕弯。"""


def build_context(hits):
    if not hits:
        return "（知识库未检索到相关条目）"
    parts = []
    for h in hits:
        tag = "【可对外】" if h["mark"] == "ext" else "【对内/仅管理员】"
        parts.append(f"--- {tag} {h['title']} ---\n{h['content']}")
    return "\n\n".join(parts)


def kb_catalog(include_internal=False):
    """知识库全部事项目录（按类目分组，含编号与价格），供模型在要素不全时给出可能方向"""
    seen = {}
    order = []
    for it in K.all_items():
        if it["mark"] == "int" and not include_internal:
            continue
        if it["cat"] not in seen:
            seen[it["cat"]] = []
            order.append(it["cat"])
        price = (it.get("price") or "—").split("（")[0]
        seen[it["cat"]].append(f"{it['no']}.{it['name']}（{price}）")
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
            # 权限控制：默认（当人口径）返回可对外条目 + 收费标准总表；
            # 对内事项、各省报价、受限清单仅管理员可见（需密码校验）
            qs = parse_qs(urlparse(self.path).query)
            internal = qs.get("internal", ["0"])[0] in ("1", "true")
            if internal:
                passed = qs.get("pass", [""])[0] == cfg.get("adminPass")
                if not passed:
                    return self._send(401, {"error": "管理员密码错误"})
                return self._send(200, {"kb": K.KB, "platform": K.PLATFORM,
                                        "quotes": K.QUOTES, "quoteHeaders": K.QUOTE_HEADERS,
                                        "quoteNotes": K.QUOTE_NOTES,
                                        "feeTable": K.FEE_TABLE, "blocked": K.BLOCKED,
                                        "admin": True,
                                        "stats": {"total": len(K.all_items()),
                                                  "ext": len(K.ext_items()),
                                                  "int": len(K.int_items())}})
            kb_pub = [{"cat": g["cat"],
                       "items": [dict(it) for it in g["items"] if it["mark"] == "ext"]}
                      for g in K.KB]
            return self._send(200, {"kb": kb_pub, "platform": K.PLATFORM,
                                    "quotes": [], "quoteHeaders": [], "quoteNotes": [],
                                    "feeTable": K.FEE_TABLE, "blocked": [],
                                    "admin": False,
                                    "stats": {"total": len(K.ext_items()),
                                              "ext": len(K.ext_items()), "int": 0}})

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
            return self._send(200, {"hits": [{"title": h["title"], "mark": h["mark"], "no": h["no"]} for h in hits]})

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
            hits = search(search_q, k=int(b.get("k") or cfg.get("topK", 4)),
                          include_internal=internal_view)

            # ---- 仅知识库检索模式 ----
            m = next((x for x in MODELS if x["id"] == model), None)
            if m and m["provider"] == "none":
                if not hits:
                    ans = ("当前知识库未检索到与提问直接相关的条目。\n\n"
                           "【可对外办理的全部事项目录】\n" + kb_catalog() +
                           "\n\n您可以从中指出想办的事项，或补充更多信息后再次提问。")
                    return self._send(200, {
                        "answer": ans, "four": four, "missing": missing,
                        "hits": [], "model": model, "mode": "kb"})
                lines = ["【仅知识库检索 · 未启用模型分析】", ""]
                for h in hits:
                    tag = "可对外" if h["mark"] == "ext" else "对内/仅管理员"
                    lines.append(f"■ {h['title']}［{tag}］\n{h['content']}\n")
                if missing:
                    lines.append("——\n提示：四要素尚缺「" + "、".join(missing) +
                                 "」，补齐后可给出更精准的判断（右上角切换到模型分析可获得完整解读）。")
                return self._send(200, {"answer": "\n".join(lines), "four": four,
                                        "missing": missing,
                                        "hits": [{"title": h["title"], "mark": h["mark"], "no": h["no"]} for h in hits],
                                        "model": model, "mode": "kb"})

            # ---- 模型分析模式 ----
            have = [k for k, v in four.items() if v]
            if missing:
                ask = "、".join(missing)
                user = (f"当事人提问：{q}\n\n"
                        f"知识库检索到的相关条目：\n{build_context(hits)}\n\n"
                        f"【知识库全部可对外事项目录】\n{kb_catalog()}\n\n"
                        f"【四要素核对结果】\n"
                        f"- 当事人已明确：{'、'.join(have) if have else '（无）'}\n"
                        f"- 仍缺失：{ask}\n\n"
                        f"请「边答边问」，严格按以下顺序回答：\n"
                        f"1. 先基于已明确的要素，对照检索条目与事项目录，把当前能确定的分析直接给出来"
                        f"（可能适用的事项、价格、材料、限制条件、已可下的初步结论）；\n"
                        f"2. 若缺失的要素会导向不同结论，用「若…则…」简要分情况说明；\n"
                        f"3. 最后用一两句话请当事人补充仍缺失的要素（{ask}），不要展开长篇追问。")
            else:
                user = (f"当事人提问：{q}\n\n"
                        f"知识库检索到的相关条目：\n{build_context(hits)}\n\n"
                        f"【四要素核对结果】\n办什么公证、户籍在哪儿、在哪儿使用、用途是什么 —— 四项均已明确。\n\n"
                        f"请直接按「结论 → 依据 → 办理要素 → 材料清单 → 价格与时长 → 下一步」"
                        f"的结构给出完整分析，不要再追问任何要素。若涉及涉外，说明是否需要海牙认证。")

            if internal_view:
                user += "\n\n（当前为管理员内部视图，可参考「对内/仅管理员」条目的结论，但答复当事人时须遵守对外口径。）"

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
                # 模型不可用时降级为知识库检索，保证服务可用
                lines = [f"⚠️ {err}", "", "已自动降级为知识库检索结果：", ""]
                for h in hits:
                    tag = "可对外" if h["mark"] == "ext" else "对内/仅管理员"
                    lines.append(f"■ {h['title']}［{tag}］\n{h['content']}\n")
                if missing:
                    lines.append("——\n提示：四要素尚缺「" + "、".join(missing) + "」。")
                return self._send(200, {"answer": "\n".join(lines), "four": four,
                                        "missing": missing, "degraded": True,
                                        "hits": [{"title": h["title"], "mark": h["mark"], "no": h["no"]} for h in hits],
                                        "model": model, "mode": "fallback"})

            return self._send(200, {"answer": ans, "four": four, "missing": missing,
                                    "hits": [{"title": h["title"], "mark": h["mark"], "no": h["no"]} for h in hits],
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
