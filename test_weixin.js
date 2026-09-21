// 微信版页面行为测试：mock 最小 DOM，执行内嵌脚本，验证检索问答输出
const fs = require('fs');
const html = fs.readFileSync('/workspace/zhengxiaoan/weixin.html', 'utf8');
const script = html.match(/<script>([\s\S]*)<\/script>/)[1];

// ---- 最小 DOM mock ----
function el(sel){
  return {
    sel, innerHTML:'', value:'', style:{}, disabled:false, scrollTop:0,
    onclick:null, _handlers:{},
    appendChild(c){ (this.children = this.children||[]).push(c); },
    addEventListener(ev, fn){ this._handlers[ev] = fn; },
    querySelectorAll(){ return []; },
  };
}
const els = {};
const $ = s => els[s] || (els[s] = el(s));
global.document = {
  querySelector: $,
  createElement(){ return el('created'); },
  body: Object.assign(el('body')),
};
global.window = { scrollTo(){}, };
const realSetTimeout = setTimeout;
global.setTimeout = (fn, ms) => fn();   // 立即执行

eval(script);   // 执行整段脚本（渲染欢迎消息 + 绑定事件）

// ---- 测试用例 ----
function ask(q){
  $('#inp').value = q;
  $('#send').onclick();
  const msgs = $('#msgs').children || [];
  const last = msgs[msgs.length - 1];
  return last ? last.innerHTML : '(无输出)';
}

let fails = 0;
function chk(name, cond, out){
  console.log((cond ? 'PASS ' : 'FAIL '), name);
  if(!cond){ fails++; console.log('   输出片段:', (out||'').slice(0, 300)); }
}

let o = ask('结婚证公证要几天');
chk('结婚证公证命中条目21', o.includes('结婚证'), o);
chk('回答周期 3-5 个工作日', o.includes('3-5 个工作日'), o);

o = ask('委托买房需要什么材料');
chk('委托买房命中条目1', o.includes('房屋、车辆买卖委托'), o);
chk('给出材料（户口本）', o.includes('户口本'), o);

o = ask('放弃继承权声明怎么办');
chk('放弃继承命中', o.includes('放弃继承'), o);

o = ask('涉外公证大概多少钱');
chk('涉外问价有响应', o.length > 50, o);

o = ask('委托书授权受托人代收房款可以吗');
chk('代收红线提示', o.includes('不能代收'), o);

o = ask('遗嘱公证怎么办');
chk('遗嘱公证有实质响应', o.includes('遗嘱') && (o.includes('司法部') || o.includes('条目')), o);

o = ask('商标转让声明需要什么材料');
chk('官方清单兜底', o.includes('司法部官方'), o);

o = ask('今天天气怎么样');
chk('无关问题给引导不硬凑', o.includes('未能匹配') || o.includes('快捷问题'), o);

// ---- 涉外国家判定（单号/双号 · 是否必须海牙）----
o = ask('结婚证公证，去美国留学用');
chk('美国：识别为涉外', o.includes('涉外国家判定'), o);
chk('美国：提到单号/双号', o.includes('单号') && o.includes('双号'), o);
chk('美国：判为海牙缔约国', o.includes('海牙') && o.includes('Apostille'), o);

o = ask('无犯罪记录公证，马来西亚签证用');
chk('马来西亚：判为需领事认证', o.includes('领事认证') || o.includes('双认证'), o);
chk('马来西亚：提示不在名单内', o.includes('不在') && o.includes('名单'), o);

o = ask('亲属关系公证，韩国留学用');
chk('韩国：判为海牙缔约国', o.includes('海牙') && o.includes('缔约国'), o);

o = ask('出生公证，越南使用');
chk('越南：判为需领事认证', o.includes('领事认证') || o.includes('双认证'), o);

o = ask('我要办宠物血统证明公证，去德国用');
chk('未收录事项也给出国家判定', o.includes('涉外国家判定') || o.includes('德国'), o);

o = ask('国内房管局过户用，要什么材料');
chk('纯国内不触发国家判定', !o.includes('涉外国家判定'), o);

// ---- 口语词形 → 规范事项（相关知识点展示）----
o = ask('意向监护公证');
chk('意向监护：识别为意定监护', o.includes('意定监护'), o);
chk('意向监护：展示官方材料', o.includes('司法部官方'), o);
chk('意向监护：提示相近条目差异', o.includes('不是同一事项'), o);

// ---- 股权类：可办理 + 标的费口径 ----
o = ask('股权转让协议公证怎么办理');
chk('股权转让：命中条目 17', o.includes('股权转让协议公证'), o);
chk('股权转让：标的费口径', o.includes('标的费') && o.includes('1.2%'), o);
chk('股权转让：不再说不可办理', !o.includes('不可办理') && !o.includes('不能办理'), o);
o = ask('股权变更怎么收费');
chk('股权变更：计费口径提示', o.includes('标的费') && o.includes('公证费'), o);

// ---- 合同/协议公证：受理范围与红线 ----
o = ask('合作合同可以做协议公证吗');
chk('合同公证：受理口径', o.includes('合同公证') || o.includes('协议公证'), o);
chk('合同公证：红线说明', o.includes('公序良俗') || o.includes('不予受理') || o.includes('受理'), o);

// 欢迎消息存在
chk('欢迎消息渲染', ($('#msgs').children||[]).length > 8, '');

console.log(fails ? `\n失败 ${fails} 项` : '\n全部通过');
process.exit(fails ? 1 : 0);
