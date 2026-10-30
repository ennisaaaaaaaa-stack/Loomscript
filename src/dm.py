"""Loomscript DM 层 v0 —— 主持人骨架 + 上下文装配器。

架构（后端设计文档 §3/§7.1）：
- assembler = 纯函数 (bundle, act, character_id, events, channel_history) -> prompt
- 三类上下文：角色agent（隔离墙）/ DM（唯一全知点）/ 玩家（双套剧情本逐幕发放）
- DM 上台（10/30拍板）：主框说话=普通消息，私聊窗按角色开
- 记忆回流（10/30拍板）：act_end 存档写一次 + game_end 全量写一次
- 降级：DM 的台词也走 AgentPort 三档（semi_manual 预排练 / tangwu / llm）
"""
import json
from engine import Session, AgentPort, SemiManualPort

DM_ID = "dm"


# ---------------------------------------------------------------------------
# 上下文装配器（纯函数，可单测）
# ---------------------------------------------------------------------------

def assemble_character_prompt(bundle, act_id, character_id, events, channel_history):
    """角色 agent 的 prompt 材料。墙=只持有到当前幕为止 + 自己 channel 的私聊史。

    隔离保证：secret_sheet 按幕切片（第 i 幕只给前 i 幕的量），后面幕的秘密
    物理上不进入材料——不是靠 prompt 恳求，是靠数据结构切掉。
    """
    acts = bundle.data["acts"]
    i = next(idx for idx, a in enumerate(acts) if a["act_id"] == act_id)
    c = bundle.chars[character_id]

    material = {
        "role": "character_agent",
        "you_are": {"id": c["id"], "name": c["name"],
                    "public_sheet": c["public_sheet"],
                    "voice": c.get("voice", "")},
        # 秘密切片：到当前幕为止。act_i 的角色只知道前 i 幔该知道的量
        "secret_slice": c.get("secret_sheet", "")[: 200 * (i + 1)],
        "world_so_far": [a["world_info"] for a in acts[: i + 1]],
        "current_scene": None,  # 由调用方按 events 推出后填
        "your_channel_history": channel_history.get(f"dm:{character_id}", []),
        "knowledge_unlocked": [],  # 由 events 结算
        "law": "你不能知道还没演到的真相。材料里没有的就是你不知道的。",
    }

    # 从事件结算当前场景与已解锁知识（纯读，不改状态）
    for ev in events:
        if ev["type"] == "scene_begin" and ev.get("act_id") == act_id:
            material["current_scene"] = ev["scene_id"]
        elif ev["type"] == "reveal":
            for k in ev.get("reveal_keys", []):
                material["knowledge_unlocked"].append(k)

    scene_id = material["current_scene"]
    if scene_id is not None:
        sc = bundle.scenes(act_id).get(scene_id)
        if sc:
            material["scene_text"] = sc["text"]
    return material


def assemble_dm_prompt(bundle, events, dm_memory=None, user_profile=None):
    """DM 的 prompt 材料——唯一全知点。

    DM = 认识用户的主持人（10/30拍板）：可陪伴可交流，复盘环节自由交流归 DM。
    全知含：完整世界剧本（全部幕）、所有角色秘密、操作指引、调度表。
    """
    return {
        "role": "dm",
        "you_are": "主持人（DM）。认识玩家，可陪伴可交流；推幕、发行动卡、提议玩法。",
        "full_script": bundle.data,  # 全知：不切片
        "memory": dm_memory or {},  # tideline 骨架版（跨局记忆回流）
        "user_profile": user_profile or {},  # 「记得你」的原料
        "law": "角色不知道的未来你知道；但你以主持人身份吞吐信息，不替玩家做决定。",
    }


# ---------------------------------------------------------------------------
# 行动卡（10/30 DM 骨架三件套之一）
# ---------------------------------------------------------------------------

def action_cards(bundle, act_id, character_id):
    """给角色/玩家的可选行动提示。v0: 从当前幕场景的 choices 直取 + 通用三件。"""
    act = bundle.act(act_id)
    cards = []
    for sc in act["scenes"]:
        for ch in sc.get("choices", []):
            cards.append({"card": "action", "id": ch["id"], "label": ch["label"],
                          "leads_to": ch.get("leads_to")})
    cards += [
        {"card": "action", "id": "free_talk", "label": "自由发言（不限选项）"},
        {"card": "action", "id": "ask_dm", "label": "和 DM 交谈（主框）"},
        {"card": "action", "id": "private", "label": "私聊某位角色",
         "target_channel": f"dm:{character_id}"},
    ]
    return cards


