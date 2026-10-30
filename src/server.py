"""Loomscript 后端服务 v0 —— 把引擎+DM 包成 HTTP/SSE。

端点：
- POST /games              建局 {bundle_id, tier, port} -> session_id + snapshot
- POST /games/{id}/say     说话 {character_id, text, channel}
- POST /games/{id}/dm      DM 结构性指令 {action, ...}（确定性，不走 LLM）
- GET  /games/{id}/events?after=SEQ   按 seq 补发事件（断线重连）
- GET  /games/{id}/stream  SSE 事件流
- GET  /games/{id}/snapshot
- GET  /games/{id}/view/{cid}   角色 agent_view（记忆层/pianist 挂点）
- GET  /games/{id}/dm_prompt     DM 全知材料（记忆层挂点）
- GET  /healthz

事件流 jsonl 落盘（sessions/{session_id}.jsonl）：服务重启可恢复，
demo 现场断电不丢对局——对拍与快照的地基。
"""
import argparse
import json
import pathlib
import sys
import threading
import time

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from engine import Bundle, Session, SemiManualPort, ContractError  # noqa: E402
from dm import (DM, assemble_character_prompt, assemble_dm_prompt, DM_ID,  # noqa: E402
                channel_history, digest_private_channels)
from memory import MemoryStore  # noqa: E402
from play_blocks import propose_clue as pb_propose_clue, sweep_deadline  # noqa: E402

BUNDLES_DIR = ROOT / "bundles"
SESSIONS_DIR = ROOT / "sessions"
MEMORY_DIR = ROOT / "dm_memory"  # DM 记忆库：跨局持久（demo 第二局「记得你」）

app = FastAPI(title="Loomscript backend v0")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

GAMES = {}  # session_id -> GameRoom
BUNDLE_CACHE = {}


