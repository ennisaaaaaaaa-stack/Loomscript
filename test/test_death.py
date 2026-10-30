"""death 事件+状态位测试 —— wt/death 分支交付验收。

检查1: 死亡按定义表确定性触发（进 A3S2 即杀，无随机）
检查2: 状态位翻转（alive=False, on_stage=False）+ snapshot 暴露
检查3: 死后 prompt 转观演形态（engine.agent_view + dm.assemble 两面）
检查4: 死讯防剧透——A1/A2 幕的 banquo 材料里搜不到自己的死讯
检查5: 死者不能在 main 说话（ContractError），私聊通道不拦
检查6: replay 一致——含 death 的事件流重放逐字节一致
检查7: 幂等——重复进死亡场景不重复杀
检查8: 全量回归：engine 7项 + dm 6项不破
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from engine import Bundle, Session, ContractError  # noqa: E402
from dm import assemble_character_prompt  # noqa: E402

bundle = Bundle.load(ROOT / "bundles" / "macbeth_full.json")
results = []


def check(name, fn):
    try:
        fn()
        results.append((name, "GREEN", ""))
    except Exception as e:
        results.append((name, "RED", repr(e)[:150]))


def play_to_a3():
    """A1→A2→A3S2（死亡场景）的完整推进，返回 (session, death_events)。"""
    s = Session(bundle).start()
    deaths = []
    plan = [("A1", ["A1S1", "A1S2", "A1S3"]), ("A2", ["A2S1", "A2S2"]),
            ("A3", ["A3S1", "A3S2"])]
    for act, scenes in plan:
        for sc in scenes:
            s.enter_scene(sc)
            s.line("macbeth", "推进", channel="main")
            for ev in s.events:
                if ev["type"] == "death":
                    deaths.append(ev)
        if act != "A3":
            s.next_act()
    return s, deaths


# ---- 检查1: 确定性触发 --------------------------------------------------
def t1_deterministic():
    for _ in range(3):
        s, deaths = play_to_a3()
        assert len(deaths) == 1, f"期望1次死亡, 得到{len(deaths)}"
        d = deaths[0]
        assert d["death_id"] == "death_banquo_a3"
        assert d["character_id"] == "banquo"
        assert d["scene_id"] == "A3S2"
        assert s.state["character_states"]["banquo"]["alive"] is False


# ---- 检查2: 状态位+snapshot ---------------------------------------------
def t2_snapshot():
    s, _ = play_to_a3()
    snap = s.to_snapshot()
    assert snap["character_states"]["banquo"]["alive"] is False
    assert snap["character_states"]["banquo"]["on_stage"] is False
    assert snap["character_states"]["macbeth"]["alive"] is True


# ---- 检3: 死后观演视角（engine 侧） ---------------------------------------
def t3_observer_engine():
    s, _ = play_to_a3()
    view = s.agent_view("banquo")
    assert view.get("observer") is True
    assert "魂魄之眼" in view.get("observer_brief", "") or \
           "看戏" in view.get("observer_brief", "")


# ---- 检查3b: 死后观演材料（DM 装配器侧） -----------------------------------
def t3b_observer_dm_assembly():
    s, _ = play_to_a3()
    mat = assemble_character_prompt(bundle, "A3", "banquo", s.events, {})
    assert mat["mode"] == "observer"
    assert mat["role"] == "observer_agent"
    assert "看戏" in mat["law"]


# ---- 检查4: 死讯防剧透 ----------------------------------------------------
def t4_no_spoil():
    # A1 幕的班柯材料（死亡远未发生）不能含死讯
    s = Session(bundle).start()
    mat = assemble_character_prompt(bundle, "A1", "banquo", s.events, {})
    blob = json.dumps(mat, ensure_ascii=False)
    assert "死亡" not in blob and "夜路遇袭" not in blob and "倒下" not in blob


# ---- 棋查5: 死者不能 main 说话 ---------------------------------------------
def t5_dead_mute():
    s, _ = play_to_a3()
    try:
        s.line("banquo", "我还活着！", channel="main")
        raise AssertionError("死者 main 发言未被拦")
    except ContractError:
        pass
    # 私聊通道不拦（观演者仍可与 DM 交流）
    s.line("banquo", "（魂魄低语）", channel="dm:banquo")


# ---- 检查6: replay 一致 ---------------------------------------------------
def t6_replay():
    s, _ = play_to_a3()
    r = Session.replay(bundle, json.loads(json.dumps(s.events)))
    assert len(r.events) == len(s.events)
    for a, b in zip(s.events, r.events):
        assert a == b, f"replay 不一致 @seq{a['seq']}"
    assert r.state["character_states"]["banquo"]["alive"] is False


# ---- 检查7: 幂等 ---------------------------------------------------------
def t7_idempotent():
    s, _ = play_to_a3()
    n_before = sum(1 for e in s.events if e["type"] == "death")
    s.enter_scene("A3S2")  # 重复进入死亡场景
    n_after = sum(1 for e in s.events if e["type"] == "death")
    assert n_before == n_after == 1, f"重复杀: {n_before}->{n_after}"


# ---- 检查8: 全量回归 ------------------------------------------------------
def t8_regression():
    import subprocess
    for t in ("test/test_engine.py", "test/test_dm.py"):
        r = subprocess.run([sys.executable, str(ROOT / t)],
                           capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, f"{t} 回归失败:\n{r.stdout[-500:]}"


check("1-deterministic-death", t1_deterministic)
check("2-snapshot-state", t2_snapshot)
check("3-observer-view", t3_observer_engine)
check("3b-observer-dm-assembly", t3b_observer_dm_assembly)
check("4-no-spoil-before-death", t4_no_spoil)
check("5-dead-cannot-speak-main", t5_dead_mute)
check("6-replay-identical", t6_replay)
check("7-idempotent", t7_idempotent)
check("8-regression", t8_regression)

print()
for n, st, msg in results:
    print(f"{st:6s} {n} {msg}")
sys.exit(0 if all(st == "GREEN" for _, st, _ in results) else 1)
