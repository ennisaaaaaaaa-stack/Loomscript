#!/usr/bin/env python3
"""终审负向钉（2026-10-31 太阳哥 Loomscript FIX-FIRST 单的修复验收）。

四枚钉，全部真起进程真打 HTTP：
  D1. P0-02 五态+timeout：PianistPort.respond 在 env 空/畸形 URL/连接拒绝/
      HTML 200/HTTP 500 JSON/读超时下，每态断言「不 raise、返回预生成 fallback」
      （降级串被 DM.speak 的 L3 兜底替换成 bundle.dm_lines.fallback）。
  D2. P0-01 全链：HTTP 建局(pianist 档)→玩家 say→pianist ledger 出现 /agent
      真调用账行（kind=dm）+ 事件流出现 dm 的 agent_line——不再假全链。
  D3. P1-01 DM 身份：D2 那笔 /agent 请求体里 kind=="dm" 且 material 带
      full_script（全知材料真送到了，不再是空名角色）。
  D4. P1-02 预算并发：PIANIST_DAILY_CALLS=1，8 并发只准 1 个 ok——
      原子占位闸生效；healthz.calls_today 仍为 1（占位不重复计数）。

纪律：与 test_pianist_runtime 同款——拉起的孩子全部带走，端口预检防孤儿。
"""
import atexit
import concurrent.futures as cf
import json
import os
import pathlib
import signal
import socket
import subprocess
import sys
import time

import httpx

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

results = []

JOBS = ROOT / "loom_jobs" / "pianist"
LEDGER = JOBS / "pianist_ledger.jsonl"
SVC_PORT = 18751
GAME_PORT = 18752
SVC = f"http://127.0.0.1:{SVC_PORT}"

CHILDREN = []


def kill_all():
    for p in CHILDREN:
        if p.poll() is None:
            p.send_signal(signal.SIGTERM)
    for p in CHILDREN:
        try:
            p.wait(timeout=5)
        except Exception:
            p.kill()


atexit.register(kill_all)


def check(name, fn):
    try:
        fn()
        results.append((name, "GREEN", ""))
    except Exception as e:
        results.append((name, "RED", repr(e)[:200]))


def read_ledger():
    rows = []
    if LEDGER.exists():
        for line in LEDGER.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def spawn_child(argv, env):
    p = subprocess.Popen(argv, cwd=str(ROOT), env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    CHILDREN.append(p)
    return p


def wait_health(client, tries=60):
    for _ in range(tries):
        try:
            if client.get("/healthz").json().get("ok"):
                return
        except Exception:
            pass
        time.sleep(0.25)
    raise RuntimeError("healthz 60 次未就绪")


def port_free(port):
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("127.0.0.1", port))
    except OSError:
        return False
    finally:
        s.close()
    return True


for p in (SVC_PORT, GAME_PORT):
    if not port_free(p):
        print(f"REFUSED: {p} 被占用——先清孤儿进程")
        sys.exit(2)

JOBS.mkdir(parents=True, exist_ok=True)
LEDGER.unlink(missing_ok=True)

env_stub = {**os.environ, "PIANIST_STUB": "1", "PIANIST_PORT": str(SVC_PORT),
            "PIANIST_JOBS_DIR": str(JOBS)}
env_game = {**env_stub, "PIANIST_AGENT_URL": f"{SVC}/agent",
            "PORT": str(GAME_PORT)}

# ---- 先起 pianist_service（stub 档，真 HTTP） ----
svc = spawn_child([sys.executable, str(ROOT / "src" / "pianist_service.py"),
                   "--port", str(SVC_PORT)], env_stub)

# ---- D1. P0-02 五态+timeout：不 raise、走 fallback ----
def t_d1_five_states():
    from dm import DM
    from engine import Bundle, PianistPort, Session, SemiManualPort  # noqa: F401

    bundle = Bundle.load(ROOT / "bundles" / "macbeth_mini.json")
    session = Session(bundle, tier="tangwu")
    session.start()

    def dm_line_for(endpoint):
        port = PianistPort(endpoint=endpoint)
        dm = DM(bundle, port)
        line = dm.speak(session, message="你怎么看？")
        return line

    fallback = bundle.data["dm_lines"]["fallback"]
    # 态1: env 空 → make_port 缺省 url（127.0.0.1:8741 没人听 → 连接拒绝，收敛）
    l1 = dm_line_for("http://127.0.0.1:59999/agent")   # 连接拒绝
    l2 = dm_line_for("not-a-url")                      # 畸形 URL
    l3 = dm_line_for("")                               # 空配置 → 可读降级（态3）
    # 态4/5: HTML 200 / HTTP 500 JSON —— 起两个一次性小服务
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class HTMLHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html>proxy login page</html>")


    class ErrHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.dumps({"ok": False, "error": "boom"}).encode()
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)


    hs = {}
    for name, h, port in (("html", HTMLHandler, 18761), ("err", ErrHandler, 18762)):
        hs[name] = HTTPServer(("127.0.0.1", port), h)
        threading.Thread(target=hs[name].serve_forever, daemon=True).start()
    try:
        l4 = dm_line_for("http://127.0.0.1:18761/agent")   # HTML 200
        l5 = dm_line_for("http://127.0.0.1:18762/agent")   # HTTP 500 JSON
    finally:
        for h in hs.values():
            h.shutdown()
    for i, line in enumerate((l1, l2, l4, l5), 1):
        assert line == fallback, f"态{i} 未走预生成 fallback: {line!r}"
    assert l3 == fallback, f"态3 未走 fallback: {l3!r}"
    # 超时态：起一个睡 30s 的服务，port timeout 设 1s —— PIANIST_PORT_TIMEOUT
    os.environ["PIANIST_PORT_TIMEOUT"] = "1"

    class SleepHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            time.sleep(30)


    hs2 = HTTPServer(("127.0.0.1", 18763), SleepHandler)
    threading.Thread(target=hs2.serve_forever, daemon=True).start()
    try:
        t0 = time.time()
        l6 = dm_line_for("http://127.0.0.1:18763/agent")
        dt = time.time() - t0
        assert l6 == fallback, f"超时态未走 fallback: {l6!r}"
        assert dt < 10, f"超时态耗时 {dt:.1f}s——timeout 没生效"
    finally:
        hs2.shutdown()
        os.environ.pop("PIANIST_PORT_TIMEOUT", None)


