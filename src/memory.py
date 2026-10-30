"""Loomscript 记忆层 v0 —— tideline 骨架版（无 embedding，可插拔升级）。

10/30 拍板落地：
- tideline 砍到骨架：去 Dreamloop 象征层 / embedding / 注意力地图
- 留 pianist 式自动复盘写入循环；写入格式 = tideline v2.3 narratives 表原样
  （gesture=骨架, context_layer=脉络, moment=时点, cognition_direction,
   related_entities, importance/emotional/recurrence/unresolved, weight）
- 写入时机：act_end 存档一次 + game_end 全量一次；蒸馏走后台（llm_call 可注入，
  主 agent 上下文零占用）
- 检索：char-bigram TF-IDF + cosine（中文免分词，零依赖）。
  赛方 API 若有 embedding endpoint，设 LOOM_MEMORY_EMBEDDER=http://... 即切换，
  retrieve() 接口不变。kmeans/IVF 在 demo 语料量级（<1k 条）下无收益，不做。
- 「记得你」：主 agent（DM）认人，角色全盲。user_profile 从 profiles 表 +
  近期 narratives 结算，game_start 时注入 DM 材料与生成管线。

集成点（server 侧三行接线，见模块尾 demo）：
  store = MemoryStore(db_path)
  room.dm = DM(bundle, port, dm_memory=store, user_profile=store.player_brief())
  # DM._archive() 产出的 entry 由 ingest_archive 消费（后台线程/asyncio 均可）
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import time
import urllib.request
from collections import Counter
from pathlib import Path

# ---------------------------------------------------------------- schema ----
# tideline v2.3 narratives DDL 子集（写入列名/语义逐列对齐，真 tideline 收编零迁移）

_DDL = """
CREATE TABLE IF NOT EXISTS narratives(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL DEFAULT '',
    ntype TEXT DEFAULT 'general',
    tags TEXT DEFAULT '[]',
    embedding TEXT,
    created_at TEXT NOT NULL,
    gesture TEXT,
    context_layer TEXT,
    moment TEXT,
    cognition_direction TEXT,
    related_entities TEXT,
    source_links TEXT,
    entities_role TEXT,
    weight REAL,
    importance INTEGER,
    emotional INTEGER,
    recurrence INTEGER,
    unresolved INTEGER
);
CREATE TABLE IF NOT EXISTS profiles(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity TEXT NOT NULL,
    ptype TEXT DEFAULT 'contact',
    content TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(entity, ptype)
);
"""


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


# ------------------------------------------------------------- retrieval ----

_CJK = re.compile(r"[\u4e00-\u9fff\w]")


def char_bigrams(text: str) -> list[str]:
    """中文按字切二元（麦克白→麦克/克白），拉丁词保留整词。免分词器。"""
    toks: list[str] = []
    buf = ""
    for ch in text:
        if _CJK.match(ch):
            buf += ch
        else:
            if buf:
                toks.extend(_pairs(buf)); buf = ""
            if ch.isalnum():
                toks.append(ch.lower())
    if buf:
        toks.extend(_pairs(buf))
    return toks


def _pairs(s: str) -> list[str]:
    return [s[i:i + 2] for i in range(len(s) - 1)] or ([s] if s else [])


def _vec(tokens: list[str]) -> dict[str, float]:
    c = Counter(tokens)
    n = sum(c.values()) or 1
    return {t: v / n for t, v in c.items()}


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(t, 0.0) for t, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


# ------------------------------------------------------------------ store ---

class MemoryStore:
    """DM 记忆库。一个玩家一个库文件；跨局=跨文件追加写入。"""

    def __init__(self, path: str | Path = "dm_memory.db", embedder: str | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_DDL)
        self.db.commit()
        # embedder: HTTP endpoint（POST {"text": ...} -> {"embedding": [...]});
        # None 时纯本地 TF-IDF。demo 默认 None——零外部依赖先跑通。
        self.embedder = embedder or os.environ.get("LOOM_MEMORY_EMBEDDER")

    # ---- 写（格式=tideline narratives v2.3 原样） --------------------------
    def write_narrative(self, gesture: str, context_layer: str = "",
                        moment: str = "", cognition_direction: str = "",
                        related_entities: list | None = None,
                        tags: list | None = None, ntype: str = "general",
                        importance: int = 3, emotional: int = 2,
                        recurrence: int = 1, unresolved: int = 1,
                        source_links: list | None = None,
                        content: str = "") -> int:
        # tideline 同款简版权重：四维各 1-5，重要性×未解占大头
        weight = round(
            0.35 * (importance / 5) + 0.25 * (emotional / 5)
            + 0.2 * (recurrence / 5) + 0.2 * (unresolved / 5), 4)
        cur = self.db.execute(
            "INSERT INTO narratives(content, ntype, tags, created_at,"
            " gesture, context_layer, moment, cognition_direction,"
            " related_entities, source_links, weight,"
            " importance, emotional, recurrence, unresolved)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (content, ntype, json.dumps(tags or [], ensure_ascii=False), _now(),
             gesture, context_layer, moment, cognition_direction,
             json.dumps(related_entities or [], ensure_ascii=False),
             json.dumps(source_links or [], ensure_ascii=False), weight,
             importance, emotional, recurrence, unresolved))
        self.db.commit()
        return cur.lastrowid

    def write_profile(self, entity: str, ptype: str, content: str) -> None:
        self.db.execute(
            "INSERT INTO profiles(entity, ptype, content, updated_at)"
            " VALUES(?,?,?,?)"
            " ON CONFLICT(entity, ptype) DO UPDATE SET"
            " content=excluded.content, updated_at=excluded.updated_at",
            (entity, ptype, content, _now()))
        self.db.commit()

    # ---- 读 ----------------------------------------------------------------
    def narratives(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM narratives ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]

    def _fmt(self, r: dict) -> dict:
        """tideline _fmt_narrative 同构输出（检索返回值）。"""
        return {
            "id": r["id"], "gesture": r["gesture"],
            "context_layer": r["context_layer"], "moment": r["moment"],
            "cognition_direction": r["cognition_direction"],
            "related_entities": json.loads(r["related_entities"] or "[]"),
            "tags": json.loads(r["tags"] or "[]"),
            "weight": r["weight"],
        }

    def retrieve(self, query: str, k: int = 5) -> list[dict]:
        """跨局检索。默认 TF-IDF；配了 embedder 走向量 cosine。接口唯一，
        升级不改调用方。"""
        rows = self.db.execute(
            "SELECT * FROM narratives ORDER BY id DESC LIMIT 1000").fetchall()
        docs = [dict(r) for r in rows]
        if not docs:
            return []
        if self.embedder:
            return self._retrieve_vec(query, docs, k)
        qv = _vec(char_bigrams(query))
        scored = [(cosine(qv, _vec(char_bigrams(
            " ".join(filter(None, [d["gesture"], d["context_layer"],
                                   d["content"]]))))), d)
            for d in docs]
        scored.sort(key=lambda x: -x[0])
        return [self._fmt(d) for _, d in scored[:k] if _ > 0.01]

    def _retrieve_vec(self, query, docs, k):
        def emb(text):
            req = urllib.request.Request(
                self.embedder,
                data=json.dumps({"text": text}).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read())["embedding"]
        q = emb(query)
        out = []
        for d in docs:
            if d["embedding"]:
                v = json.loads(d["embedding"])
                score = sum(a * b for a, b in zip(q, v))
                out.append((score, d))
        out.sort(key=lambda x: -x[0])
        return [self._fmt(d) for _, d in out[:k]]

    # ---- 复盘蒸馏（后台 session，llm_call 注入；测试用假实现） --------------
    DISTILL_PROMPT = (
        "你是记忆蒸馏器。把这段游戏复盘材料蒸馏成 {n} 条 tideline 叙事记忆，"
        "每条含 gesture(动作/事件一句话), context_layer(背景脉络), moment(时点),"
        " cognition_direction(认知方向), related_entities, importance/emotional/"
        "recurrence/unresolved(1-5)。只输出 JSON 数组。材料：\n{material}")

    def distill(self, material: str, llm_call, n: int = 5, game_id: str = "") -> list[int]:
        """material=一局/一幕的复盘材料；llm_call(prompt)->str。产出写库。
        对局内不调用（act_end/game_end 后台消费）。game_id 进 tags 便于
        按局过滤。"""
        raw = llm_call(self.DISTILL_PROMPT.format(n=n, material=material))
        m = re.search(r"\[.*\]", raw, re.S)
        items = json.loads(m.group(0)) if m else []
        ids = []
        for it in items:
            ids.append(self.write_narrative(
                gesture=it.get("gesture", ""),
                context_layer=it.get("context_layer", ""),
                moment=it.get("moment", ""),
                cognition_direction=it.get("cognition_direction", ""),
                related_entities=it.get("related_entities"),
                tags=(it.get("tags", ["game"]) + ([game_id] if game_id else [])),
                ntype=it.get("ntype", "game_review"),
                importance=it.get("importance", 3),
                emotional=it.get("emotional", 2),
                recurrence=it.get("recurrence", 1),
                unresolved=it.get("unresolved", 1)))
        return ids

    def ingest_archive(self, entry: dict, llm_call, game_id: str = "") -> list[int]:
        """消费 DM._archive() 产出的存档 entry（act_archive/game_archive）。
        终局档案额外落一条 game_marker（结构数据，不走 LLM）——局数以
        marker 计，不数 moment（一局多幕多复盘，moment 必然多于局数）。
        llm_call=None → journal 原文入库（无 LLM 档：手写手账就是蒸馏）。"""
        kind = entry.get("kind", "act_archive")
        n = 5 if kind == "act_archive" else 8
        ids = []
        if kind == "game_archive":
            gid = game_id or _now()
            ids.append(self.write_narrative(
                gesture=f"一局结束（{gid}）",
                context_layer=entry.get("title", ""),
                moment=gid, ntype="game_marker",
                tags=[gid], importance=1, emotional=1,
                recurrence=1, unresolved=1))
        if llm_call is None:
            for note in entry.get("journal", []):
                ids.append(self.write_narrative(
                    gesture=note, context_layer=f"{entry.get('title','')}·存档",
                    moment=game_id or kind, ntype="journal_raw",
                    tags=["journal", game_id] if game_id else ["journal"]))
            return ids
        material = json.dumps({
            "kind": kind, "act_ended": entry.get("act_ended"),
            "journal": entry.get("journal", []),
            "events_upto": entry.get("events_upto"),
        }, ensure_ascii=False)
        ids += self.distill(material, llm_call, n=n, game_id=game_id)
        return ids

    # ---- 「记得你」材料（game_start 注入 DM 与生成管线） ---------------------
    def player_brief(self, top: int = 5) -> dict:
        """关于这位玩家：profiles 常驻画像 + 近期高权重叙事。第二局 DM 的
        user_profile 就是这个——开场白零差异化，「记得」织进主持词与选本。"""
        prof = self.db.execute(
            "SELECT ptype, content FROM profiles WHERE entity='player'"
            " ORDER BY ptype").fetchall()
        nar = self.narratives()[:20]
        nar.sort(key=lambda r: -(r["weight"] or 0))
        return {
            "profiles": {r["ptype"]: r["content"] for r in prof},
            "recent_memories": [self._fmt(r) for r in nar[:top]],
            "games_played": self.db.execute(
                "SELECT COUNT(*) FROM narratives"
                " WHERE ntype='game_marker'").fetchone()[0],
        }


if __name__ == "__main__":  # 自测：两局流转的最小演示
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as td:
        store = MemoryStore(Path(td) / "demo.db")
        fake_llm = lambda p: json.dumps([{
            "gesture": "玩家在邓肯寝殿外犹豫了很久，最后选择亲手行凶",
            "context_layer": "麦克白第一幕，预言的压力第一次变成行动",
            "moment": "game1/act1",
            "cognition_direction": "从旁观者切换为亲手沾血的主角",
            "related_entities": ["麦克白", "邓肯"],
            "importance": 5, "emotional": 4, "recurrence": 2,
            "unresolved": 3}], ensure_ascii=False)
        store.distill("第一局复盘材料", fake_llm)
        store.write_profile("player", "fact", "偏好在道德边缘反复横跳后再下手")
        brief = store.player_brief()
        assert brief["profiles"]["fact"].startswith("偏好"), brief
        hits = store.retrieve("上局玩家对邓肯做了什么")
        assert hits and "邓肯" in str(hits[0]), hits
        print("two-round demo OK:")
        print("  brief:", json.dumps(brief, ensure_ascii=False)[:200], "...")
        print("  retrieve[0]:", hits[0]["gesture"])
