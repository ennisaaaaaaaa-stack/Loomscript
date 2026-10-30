#!/usr/bin/env python3
"""Convert 咖啡哥 content pack -> Loomscript bundle format.

Sources (read-only):
  /home/ubuntu/loomscript_materials/LoomScript_咖啡交付包(1)/LoomScript_咖啡哥交付包/sample/

Target: <repo>/bundles/macbeth_full.json  (bundle.schema v0.1)

Mapping decisions (documented inline):
- characters: A1_roles 11人 -> 6 playable + 5 NPC。public_sheet=公开面, secret_sheet=秘密面(开局切片,
  V3已把未来信息清干净, direct copy is safe), voice=语气指纹 join。
- acts/scenes: A3_world 5 acts x 3 scenes(BG refs) -> 我们 acts[].scenes[] 用 A3 的 open/world 做幕叙事,
  scene text 用 A3.act.open + per-scene BG 描述(assets/B1_scenes.md 里有, 但 JSON 优先);
  reveals = eventsequence 的每事件 -> reveal key (scene_reveals 按 release_event 对齐 C1)。
- props: C1_clues 10张 -> props[], 每个 clue 一条 prop, reveal 事件用 clue_found。
- cards: C2 symbol_cards 3张 -> cards[]。
- endgame: endings.json 三尾声 -> endgame{endings[]}。
- assets: B1_scenes 11场景 -> assets[](scene_image), C1 配图 -> prop_icon。
  本次先不塞图片文件本体, 只建 id/uri 占位 — 成图是 D2 的活, 不阻塞 bundle。
- actor_turns (v0.2): sample/actor_turns/<role>/<cue_id>.json 52个逐轮演员包
  + server_only/line_cues.json 的 cue 元数据(event/tick/speaker/recipient/requires_fact_ids)
  + A3_world acts[].eventsequence 做 event->act 映射
  -> 顶层 actor_turns: {act_id: {role_id: [cue...]}, "_meta": {...}}。
  天然粒度是剧情事件逐轮(cue), event 前缀即幕号(a1_prophecy -> A1)。
  按 act 一级分桶: 装配侧对 act_id 切片即得数据结构级防剧透(与 secret_sheet 切片同思路)。
  pack 内部(self_profile/confirmed_knowledge/own_lines/current_goal/visible_clues/visible_prop_pages)
  原样搬运, 中文 key 是内容层, 转换器不翻译内容。
"""
import json, pathlib, sys

SRC = pathlib.Path("/home/ubuntu/loomscript_materials/LoomScript_咖啡交付包(1)/LoomScript_咖啡哥交付包/sample")
# 输出随脚本所在仓库走（脚本相对），不再写死绝对路径——worktree 里重跑不得污染主仓
OUT = pathlib.Path(__file__).resolve().parent.parent / "bundles" / "macbeth_full.json"

PLAYABLE = ["macbeth", "lady_macbeth", "banquo", "macduff", "malcolm", "ross"]

PACK_KEYS = ["self_profile", "confirmed_knowledge", "own_lines", "current_goal",
             "visible_clues", "visible_prop_pages"]  # 演员包顶层结构(合同层); 内部中文key是内容层


