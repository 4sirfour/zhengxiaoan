# -*- coding: utf-8 -*-
"""生成「证小安 · 微信版」单文件 HTML。

背景：完整版托管在 app.workbuddy.host，其网关 WAF 拦截微信 UA（403），
微信内置浏览器打不开；而 workbuddy.link（artifact 域）微信可正常打开。
本脚本把知识库数据 + 检索/四要素逻辑全部内嵌进单个 HTML（不发起任何
跨域请求），发布到 workbuddy.link 后即可在微信内使用。

功能范围（微信精简版）：
- 知识库检索：别名/事项名/字段匹配，给出 ☑/☐、要求、材料
- 四要素引导 + 办理周期（25 省报价表口径）
- 司法部官方清单兜底（72 项）
- 「代收房款」等红线口径强制提示
- 完整版能力（模型分析/联网核实/图片识别）引导到浏览器打开完整版
"""
import json
import kb_data as K
import kb_official as O
import hague_data as HG

# 完整版后端地址（需服务器在线时可用）；weixin.html 为纯静态，
# GitHub Pages 永久托管地址：https://4sirfour.github.io/zhengxiaoan/
API = "https://4sirfour.github.io/zhengxiaoan/"

DATA = {
    "kb": [{"no": it["no"], "ok": it["ok"], "name": it["name"], "cat": it["cat"],
            "fields": [[k, v] for k, v in it["fields"]], "alias": K.alias_of(it["no"])}
           for it in K.all_items()],
    "feeTable": K.FEE_TABLE,
    "limited": K.LIMITED,
    "blocked": K.BLOCKED,
    "platform": K.PLATFORM,
    "official": O.OFFICIAL,
    "quotesLite": [{"prov": q["prov"], "way": q["way"], "tr": q["tr"],
                    "period": q["period"], "periodAuth": q["periodAuth"]} for q in K.QUOTES],
    # 涉外国家判定：外交部《公约》缔约国名单（127 国）+ 别名归一表
    "hague": HG.HAGUE_MEMBERS_CN,
    "hagueAlias": HG.HAGUE_ALIAS,
    # 口语 → 官方规范术语（用于官方清单匹配与相近条目提醒）
    "spoken": {"意向监护": "意定监护", "意向监护公证": "意定监护",
               "意定监护公证": "意定监护", "监护公证": "法定监护",
               "监护权公证": "法定监护", "转让股权": "股权转让协议",
               "股权转让": "股权转让协议", "遗嘱公证": "处理事务的遗嘱",
               "遗嘱": "处理事务的遗嘱", "公司股权协议": "股权转让协议"},
}
DATA_JS = json.dumps(DATA, ensure_ascii=False, separators=(",", ":"))

HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>证小安 · 公证问答（微信版）</title>
<style>
:root{--brand:#3b6ef0;--line:#e4e9f2;--panel:#fff;--bg:#f2f5fa;--muted:#7b8798;--ink:#22314d}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;background:var(--bg);color:var(--ink);
  font:14px/1.7 -apple-system,"PingFang SC","Helvetica Neue","Microsoft YaHei",sans-serif}
#top{background:var(--brand);color:#fff;padding:12px 16px;font-size:15.5px;font-weight:600;
  display:flex;align-items:center;gap:8px;position:sticky;top:0;z-index:9}
#top .lg{width:26px;height:26px;border-radius:7px;background:rgba(255,255,255,.2);display:flex;
  align-items:center;justify-content:center;font-size:13px}
#top small{font-weight:400;opacity:.85;font-size:11.5px;margin-left:2px}
#msgs{max-width:640px;margin:0 auto;padding:14px 12px 130px}
.msg{display:flex;margin:10px 0;align-items:flex-start;gap:8px}
.msg.u{flex-direction:row-reverse}
.av{flex:0 0 30px;width:30px;height:30px;border-radius:8px;background:var(--brand);color:#fff;
  display:flex;align-items:center;justify-content:center;font-size:12.5px;margin-top:2px}
