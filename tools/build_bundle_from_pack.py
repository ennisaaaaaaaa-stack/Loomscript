#!/usr/bin/env python3
"""Convert 咖啡哥 content pack -> Loomscript bundle format.

Sources (read-only):
  /home/ubuntu/loomscript_materials/LoomScript_咖啡交付包(1)/LoomScript_咖啡哥交付包/sample/

Target: /home/ubuntu/loomscript/bundles/macbeth_full.json  (bundle.schema v0.1)

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
"""
import json, pathlib, sys

SRC = pathlib.Path("/home/ubuntu/loomscript_materials/LoomScript_咖啡交付包(1)/LoomScript_咖啡哥交付包/sample")
OUT = pathlib.Path("/home/ubuntu/loomscript/bundles/macbeth_full.json")

A1 = {r["角色id"]: r for r in (json.load(open(SRC / "A1_roles" / f"{fid}.json")) for fid in
        ["macbeth","lady_macbeth","banquo","macduff","malcolm","ross","duncan","fleance","witch_1","witch_2","witch_3"])}
CAST = {c["id"]: c for c in json.load(open(SRC / "cast.json"))}
WORLD = json.load(open(SRC / "A3_world.json"))
CLUES = json.load(open(SRC / "C1_clues.json"))
PROPNOTE = json.load(open(SRC / "C2_prophecy_notebook.json"))
ENDINGS = json.load(open(SRC / "endings.json"))

PLAYABLE = ["macbeth","lady_macbeth","banquo","macduff","malcolm","ross"]

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
    b1 = json.load(open(SRC / "assets" / "B1_scenes.json"))
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
    acts.append({
        "act_id": act["id"],
        "title": act["title"],
        "world_info": act["world"],
        "scenes": scenes,
    })

# ---- props (clue cards) ----
props = []
for c in CLUES:
    props.append({
        "id": c["id"],
        "name": c["title"],
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

# ---- endgame ----
endgame = {
    "rule": ENDINGS.get("rules", ""),
    "priority": ENDINGS.get("priority", []),
    "endings": [
        {
            "id": e["id"],
            "title": e["title"],
            "condition": e.get("condition", {}),
            "text": e.get("text", ""),
        } for e in ENDINGS.get("endings", [])
    ],
}

# ---- assets (placeholder ids; D2 fills uris after 即梦 generation) ----
assets = []
for act in WORLD["acts"]:
    for bg_ref in act.get("scenes", []):
        assets.append({"id": bg_ref, "kind": "scene_image", "uri": f"assets/bg/{bg_ref}.png", "status": "pending"})
for c in CLUES:
    assets.append({"id": f"ICON_{c['id']}", "kind": "prop_icon", "uri": f"assets/icons/{c['id']}.png", "status": "pending"})

bundle = {
    "id": "macbeth_full_v1",
    "title": "麦克白 · 全五幕",
    "version": "1.0.0",
    "language": "zh",
    "source_pack": "LoomScript_咖啡交付包(1) content_revision=" + str(WORLD.get("content_revision", "?")),
    "adaptation_note": WORLD.get("adaptation_note", ""),
    "characters": characters,
    "acts": acts,
    "props": props,
    "cards": cards,
    "endgame": endgame,
    "assets": assets,
}

OUT.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"bundle written: {OUT} ({OUT.stat().st_size} bytes)")
print(f"characters={len(characters)} acts={len(acts)} scenes={sum(len(a['scenes']) for a in acts)} "
      f"props={len(props)} cards={len(cards)} endings={len(endgame['endings'])} assets={len(assets)}")

# self-check: id uniqueness
ids = [c['id'] for c in characters] + [s['scene_id'] for a in acts for s in a['scenes']]
assert len(ids) == len(set(ids)), "id collision"
print("self-check: id uniqueness OK")
