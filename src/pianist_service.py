#!/usr/bin/env python3
"""pianist service — 自带进场 的 agent 运行时（Emergence-Pianist 内置版）。

血统：从家宅 conductor 移植的拉起纪律，砍到 Loomscript 需要的形状——
  留：一次一令的 session 模型、预算闸（机械计数硬停）、死亡留名、
      尾巴截取（验尸材料）、同解释器钉子（launch 侧）。
  砍：part 池/漫游/自学习热点扫描/spoor 审批环/shell 治理层
      （10/28 拍板：演出运行时全确定性，不装自学习自驱动）。

接口（PianistPort 合同的超集，engine.PianistPort 零改动可打）：
  POST /agent    {snapshot?, agent_view?, cue?, kind?, material?, message?} -> {line}
  GET  /healthz  {ok, calls_today, budget, model, stub}

纪律落地：
- 预算闸：当日 llm_call 尝试数（成败都计，与 conductor 数 draws 同口径）
  >= PIANIST_DAILY_CALLS → 429 硬停，报错明说。计数从盘上 ledger 重放——
  服务重启不洗预算（重启不是免费额度）。
- 死亡留名：SIGTERM/正常关停落 service_down 行——拆下来的器官不喊疼，
  但关停必须有账（家规：丢数据要响）。
- stub 档：PIANIST_STUB=1 → 零网络确定性应答（前端联调/测试/无key演示）。
"""
import json
import os
import pathlib
import threading
import time
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

STUB = os.environ.get("PIANIST_STUB") == "1"
JOBS_DIR = pathlib.Path(os.environ.get(
    "PIANIST_JOBS_DIR", pathlib.Path(__file__).resolve().parent.parent / "loom_jobs" / "pianist"))
LEDGER = JOBS_DIR / "pianist_ledger.jsonl"
DAILY_CALLS = int(os.environ.get("PIANIST_DAILY_CALLS", "300"))
LLM_BASE_URL = os.environ.get("PIANIST_LLM_BASE_URL", "")
LLM_API_KEY = os.environ.get("PIANIST_LLM_API_KEY", "")
LLM_MODEL = os.environ.get("PIANIST_LLM_MODEL", "glm-5.2")
LLM_TIMEOUT = float(os.environ.get("PIANIST_LLM_TIMEOUT", "45"))

_ledger_lock = threading.RLock()  # RLock：占位闸内嵌调 ledger()，可重入不自杀
_budget_state = {"date": None, "count": 0}  # 锁内热账：跨请求原子占位（终审 P1-02）


def _try_reserve_budget(kind: str) -> bool:
    """锁内原子「检查+占位」（终审 P1-02）：预算内先记账再放行，超了落
    budget_exhausted 账拒进。计数仍以盘上 ledger 为准（重启不洗预算），
    热账只是同进程内的并发闸——首调时从盘重放预热。"""
    with _ledger_lock:
        today = _now()[:10]
        if _budget_state["date"] != today:
            _budget_state.update(date=today, count=calls_today())
        if _budget_state["count"] >= DAILY_CALLS:
            # 拒进账行用 llm_reject 类型：不计入 calls_today——
            # 预算耗尽后的重试不该继续抬高计数（否则闸越拒越紧）
            ledger({"type": "llm_reject", "kind": kind,
                    "status": "budget_exhausted"})
            return False
        # 占位账先落：后面的 llm_call 账只更新状态，不重复计数
        _budget_state["count"] += 1
        ledger({"type": "llm_call", "kind": kind, "ok": None,
                "status": "reserved"})
        return True


def _settle_budget(kind: str, ok: bool, status: str, **extra):
    """占位 → 终态：reserved 之后的那笔终态账改用 settle 类型，
    calls_today 只数 llm_call（含 reserved 占位），不重复计数。"""
    ledger({"type": "llm_settle", "kind": kind, "ok": ok,
            "status": status, **extra})

app = FastAPI(title="Loomscript pianist runtime")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])


