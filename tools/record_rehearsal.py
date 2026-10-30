#!/usr/bin/env python3
"""录一局真实游玩入 DM 记忆库，第二局验证「记得你」。

用途：demo 运维点（设计文档 §3）——舞台上第二局才有「记得你」可演。
正式录制=她真玩一局（前端+SSE+真 DM 台词）；本脚本是机制验收器：
同样的 API 序列走两遍，第一局入库，第二局 dm_prompt 里记忆在场。

跑法：python3 tools/record_rehearsal.py [--keep-db]
"""
import argparse
import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from engine import Bundle, Session  # noqa: E402
from dm import DM  # noqa: E402
from engine import SemiManualPort  # noqa: E402
from memory import MemoryStore  # noqa: E402


def play_one_game(bundle, store):
    """一局排练：真实 API 序列（建局→私聊→搜证→推幕→终局复盘）。"""
    s = Session(bundle, tier="tangwu")
    s.start()
    dm = DM(bundle, SemiManualPort({}), dm_memory=store or {},
            user_profile=(store.player_brief() if store else {}))
    dm.opening(s)

    acts = bundle.data["acts"]
    # 第一幕：私聊 + 搜证
    s.enter_scene(acts[0]["scenes"][0]["scene_id"])
    s.fire_reveals(acts[0]["scenes"][0]["scene_id"])
    s.line("lady_m", "国王今夜宿在城堡，这是最好的时机。", channel="dm:lady_m")
    s.line("macbeth", "可他是我的亲戚、我的君王。", channel="main")
    # 玩家真玩会翻到的行动卡
    dm.deal_cards(s, "macbeth")
    # 搜证：DM 提议线索（若 bundle 有 clues；propose_clue 是 wt/play 交付，
    # 未合并前跳过——录制机制验收不依赖它）
    if hasattr(dm, "propose_clue"):
        for clue in bundle.data.get("clues", []):
            dm.propose_clue(s, clue["clue_id"])

    # 推幕到终局
    for _ in range(len(acts) - 1):
        dm.advance_act(s)
        # 中途私聊几轮
        s.line("lady_m", "你已经走到这一步了，退回去就是懦弱。", channel="dm:lady_m")
    dm.advance_act(s)  # 最后一幕 → game_end + 记忆全量入库
    dm.review(s, "这一夜的重量，你如何安放？")
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", default="macbeth_mini")
    ap.add_argument("--db", default=None, help="默认临时库；给路径则复用真库")
    args = ap.parse_args()

    bundle_path = ROOT / "bundles" / f"{args.bundle}.json"
    bundle = Bundle.load(bundle_path)

    if args.db:
        store = MemoryStore(pathlib.Path(args.db))
    else:
        tmp = tempfile.mkdtemp(prefix="loom_rehearsal_")
        store = MemoryStore(pathlib.Path(tmp) / "dm_memory.db")

    print("== 第一局：真实序列入记忆库 ==")
    s1 = play_one_game(bundle, store)
    n_events_1 = len(s1.events)
    print(f"   events={n_events_1}")

    print("== 第二局：dm_prompt 验证「记得你」 ==")
    brief = store.player_brief()
    print("   player_brief:", json.dumps(brief, ensure_ascii=False)[:300])
    s2 = Session(bundle, tier="tangwu")
    s2.start()
    dm2 = DM(bundle, SemiManualPort({}), dm_memory=store,
             user_profile=brief)
    dm2.opening(s2)
    mat = None
    from dm import assemble_dm_prompt
    mat = assemble_dm_prompt(bundle, s2.events, dm_memory={"brief": brief},
                             user_profile=brief)
    has_memory = bool(mat.get("memory") and mat["memory"].get("brief"))
    has_profile = bool(mat.get("user_profile"))
    print(f"   dm_prompt.memory 在场: {has_memory}")
    print(f"   dm_prompt.user_profile 在场: {has_profile}")

    ok = has_memory and has_profile
    print()
    print("REHEARSAL", "GREEN" if ok else "RED",
          f"(2局, 第一局{n_events_1}事件入库)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
