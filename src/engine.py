"""Loomscript 引擎核心 v0 —— 合同驱动的状态机。
只认 contracts/ 三件套，不 import 任何前端。事件溯源：状态=事件流的纯函数。
降级档（pianist/堂屋/半人工）只是 snapshot 里一个字段——同一接口进。
"""
import json, time, uuid, pathlib
from datetime import datetime, timezone
from jsonschema import Draft202012Validator

ROOT = pathlib.Path(__file__).resolve().parent.parent
_SCHEMAS = {}
for _n in ("bundle", "event", "snapshot"):
    with open(ROOT / "contracts" / f"{_n}.schema.json", encoding="utf-8") as _f:
        _SCHEMAS[_n] = Draft202012Validator(json.load(_f))


class ContractError(Exception):
    """合同违约——数据不符合三件套之一。"""


def validate(instance, kind):
    errs = sorted(_SCHEMAS[kind].iter_errors(instance), key=lambda e: list(e.path))
    if errs:
        raise ContractError(f"{kind} contract violated: {errs[0].message}")


def _now():
    return datetime.now(timezone.utc).isoformat()


class Bundle:
    """剧本包：生成模块的输出、游玩模块的输入。"""
    def __init__(self, data):
        validate(data, "bundle")
        self.data = data
        self.acts = {a["act_id"]: a for a in data["acts"]}
        self.chars = {c["id"]: c for c in data["characters"]}

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f))

    def act(self, act_id):
        return self.acts[act_id]

    def scenes(self, act_id):
        return {s["scene_id"]: s for s in self.act(act_id)["scenes"]}


class Session:
    """一局对局。emit=追加事件并应用；apply=纯状态转移。replay 可从事件流完整重建。"""
    def __init__(self, bundle, tier="tangwu"):
        self.bundle = bundle
        self.session_id = str(uuid.uuid4())
        self.tier = tier
        self.events = []
        self.state = None  # None = 未开局

    # ---- 事件层 --------------------------------------------------------
    def _s(self):
        """开局后的状态访问器——未开局就动状态，合同违约。"""
        if self.state is None:
            raise ContractError("game not started")
        return self.state

    def emit(self, **fields):
        ev = {"session_id": self.session_id, "seq": len(self.events),
              "ts": _now(), **fields}
        validate(ev, "event")
        self.events.append(ev)
        self.apply(ev)
        return ev

    def apply(self, ev):
        if self.state is None:
            if ev["type"] != "game_start":
                raise ContractError("first event must be game_start")
            self._init_state()
            return
        t = ev["type"]
        if t == "act_begin":
            self._s()["act_id"] = ev["act_id"]
            self._s()["scene_id"] = None
        elif t == "scene_begin":
            self._s()["scene_id"] = ev["scene_id"]
        elif t in ("player_line", "agent_line"):
            cs = self._s()["character_states"][ev["character_id"]]
            cs["lines_spoken"] += 1
        elif t == "reveal":
            for k in ev.get("reveal_keys", []):
                for cid, cs in self._s()["character_states"].items():
                    if self.bundle.chars[cid].get("is_player"):
                        cs["knowledge_unlocked"].append(k)  # 真相揭示给玩家视角
        elif t == "prop_gained":
            self._s()["props_held"].append(ev["prop_id"])
        elif t == "card_draw":
            self._s()["cards_drawn"].append(ev["card_id"])
        # act_end/game_end/review：状态不动，事件为证

    def _init_state(self):
        self.state = {
            "bundle_id": self.bundle.data["id"],
            "act_id": None, "scene_id": None, "seq": -1,
            "character_states": {
                c["id"]: {"on_stage": True, "lines_spoken": 0,
                          "knowledge_unlocked": []}
                for c in self.bundle.data["characters"]},
            "props_held": [], "cards_drawn": [], "cg_unlocked": [],
            "degradation_tier": self.tier,
        }

    # ---- 游玩操作 ------------------------------------------------------
    def start(self):
        self.emit(type="game_start")
        first = self.bundle.data["acts"][0]["act_id"]
        self.emit(type="act_begin", act_id=first)
        return self

    def enter_scene(self, scene_id):
        self.emit(type="scene_begin", act_id=self._s()["act_id"], scene_id=scene_id)

    def line(self, cid, text):
        t = "player_line" if self.bundle.chars[cid].get("is_player") else "agent_line"
        self.emit(type=t, character_id=cid, act_id=self._s()["act_id"],
                  scene_id=self._s()["scene_id"], text=text)

    def fire_reveals(self, scene_id):
        """场景内的揭示一次性结算。"""
        scene = self.bundle.scenes(self._s()["act_id"])[scene_id]
        keys = scene.get("reveals", [])
        if keys:
            self.emit(type="reveal", act_id=self._s()["act_id"],
                      scene_id=scene_id, reveal_keys=keys)

    def gain_prop(self, prop_id):
        self.emit(type="prop_gained", act_id=self._s()["act_id"], prop_id=prop_id)

    def next_act(self):
        acts = [a["act_id"] for a in self.bundle.data["acts"]]
        i = acts.index(self._s()["act_id"])
        self.emit(type="act_end", act_id=self._s()["act_id"])
        if i + 1 < len(acts):
            self.emit(type="act_begin", act_id=acts[i + 1])
        else:
            self.emit(type="game_end", review_text=None)

    # ---- 防剧透：agent 视野 = 到当前幕为止 + 已揭示 ----------------------
    def agent_view(self, cid):
        c = self.bundle.chars[cid]
        acts = self.bundle.data["acts"]
        i = [a["act_id"] for a in acts].index(self._s()["act_id"])
        ctx = {"world": [a["world_info"] for a in acts[: i + 1]],
               "public_sheet": c["public_sheet"],
               "secret_sheet": c.get("secret_sheet", "")[: 200 * (i + 1)],
               "knowledge_unlocked":
                   self._s()["character_states"][cid]["knowledge_unlocked"],
               "note": "AI演员不能知道还没演到的真相"}
        return ctx

    # ---- 快照 ----------------------------------------------------------
    def to_snapshot(self):
        snap = {"session_id": self.session_id,
                "bundle_id": self._s()["bundle_id"],
                "act_id": self._s()["act_id"],
                "scene_id": self._s()["scene_id"],
                "seq": len(self.events) - 1,
                "character_states": self._s()["character_states"],
                "props_held": self._s()["props_held"],
                "cards_drawn": self._s()["cards_drawn"],
                "cg_unlocked": self._s()["cg_unlocked"],
                "degradation_tier": self._s()["degradation_tier"]}
        validate(snap, "snapshot")
        return snap

    @classmethod
    def replay(cls, bundle, events):
        """事件流 → 完整对局。复盘/断点续演/对拍的地基。"""
        s = cls(bundle, tier=events[0].get("tier", "tangwu"))
        for ev in events:
            validate(ev, "event")
            if ev["session_id"] != s.session_id:
                s.session_id = ev["session_id"]  # 重建原局 id
            s.events.append(ev)
            s.apply(ev)
        return s