def _now():
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def ledger(row: dict):
    """追加一行账。唯一写入口——预算闸与死亡留名都从这里读回。"""
    row = {"ts": _now(), **row}
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    with _ledger_lock:
        with open(LEDGER, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def calls_today() -> int:
    """当日 llm_call 尝试数。从盘重放——重启不洗预算。"""
    today = _now()[:10]
    n = 0
    try:
        with open(LEDGER, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get("type") == "llm_call" and str(r.get("ts", "")).startswith(today):
                    n += 1
    except FileNotFoundError:
        return 0
    return n


# ---------------------------------------------------------------- LLM 调用

def llm_chat(system: str, user: str) -> str:
    """OpenAI 兼容 /chat/completions，urllib 直连——运行时不引新依赖。"""
    import urllib.request
    payload = json.dumps({
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.8,
    }).encode()
    req = urllib.request.Request(
        LLM_BASE_URL.rstrip("/") + "/chat/completions", data=payload,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {LLM_API_KEY}"})
    with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as resp:
        data = json.load(resp)
    return data["choices"][0]["message"]["content"]


def build_messages(body: dict):
    """三类牌面 → (system, user)。合同字段（snapshot/agent_view/cue）与
    富材料（material/message）都收——PianistPort 薄路径与 server 富路径共用一门。"""
    kind = body.get("kind") or "character"
    if kind == "dm":
        m = body.get("material") or {}
        system = (
            "你是剧本杀《%s》的主持人（DM）。认识玩家，可陪伴可交流。\n"
            "规则：不替玩家做任何决定；回复简短自然（1-3句，中文口语）；"
            "可以引用材料里的预生成台词但别照本宣科。\n"
            "------ 材料 JSON ------\n%s" % (
                m.get("title", ""), json.dumps(m, ensure_ascii=False)))
        user = str(body.get("message") or "（玩家在看你）")
    elif kind == "distill":
        system = str(body.get("material") or "")
        user = "（按 system 指令产出，不要额外解释）"
    else:  # character
        m = body.get("material") or {}
        you = m.get("you_are") or {}
        system = (
            "你是剧本杀角色「%s」。只根据材料说话——材料里没有的就是你不知道的。\n"
            "输出一句台词（不超过60字，中文），只输出台词本身，不要旁白不要解释。\n"
            "------ 材料 JSON ------\n%s" % (
                you.get("name", ""),
                json.dumps(m, ensure_ascii=False)))
        user = "轮到你了，说你的台词。"
    return system, user


class AgentRequest(BaseModel):
    snapshot: dict | None = None
    agent_view: dict | None = None
    cue: dict | None = None
    kind: str | None = None
    material: dict | None = None
    message: str | None = None


@app.post("/agent")
def agent(body: AgentRequest):
    raw = body.model_dump()
    kind = raw.get("kind") or "character"

    # 预算闸在调用前（conductor：当日 draws 满 → 当天硬停，不商量）。
    # 终审 P1-02：检查+占位收进同一把锁，并发不再穿透。
    if not _try_reserve_budget(kind):
        return {"ok": False, "error": "budget_exhausted",
                "detail": f"今日 {_budget_state['count']}/{DAILY_CALLS} 次已用完（PIANIST_DAILY_CALLS）"}

    t0 = time.time()
    try:
        if STUB:
            time.sleep(0.05)  # 模拟一点延迟，前端 loading 态可见
            m = raw.get("material") or {}
            you = m.get("you_are") or {}
            line = (f"（{kind}·stub·{you.get('name', 'dm')}）"
                    + str(raw.get("message") or "cue=" + json.dumps(
                        raw.get("cue") or {}, ensure_ascii=False))[:40])
            ok, status = True, "stub"
        else:
            if not (LLM_BASE_URL and LLM_API_KEY):
                _settle_budget(kind, False, "no_llm_config")
                return {"ok": False, "error": "no_llm_config",
                        "detail": "PIANIST_LLM_BASE_URL / PIANIST_LLM_API_KEY 未配置"
                                  "（或设 PIANIST_STUB=1 走确定性档）"}
            system, user = build_messages(raw)
            line = llm_chat(system, user)
            ok, status = True, "llm"
        _settle_budget(kind, ok, status,
                       latency_ms=int((time.time() - t0) * 1000))
        return {"ok": True, "line": line}
    except Exception as e:  # 尾巴截取：验尸材料随账落盘
        tail = f"{type(e).__name__}: {e}"[:200]
        _settle_budget(kind, False, "error",
                       latency_ms=int((time.time() - t0) * 1000),
                       error_tail=tail)
        return {"ok": False, "error": "llm_failed", "detail": tail}


@app.get("/healthz")
def healthz():
    return {"ok": True, "stub": STUB, "model": LLM_MODEL,
            "calls_today": calls_today(), "budget": DAILY_CALLS}


@app.on_event("shutdown")
def _shutdown():
    # 死亡留名（家规：拆下来的器官不喊疼，但关停必须有账）
    ledger({"type": "service_down", "reason": "shutdown"})


def main():
    import argparse
    import uvicorn
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int,
                    default=int(os.environ.get("PIANIST_PORT", "8741")))
    args = ap.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
