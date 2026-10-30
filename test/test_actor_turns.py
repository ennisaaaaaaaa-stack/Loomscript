"""actor_turns 逐轮演员包全链路测试 —— wt/actor 分支交付验收。

检查1: 转换器产出含 actor 数据（build() 直跑素材，52 cue / 11 角色 / 5 幕全进 bundle）
检查2: 产出的 bundle 过 bundle.schema（含新增 actor_turns 合同段）
检查3: prompt 里当前幕的演员包在场（cue 与内容都在）
检查4: NPC（witch_1 等）同样装配
检查5: 防剧透硬线——第 N 幕 prompt 绝不出现第 N+1 幕及以后的演员包
       （cue_id 级 + 内容级双验：未来独有的台词文本不得出现在当前材料里）
检查6: DM 仍全知（actor_turns 全量随 bundle.data 进 DM 材料）
检查7: 无 actor_turns 的旧 bundle（mini）不炸，cues 为空——向后兼容
检查8: 演员包是静态数据，不产生事件流变化——全量 bundle 上跑一局，replay 恒等
"""
import json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
from engine import Bundle, Session, validate  # noqa: E402
from dm import assemble_character_prompt, assemble_dm_prompt  # noqa: E402
from build_bundle_from_pack import build  # noqa: E402

results = []


def check(name, fn):
    try:
        fn()
        results.append((name, "GREEN", ""))
    except Exception as e:
        results.append((name, "RED", repr(e)[:150]))


FULL = ROOT / "bundles" / "macbeth_full.json"


# ---- 检查1: 转换器产出含 actor 数据 ----------------------------------------
def _t1():
    b = build()  # 从素材直跑，不信任既有产物
    at = b["actor_turns"]
    acts = {a for a in at if a != "_meta"}
    assert acts == {"A1", "A2", "A3", "A4", "A5"}, f"act buckets wrong: {acts}"
    n_cues = sum(len(c) for roles in (at[a] for a in acts) for c in roles.values())
    n_roles = {r for a in acts for r in at[a]}
    assert n_cues == 52, f"cue count {n_cues} != 52"
    assert len(n_roles) == 11, f"role count {len(n_roles)} != 11"
    # 与磁盘产物一致（转换器可重跑、无手修）
    on_disk = json.load(open(FULL, encoding="utf-8"))
    assert on_disk["actor_turns"] == at, "disk bundle diverged from build()"
    # pack 结构完整 + U/CUE 两类都有
    assert any(c["cue_id"].startswith("U") for a in acts for cs in at[a].values() for c in cs)
    assert any(c["cue_id"].startswith("CUE") for a in acts for cs in at[a].values() for c in cs)
    for a in acts:
        for cs in at[a].values():
            for c in cs:
                assert c["pack"]["own_lines"], f'{c["cue_id"]} no own_lines'
                assert c["pack"]["current_goal"]
    # 每 act 内按 tick 升序
    for a in acts:
        for cs in at[a].values():
            ticks = [c["tick"] for c in cs]
            assert ticks == sorted(ticks), f"{a} ticks not sorted"


check("1-converter-actor-data", _t1)


# ---- 检查2: 过 schema（Bundle.load 即 validate，再显式验一遍） --------------
def _t2():
    b = Bundle.load(FULL)
    validate(b.data, "bundle")  # 显式；含 actor_turns 新合同段
    at = b.data["actor_turns"]
    assert at["_meta"]["cue_count"] == 52
    # schema 必填项抽查：pack 六字段在合同里 required
    c = at["A1"]["macbeth"][0]
    for k in ("self_profile", "confirmed_knowledge", "own_lines",
              "current_goal", "visible_clues", "visible_prop_pages"):
        assert k in c["pack"], f"pack missing {k}"


check("2-schema-valid", _t2)


# ---- 公共: 全量 bundle 上一局带事件流的 session -----------------------------
def played_session():
    b = Bundle.load(FULL)
    s = Session(b).start()
    s.enter_scene("A1S1")
    s.line("macbeth", "把你们刚才的意思说清楚。")
    s.line("witch_1", "葛莱密斯的爵士，停一停。")
    return s


# ---- 检查3: 当前幕演员包在场 ------------------------------------------------
def _t3():
    s = played_session()
    b = s.bundle
    mat = assemble_character_prompt(b, "A1", "macbeth", s.events, {})
    assert mat["actor_turns"]["act_id"] == "A1"
    a1_cues = b.data["actor_turns"]["A1"]["macbeth"]
    assert len(mat["actor_turns"]["cues"]) == len(a1_cues) > 0
    blob = json.dumps(mat, ensure_ascii=False)
    for c in a1_cues:
        assert c["cue_id"] in blob, f'{c["cue_id"]} missing from A1 material'
    # 内容级：A1 某条获准台词确实进了材料
    some_line = a1_cues[0]["pack"]["own_lines"][0]["text"]
    assert some_line in blob, "current-act own_line not in material"


check("3-current-act-in-prompt", _t3)


