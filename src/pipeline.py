#!/usr/bin/env python3
"""Loomscript 生成编排 DAG + 死后拉起（7.2 + 7.3）。

写死 DAG，不装自主 conductor（10/28 确定性拍板）：
  parse_input -> build_acts -> gen_characters(N并发) -> gen_actor_turns(N并发)
  -> gen_cg_list -> gen_props_journal -> validate_bundle
stage barrier 明写：前一 stage 全绿才进下一个。

死后拉起（台账+心跳+幂等续跑）：
  台账 loom_jobs/<run_id>/ledger.json，任务 {task_id, stage, input_hash,
  status, output_ref, attempts, updated_at}。worker 死了重拉；output_ref
  已存在且 status=done -> 跳过。逐字节重放的对局期姊妹篇：生成期用台账
  断点续跑，对局期用快照重放复活，同一哲学——确定性=可恢复。

生成 stage 本体是 stub（恒等/简单变换）：DAG/台账/barrier/恢复机制是真的，
比赛现场真生成接咖啡哥 prompt 零件（设计文档 §7.2）。
"""
import hashlib
import json
import os
import pathlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor

WORKERS = 2  # 并发预算证明用；现场可调

# (stage 名, 是否 fanout)
STAGES = [
    ("parse_input", False),
    ("build_acts", False),
    ("gen_characters", True),
    ("gen_actor_turns_per_act", True),
    ("gen_cg_list", False),
    ("gen_props_journal", False),
    ("validate_bundle", False),
]


# ---------------------------------------------------------------- 台账

def _hash(obj):
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


