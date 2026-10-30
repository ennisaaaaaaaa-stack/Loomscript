#!/usr/bin/env python3
"""结局判定 + 象征卡发射（D1 晚补课）。

缺口1（她点的「结局分支做了吗」）：endgame.endings 有完整数据（END01-03
+priority+条件），但引擎不判定——game_end 只落个 review_text=None。
本套件钉：
  1. game_end 时引擎按 endgame.priority 依序评估 endings 条件
  2. 条件求值需要的口径（public_testimony_count_min / archive_preserved）
     由事件流结算——公开证言=玩家 player_line 在 main 通道的唯一署名数
  3. 命中结局随 game_end 事件下发（ending_id/title/text）
  4. cg_unlocked 按命中结局的 cg_id 落账
  5. 无 endgame.endings 的旧 bundle -> 维持现状（不判定，向后兼容）

缺口2（「抽卡没人发射」）：card_draw 事件引擎认、状态记（cards_drawn），
但没有任何发射口——现在 DM 层能按 bundle.cards 提议抽卡，发射前校验
  6. cards 表里有的卡能抽（card_draw 落账+cards_drawn 记账）
  7. 不存在的卡 -> ContractError
  8. 同一张卡幂等：同局重复抽 -> None
  9. cards 为空的老 bundle -> ContractError（没内容可抽不是静默）
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from engine import Bundle, Session, SemiManualPort, ContractError  # noqa: E402
from dm import DM  # noqa: E402
from play_blocks import propose_clue  # noqa: E402

results = []


def check(name, ok, note=""):
    results.append((name, bool(ok)))
    print(("GREEN " if ok else "RED   ") + name + (f"  | {note}" if note else ""))


data = json.loads((ROOT / "bundles" / "macbeth_mini.json").read_text(encoding="utf-8"))
# 拿 mini 的骨架但换成 full 的结局数据（判定数据真来源）
full = json.loads((ROOT / "bundles" / "macbeth_full.json").read_text(encoding="utf-8"))
data["endgame"] = full["endgame"]
data["cards"] = full.get("cards", [])
data["clues"] = full.get("clues", [])  # 空——clues 数据缺口单独钉（见 test 10）
# 结局->CG 映射机制用夹具钉（真实 macbeth_full 的 endings 不带 cg_id，
# B3 十张 CG 与结局的映射是内容侧缺口，机制按「数据给了就落账」设计）
data["endgame"]["endings"][2]["cg_id"] = "CG10"
# 证言口径=player_line（真人玩家）；把 lady_m 翻成玩家模拟双人局
for c in data["characters"]:
    if c["id"] == "lady_m":
        c["is_player"] = True

b = Bundle(data)
s = Session(b, tier="semi_manual")
s.start()
dm = DM(b, SemiManualPort({}))

# ---- 抽卡（缺口2） ----------------------------------------------------
from play_blocks import draw_card  # noqa: E402

ev = draw_card(s, "CARD01", character_id="macbeth")
check("1-draw-card-fires", ev is not None and ev["type"] == "card_draw",
      f"ev={ev and ev['type']}")
check("2-draw-card-recorded", "CARD01" in s._s()["cards_drawn"])
try:
    draw_card(s, "NOPE", character_id="macbeth")
    check("3-draw-unknown-card-rejected", False, "no error raised")
except ContractError:
    check("3-draw-unknown-card-rejected", True)
ev2 = draw_card(s, "CARD01", character_id="macbeth")
check("4-draw-idempotent", ev2 is None, f"ev2={ev2}")

# ---- 证言口径结算（结局判定的原料） ------------------------------------
# 六名玩家在各自存活窗口内公开作证：mini 只有 macbeth 是玩家，模拟
# 3 条 main 通道 player_line（唯一署名=macbeth 一人，口径见 endings.rules）
s.line("macbeth", "我当众作证：命令是我下的。", channel="main")
s.line("macbeth", "再次作证，重复只计一次。", channel="main")

from play_blocks import public_testimony_count  # noqa: E402

n = public_testimony_count(s)
check("5-testimony-unique-signatures", n == 1, f"count={n} (expect 1)")
s.line("lady_m", "我也作证。", channel="main")
n2 = public_testimony_count(s)
check("6-testimony-second-signer", n2 == 2, f"count={n2} (expect 2)")

# ---- 结局判定（缺口1） --------------------------------------------------
from play_blocks import judge_ending  # noqa: END

# archive_preserved 未在任何事件里表达 -> False -> END03 命中（priority 首位）
ending = judge_ending(s)
check("7-judge-returns-priority-first-match",
      ending is not None and ending["id"] == "END03",
      f"ending={ending and ending.get('id')}")

# DM 推终幕 -> game_end 带命中结局
dm.advance_act(s)  # A1 -> A2
dm.advance_act(s)  # A2 -> game_end
ge = [e for e in s.events if e["type"] == "game_end"][-1]
check("8-game-end-carries-ending",
      ge.get("ending_id") == "END03" and bool(ge.get("ending_text")),
      f"ending_id={ge.get('ending_id')}")
check("9-cg-unlocked-on-ending", s._s()["cg_unlocked"] == ["CG10"],
      f"cg_unlocked={s._s()['cg_unlocked']}")

# ---- 向后兼容：无 endings 的旧 bundle -----------------------------------
b2 = Bundle(json.loads((ROOT / "bundles" / "macbeth_mini.json").read_text(encoding="utf-8")))
s2 = Session(b2, tier="semi_manual")
s2.start()
ending2 = judge_ending(s2)
check("10-no-endings-legacy-none", ending2 is None, f"{ending2}")

print()
bad = [r for r in results if not r[1]]
print(f"{len(results) - len(bad)}/{len(results)} GREEN")
sys.exit(1 if bad else 0)