def build(src=SRC):
    A1 = {r["角色id"]: r for r in (json.load(open(src / "A1_roles" / f"{fid}.json")) for fid in
            ["macbeth","lady_macbeth","banquo","macduff","malcolm","ross","duncan","fleance","witch_1","witch_2","witch_3"])}
    CAST = {c["id"]: c for c in json.load(open(src / "cast.json"))}
    WORLD = json.load(open(src / "A3_world.json"))
    CLUES = json.load(open(src / "C1_clues.json"))
    PROPNOTE = json.load(open(src / "C2_prophecy_notebook.json"))
    ENDINGS = json.load(open(src / "endings.json"))

    def char_name(cid):
        return CAST[cid]["name"] if cid in CAST else cid

    # ---- characters ----
    characters = []
    for cid in PLAYABLE + [c for c in A1 if c not in PLAYABLE]:
        a1 = A1[cid]
        characters.append({
            "id": cid,
            "name": char_name(cid),
            "is_player": cid in PLAYABLE,
            "public_sheet": a1["公开面"],
            "secret_sheet": a1["秘密面"],
            "voice": " / ".join(a1["语气指纹"]),
        })

    # ---- acts & scenes ----
    # A3 acts[].scenes = ["BG01", ...] (asset refs). Scene text: use B1 mapping if available,
    # else fall back to act.open (honest placeholder, marked in adaptation_note).
    acts = []
    scene_asset_map = {}
    try:
        b1 = json.load(open(src / "assets" / "B1_scenes.json"))
        for s in b1:
            scene_asset_map[s.get("id")] = s
    except FileNotFoundError:
        pass  # B1 only in md; assets stay placeholder

    for act in WORLD["acts"]:
        scenes = []
        for idx, bg_ref in enumerate(act.get("scenes", []), 1):
            aid = act["id"]
            sid = f"{aid}S{idx}"
            info = scene_asset_map.get(bg_ref)
            text = (info.get("description") or info.get("text") or act["open"]) if info else act["open"]
            # reveals: align clue release events to scene order within the act (C1.release_event)
            act_events = act.get("eventsequence", [])
            reveals = []
            cl_ids_in_act = [c for c in CLUES if c["act_id"] == aid]
            for c in cl_ids_in_act:
                if c.get("release_event") in act_events:
                    reveals.append(c["id"])
            scenes.append({
                "scene_id": sid,
                "text": text,
                "image_id": bg_ref,
                "reveals": reveals,
            })
        # endgame lives top-level; ensure every act has required world text
        acts.append({
            "act_id": act["id"],
            "title": act["title"],
            "world_info": act["world"] or act.get("change", "") or f'{act["title"]}幕',
            "scenes": scenes,
        })

    # ---- props (clue cards) ----
    ACT_OF = {"A1": ["CL01","CL02"], "A2": ["CL03","CL04"], "A3": ["CL05","CL06"],
              "A4": ["CL07","CL08"], "A5": ["CL09","CL10"]}
    props = []
    for c in CLUES:
        props.append({
            "id": c["id"],
            "name": c["title"],
            "act_introduced": next((a for a, ids in ACT_OF.items() if c["id"] in ids), c.get("act_id", "A1")),
            "description": c["content"],
            "redline": c.get("redline", ""),
            "visibility": c.get("visibility", []),
            "release_event": c.get("release_event", ""),
        })

    # ---- cards (symbol cards from C2) ----
    cards = []
    for sc in PROPNOTE.get("symbol_cards", []):
        cards.append({
            "id": sc.get("id", f"CARD{len(cards)+1:02d}"),
            "name": sc.get("name", sc.get("title", "")),
            "symbol": sc.get("symbol", sc.get("meaning", "")),
        })

    # ---- endgame (schema: conditions[{id,description}] + review_prompt) ----
    endgame = {
        "conditions": [
            {"id": e["id"], "description": f'{e["title"]} :: {json.dumps(e.get("condition", {}), ensure_ascii=False)[:160]}'}
            for e in ENDINGS.get("endings", [])
        ],
        "review_prompt": "回头看这一路：哪一步是你自己的选择，哪一步是预言替你走的？",
        "priority": ENDINGS.get("priority", []),
        "endings": [
            {"id": e["id"], "title": e["title"], "condition": e.get("condition", {}), "text": e.get("text", "")}
            for e in ENDINGS.get("endings", [])
        ],
        "rules": ENDINGS.get("rules", ""),
    }

    # ---- assets (placeholder ids; D2 fills uris after 即梦 generation) ----
    assets = []
    for act in WORLD["acts"]:
        for bg_ref in act.get("scenes", []):
            assets.append({"id": bg_ref, "kind": "scene_image", "uri": f"assets/bg/{bg_ref}.png", "status": "pending"})
    for c in CLUES:
        assets.append({"id": f"ICON_{c['id']}", "kind": "prop_icon", "uri": f"assets/icons/{c['id']}.png", "status": "pending"})

    # ---- deaths (canon-locked, data-driven; wt/death) ----
    # 依据（素材包，只读）：
    #   1. A3_world.json canon_locked[1]: "班柯于A3遇害，弗里恩斯逃走"
    #   2. A3_world.json acts[A3].eventsequence: [a3_coronation, a3_ambush, a3_report,
    #      a3_banquet, a3_close] —— a3_ambush(父子遇袭)为第2事件，对应本幕第2场景 A3S2
    #      (BG refs BG02/BG05/BG11: 宫廷加冕/夜路伏杀/宴厅)
    #   3. location_matrix.json A3.banquo: "福累斯夜路→死亡"; A4/A5.banquo: "死亡"
    # 素材无专门 deaths 字段，故在此显式声明（触发时点=进入 A3S2，确定性、可重放）。
    deaths = [
        {
            "id": "death_banquo_a3",
            "character_id": "banquo",
            "act_id": "A3",
            "scene_id": "A3S2",
            "description": "夜路遇袭：班柯倒在福累斯城外的路上，弗里恩斯趁乱逃走。空席从此有了名字。",
            "observer_brief": "你是班柯——此刻起你以魂魄之眼看戏：见证宴席上的空位如何撬动王座，"
                              "只观察，不再行动；台上人看不见你，你看得见他们。",
        },
    ]
    # 声明与素材 canon 对照：canon_locked 明言班柯于A3遇害才允许生成（防素材改版后静默漂移）
    DEATH_EVIDENCE = "班柯于A3遇害"
    canon_blob = json.dumps(WORLD.get("canon_locked", []), ensure_ascii=False)
    assert DEATH_EVIDENCE in canon_blob, "canon_locked 不再含『班柯于A3遇害』——deaths 声明需人工复核"

    # deaths 挂进对应场景（进入场景即触发；acts 已在上面建好，此处回填）
    DEATH_BY_SCENE = {}
    for d in deaths:
        DEATH_BY_SCENE.setdefault(d["scene_id"], []).append(d["id"])
    for act in acts:
        for sc in act["scenes"]:
            if sc["scene_id"] in DEATH_BY_SCENE:
                sc["deaths"] = DEATH_BY_SCENE[sc["scene_id"]]

    # ---- actor_turns (v0.2): 逐轮演员包, 按 act 分桶 ----
    actor_turns = build_actor_turns(src, WORLD)

    bundle = {
        "id": "macbeth_full_v1",
        "title": "麦克白 · 全五幕",
        "version": "1.1.0",
        "language": "zh",
        "source_pack": "LoomScript_咖啡交付包(1) content_revision=" + str(WORLD.get("content_revision", "?")),
        "adaptation_note": WORLD.get("adaptation_note", ""),
        "characters": characters,
        "acts": acts,
        "deaths": deaths,
        "props": props,
        "cards": cards,
        "endgame": endgame,
        "assets": assets,
        "actor_turns": actor_turns,
    }
    return bundle


