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
        self.deaths = {d["id"]: d for d in data.get("deaths", [])}

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
            cid = ev["character_id"]
            if cid in self._s()["character_states"]:  # DM 等非 bundle 说话人不计数
                self._s()["character_states"][cid]["lines_spoken"] += 1
        elif t == "reveal":
            for k in ev.get("reveal_keys", []):
                for cid, cs in self._s()["character_states"].items():
                    if self.bundle.chars[cid].get("is_player"):
                        cs["knowledge_unlocked"].append(k)  # 真相揭示给玩家视角
        elif t == "death":
            # 死亡=确定性状态翻转：alive->False。事件在流里，重放即复现
            cid = ev["character_id"]
            self._s()["character_states"][cid]["alive"] = False
            self._s()["character_states"][cid]["on_stage"] = False
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
                c["id"]: {"on_stage": True, "alive": True, "lines_spoken": 0,
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
        self._settle_deaths(scene_id)

    def _settle_deaths(self, scene_id):
        """死亡结算：scene.deaths 按定义表确定性触发。进场景即结算（对应原作
        节拍），无随机无时间；重复进入同一场景不重复杀（事件流里查重）。"""
        scene = self.bundle.scenes(self._s()["act_id"])[scene_id]
        for did in scene.get("deaths", []):
            if any(e["type"] == "death" and e.get("death_id") == did
                   for e in self.events):
                continue  # 幂等：同一定义只死一次
            d = self.bundle.deaths[did]
            self.emit(type="death", death_id=did, character_id=d["character_id"],
                      act_id=d["act_id"], scene_id=d["scene_id"],
                      channel="main", text=d["description"])

    def line(self, cid, text, channel="main", pose=None):
        # 死者不以角色身份进推进通道：main 拒绝（观演者与 DM/复盘的交流
        # 走 DM 主框或 channel，不占剧情推进位）
        if (cid in self._s()["character_states"]
                and not self._s()["character_states"][cid]["alive"]
                and channel == "main"):
            raise ContractError(
                f"character {cid} is dead (observer); cannot speak in main")
        t = "player_line" if self.bundle.chars[cid].get("is_player") else "agent_line"
        kw = dict(type=t, character_id=cid, act_id=self._s()["act_id"],
                  text=text, channel=channel)
        if pose is not None:  # 动作标注：生成管线异步差分立绘的记账位
            kw["pose"] = pose
        if self._s()["scene_id"] is not None:  # 幕已开未进场景=诚实省略，同 DM._stage
            kw["scene_id"] = self._s()["scene_id"]
        self.emit(**kw)

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
        if cid == "dm":
            # DM 全知视角：不走角色切片（防剧透线不适用于主持人）
            return {"dm": True,
                    "act_id": self._s()["act_id"],
                    "scene_id": self._s()["scene_id"],
                    "note": "DM 全知：完整世界信息在 dm_prompt 端点"}
        c = self.bundle.chars[cid]
        acts = self.bundle.data["acts"]
        i = [a["act_id"] for a in acts].index(self._s()["act_id"])
        alive = self._s()["character_states"][cid]["alive"]
        ctx = {"world": [a["world_info"] for a in acts[: i + 1]],
               "public_sheet": c["public_sheet"],
               "secret_sheet": c.get("secret_sheet", "")[: 200 * (i + 1)],
               "knowledge_unlocked":
                   self._s()["character_states"][cid]["knowledge_unlocked"],
               "alive": alive,
               "note": "AI演员不能知道还没演到的真相"}
        if not alive:
            # 观演视角：不退场，改看戏。幕切片与防剧透线不变（观演≠全知）
            ctx["observer"] = True
            ctx["observer_brief"] = self._observer_brief(cid)
            ctx["note"] = ("你已退场，转为观察者视角看戏。"
                           "AI演员不能知道还没演到的真相。")
        return ctx

    def _observer_brief(self, cid):
        for d in self.bundle.deaths.values():
            if d["character_id"] == cid:
                return d.get("observer_brief",
                             "肉身已谢幕，你的目光留在台上——只看，不再推进。")
        return "肉身已谢幕，你的目光留在台上——只看，不再推进。"

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


class AgentPort:
    """降级接口座——AI 演员的台词从哪来。三档同一接口进（架构横切项）。
    pianist 档：接 pianist 最简版（无自学习无自驱动，带任务编排=conductor）。
    tangwu 档：堂屋代理顶班。semi_manual 档：人工/脚本提示。
    demo 当天按 pianist 健康度现场选档，引擎不感知差别。"""

    def __init__(self, tier="tangwu"):
        self.tier = tier

    def respond(self, session, cid):
        raise NotImplementedError


class SemiManualPort(AgentPort):
    """半人工档：预排练的台词表按 (角色, 场景, 已发言次数) 查表。排练过的确定性输出。"""

    def __init__(self, script_lines):
        super().__init__(tier="semi_manual")
        self.script = script_lines  # {(cid, scene_id, nth): text}

    def respond(self, session, cid):
        st = session._s()
        nth = st["character_states"].get(cid, {}).get("lines_spoken", 0)
        return self.script.get((cid, st["scene_id"], nth),
                               "……（半人工档：无预排练台词）")


class PianistPort(AgentPort):
    """pianist 档：调 pianist 编排层（conductor）。最简版 tideline 带跨局复盘记忆。
    接口约定：POST {snapshot, agent_view, cue} -> {line}。联调窗前先立座，不锁实现。"""

    def __init__(self, endpoint=None):
        super().__init__(tier="pianist")
        self.endpoint = endpoint  # None = 未接线，respond 时明确报错

    def respond(self, session, cid):
        if not self.endpoint:
            raise ContractError("pianist 未接线：endpoint 未配置（联调窗定）")
        import json as _json, urllib.request as _u
        payload = _json.dumps({"snapshot": session.to_snapshot(),
                               "agent_view": session.agent_view(cid),
                               "cue": {"act": session._s()["act_id"],
                                       "scene": session._s()["scene_id"]}}).encode()
        req = _u.Request(self.endpoint, data=payload,
                         headers={"Content-Type": "application/json"})
        with _u.urlopen(req, timeout=30) as resp:
            data = _json.load(resp)
        if not data.get("line"):  # 服务报错（预算闸/无key/异常）时给可读降级，不炸引擎
            detail = data.get("detail") or data.get("error") or "no line"
            return f"……（pianist 档：服务报错降级 | {detail}）"
        return data["line"]
