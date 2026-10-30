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


def _archived_clues(session):
    """已归档（逾期处理过）的线索集合——从 journal_push 事件的 clue_id 字段读。

    journal_push 载荷带 clue_id 字段（归档专用）；没有该字段的手账不参与
    去重。归档幂等：同一线索只归档一次，重复 sweep 不重复落账。
    """
    return {ev.get("clue_id") for ev in session.events
            if ev["type"] == "journal_push" and ev.get("clue_id")}


def sweep_deadline(session, journal_emitter=None):
    """must_ready_by 死线扫描（advance_act 调用）：到线未发 -> 归档 journal_push。

    journal_emitter: 可注入的 journal 发射器（默认 session.emit journal_push）。
    不 raise——「DM 嗓子哑了剧本自己走」降级的一部分。

    幂等键=clue_id（与 propose_clue 同一把尺）：act_scoped 线索按合同由
    生成器负责命名空间（A1:x / A2:x 是两条线索），引擎侧裸 clue_id 一局
    只发一次——已发射即已履约，永不归档；已归档的不重复归档。
    """
    bundle = session.bundle
    fired = fired_clues(session)
    archived = _archived_clues(session)
    cur_idx = _act_index(bundle, session._s()["act_id"])
    for clue in bundle.data.get("clues", []):
        cid = clue["clue_id"]
        if cid in fired or cid in archived:
            continue
        deadline_idx = _act_index(bundle, clue.get("must_ready_by", FINAL))
        if deadline_idx < cur_idx:
            text = (f"线索{cid}逾期未发（死线{clue.get('must_ready_by', FINAL)}"
                    f"已过），已归档")
            if journal_emitter is not None:
                journal_emitter(text, clue_id=cid)
            else:
                session.emit(type="journal_push", journal_text=text,
                             clue_id=cid, act_id=session._s()["act_id"])