def build_actor_turns(src, world):
    """逐轮演员包 -> {act_id: {role_id: [cue...]}}。

    - cue 元数据(event/tick/speaker/recipient/requires_fact_ids)来自 server_only/line_cues.json
    - event -> act 映射来自 A3_world acts[].eventsequence(event 前缀只是校验, 不作映射依据)
    - pack 本体来自 actor_turns/<role>/<cue_id>.json, 顶层结构按 PACK_KEYS 校验
    - 每 act 内 cue 按 tick 升序
    """
    line_cues = json.load(open(src / "server_only" / "line_cues.json"))
    cue_meta = {c["id"]: c for c in line_cues}

    event2act = {}
    for act in world["acts"]:
        for ev in act.get("eventsequence", []):
            assert ev not in event2act, f"event {ev} in multiple acts"
            event2act[ev] = act["id"]

    actor_turns = {}
    at_dir = src / "actor_turns"
    n_packs = 0
    for role_dir in sorted(at_dir.iterdir()):
        if not role_dir.is_dir():
            continue
        role = role_dir.name
        for cue_file in sorted(role_dir.glob("*.json")):
            cue_id = cue_file.stem
            meta = cue_meta[cue_id]  # KeyError = 素材两处清单失配, 转换即报
            assert meta["speaker_role_id"] == role, f"{cue_id}: speaker mismatch"
            act_id = event2act[meta["event"]]  # KeyError = event 不在世界事件序列里
            pack = json.load(open(cue_file))
            assert set(PACK_KEYS) <= set(pack), f"{cue_id}: pack 结构缺字段 {set(PACK_KEYS) - set(pack)}"
            cue = {
                "cue_id": cue_id,
                "event": meta["event"],
                "tick": meta["tick"],
                "status": pack.get("status", "active"),
                "recipient_role_id": meta.get("recipient_role_id"),
                "requires_fact_ids": meta.get("requires_fact_ids", []),
                "pack": {k: pack[k] for k in PACK_KEYS},
            }
            actor_turns.setdefault(act_id, {}).setdefault(role, []).append(cue)
            n_packs += 1

    # 每 act 内按 tick 排序（派发顺序）
    for act_roles in actor_turns.values():
        for cues in act_roles.values():
            cues.sort(key=lambda c: c["tick"])

    # _meta: 审计用（cues 总数/来源），不参与装配
    actor_turns["_meta"] = {
        "source": "sample/actor_turns + server_only/line_cues.json",
        "cue_count": n_packs,
        "note": "投放规则V3: cue dispatch 须引擎选轮+送达回执, bundle 只携带静态包, 装配按当前幕切片",
    }
    return actor_turns


def main():
    bundle = build()
    OUT.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"bundle written: {OUT} ({OUT.stat().st_size} bytes)")
    at = bundle["actor_turns"]
    n_cues = sum(len(cues) for aid, roles in at.items() if aid != "_meta" for cues in roles.values())
    n_roles = len({r for aid, roles in at.items() if aid != "_meta" for r in roles})
    print(f"characters={len(bundle['characters'])} acts={len(bundle['acts'])} "
          f"scenes={sum(len(a['scenes']) for a in bundle['acts'])} "
          f"props={len(bundle['props'])} cards={len(bundle['cards'])} "
          f"endings={len(bundle['endgame']['endings'])} assets={len(bundle['assets'])} deaths={len(bundle['deaths'])} "
          f"actor_turns: cues={n_cues} roles={n_roles} acts={sorted(a for a in at if a != '_meta')}")

    # self-check: id uniqueness
    ids = [c['id'] for c in bundle['characters']] + [s['scene_id'] for a in bundle['acts'] for s in a['scenes']]
    assert len(ids) == len(set(ids)), "id collision"
    print("self-check: id uniqueness OK")


if __name__ == "__main__":
    main()