# ---------------------------------------------------------------------------
# DM 骨架
# ---------------------------------------------------------------------------

class DM:
    """主持人：推幕、给角色发行动卡、提议玩法、复盘引导、记忆回流。

    台词来源走 AgentPort（三档降级同接口）；DM 的结构性动作（推幕/发卡）
    是确定性的，不走 LLM——「预生成骨架+现场表演」的分工线。
    """

    def __init__(self, bundle, port: AgentPort, dm_memory=None, user_profile=None):
        self.bundle = bundle
        self.port = port  # DM 台词档位（semi_manual 预排练可全离线跑）
        self.memory = dm_memory or {}
        self.user_profile = user_profile or {}
        self.journal = []  # DM 手账（journal_push 的原料）

    # -- 开场白 + 玩法提议（结构性，模板生成；有 port 则用 port 演出） -------
    def _stage(self, session: Session):
        """当前位置字段；scene 尚未进入时省略（合同不收 null）。"""
        kw = {"act_id": session._s()["act_id"]}
        if session._s()["scene_id"] is not None:
            kw["scene_id"] = session._s()["scene_id"]
        return kw

    def opening(self, session: Session):
        title = self.bundle.data["title"]
        chars = "、".join(c["name"] for c in self.bundle.data["characters"]
                         if not c.get("is_player"))
        text = (f"欢迎来到《{title}》。我是主持人，全程陪着你。"
                f"今晚与你同台的演员：{chars}。"
                f"你可以自由发言推进剧情，可以打开私聊窗找某位角色密谈，"
                f"也可以随时和我聊。想先听我提议一种玩法吗？")
        return session.emit(type="agent_line", character_id=DM_ID,
                            channel="main", text=text, **self._stage(session))

    def propose_play(self, session: Session):
        """提议玩法（DM 三件套之三）。"""
        text = ("提议玩法：跟着台词的节奏走，该说话时说话；"
                "每个场景结束我会推幕并结算揭示。随时可以密谈——"
                "有些话只有私聊里说得出口。")
        return session.emit(type="agent_line", character_id=DM_ID,
                            channel="main", text=text, **self._stage(session))

    # -- 行动卡（结构化事件，前端翻牌） ------------------------------------
    def deal_cards(self, session: Session, character_id):
        for card in action_cards(self.bundle, session._s()["act_id"], character_id):
            session.emit(type="choice", character_id=character_id,
                         choice_id=card["id"],
                         text=card.get("label"), **self._stage(session))

    # -- 推幕（确定性结构动作 + DM 报幕词） ----------------------------------
    def advance_act(self, session: Session):
        acts = [a["act_id"] for a in self.bundle.data["acts"]]
        i = acts.index(session._s()["act_id"])
        nxt = acts[i + 1] if i + 1 < len(acts) else None
        if nxt:
            title = self.bundle.act(nxt)["title"]
            session.emit(type="act_end", act_id=acts[i])
            session.emit(type="act_begin", act_id=nxt)
            session.emit(type="agent_line", character_id=DM_ID, channel="main",
                         text=f"—— 第{len(acts[:i+1])+1}幕 · {title} ——",
                         act_id=nxt)
            self._archive(session, act_ended=acts[i])
        else:
            session.emit(type="act_end", act_id=acts[i])
            session.emit(type="game_end", review_text=None)
            self._archive(session, act_ended=acts[i], final=True)

    # -- 手账（journal_push 的原料池） ---------------------------------------
    def note(self, session: Session, journal_text):
        self.journal.append(journal_text)
        return session.emit(type="journal_push", journal_text=journal_text,
                            act_id=session._s()["act_id"])

    # -- 记忆回流（10/30拍板：act_end 写一次 + game_end 全量写一次） ----------
    def _archive(self, session: Session, act_ended=None, final=False):
        """存档点写入。后台 session 写不占主 agent 上下文——这里只产出
        待写材料，真正的 tideline 写入由后端异步消费（对局内零阻塞）。"""
        entry = {
            "kind": "act_archive" if not final else "game_archive",
            "act_ended": act_ended,
            "snapshot": session.to_snapshot(),
            "events_upto": len(session.events),
            "journal": list(self.journal),
        }
        self.memory.setdefault("archives", []).append(entry)
        return entry

    # -- DM 台词（演出层：走 port，可降级） -----------------------------------
    def speak(self, session: Session):
        return self.port.respond(session, DM_ID)

    # -- 复盘引导（game_end 后的 review 事件；自由交流归 DM） ------------------
    def review(self, session: Session, review_text):
        return session.emit(type="review", review_text=review_text,
                            act_id=session._s()["act_id"] if session.state else None)