check("D1-p0-02-five-states-timeout", t_d1_five_states)

# ---- D2+D3. P0-01 全链 + P1-01 DM 身份 ----
captured = []


def t_d23_full_chain():
    # 在 pianist_service 前面垫一个记录代理：转发到真服务，留底请求体
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class RecordingProxy(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(n)
            try:
                captured.append(json.loads(body))
            except Exception:
                captured.append({"_raw": body[:200].decode(errors="replace")})
            # 转发到真 pianist_service
            fwd = httpx.post(f"{SVC}/agent", content=body,
                             headers={"Content-Type": "application/json"},
                             timeout=30)
            self.send_response(fwd.status_code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(fwd.content)


    proxy = HTTPServer(("127.0.0.1", 18764), RecordingProxy)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()

    env_proxy = {**env_game, "PIANIST_AGENT_URL": "http://127.0.0.1:18764/agent"}
    game = spawn_child([sys.executable, str(ROOT / "src" / "server.py"),
                        "--port", str(GAME_PORT)], env_proxy)
    c = httpx.Client(base_url=f"http://127.0.0.1:{GAME_PORT}", timeout=30)
    try:
        for _ in range(60):
            try:
                if c.get("/healthz").status_code == 200:
                    break
            except Exception:
                time.sleep(0.25)
        else:
            raise RuntimeError("game server 未就绪")

        g = c.post("/games", json={"bundle_id": "macbeth_mini",
                                   "port": "pianist"}).json()
        sid = g["session_id"]
        assert g["snapshot"]["act_id"], g

        r = c.post(f"/games/{sid}/say",
                   json={"character_id": "macbeth", "text": "今夜可有异象？"})
        assert r.status_code == 200, r.text
        evs = r.json()["events"]
        dm_lines = [e for e in evs
                    if e.get("type") == "agent_line" and e.get("character_id") == "dm"]
        assert dm_lines, f"DM 未接话: {[e['type'] for e in evs]}"
        assert not dm_lines[0]["text"].startswith("……（pianist 档：服务报错降级"), \
            f"stub 档不该降级: {dm_lines[0]['text']!r}"
    finally:
        c.close()
        proxy.shutdown()
        game.send_signal(signal.SIGTERM)
        try:
            game.wait(timeout=5)
        except subprocess.TimeoutExpired:
            game.kill()

    # D3：代理留底的请求体——kind=dm + 全知材料
    assert captured, "pianist /agent 从未被调用——假全链仍在"
    req = captured[0]
    assert req.get("kind") == "dm", f"kind 不是 dm: {req.get('kind')!r}"
    mat = req.get("material") or {}
    assert mat.get("full_script"), "全知材料没送到（P1-01）"
    assert mat.get("you_are") and "主持人" in mat["you_are"], mat.get("you_are")


check("D2-p0-01-full-chain", t_d23_full_chain)

# ---- D4. P1-02 预算并发：DAILY_CALLS=1，8 并发只准 1 个 ok ----
def t_d4_budget_concurrency():
    svc.send_signal(signal.SIGTERM)
    try:
        svc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        svc.kill()
    LEDGER.unlink(missing_ok=True)
    env_1 = {**env_stub, "PIANIST_DAILY_CALLS": "1"}
    svc2 = spawn_child([sys.executable, str(ROOT / "src" / "pianist_service.py"),
                        "--port", str(SVC_PORT)], env_1)
    try:
        c = httpx.Client(base_url=SVC, timeout=15)
        wait_health(c)

        def hit(_):
            try:
                r = c.post("/agent", json={"kind": "dm",
                                           "message": "并发压测"}).json()
                return bool(r.get("ok"))
            except Exception:
                return False

        with cf.ThreadPoolExecutor(max_workers=8) as ex:
            oks = list(ex.map(hit, range(8)))
        assert sum(oks) == 1, f"8 并发 ok={sum(oks)}——预算闸被穿透（P1-02）"
        h = c.get("/healthz").json()
        assert h["calls_today"] == 1, f"calls_today={h['calls_today']}——占位重复计数"
        c.close()
    finally:
        svc2.send_signal(signal.SIGTERM)
        try:
            svc2.wait(timeout=5)
        except subprocess.TimeoutExpired:
            svc2.kill()


check("D4-p1-02-budget-concurrency", t_d4_budget_concurrency)

# ---- 报告 ----
green = sum(1 for _, s, _ in results if s == "GREEN")
for name, st, note in results:
    mark = f"{st:5}"
    tail = f"  | {note}" if note else ""
    print(f"{mark} {name}{tail}")
print(f"\n{green}/{len(results)} GREEN")
sys.exit(0 if green == len(results) else 1)
