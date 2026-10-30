#!/usr/bin/env python3
"""把咖啡哥 C1 搜证卡转成 clues 总表进 macbeth_full。

C1 -> clues 映射：clue_id=C1.id, title=C1.title, text=C1.content,
visible_at=C1.act_id, must_ready_by=final（数据未标死线，先全宽）,
act_scoped=False, payload 带 redline/visibility/type 供 DM/前端取用。
幂等：clues 已含同 id 则跳过。
"""
import json
import pathlib

ROOT = pathlib.Path("/home/ubuntu/loomscript")
MAT = pathlib.Path("/home/ubuntu/loomscript_materials/LoomScript_咖啡交付包(1)/LoomScript_咖啡哥交付包")

pack = json.loads((MAT / "sample" / "C1_clues.json").read_text(encoding="utf-8"))
bp = ROOT / "bundles" / "macbeth_full.json"
data = json.loads(bp.read_text(encoding="utf-8"))

have = {c["clue_id"] for c in data.get("clues", [])}
added = 0
for c in pack:
    if c["id"] in have:
        continue
    data.setdefault("clues", []).append({
        "clue_id": c["id"],
        "title": c["title"],
        "text": c["content"],
        "visible_at": c["act_id"],
        "must_ready_by": "final",
        "act_scoped": False,
        "payload": {
            "payload_type": c.get("type", ""),  # 避让 event 的 type 字段名
            "redline": c.get("redline", ""),
            "visibility": c.get("visibility", []),
            "release_event": c.get("release_event", ""),
            "source_note": c.get("source_note", ""),
        },
    })
    added += 1

# 结局->CG 映射缺口：END01->CG09 / END02->CG10 / END03->CG? 需她/咖啡哥定。
# 引擎机制已支持（endings[i].cg_id），本脚本不动这块——数据拍板归内容侧。

from sys import path as sp
sp.insert(0, str(ROOT / "src"))
from engine import Bundle  # noqa: E402

Bundle(data)  # 合同校验：转完必须合法
bp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
              encoding="utf-8")
print(f"clues added: {added}; total clues: {len(data['clues'])}")
