#!/usr/bin/env python3
"""L3 降级（B案）：DM 台词预生成烤进剧本包——dm_lines 合同 + DM 层取用。

B案拍板（10/30 晚）：降级第三层=纯合同+预生成台词。机制先行，咖啡哥的
真剧本到了把台词数据填进 bundle 即可，引擎不改。
验收点：dm_lines 存在时 DM 结构性台词全部从剧本包取（确定性、零 LLM）；
dm_lines 缺省时回落引擎模板（旧 bundle 向后兼容，既有套件覆盖）。
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from engine import Bundle, Session, SemiManualPort  # noqa: E402
from dm import DM  # noqa: E402

results = []


def check(name, ok, note=""):
    results.append((name, bool(ok)))
    print(("GREEN " if ok else "RED   ") + name + (f"  | {note}" if note else ""))


data = json.loads((ROOT / "bundles" / "macbeth_mini.json").read_text(encoding="utf-8"))
data["dm_lines"] = {
    "opening": "[预生成]开场白_MARKER_OPEN",
    "propose_play": "[预生成]玩法提议_MARKER_PLAY",
    "act_report": {"A2": "[预生成]第二幕报幕_MARKER_A2"},
    "review": "[预生成]复盘引导_MARKER_REV",
    "fallback": "[预生成]兜底台词_MARKER_FB",
}

b = Bundle(data)  # 合同必须接受 dm_lines（无 dm_lines 的兼容面走既有套件）
s = Session(b, tier="semi_manual")
s.start()
dm = DM(b, SemiManualPort({}))

ev = dm.opening(s)
check("1-opening-from-bundle", "MARKER_OPEN" in ev["text"], ev["text"][:40])

ev = dm.propose_play(s)
check("2-propose_play-from-bundle", "MARKER_PLAY" in ev["text"], ev["text"][:40])

acts = [a["act_id"] for a in data["acts"]]
if "A2" in acts and s._s()["act_id"] == "A1":
    dm.advance_act(s)
    reports = [e for e in s.events
               if e["type"] == "agent_line" and e.get("act_id") == "A2"]
    check("3-act_report-from-bundle",
          any("MARKER_A2" in e["text"] for e in reports),
          reports[-1]["text"][:40] if reports else "no report line")
else:
    check("3-act_report-from-bundle", False, f"acts={acts} unexpected")

ev = dm.review(s, "")  # 空复盘文本 -> 预生成复盘词
check("4-review-from-bundle", "MARKER_REV" in (ev["review_text"] or ""),
      (ev["review_text"] or "")[:40])

line = dm.speak(s)  # semi_manual 档自由交流兜底
check("5-speak-fallback", "MARKER_FB" in line, line[:40])

# 向后兼容：无 dm_lines 的旧 bundle 走引擎模板
b2 = Bundle(json.loads((ROOT / "bundles" / "macbeth_mini.json").read_text(encoding="utf-8")))
s2 = Session(b2, tier="semi_manual")
s2.start()
dm2 = DM(b2, SemiManualPort({}))
ev2 = dm2.opening(s2)
check("6-template-fallback", "欢迎来到" in ev2["text"], ev2["text"][:40])

print()
bad = [r for r in results if not r[1]]
print(f"{len(results) - len(bad)}/{len(results)} GREEN")
sys.exit(1 if bad else 0)
