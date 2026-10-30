"""Loomscript 引擎六项检查 —— freeze 夜验收的正式化版本。
跑法: python3 test/test_engine.py   (cwd=repo root 或任意，路径自动解析)
六项: load / 2-acts / snapshot / anti-spoil-view / replay-identical / guard
附加: 新合同字段(channel/clue_found/journal_push/reveal_texts)冒烟
"""
import json, pathlib, sys, copy

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from engine import Bundle, Session, ContractError  # noqa: E402

bundle = Bundle.load(ROOT / "bundles" / "macbeth_mini.json")
results = []


def check(name, fn):
    try:
        fn()
        results.append((name, "GREEN", ""))
    except Exception as e:
        results.append((name, "RED", str(e)[:120]))


# 1. load: 合同校验通过
check("load", lambda: Bundle.load(ROOT / "bundles" / "macbeth_mini.json"))

# 2. 两幕完整对局跑通
def _full_game():
    s = Session(bundle).start()
    for act in bundle.data["acts"]:
        aid = act["act_id"]
        for sc in act["scenes"]:
            s.enter_scene(sc["scene_id"])
            for c in bundle.data["characters"]:
                if not c.get("is_player"):
                    s.line(c["id"], f"[{c['name']}] 台词占位")
            s.line("macbeth", "我按命运的推手走。")
            s.fire_reveals(sc["scene_id"])
        s.next_act()
    return s


full = _full_game()
check("2-acts", lambda: full.state["act_id"] == bundle.data["acts"][-1]["act_id"])


# 3. snapshot 合法
check("snapshot", lambda: full.to_snapshot())


# 4. 防剧透: 第一幕时班柯的视野里没有弑王秘密
def _anti_spoil():
    s = Session(bundle).start()
    s.enter_scene(bundle.data["acts"][0]["scenes"][0]["scene_id"])
    view = json.dumps(s.agent_view("banquo"), ensure_ascii=False)
    assert "弑王" not in view and "森林移动" not in view, f"班柯视野泄漏: {view[:200]}"


check("anti-spoil-view", _anti_spoil)


# 5. replay 逐字节一致
def _replay():
    s2 = _full_game()
    rebuilt = Session.replay(bundle, copy.deepcopy(s2.events))
    a = json.dumps(s2.to_snapshot(), ensure_ascii=False, sort_keys=True)
    b = json.dumps(rebuilt.to_snapshot(), ensure_ascii=False, sort_keys=True)
    assert a == b, "snapshot mismatch after replay"


check("replay-identical", _replay)


# 6. guard: 未开局动状态=合同违约
def _guard():
    s = Session(bundle)
    try:
        s.enter_scene("any")
        raise AssertionError("should have raised")
    except ContractError:
        pass


check("guard", _guard)


# 7. 新合同字段冒烟: channel/clue_found/journal_push/reveal_texts 走引擎
def _new_fields():
    s = Session(bundle).start()
    s.enter_scene(bundle.data["acts"][0]["scenes"][0]["scene_id"])
    s.line("macbeth", "（低声）你们看见了什么？", channel="main")
    s.emit(type="agent_line", character_id="lady_m",
           channel="dm:lady_m", text="记住你今晚的诺言。",
           act_id=s._s()["act_id"], scene_id=s._s()["scene_id"])
    s.emit(type="clue_found", act_id=s._s()["act_id"],
           scene_id=s._s()["scene_id"], clue_id="clue_dagger_hilt",
           text="带血的刀柄，纹章不属于麦克白家。")
    s.emit(type="journal_push", act_id=s._s()["act_id"],
           journal_text="DM手账：预言已种下，等它发芽。")
    s.emit(type="reveal", act_id=s._s()["act_id"], scene_id=s._s()["scene_id"],
           reveal_keys=["prophecy_fulfilled"],
           reveal_texts=["女巫的第三个预言，以无人预料的方式应验了。"])
    s.emit(type="error", act_id=s._s()["act_id"],
           text="DM嗓子哑了，剧本自己往下走", error_code="dm_degraded")
    snap = s.to_snapshot()
    assert snap["seq"] >= 7


check("new-fields-smoke", _new_fields)

# ---- 汇报 -----------------------------------------------------------
fails = [r for r in results if r[1] == "RED"]
for name, st, msg in results:
    print(f"  {st:5}  {name}" + (f"  <- {msg}" if msg else ""))
print(f"\n{len(results) - len(fails)}/{len(results)} GREEN")
sys.exit(1 if fails else 0)