class Ledger:
    """任务台账：落盘 JSON，写入原子（唯一 tmp+rename）。心跳=updated_at。

    线程安全：flush 串行化（锁），tmp 文件名带线程 id——并发 fanout 的
    多 worker 同时记账不互踩（同一路径 tmp 会被 replace 拿走）。
    """

    def __init__(self, run_dir: pathlib.Path):
        self.path = run_dir / "ledger.json"
        self.out_dir = run_dir / "outputs"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.tasks = {}
        self._lock = __import__("threading").Lock()
        self._seq = 0
        if self.path.exists():
            self.tasks = json.loads(self.path.read_text(encoding="utf-8"))

    def _flush(self):
        with self._lock:
            self._seq += 1
            tmp = self.path.with_name(
                f"ledger.{self._seq}.tmp")
            tmp.write_text(json.dumps(self.tasks, ensure_ascii=False, indent=1),
                           encoding="utf-8")
            tmp.replace(self.path)

    def claim(self, task_id, stage, input_hash):
        """领任务：已 done 且产物在 -> None（跳过）；否则记 attempt 返回任务位。"""
        t = self.tasks.get(task_id)
        if t and t["status"] == "done" and t["output_ref"] and \
                pathlib.Path(t["output_ref"]).exists():
            return None
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        t = {"task_id": task_id, "stage": stage, "input_hash": input_hash,
             "status": "running", "output_ref": None,
             "attempts": (t["attempts"] + 1) if t else 1, "updated_at": now}
        self.tasks[task_id] = t
        self._flush()
        return t

    def complete(self, task_id, output):
        p = self.out_dir / f"{task_id}.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
        t = self.tasks[task_id]
        t.update(status="done", output_ref=str(p),
                 updated_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
        self._flush()

    def fail(self, task_id, err):
        t = self.tasks[task_id]
        t.update(status="failed", error=str(err)[:200],
                 updated_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
        self._flush()

    def stage_status(self, stage):
        st = [t for t in self.tasks.values() if t["stage"] == stage]
        if not st:
            return "pending"
        if all(t["status"] == "done" for t in st):
            return "done"
        if any(t["status"] == "failed" for t in st):
            return "failed"
        return "partial"

    def done_count(self):
        return sum(1 for t in self.tasks.values() if t["status"] == "done")


# ---------------------------------------------------------------- stage 本体（stub 生成）

def stage_fns():
    """各 stage 的生成函数（stub：确定性恒等/轻量变换）。

    真实现=咖啡哥 prompt 零件；此处结构与签名是真的。
    每个函数 (整体输入, 任务负载) -> 任务输出。
    """
    def parse_input(doc, item):
        return {"chars_raw": doc.get("characters", []),
                "acts_raw": doc.get("acts", []), "meta": doc.get("meta", {})}

    def build_acts(parsed, item):
        return {"act_ids": [a["act_id"] for a in parsed["acts_raw"]],
                "n_acts": len(parsed["acts_raw"])}

    def gen_character(parsed, item):
        c = dict(item)
        c.setdefault("voice", "待生成")
        c["gen"] = True
        return c

    def gen_actor_turns(acts_info, item):
        act_id = item["act_id"]
        chars = item["characters"]
        return {act_id: {cid: [{"cue": f"{act_id}/{cid}/t{i}",
                                "line": "（待咖啡哥零件生成）"} for i in range(2)]
                         for cid in chars}}

    def gen_cg_list(parsed, item):
        return {"cg": [f"cg_{aid}" for aid in parsed["act_ids"]]}

    def gen_props_journal(parsed, item):
        return {"props_journal": [f"prop_{aid}" for aid in parsed["act_ids"]]}

    def validate_bundle(doc, item):
        # 结构校验 stub：关键字段在场（真实现走 bundle.schema）
        for k in ("id", "title", "characters", "acts"):
            if k not in doc:
                raise ValueError(f"bundle missing field: {k}")
        return {"valid": True}

    return {"parse_input": parse_input, "build_acts": build_acts,
            "gen_characters": gen_character,
            "gen_actor_turns_per_act": gen_actor_turns,
            "gen_cg_list": gen_cg_list,
            "gen_props_journal": gen_props_journal,
            "validate_bundle": validate_bundle}


# ---------------------------------------------------------------- 进度事件（生成进度=事件流）

def progress(run_dir, stage, msg):
    """进度事件追加落盘（前端时间线组件可复用同一渲染路）。"""
    p = run_dir / "progress.jsonl"
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                            "stage": stage, "msg": msg}, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- DAG 执行

class PipelineError(Exception):
    pass


def run_pipeline(doc, run_dir, crash_after=None):
    """跑完写死 DAG。crash_after=k: 完成 k 个任务后进程自杀（恢复测试用）。

    返回最终 bundle 字典。幂等：重跑跳过 done 任务。
    """
    run_dir = pathlib.Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    led = Ledger(run_dir)
    fns = stage_fns()

    # 载入已完成任务的输出（断点续跑的输入材料）
    def out_of(task_id):
        t = led.tasks.get(task_id)
        if t and t["status"] == "done":
            return json.loads(pathlib.Path(t["output_ref"]).read_text("utf-8"))
        return None

    completed = 0

    def exec_task(task_id, stage, input_hash, fn, arg, item):
        nonlocal completed
        if led.claim(task_id, stage, input_hash) is None:
            progress(run_dir, stage, f"skip {task_id} (done)")
            return out_of(task_id)
        progress(run_dir, stage, f"run {task_id}")
        try:
            res = fn(arg, item)
            led.complete(task_id, res)
            completed += 1
            if crash_after is not None and completed >= crash_after:
                progress(run_dir, stage, f"CRASH after {completed} tasks")
                os._exit(70)  # 模拟 worker 死亡（不清理，台账即现场）
            return res
        except Exception as e:  # noqa: BLE001 台账记失败，barrier 拦截
            led.fail(task_id, e)
            raise

    # stage 1: parse_input（串行）
    r = exec_task("parse_input", "parse_input", _hash(doc),
                  fns["parse_input"], doc, None)
    # stage 2: build_acts（串行）
    acts_info = exec_task("build_acts", "build_acts", _hash(r),
                          fns["build_acts"], r, None)
    # barrier：parse/build 必须成功才进生成段（上面 raise 会直接冒出）

    # stage 3: gen_characters（fanout N 并发）
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(exec_task, f"gen_characters:{c['id']}",
                          "gen_characters", _hash(c),
                          fns["gen_characters"], r, c): c["id"]
                for c in r["chars_raw"]}
        chars = [f.result() for f in futs]  # barrier：全部结算
    # 任一失败 -> raise，后续 stage 不进（stage_status 也会显 failed）

    # stage 4: gen_actor_turns_per_act（fanout）
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        items = [{"act_id": aid,
                  "characters": [c["id"] for c in r["chars_raw"]]}
                 for aid in acts_info["act_ids"]]
        futs = [ex.submit(exec_task, f"gen_actor_turns:{it['act_id']}",
                          "gen_actor_turns_per_act", _hash(it),
                          fns["gen_actor_turns_per_act"], r, it)
                for it in items]
        turns_list = [f.result() for f in futs]
    actor_turns = {}
    for t in turns_list:
        actor_turns.update(t)

    # stage 5/6: cg + props_journal（可并行——对拍 §7.2「后两段并行」）
    with ThreadPoolExecutor(max_workers=2) as ex:
        f1 = ex.submit(exec_task, "gen_cg_list", "gen_cg_list", _hash(acts_info),
                       fns["gen_cg_list"], acts_info, None)
        f2 = ex.submit(exec_task, "gen_props_journal", "gen_props_journal",
                       _hash(acts_info), fns["gen_props_journal"], acts_info, None)
        cg, props = f1.result(), f2.result()

    # stage 7: validate_bundle（barrier 终点）
    bundle = dict(doc)
    bundle["characters"] = chars
    bundle["actor_turns"] = actor_turns
    bundle["generated"] = {"cg": cg["cg"], "props_journal": props["props_journal"]}
    exec_task("validate_bundle", "validate_bundle", _hash(bundle),
              fns["validate_bundle"], bundle, None)

    progress(run_dir, "validate_bundle", "DAG complete")
    return bundle
