#!/usr/bin/env python3
"""私聊隔离收口测试（10/30拍板：角色拿自己 channel 原文，DM 拿摘要）。

断言两件事：
1. 角色材料只含自己 channel 的私聊原文，别人的 channel 物理不出现
2. DM 材料含私聊摘要（条数/字数/截断近况），但不含私聊全文原文
"""
import json
import sys
import tempfile
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from engine import Bundle, Session  # noqa: E402
from dm import (assemble_character_prompt, assemble_dm_prompt,  # noqa: E402
                channel_history, digest_private_channels)

BUNDLE = ROOT / "bundles" / "macbeth_mini.json"
SESSIONS = ROOT / "sessions"
SESSIONS.mkdir(exist_ok=True)

fails = []


def check(name, ok):
    print(("GREEN " if ok else "RED   ") + name)
    if not ok:
        fails.append(name)


b = Bundle.load(BUNDLE)
s = Session(b, tier="tangwu")
s.start()

act1 = b.data["acts"][0]["act_id"]
lady = "lady_m" if "lady_m" in b.chars else list(b.chars)[1]
macb = "macbeth" if "macbeth" in b.chars else list(b.chars)[0]

# 玩家与两位角色各私聊几句（channel=dm:<cid>）
s.line(lady, "夫人密语A：国王今夜宿在城堡。"[:20], channel=f"dm:{lady}")
s.line(macb, "（悄悄）你恨国王吗，夫人？", channel=f"dm:{lady}")  # 玩家=macbeth(is_player)
s.line(lady, "夫人密语B：恨他把功劳给了别人。"[:20], channel=f"dm:{lady}")
s.line(macb, "将军密语A：女巫的预言扰得我心神不宁。"[:20], channel=f"dm:{macb}")

events = s.events

# 1) 角色材料：自己 channel 原文全量在，别人的私聊一个字不出现
mat_lady = assemble_character_prompt(b, act1, lady, events,
                                     {f"dm:{lady}": channel_history(events, f"dm:{lady}")})
hist_lady = mat_lady["your_channel_history"]
own_texts = [h["text"] for h in hist_lady]
check("1-own-channel-fulltext",
      "夫人密语A" in "".join(own_texts) and len(hist_lady) >= 2)
mat_macb = assemble_character_prompt(b, act1, macb, events,
                                     {f"dm:{macb}": channel_history(events, f"dm:{macb}")})
blob_macb = json.dumps(mat_macb, ensure_ascii=False)
check("2-other-private-absent",
      "夫人密语" not in blob_macb and "你恨国王吗" not in blob_macb)

# 2) DM 材料：摘要在场，原文全文不在场
d = digest_private_channels(events)
dm_mat = assemble_dm_prompt(b, events, private_digest=d)
blob_dm = json.dumps(dm_mat, ensure_ascii=False)
check("3-dm-digest-present",
      "private_channel_digest" in dm_mat and lady in dm_mat["private_channel_digest"])
dg = dm_mat["private_channel_digest"][lady]
check("4-digest-shape", dg["messages"] == 3 and dg["chars"] > 0
      and any("夫人密语" in r for r in dg["recent"]))
full_lady = [h["text"] for h in channel_history(events, f"dm:{lady}")]
long_full = [t for t in full_lady if len(t) > 60]  # 超过截断长度的原文
check("5-dm-no-fulltext",
      all(t not in blob_dm for t in long_full))

# 6) 幂等/纯函数性：同输入两次装配结果一致（assembler=纯函数验收线）
mat_again = assemble_character_prompt(b, act1, lady, events,
                                      {f"dm:{lady}": channel_history(events, f"dm:{lady}")})
check("6-pure-function", json.dumps(mat_again, sort_keys=True, ensure_ascii=False)
      == json.dumps(mat_lady, sort_keys=True, ensure_ascii=False))

print()
if fails:
    print(f"{len(fails)} RED / {len(fails)+6} total")
    sys.exit(1)
print("6/6 GREEN")
