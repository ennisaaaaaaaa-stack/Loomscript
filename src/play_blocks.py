#!/usr/bin/env python3
"""Loomscript play blocks (7.4) — DM 提议 -> 引擎校验放行。

设计立场（设计文档 §7.4 + 10/30 拍板）：DM 按 A4 节拍提议玩法块，引擎按
合同约束（visible_at 最早可见 / must_ready_by 生成死线）校验后发射。
DM 只能提议不能发射——确定性不破，演出层（jitter_text）不参与校验。

act 序比较：visible_at / must_ready_by 是幕 id，按 bundle.data['acts']
列表序号比较（'act1' 在 act2 之前 = 序号 0 < 1）。'final' = 最后一幕。
"""
from engine import ContractError

FINAL = "final"


def _act_index(bundle, act_id):
    """幕 id -> 序号。'final' 映射到最后一幕（死线语义：过最后一幕仍未发）。"""
    ids = [a["act_id"] for a in bundle.data["acts"]]
    if act_id == FINAL:
        return len(ids) - 1
    if act_id not in ids:
        raise ContractError(f"unknown act id in constraint: {act_id}")
    return ids.index(act_id)


def fired_clues(session):
    """已发射线索的 key 集合（含 act_scoped 前缀形态）。"""
    keys = set()
    for ev in session.events:
        if ev["type"] == "clue_found":
            keys.add(ev.get("clue_id", ""))  # 全局幂等键=clue_id
    return keys


def _key(clue_id, act_id, act_scoped=False):
    return f"{act_id}:{clue_id}" if act_scoped else clue_id


def _clue_table(bundle):
    return {c["clue_id"]: c for c in bundle.data.get("clues", [])}


def propose_clue(session, clue_id, jitter_text=None):
    """DM 提议线索。引擎校验放行；不放行不落账。

    返回 clue_found 事件（放行）或 None（幂等跳过）。
    拦截（太早/未知线索）raise ContractError——错误是合同的一部分。

    幂等键=clue_id 全局唯一：act_scoped 线索由生成器负责按幕命名空间
    （如 A1:blood_hand / A2:blood_hand 是两条线索）；引擎侧同一 clue_id
    一局只发一次，跨幕同 id 再提议 -> None。
    """
    table = _clue_table(session.bundle)
    clue = table.get(clue_id)
    if clue is None:
        raise ContractError(f"unknown clue: {clue_id}")

    cur_idx = _act_index(session.bundle, session._s()["act_id"])
    visible_idx = _act_index(session.bundle, clue["visible_at"])
    if cur_idx < visible_idx:
        raise ContractError(
            f"clue {clue_id} not yet visible (visible_at={clue['visible_at']}, "
            f"current={session._s()['act_id']})")

    if clue_id in fired_clues(session):
        return None  # 幂等：同一线索一局只发一次

    payload = dict(clue.get("payload") or {})
    if jitter_text is not None:
        payload["jitter_text"] = jitter_text
    return session.emit(type="clue_found", clue_id=clue_id,
                        act_id=session._s()["act_id"],
                        **payload)


def sweep_deadline(session, journal_emitter=None):
    """must_ready_by 死线扫描（advance_act 调用）：到线未发 -> 归档 journal_push。

    journal_emitter: 可注入的 journal 发射器（默认 session.emit journal_push）。
    不 raise——「DM 嗓子哑了剧本自己走」降级的一部分。
    """
    bundle = session.bundle
    fired = fired_clues(session)
    next_act_idx = _act_index(bundle, session._s()["act_id"])
    for clue in bundle.data.get("clues", []):
        key = _key(clue["clue_id"], session._s()["act_id"],
                   bool(clue.get("act_scoped", False)))
        if key in fired:
            continue
        deadline_idx = _act_index(bundle, clue.get("must_ready_by", FINAL))
        if deadline_idx < next_act_idx:
            text = (f"线索{clue['clue_id']}逾期未发（死线{clue.get('must_ready_by', FINAL)}"
                    f"已过），已归档")
            if journal_emitter is not None:
                journal_emitter(text)
            else:
                session.emit(type="journal_push", journal_text=text,
                             act_id=session._s()["act_id"])
