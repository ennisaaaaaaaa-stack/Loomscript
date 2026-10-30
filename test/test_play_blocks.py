#!/usr/bin/env python3
"""play blocks (7.4) 测试 —— DM 提议 -> 引擎校验放行。

检查1: 正常放行——visible_at=A1 在 A1 发 -> clue_found 落账（载荷带 payload）
检查2: 太早拦截——visible_at=A2 在 A1 发 -> ContractError，不落账
检查3: 幂等——同 clue 发两次，第二次 None 不落账
检查4: act_scoped 互斥——A1 发过的 clue，A2 同 id 再发 -> None（act 作用域去重）
       （不带 act_scoped 的 clue：跨幕同 id 也幂等——clue_id 唯一）
检查5: must_ready_by 逾期归档——advance_act 过死线 -> journal_push 落账
检查6: jitter_text 不参与校验——带与不带都放行，载荷透传
"""
import copy
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from engine import Bundle, Session, ContractError  # noqa: E402
from play_blocks import propose_clue, sweep_deadline  # noqa: E402

fails = []


def check(name, ok):
    print(("GREEN " if ok else "RED   ") + name)
    if not ok:
        fails.append(name)


def make_bundle():
    """mini bundle + clues 段（visible_at/must_ready_by 用真实幕 id）。"""
    data = json.load(open(ROOT / "bundles" / "macbeth_mini.json",
                          encoding="utf-8"))
    data["clues"] = [
        {"clue_id": "dagger", "title": "幻影匕首", "text": "一把看不见的刀。",
         "visible_at": "A1", "must_ready_by": "A1",
         "payload": {"title": "幻影匕首", "jitter_text": "看，那把刀悬在半空。"}},
        {"clue_id": "crown_whisper", "title": "王冠低语", "text": "预言的第二声。",
         "visible_at": "A2", "must_ready_by": "A2"},
        {"clue_id": "blood_hand", "title": "血手", "text": "洗不净的手。",
         "visible_at": "A1", "must_ready_by": "A1", "act_scoped": True},
    ]
    return Bundle(data)


b = make_bundle()
s = Session(b, tier="tangwu")
s.start()  # game_start + act_begin(A1)（engine.start 语义见 test_engine）

# 1) 正常放行
ev = propose_clue(s, "dagger")
ok1 = (ev is not None and ev["type"] == "clue_found"
       and ev.get("jitter_text") == "看，那把刀悬在半空。"
       and s.events[-1] is ev)
check("1-fire-on-visible", ok1)

# 2) 太早拦截
n = len(s.events)
try:
    propose_clue(s, "crown_whisper")  # visible_at=A2, 当前 A1
    ok2 = False
except ContractError:
    ok2 = len(s.events) == n  # 不落账
check("2-block-too-early", ok2)

# 3) 幂等
again = propose_clue(s, "dagger")
check("3-idempotent", again is None)

# 4) act_scoped 互斥：A1 已发 blood_hand，推到 A2 同 id 再提议 -> None
propose_clue(s, "blood_hand")  # A1 发掉
from dm import DM  # noqa: E402
from engine import SemiManualPort  # noqa: E402
dm = DM(b, SemiManualPort({}))
dm.advance_act(s)  # A1 -> A2（推进时 sweep_deadline 尚未接线，手动扫）
sweep_deadline(s)
ev2 = propose_clue(s, "blood_hand")  # act_scoped: A1 已发，A2 再提议
check("4-act-scoped-dedup", ev2 is None)
# 4b) 已发射线索永不误报逾期（回归：act_scoped 键不匹配曾致误报归档）
late_jrn = [e for e in s.events if e["type"] == "journal_push"
            and "逾期" in e.get("journal_text", "")]
check("4b-fired-never-archived", not late_jrn)

# 5) must_ready_by 逾期归档：dagger(A1 死线) 在 A2 扫描 -> journal_push
# （dagger 已在检查1发射，所以改用「未发射且死线已过」的独立线索验证）
b2 = copy.deepcopy(b.data)
b2["clues"] = [
    {"clue_id": "dagger", "title": "幻影匕首", "text": "一把看不见的刀。",
     "visible_at": "A1", "must_ready_by": "A1"},
    {"clue_id": "late_one", "title": "迟到线索", "text": "死线已过。",
     "visible_at": "A1", "must_ready_by": "A1"},
]
bb = Bundle(b2)
ss = Session(bb, tier="tangwu")
ss.start()
propose_clue(ss, "dagger")  # 只发 dagger，late_one 欠着
dm2 = DM(bb, SemiManualPort({}))
dm2.advance_act(ss)  # 到 A2
sweep_deadline(ss)
sweep_deadline(ss)  # 重复扫描：归档幂等（回归：曾重复归档）
journals = [e for e in ss.events if e["type"] == "journal_push"]
ok5 = (sum(1 for e in journals if "late_one" in e["journal_text"]) == 1
       and not any("dagger" in e["journal_text"] for e in journals))
check("5-deadline-sweep", ok5)

# 6) jitter_text 不参与校验：A1 提议 A2 线索，带不带 jitter 都拦；
#    到 A2 后带 jitter 放行且透传
s3 = Session(make_bundle(), tier="tangwu")
s3.start()
ok6 = False
try:
    propose_clue(s3, "crown_whisper", jitter_text="DM 的演出抖动")
except ContractError:
    ok6 = True  # 太早，jitter 救不了它
s3b = Session(make_bundle(), tier="tangwu")
s3b.start()
DM(make_bundle(), SemiManualPort({})).advance_act(s3b)  # 到 A2
ev6b = propose_clue(s3b, "crown_whisper", jitter_text="演出措辞")
ok6 = ok6 and ev6b is not None and ev6b.get("jitter_text") == "演出措辞"
check("6-jitter-not-validated", ok6)

print()
if fails:
    print(f"{len(fails)} RED / {6} total")
    sys.exit(1)
print("6/6 GREEN")