# ---- 检查4: NPC 也有演员包 ---------------------------------------------------
def _t4():
    s = played_session()
    b = s.bundle
    for npc in ("witch_1", "witch_2", "duncan"):
        mat = assemble_character_prompt(b, "A1", npc, s.events, {})
        cues = mat["actor_turns"]["cues"]
        assert cues, f"NPC {npc} got empty cues in A1"
        blob = json.dumps(mat, ensure_ascii=False)
        assert cues[0]["cue_id"] in blob


check("4-npc-assembled", _t4)


# ---- 检查5: 防剧透硬线（cue_id 级 + 内容级） --------------------------------
def _t5():
    s = played_session()
    b = s.bundle
    at = b.data["actor_turns"]
    act_ids = [a["act_id"] for a in b.data["acts"]]
    all_roles = sorted(c["id"] for c in b.data["characters"])
    for i, act in enumerate(act_ids):
        future_acts = act_ids[i + 1:]
        future_cues = [c for fa in future_acts for cs in at.get(fa, {}).values() for c in cs]
        # 未来独有内容：只出现在未来幕、不出现在 <= 当前幕 的台词文本（跨幕重复的句子不冤枉人）
        past_lines = {l["text"]
                      for pa in act_ids[: i + 1] for cs in at.get(pa, {}).values()
                      for c in cs for l in c["pack"]["own_lines"]}
        future_only_lines = sorted({l["text"] for c in future_cues for l in c["pack"]["own_lines"]
                                    if l["text"] not in past_lines})
        for role in all_roles:
            mat = assemble_character_prompt(b, act, role, s.events, {})
            blob = json.dumps(mat, ensure_ascii=False)
            for c in future_cues:
                assert c["cue_id"] not in blob, \
                    f"{role}@{act} leaked future cue {c['cue_id']} ({c['event']})"
            for line in future_only_lines:
                assert line not in blob, \
                    f"{role}@{act} leaked future line: {line[:30]}"
    # 反向 sanity：A5（末幕）材料里 A5 自己的 cue 在
    mat = assemble_character_prompt(b, "A5", "macbeth", s.events, {})
    blob = json.dumps(mat, ensure_ascii=False)
    assert at["A5"]["macbeth"][0]["cue_id"] in blob


check("5-no-future-act-spoilers", _t5)


# ---- 检查6: DM 仍全知（全量 actor_turns 随 bundle 进 DM 材料） ----------------
def _t6():
    s = played_session()
    dm_mat = assemble_dm_prompt(s.bundle, s.events)
    dm_blob = json.dumps(dm_mat, ensure_ascii=False)
    assert '"_meta"' in dm_blob and '"cue_count": 52' in dm_blob
    # 未来幕的 cue 在 DM 材料在场（全知），对照检查5的角色墙
    assert "U0" in dm_blob and "CUE_WH" in dm_blob


check("6-dm-omniscient-actor-turns", _t6)


# ---- 检查7: 无 actor_turns 的旧 bundle 向后兼容 ------------------------------
def _t7():
    b = Bundle.load(ROOT / "bundles" / "macbeth_mini.json")
    validate(b.data, "bundle")
    s = Session(b).start()
    s.enter_scene("A1S1")
    mat = assemble_character_prompt(b, "A1", "macbeth", s.events, {})
    assert mat["actor_turns"]["cues"] == [], "mini bundle should yield empty cues, not crash"


check("7-mini-backward-compat", _t7)


# ---- 检查8: 演员包静态下发，事件流不变、replay 恒等 ---------------------------
def _t8():
    s = played_session()
    for cid in ("macbeth", "witch_1", "banquo"):
        assemble_character_prompt(s.bundle, "A1", cid, s.events, {})  # 装配不 emit
    n_before = len(s.events)
    assemble_dm_prompt(s.bundle, s.events)
    assert len(s.events) == n_before, "assembly must not emit events"
    # 推到 A2 再验一次切片变化 + replay 恒等
    s.fire_reveals("A1S1")
    s.next_act()
    assert s._s()["act_id"] == "A2"
    mat = assemble_character_prompt(s.bundle, "A2", "macbeth", s.events, {})
    assert mat["actor_turns"]["act_id"] == "A2"
    assert len(mat["actor_turns"]["cues"]) == len(s.bundle.data["actor_turns"]["A2"]["macbeth"]) > 0
    rebuilt = Session.replay(s.bundle, json.loads(json.dumps(s.events)))
    a = json.dumps(s.to_snapshot(), ensure_ascii=False, sort_keys=True)
    d = json.dumps(rebuilt.to_snapshot(), ensure_ascii=False, sort_keys=True)
    assert a == d, "replay mismatch"


check("8-static-no-event-flow-change", _t8)


fails = [r for r in results if r[1] == "RED"]
for name, st, msg in results:
    print(f"  {st:5}  {name}" + (f"  <- {msg}" if msg else ""))
print(f"\n{len(results) - len(fails)}/{len(results)} GREEN")
sys.exit(1 if fails else 0)