.msg.u .av{background:#8fa8dd}
.bub{max-width:82%;padding:10px 13px;border-radius:12px;background:var(--panel);
  box-shadow:0 1px 2px rgba(20,40,90,.06);white-space:pre-wrap;word-break:break-word;font-size:13.8px}
.msg.u .bub{background:var(--brand);color:#fff}
.bub b{font-weight:600}
.bub .sm{color:var(--muted);font-size:12px}
.bub .hl{background:#fff7e0;border:1px solid #f0e2b0;border-radius:6px;padding:6px 9px;margin-top:8px;
  font-size:12.8px;color:#6b5510}
.bub .ok{color:#0a8f4e;font-weight:600}
.bub .no{color:#c0392b;font-weight:600}
.chips{max-width:640px;margin:4px auto 0;padding:0 12px;display:flex;flex-wrap:wrap;gap:7px}
.chips button{border:1px solid var(--line);background:#fff;border-radius:15px;padding:6px 12px;
  font-size:12.5px;color:#3c4c6b}
.chips button:active{background:#eef2fb}
#composer{position:fixed;left:0;right:0;bottom:0;background:var(--panel);
  border-top:1px solid var(--line);padding:9px 10px calc(9px + env(safe-area-inset-bottom))}
.cwrap{max-width:640px;margin:0 auto;display:flex;gap:8px;align-items:flex-end}
.cwrap textarea{flex:1;border:1px solid var(--line);border-radius:10px;padding:9px 11px;
  font-size:14px;resize:none;outline:0;height:42px;max-height:110px;line-height:1.5;background:var(--bg)}
.cwrap button{border:0;background:var(--brand);color:#fff;border-radius:10px;padding:10px 17px;font-size:14px}
.cwrap button:disabled{background:#c7d2e8}

/* ===== GitHub Pages 桌面端适配（仅宽屏生效，移动端不受影响） ===== */
@media (min-width: 760px) {
  body {
    background: linear-gradient(160deg,#eef3fb 0%,#e2e9f6 100%) !important;
    display: flex !important;
    flex-direction: column !important;   /* 关键：纵向堆叠，保持原版结构 */
    align-items: center !important;
    padding: 26px 16px 44px !important;
    min-height: 100vh !important;
    box-sizing: border-box !important;
  }
  body > * { width: 100%; max-width: 680px !important; }

  /* 三段拼成一张卡片：头部圆顶、输入区圆底、聊天区白底 */
  #top {
    border-radius: 16px 16px 0 0 !important;
    box-shadow: 0 10px 30px rgba(30,50,90,.10) !important;
  }
  #msgs {
    background: #fff !important;
    box-shadow: 0 18px 46px rgba(30,50,90,.12) !important;
    padding-left: 14px !important; padding-right: 14px !important;
    min-height: 52vh !important;
  }
  .chips {
    background: #fff !important;
    box-shadow: 0 18px 46px rgba(30,50,90,.12) !important;
    padding: 4px 14px 10px !important;
  }
  #composer {
    background: #fff !important;
    border-radius: 0 0 16px 16px !important;
    box-shadow: 0 18px 46px rgba(30,50,90,.12) !important;
    padding-bottom: 16px !important;
  }
}
@media (min-width: 1100px) { body > * { max-width: 720px !important; } }

</style>
</head>
<body>
<div id="top"><span class="lg">证</span>证小安 · 公证问答<small>微信版</small></div>
<div id="msgs"></div>
<div class="chips" id="chips"></div>
<div id="composer"><div class="cwrap">
  <textarea id="inp" rows="1" placeholder="描述您的公证需求…"></textarea>
  <button id="send">发送</button>
</div></div>
<script>
const KB = __DATA__;
const FULL = __FULLURL__;

/* ================= 检索（与后端同源的简化实现） ================= */
const GENERIC = new Set("公证 办理 申请 需要 什么 材料 如何 怎么 可以 是否 请问 我想 我要 户籍 使用 用途 用于 国内 国外 境外 多少 钱 几天 时间".split(" "));
const SUFFIX = ["公证","证明","声明","协议","合同","书","文件","事项","服务"];
const ALIAS_IDX = {};
KB.kb.forEach(it => (it.alias||[]).forEach(a => ALIAS_IDX[a] = it.no));

function tokenize(q){
  const s = (q||"").replace(/[\\s，。？！、,\\.!\\?·：:；;（）()【】\\[\\]"'～~—\\-]/g,"");
  const out = new Set();
  for(let n=2;n<=3;n++)
    for(let i=0;i+n<=s.length;i++) out.add(s.slice(i,i+n));
  if(s.length===1) out.add(s);
  return [...out];
}
function coreSubject(name){
  let n = (name||"").replace(/[（(][^）)]*[）)]/g,"").split("·").pop().trim();
  n = n.replace(/^\\d+[\\.、]\\s*/,"").replace(/^(涉外的?|国内的?)/,"");
  SUFFIX.forEach(s => n = n.split(s).join(""));
  return n.trim();
}
function search(q){
  const toks = tokenize(q);
  if(!toks.length) return [];
  const df = t => KB.kb.reduce((c,it)=>c+((it._text||"").includes(t)?1:0),0) || 1;
  const scored = [];
  for(const it of KB.kb){
    it._text = it._text || (it.name + " " + (it.alias||[]).join(" ") + " " +
      it.fields.map(f=>f[0]+f[1]).join(" ") + " " + it.cat);
    let sc = 0, hits = 0;
    for(const t of toks){
      if(it._text.includes(t)){
        hits++;
        sc += (1/(1+Math.log(1+KB.kb.length/df(t)))) * Math.sqrt(t.length);
      }
    }
    if(!hits) continue;
    sc *= 1 + 0.35*hits/toks.length;
    const aliasHit = (it.alias||[]).find(a => a.length>=2 && q.includes(a));
    if(aliasHit) sc += 10;
    if(q.includes(coreSubject(it.name)) && coreSubject(it.name).length>=2) sc += 8;
    scored.push([sc,it]);
  }
  scored.sort((a,b)=>b[0]-a[0]);
  return scored.slice(0,3).filter(x=>x[0]>=0.5).map(x=>x[1]);
}
function isRelevant(q, it){
  if((it.alias||[]).some(a=>a.length>=2 && q.includes(a))) return true;
  const c = coreSubject(it.name);
  if(c.length>=2 && q.includes(c)) return true;
  // 3 字片段才视为相关，避免「商标转让声明」被「转让股权」这类共享 2 字词的条目截胡
  for(let i=0;i+3<=c.length;i++) if(q.includes(c.slice(i,i+3))) return true;
  return false;
}

/* ================= 四要素 ================= */
const FOUR = {
  "办什么公证": ["办什么","什么公证","办理什么","想办","要办","办理","申请"],
  "户籍在哪儿": ["户籍","户口","籍贯","老家"],
  "在哪儿使用": ["在哪用","哪里用","使用地","拿去","用于哪个","哪个国家","出到","用在","申根","美国","加拿大","澳大利亚","英国","日本","韩国","德国","法国","意大利","西班牙","马来西亚","泰国","新加坡","俄罗斯","新西兰","荷兰"],
  "用途是什么": ["用途","干什么用","做什么用","为了","用来","目的","卖给","过户给","给子女","给孩子","给父母","转给","担保","申根","签证","认证","落户","上学","入学","留学","移民","继承"]
};
const PROVS = KB.quotesLite.map(q=>q.prov).concat(["香港","澳门","台湾"]);
function extractFour(t){
  t = t||"";
  const g = {};
  for(const k in FOUR) g[k] = FOUR[k].some(w=>t.includes(w));
  if(!g["办什么公证"]) g["办什么公证"] = ["委托","声明","协议","合同","签字","印鉴","继承","遗嘱","出生","学历","学位","成绩单","毕业证","抚养权","监护","亲属关系","结婚证","离婚","死亡证明","身份证","户口本","护照","曾用名","财产约定","赠与","过户","股权","无犯罪","未婚","出入境","驾照","在职","复印件"].some(w=>t.includes(w));
  if(!g["户籍在哪儿"]) g["户籍在哪儿"] = PROVS.some(p=>t.includes(p));
  return g;
}
function missingFour(t){
  const g = extractFour(t);
  return Object.keys(g).filter(k=>!g[k]);
}

/* ================= 涉外国家判定：单号/双号 · 是否必须海牙 ================= */
/* 判定依据：外交部《公约》缔约国名单（127 国），内嵌于 KB.hague */
const COUNTRY_WORDS = ["申根","美国","加拿大","澳大利亚","澳洲","新西兰","英国","爱尔兰",
  "日本","韩国","新加坡","马来西亚","泰国","越南","菲律宾","印度尼西亚","印尼","柬埔寨",
  "老挝","缅甸","印度","巴基斯坦","孟加拉","斯里兰卡","尼泊尔","哈萨克斯坦","乌兹别克斯坦",
  "蒙古","阿联酋","迪拜","沙特","卡塔尔","科威特","阿曼","巴林","以色列","土耳其","伊朗",
  "伊拉克","约旦","德国","法国","意大利","西班牙","葡萄牙","荷兰","比利时","卢森堡","瑞士",
  "奥地利","瑞典","挪威","丹麦","芬兰","冰岛","波兰","捷克","斯洛伐克","匈牙利","罗马尼亚",
  "保加利亚","希腊","克罗地亚","斯洛文尼亚","塞尔维亚","俄罗斯","乌克兰","白俄罗斯",
  "立陶宛","拉脱维亚","爱沙尼亚","格鲁吉亚","亚美尼亚","阿塞拜疆","埃及","南非","尼日利亚",
  "肯尼亚","摩洛哥","阿尔及利亚","突尼斯","坦桑尼亚","加纳","巴西","阿根廷","智利","秘鲁",
  "哥伦比亚","委内瑞拉","厄瓜多尔","玻利维亚","乌拉圭","巴拉圭","墨西哥","巴拿马",
  "哥斯达黎加","古巴","牙买加","欧盟"];
const COUNTRY_ALIAS = {"申根国":"申根","冰島":"冰岛","俄国":"俄罗斯","澳洲":"澳大利亚",
  "印尼":"印度尼西亚","迪拜":"阿联酋","美利坚合众国":"美国",
  "大不列颠及北爱尔兰联合王国":"英国","俄罗斯联邦":"俄罗斯","大韩民国":"韩国"};
function findCountries(t){
  t = t||"";
  const found = [];
  for(const c of COUNTRY_WORDS){
    const i = t.indexOf(c);
    if(i>=0) found.push([i, COUNTRY_ALIAS[c]||c]);
  }
  found.sort((a,b)=>a[0]-b[0]);
  const out = [];
  for(const [_i,c] of found) if(!out.includes(c)) out.push(c);
  return out;
}
function isHague(c){
  if(!c) return false;
  if(c==="申根"||c==="欧盟") return true;
  const n = COUNTRY_ALIAS[c]||c;
  if((KB.hague||[]).includes(n)) return true;
  for(const m of (KB.hague||[])){
    if(m.length>=2 && (m.includes(n)||n.includes(m))) return true;
  }
  return false;
}
function countryText(countries){
  if(!countries || !countries.length) return "";
  const L = ["【涉外国家判定 · 单号/双号与海牙认证】"];
  for(const c of countries){
    L.push(`● ${c}：`);
    L.push("  · 单号/双号：涉外通常建议做【双号】（双号＝中文原件＋译文均公证，"
      + "境外对译文效力认可度更高）；若使用地只要中文文件，可做单号。以使用地要求为准。");
    if(isHague(c)){
      L.push(`  · 是否必须海牙认证：${c} 属《取消外国公文书认证要求的公约》（海牙公约）`
        + "缔约国，通常办【海牙认证（附加证明书/Apostille）】即可，无需领事认证（双认证）。"
        + "个别收件机构可能另有要求，办理前请再确认。");
    }else{
      L.push(`  · 是否必须海牙认证：${c} 不在外交部公布的《公约》缔约国名单内，`
        + "通常需办【领事认证（使馆认证，即双认证）】：公证 → 外交部/地方外办认证 → "
        + `使用国驻华使领馆认证。若该国近期已加入公约，以使用地机构口径为准。`);
    }
  }
  L.push("");
  L.push("（依据：中国领事服务网（外交部）《公约》缔约国名单，共 127 个缔约国；"
    + "名单为官方口径，个别收件机构可能有额外要求。）");
  return L.join("\\n");
}

/* ================= 回答生成（纯规则，绝不编造） ================= */
const PERIOD_W = ["几天","多久","多长时间","多少天","几个工作日","周期","多久能拿","什么时候能拿"];
function esc(s){return (s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")}
function periodText(){
  const p = [...new Set(KB.quotesLite.map(q=>q.period))].join(" / ").replace(/工/g," 个工作日");
  const a = [...new Set(KB.quotesLite.map(q=>q.periodAuth))].join(" / ").replace(/工/g," 个工作日");
  return `· 办理周期：公证出具 ${p}（知识库覆盖的 25 省口径一致）\\n· 若使用地要求海牙/领事认证：公证+认证合计 ${a}`;
}
function fieldOf(it, name){
  const f = (it.fields||[]).find(x=>x[0]===name);
  return f ? f[1].trim() : "";
}
function officialLookup(q){
  const keys = Object.keys(KB.official).sort((a,b)=>b.length-a.length);
  for(const k of keys){
    if(q.includes(k)){
      const m = KB.official[k].materials || [];
      return {name: KB.official[k].name || k,
        text: m.map((x,i)=>`  ${i+1}. ${x}`).join("\\n")};
    }
  }
  // 口语词形预替换：问句含口语键（如「意向监护」）时，用规范术语再查一轮
  const spoken = KB.spoken || {};
  for(const sp of Object.keys(spoken).sort((a,b)=>b.length-a.length)){
    if(q.includes(sp)){
      const formal = spoken[sp];
      for(const k of keys){
        if(k===formal || k.includes(formal) || formal.includes(k)){
          const m = KB.official[k].materials || [];
          return {name: KB.official[k].name || k, spoken: sp, formal: formal,
            text: m.map((x,i)=>`  ${i+1}. ${x}`).join("\\n")};
        }
      }
    }
  }
  return null;
}
function answer(q){
  const parts = [];
  let hits = search(q).filter(it=>isRelevant(q,it));
  const miss = missingFour(q);
  const wantPeriod = PERIOD_W.some(w=>q.includes(w));
  const countries = findCountries(q);
  const cText = countryText(countries);
  // 口语词形检测：问句含口语写法且官方清单有规范事项时，
  // 先展示规范事项知识点，命中的 KB 条目降级为「相近条目参考」
  const offPre = officialLookup(q);
  const spokenMatch = offPre && offPre.spoken && offPre.formal;

  if(spokenMatch){
    parts.push(`您问的「${esc(offPre.spoken)}」是口语写法，对应官方规范事项 <b>${esc(offPre.formal)}</b>。`);
    parts.push(`\\n■ ${esc(offPre.name)}［来源：司法部官方证明材料清单］\\n${esc(offPre.text)}`);
    if(hits.length){
      const it0 = hits[0];
      parts.push(`\\n——\\n说明：知识库中的「${esc(it0.name)}」条目针对的是<b>其他监护相关事项</b>（监护权变更、过继、收养等，此类声明无效不能公证），与<b>${esc(offPre.formal)}</b>（法律允许的书面协议安排）<b>不是同一事项</b>，该条目的「不能办理」结论不适用于您的问题。`);
    }
    if(wantPeriod) parts.push(periodText());
    if(cText) parts.push("\\n"+cText);
    if(miss.length) parts.push(`\\n——\\n为给出准确结论，请补充：<b>${miss.join("、")}</b>。`);
    parts.push(`<span class="sm">价格以办理公证处对「${esc(offPre.formal)}」的报价为准｜如需模型分析与联网核实，请在浏览器打开完整版：${FULL}</span>`);
    if(q.includes("代收") && !/不能代收/.test(parts.join("")))
      parts.push(`<div class="hl">⚠️ 口径提示：若委托书涉及授权受托人<b>代收房款</b>——按知识库口径，<b>卖房款项不能代收</b>（条目 1「要求」）。请以办理公证处最终口径为准。</div>`);
    return parts.join("\\n");
  }

  if(hits.length){
    const it = hits[0];
    const ok = it.ok;
    parts.push(`<b>${esc(it.name)}</b>［${ok?'<span class="ok">☑ 可办理</span>':'<span class="no">☐ 不能办理</span>'}］`);
    const what = fieldOf(it,"办什么公证"); if(what) parts.push(`· 办什么：${esc(what)}`);
    const req = fieldOf(it,"要求"); if(req) parts.push(`· 限制/要求：${esc(req)}`);
    const mat = fieldOf(it,"材料");
    parts.push(mat ? `· 材料：${esc(mat)}` : "· 材料：知识库暂未收录该事项的材料清单，以办理公证处口径为准");
    if(wantPeriod) parts.push(periodText());
    const price = fieldOf(it,"价格");
    if(price && price!=="—") parts.push(`· 价格：${esc(price)}（最终以平台/公证处确认为准）`);
    if(cText) parts.push("\\n"+cText);
    if(miss.length) parts.push(`\\n——\\n为给出准确结论，请补充：<b>${miss.join("、")}</b>。`);
    parts.push(`<span class="sm">依据：知识库条目 ${it.no}｜微信精简版不含 AI 分析，如需模型分析、联网核实、图片识别，请在浏览器打开完整版：${FULL}</span>`);
  } else {
    const off = officialLookup(q);
    if(off){
      parts.push(`当前知识库暂未收录该事项，以下为<b>司法部官方证明材料清单 · ${esc(off.name)}</b>：\\n${esc(off.text)}`);
      if(wantPeriod) parts.push(periodText());
      if(cText) parts.push("\\n"+cText);
      if(miss.length) parts.push(`\\n——\\n请补充：<b>${miss.join("、")}</b>。`);
      parts.push(`<span class="sm">来源：司法部官方清单｜完整版可在浏览器打开：${FULL}</span>`);
    } else if(cText){
      // 涉外场景：即便未匹配到条目，也必须给出国家判定（用户明确要求）
      parts.push("当前知识库暂未收录该事项的具体条目，以下为涉外使用地的判定结论：");
      parts.push("\\n"+cText);
      if(wantPeriod) parts.push(periodText());
      if(miss.length) parts.push(`\\n——\\n请补充：<b>${miss.join("、")}</b>，以便匹配到具体公证事项。`);
      parts.push(`<span class="sm">如需模型分析与联网核实，请在浏览器打开完整版：${FULL}</span>`);
    } else {
      parts.push("未能匹配到具体公证事项。请描述得更具体些，例如：\\n· 「委托买房需要什么材料」\\n· 「结婚证公证要几天」\\n· 「放弃继承权声明怎么办」\\n或点击下方快捷问题。");
    }
  }
  // 红线口径：代收房款
  if(q.includes("代收") && !/不能代收/.test(parts.join("")))
    parts.push(`<div class="hl">⚠️ 口径提示：若委托书涉及授权受托人<b>代收房款</b>——按知识库口径，<b>卖房款项不能代收</b>（条目 1「要求」）。请以办理公证处最终口径为准。</div>`);
  return parts.join("\\n");
}

/* ================= UI ================= */
const $ = s=>document.querySelector(s);
function push(role, html){
  const d = document.createElement("div");
  d.className = "msg "+role;
  d.innerHTML = `<div class="av">${role==="a"?"证":"我"}</div><div class="bub">${html}</div>`;
  $("#msgs").appendChild(d);
  window.scrollTo(0, document.body.scrollHeight);
}
const CHIPS = ["结婚证公证要几天","委托买房需要什么材料","放弃继承权声明公证怎么办","涉外公证大概多少钱","无犯罪记录公证怎么办","亲属关系公证需要什么"];
$("#chips").innerHTML = CHIPS.map(c=>`<button>${c}</button>`).join("");
$("#chips").onclick = e=>{ if(e.target.tagName==="BUTTON"){ $("#inp").value = e.target.textContent; send(); } };

let BUSY = false;
function send(){
  if(BUSY) return;
  const v = $("#inp").value.trim();
  if(!v) return;
  BUSY = true; $("#send").disabled = true;
  $("#inp").value = ""; $("#inp").style.height = "auto";
  push("u", esc(v));
  setTimeout(()=>{
    push("a", answer(v));
    BUSY = false; $("#send").disabled = false;
  }, 180);
}
$("#send").onclick = send;
$("#inp").addEventListener("keydown", e=>{ if(e.key==="Enter" && !e.shiftKey){ e.preventDefault(); send(); }});
$("#inp").addEventListener("input", function(){ this.style.height="auto"; this.style.height=Math.min(this.scrollHeight,110)+"px"; });

push("a", `您好，我是证小安公证助手（<b>微信精简版</b>）。
· 直接提问即可，例如「委托买房需要什么材料」「结婚证公证要几天」
· 覆盖 ${KB.kb.length} 项公证事项、司法部官方材料清单 ${Object.keys(KB.official).length} 项、各省办理周期
<div class="hl">当前处于微信内置浏览器。如需 <b>AI 模型分析、联网核实、上传图片识别</b> 完整能力，请复制链接到浏览器打开完整版：\\n${FULL}</div>`);
</script>
</body>
</html>"""

html = (HTML.replace("__DATA__", DATA_JS)
            .replace("__FULLURL__", json.dumps(API, ensure_ascii=False)))

out = "/workspace/zhengxiaoan/weixin.html"
open(out, "w", encoding="utf-8").write(html)
print("生成:", out, f"{len(html.encode())//1024} KB")