class GameRoom:
    """一局在内存里的家：Session + DM + 事件持久化 + 锁。"""

    def __init__(self, bundle: Bundle, tier: str, port_kind: str,
                 memory_store: MemoryStore | None = None,
                 distill_llm=None):
        self.bundle = bundle
        self.session = Session(bundle, tier=tier)
        self.store = memory_store  # None=测试态（dm.memory 保持 dict）
        self.dm = DM(bundle, SemiManualPort({}),
                     dm_memory=memory_store or {},
                     user_profile=(memory_store.player_brief()
                                   if memory_store else {}),
                     distill_llm=distill_llm)
        self.port_kind = port_kind
        self.lock = threading.Lock()
        self.jsonl = SESSIONS_DIR / f"{self.session.session_id}.jsonl"
        SESSIONS_DIR.mkdir(exist_ok=True)
        before = len(self.session.events)
        self.session.start()  # game_start + 第一幕 act_begin
        self.dm.opening(self.session)  # 开场白落进事件流
        self._persist(self.session.events[before:])

    def _persist(self, events):
        if not events:
            return
        with open(self.jsonl, "a", encoding="utf-8") as f:
            for ev in events:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")

    def events_after(self, after_seq):
        evs = []
        with open(self.jsonl, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    ev = json.loads(line)
                    if ev["seq"] > after_seq:
                        evs.append(ev)
        return evs

    def last_seq(self):
        evs = self.events_after(-1)
        return evs[-1]["seq"] if evs else -1


def get_room(sid) -> GameRoom:
    room = GAMES.get(sid)
    if room is None:
        raise HTTPException(404, f"session {sid} not found")
    return room


def get_bundle(bundle_id: str) -> Bundle:
    if bundle_id not in BUNDLE_CACHE:
        path = BUNDLES_DIR / f"{bundle_id}.json"
        if not path.exists():
            raise HTTPException(404, f"bundle {bundle_id} not found")
        BUNDLE_CACHE[bundle_id] = Bundle.load(path)
    return BUNDLE_CACHE[bundle_id]


# ---------------------------------------------------------------- 建局/状态

@app.post("/games")
def create_game(body: dict):
    bundle = get_bundle(body.get("bundle_id", "macbeth_mini"))
    store = None
    if body.get("memory", True):  # 默认开记忆：demo 第二局有「记得你」
        memory_db = MEMORY_DIR / "dm_memory.db"
        store = MemoryStore(memory_db)
    room = GameRoom(bundle, tier=body.get("tier", "tangwu"),
                    port_kind=body.get("port", "semi_manual"),
                    memory_store=store)
    GAMES[room.session.session_id] = room
    return {"session_id": room.session.session_id,
            "snapshot": room.session.to_snapshot(),
            "last_seq": room.last_seq()}


@app.get("/games/{sid}/snapshot")
def snapshot(sid: str):
    room = get_room(sid)
    with room.lock:
        return room.session.to_snapshot()


@app.get("/games/{sid}/events")
def events(sid: str, after: int = -1):
    return get_room(sid).events_after(after)


@app.get("/games/{sid}/stream")
def stream(sid: str, after: int = -1):
    room = get_room(sid)

    def gen():
        last = after
        idle = 0
        while True:
            evs = room.events_after(last)
            for ev in evs:
                last = ev["seq"]
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            if evs:
                idle = 0
            else:
                idle += 1
                if idle % 15 == 0:  # ~15s 一次心跳
                    yield ": ping\n\n"
            time.sleep(1)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------- 游玩动作

@app.post("/games/{sid}/say")
def say(sid: str, body: dict):
    room = get_room(sid)
    cid = body.get("character_id")
    text = body.get("text", "")
    channel = body.get("channel", "main")
    with room.lock:
        try:
            before = len(room.session.events)
            room.session.line(cid, text, channel=channel, pose=body.get("pose"))
            new = room.session.events[before:]
        except ContractError as e:
            raise HTTPException(400, str(e))
        room._persist(new)
        return {"events": new, "snapshot": room.session.to_snapshot()}


@app.post("/games/{sid}/scene")
def enter_scene(sid: str, body: dict):
    room = get_room(sid)
    with room.lock:
        before = len(room.session.events)
        room.session.enter_scene(body["scene_id"])
        room.session.fire_reveals(body["scene_id"])
        new = room.session.events[before:]
        room._persist(new)
        return {"events": new, "snapshot": room.session.to_snapshot()}


DM_ACTIONS = ("opening", "propose_play", "deal_cards", "advance_act",
              "review", "note", "propose_clue")


@app.post("/games/{sid}/dm")
def dm_action(sid: str, body: dict):
    room = get_room(sid)
    action = body.get("action")
    if action not in DM_ACTIONS:
        raise HTTPException(400, f"unknown dm action: {action}")
    with room.lock:
        before = len(room.session.events)
        if action == "opening":
            room.dm.opening(room.session)
        elif action == "propose_play":
            room.dm.propose_play(room.session)
        elif action == "deal_cards":
            room.dm.deal_cards(room.session, body["character_id"])
        elif action == "advance_act":
            room.dm.advance_act(room.session)
            sweep_deadline(room.session)  # 死线扫描：逾期线索归档（降级的一部分）
        elif action == "review":
            room.dm.review(room.session, body.get("review_text", ""))
        elif action == "note":
            room.dm.note(room.session, body["journal_text"])
        elif action == "propose_clue":
            try:
                pb_propose_clue(room.session, body["clue_id"],
                                jitter_text=body.get("jitter_text"))
            except ContractError as e:
                raise HTTPException(400, str(e))
        new = room.session.events[before:]
        room._persist(new)
        return {"events": new, "snapshot": room.session.to_snapshot()}


# ---------------------------------------------------------------- 挂点

@app.get("/games/{sid}/view/{cid}")
def agent_view(sid: str, cid: str):
    room = get_room(sid)
    with room.lock:
        return assemble_character_prompt(
            room.bundle, room.session._s()["act_id"], cid,
            room.session.events,
            {f"dm:{cid}": channel_history(room.session.events, f"dm:{cid}")})


@app.get("/games/{sid}/dm_prompt")
def dm_prompt(sid: str):
    room = get_room(sid)
    with room.lock:
        mem = room.dm.memory
        brief_fn = getattr(mem, "player_brief", None)
        if brief_fn:  # MemoryStore → 摘要视图（不漏 sqlite 句柄）
            mem = {"brief": brief_fn()}
        return assemble_dm_prompt(room.bundle, room.session.events,
                                  dm_memory=mem,
                                  user_profile=room.dm.user_profile,
                                  private_digest=digest_private_channels(
                                      room.session.events))


@app.get("/games/{sid}/memory")
def memory_view(sid: str, q: str = "", k: int = 5):
    """DM 记忆库观察窗（jury 演示用）：brief + 可选检索。"""
    room = get_room(sid)
    store = room.dm.memory
    if not hasattr(store, "player_brief"):
        return {"memory": "dict-mode（测试模式），无 tideline 库"}
    out = {"brief": getattr(store, "player_brief", lambda: None)()}
    if q:
        retriever = getattr(store, "retrieve", None)
        if retriever:
            out["retrieve"] = retriever(q, k=k)
    return out


@app.get("/healthz")
def healthz():
    return {"ok": True, "games": len(GAMES),
            "bundles": sorted(p.stem for p in BUNDLES_DIR.glob("*.json"))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8740)
    args = ap.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
