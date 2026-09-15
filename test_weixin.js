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

// 欢迎消息存在
chk('欢迎消息渲染', ($('#msgs').children||[]).length > 8, '');

console.log(fails ? `\n失败 ${fails} 项` : '\n全部通过');
process.exit(fails ? 1 : 0);
