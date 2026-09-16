#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""涉外国家判定（单号/双号 · 是否必须海牙）专项回归测试。

覆盖：
  ① 国家识别 find_countries（多国、区域、别名归一化）
  ② 涉外判定 is_overseas_q
  ③ 判定检索 country_rule_search（联网，容错）
  ④ 结论组装 country_ruling_note（海牙成员 / 非成员 / 未知 + 不确定性说明）
"""
import sys, importlib.util

spec = importlib.util.spec_from_file_location("srv", "/workspace/zhengxiaoan/server.py")
S = importlib.util.module_from_spec(spec)
sys.modules["srv"] = S
spec.loader.exec_module(S)

PASS = FAIL = 0


def ck(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name} {extra}")


print("=== ① 国家识别 ===")
ck("美国", S.find_countries("我孩子要去美国留学") == ["美国"])
ck("韩国", "韩国" in S.find_countries("户籍河北，韩国留学用"))
ck("申根归一", S.find_countries("申根签用") == ["申根"])
ck("申根国归一", S.find_countries("申根国用的") == ["申根"])
ck("澳洲归一", S.find_countries("去澳洲") == ["澳大利亚"])
ck("印尼归一", S.find_countries("印尼签证") == ["印度尼西亚"])
ck("迪拜归一", S.find_countries("迪拜工作") == ["阿联酋"])
ck("无国家", S.find_countries("国内过户用") == [])
ck("多国去重", S.find_countries("美国和加拿大都要用") == ["美国", "加拿大"])
ck("按位置排序", S.find_countries("先英国后美国") == ["英国", "美国"])

print("=== ② 涉外判定 ===")
ck("有国家即涉外", S.is_overseas_q("美国", ["美国"]))
ck("涉外字样", S.is_overseas_q("涉外公证"))
ck("海牙字样", S.is_overseas_q("要不要海牙"))
ck("双认证字样", S.is_overseas_q("需要双认证吗"))
ck("签证字样", S.is_overseas_q("办签证用的"))
ck("纯国内不涉外", not S.is_overseas_q("国内房管局过户", []))

print("=== ③ 判定结论组装 ===")
n_us = S.country_ruling_note(["美国"], item="结婚证公证")
ck("含单号/双号说明", "单号" in n_us and "双号" in n_us)
ck("美国判为海牙国", "海牙" in n_us and "Apostille" in n_us)
ck("美国不用双认证", "无需" in n_us)
n_my = S.country_ruling_note(["马来西亚"], item="无犯罪记录公证")
ck("马来西亚判为非海牙/领事认证", "领事认证" in n_my or "双认证" in n_my)
n_xx = S.country_ruling_note(["某未知国"], item="出生公证")
ck("名单外国判为需领事认证", "领事认证" in n_xx or "双认证" in n_xx)
ck("名单外国保留核实建议", "以使用地" in n_xx or "确认" in n_xx)
ck("附官方名单来源", "外交部" in n_xx or "领事服务网" in n_xx)
ck("空国家返回空", S.country_ruling_note([]) == "")

print("=== ④ 联网判定检索（容错，不强制成功）===")
try:
    txt, ok = S.country_rule_search("美国", item="结婚证公证", timeout=9)
    print(f"  · 检索返回 ok={ok} len={len(txt or '')}")
    ck("检索函数可调用", isinstance(ok, bool))
    if ok:
        ck("检索文本含'公证'", "公证" in txt)
except Exception as e:
    ck("检索不抛异常", False, str(e))

print("=== ⑤ 四要素：国家算已明确使用地 ===")
f = S.extract_four("我要办结婚证公证，去美国留学用")
ck("使用地明确", f["在哪儿使用"])
f2 = S.extract_four("办无犯罪记录公证，韩国签证用")
ck("韩国使用地明确", f2["在哪儿使用"])

print("=== ⑥ 官方缔约国名单（外交部）===")
import hague_data as HG
ck("名单规模 127", len(HG.HAGUE_MEMBERS_CN) == 127, f"实际 {len(HG.HAGUE_MEMBERS_CN)}")
ck("含美国", HG.is_hague_member("美国")[0])
ck("含日本", HG.is_hague_member("日本")[0])
ck("含韩国", HG.is_hague_member("韩国")[0])
ck("含申根区域", HG.is_hague_member("申根")[0])
ck("全称归一(美利坚合众国)", HG.is_hague_member("美利坚合众国")[0])
ck("全称归一(大不列颠及北爱尔兰联合王国)", HG.is_hague_member("大不列颠及北爱尔兰联合王国")[0])
ck("马来西亚不在名单", not HG.is_hague_member("马来西亚")[0])
ck("越南不在名单", not HG.is_hague_member("越南")[0])
ck("埃及不在名单(注3)", not HG.is_hague_member("埃及")[0])
ck("来源含领事服务网", "领事服务网" in HG.hague_source_note())

print(f"\n结果：{PASS} 通过 / {FAIL} 失败")
sys.exit(1 if FAIL else 0)
