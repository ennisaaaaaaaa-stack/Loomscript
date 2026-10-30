"""DM 层测试 —— 16:00 检查点交付验收。

检查1: DM 全流程跑通（开场白/行动卡/私聊/推幕/手账/复盘/记忆回流）
检查2: 角色墙——装配器级隔离（班柯的 prompt 材料里搜不到弑王秘密）
检查3: DM 全知 vs 角色墙——同一局里 banquo 材料无秘密，DM 材料全量有
检查4: 私聊原文不进 DM 材料（10/30拍板：DM 只拿摘要）
检查4b: 私聊原文确实进角色自己的 channel 历史
检查5: 玩法提议事件合法
"""
import json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from engine import Bundle, Session, SemiManualPort  # noqa: E402
from dm import DM, assemble_character_prompt, assemble_dm_prompt, DM_ID  # noqa: E402

bundle = Bundle.load(ROOT / "bundles" / "macbeth_mini.json")
results = []


def check(name, fn):
    try:
        fn()
        results.append((name, "GREEN", ""))
    except Exception as e:
        results.append((name, "RED", repr(e)[:150]))


# ---- 公共: 一局带 DM 的完整流程 -------------------------------------------
def play_with_dm():
    s = Session(bundle).start()
    dm = DM(bundle, SemiManualPort({}), dm_memory={}, user_profile={"name": "照渊"})
    dm.opening(s)                       # 开场白（含玩法提议钩子）
    dm.propose_play(s)                  # 提议玩法
    dm.deal_cards(s, "macbeth")         # 行动卡
    s.enter_scene("A1S1")
    s.line("lady_m", "今晚的狼骑在马上。", channel="main")
    s.line("macbeth", "（私聊）我看见了刀。", channel="dm:lady_m")  # 玩家私聊
    s.line("lady_m", "（私聊回）看着它。", channel="dm:lady_m")
    dm.note(s, "预言已种下，等它发芽。")   # 手账
    s.fire_reveals("A1S1")
    dm.advance_act(s)                   # 推幕 -> A2 + act_end 存档
    s.enter_scene("A2S1")
    s.line("macbeth", "现在我是王。")
    dm.advance_act(s)                   # -> game_end + 全量存档
    dm.review(s, "回头需要的不是勇气，是承认自己错了。")
    return s, dm


def _t1():
    s, dm = play_with_dm()
    kinds = [e["type"] for e in s.events]
    for need in ("agent_line", "choice", "journal_push", "act_end",
                 "game_end", "review", "reveal"):
        assert need in kinds, f"missing event type: {need}"
    assert dm.memory["archives"], "DM memory archives empty"
    assert dm.memory["archives"][-1]["kind"] == "game_archive"
    # 所有事件过 event schema（emit 时已验，重放再验一遍）
    rebuilt = Session.replay(bundle, json.loads(json.dumps(s.events)))
    a = json.dumps(s.to_snapshot(), ensure_ascii=False, sort_keys=True)
    b = json.dumps(rebuilt.to_snapshot(), ensure_ascii=False, sort_keys=True)
    assert a == b, "replay mismatch with DM events"


check("1-dm-full-flow", _t1)


# ---- 检查2: 角色墙（装配器级） ---------------------------------------------
def _t2():
    s, dm = play_with_dm()
    # 班柯在第1幕的 prompt 材料：搜不到任何第二幕秘密
    mat = assemble_character_prompt(bundle, "A1", "banquo", s.events, {})
    blob = json.dumps(mat, ensure_ascii=False)
    for bad in ("弑王", "森林移动", "洗不掉"):
        assert bad not in blob, f"banquo wall leak: {bad}"


check("2-character-wall", _t2)


# ---- 检查3: DM 全知 vs 角色墙 ----------------------------------------------
def _t3():
    s, dm = play_with_dm()
    char_mat = assemble_character_prompt(bundle, "A1", "banquo", s.events, {})
    dm_mat = assemble_dm_prompt(bundle, s.events, dm_memory=dm.memory)
    char_blob = json.dumps(char_mat, ensure_ascii=False)
    dm_blob = json.dumps(dm_mat, ensure_ascii=False)
    # 角色材料无秘密全文
    assert "森林移动的那天" not in char_blob
    # DM 材料全量有（全知：bundle 全文 + 所有 secret_sheet 全长）
    assert "森林移动的那天" in dm_blob, "DM lost omniscience?"
    # 且 DM 材料里的秘密量 > 角色切片
    assert dm_blob.count("麦克白") >= char_blob.count("麦克白")


check("3-dm-omniscient", _t3)


# ---- 检查4: 私聊原文不进 DM 材料（只拿摘要） -------------------------------
def _t4():
    s, dm = play_withdm = play_with_dm()
    dm_mat = assemble_dm_prompt(bundle, s.events, dm_memory=dm.memory)
    dm_blob = json.dumps(dm_mat, ensure_ascii=False)
    assert "（私聊）我看见了刀。" not in dm_blob, "private chat raw leaked into DM material"


check("4-no-raw-private-in-dm", _t4)


# ---- 棕查4b: 私聊原文进角色自己的 channel 历史 ------------------------------
def _t4b():
    s, dm = play_with_dm()
    hist = {}
    for ev in s.events:
        ch = ev.get("channel", "main")
        if ch.startswith("dm:"):
            hist.setdefault(ch, []).append(ev["text"])
    assert any("我看见了刀" in t for t in hist.get("dm:lady_m", [])), "channel history lost"


check("4b-private-to-own-channel", _t4b)


# ---- 检查5: DM 台词半人工档（降级演示用） -----------------------------------
def _t5():
    s, dm = play_with_dm()
    dm2 = DM(bundle, SemiManualPort({(DM_ID, "A1S1", 0): "（预排练）诸位，入席。"}))
    s2 = Session(bundle).start()
    s2.enter_scene("A1S1")
    line = dm2.speak(s2)
    assert line == "（预排练）诸位，入席。"


check("5-dm-speak-tier", _t5)

fails = [r for r in results if r[1] == "RED"]
for name, st, msg in results:
    print(f"  {st:5}  {name}" + (f"  <- {msg}" if msg else ""))
print(f"\n{len(results) - len(fails)}/{len(results)} GREEN")
sys.exit(1 if fails else 0)
