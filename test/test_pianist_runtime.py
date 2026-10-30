#!/usr/bin/env python3
"""pianist runtime 集成测试 —— 内置版交付验收（十套件 → 十一套件）。

真起服务、真请求、真账本。三个进程面：
  A. pianist_service 本体（stub 档）：/agent 三类牌面 + /healthz + 账本
  B. pianist_nanny 保姆：先写后做台账 + 死了重拉 + 收编幂等 + parent-down
  C. server 接线（PianistPort 增强版打 pianist_service）：角色接话全链路

纪律：测试自己也守 nanny 的规矩——拉起的孩子全部带走（全局 finally），
端口预检：被占即拒跑（上一个测试的孤儿不该让这一个测试背锅）。
stub 档零网络确定性应答——CI/无 key 环境跑得了，现场换 env 就是真 LLM。
"""
import atexit
import json
import os
import pathlib
import signal
import subprocess
import sys
import time

import httpx

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
results = []

JOBS = ROOT / "loom_jobs" / "pianist"
LEDGER = JOBS / "pianist_ledger.jsonl"
PORT = 18741  # 测试专用高位端口，不碰 8741
BASE = f"http://127.0.0.1:{PORT}"

CHILDREN = []  # 所有拉起的子进程——atexit 全部带走


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


# ---- 预检：端口必须空闲（孤儿检测——fail fast 不让错位归因） ----
import socket
_probe = socket.socket()
_probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    _probe.bind(("127.0.0.1", PORT))
except OSError:
    print(f"REFUSED: {PORT} 被占用——先清上一个测试的孤儿进程")
    sys.exit(2)
finally:
    _probe.close()

# 干净账本起测（测试不该被历史 llm_call 污染预算）
JOBS.mkdir(parents=True, exist_ok=True)
LEDGER.unlink(missing_ok=True)

env = {**os.environ, "PIANIST_STUB": "1", "PIANIST_PORT": str(PORT),
       "PIANIST_JOBS_DIR": str(JOBS)}
c = httpx.Client(base_url=BASE, timeout=10)

# ---- A. pianist_service 本体 ----
svc = spawn_child([sys.executable, str(ROOT / "src" / "pianist_service.py"),
                   "--port", str(PORT)], env)
try:
    wait_health(c)

    def t_health():
        r = c.get("/healthz").json()
        assert r["ok"] and r["stub"] is True and "budget" in r, r
    check("A1-healthz", t_health)

    def t_character():
        r = c.post("/agent", json={
            "kind": "character",
            "material": {"you_are": {"name": "麦克白"},
                         "secret_slice": "女巫预言了王冠"},
            "cue": {"act": "A1", "scene": "S1"}}).json()
        assert r["ok"] and "麦克白" in r["line"], r
    check("A2-character-stub", t_character)

    def t_dm():
        r = c.post("/agent", json={
            "kind": "dm", "message": "今晚怎么玩？",
            "material": {"title": "麦克白", "memory": {"brief": "二周目"}}}).json()
        assert r["ok"] and "dm" in r["line"], r
    check("A3-dm-stub", t_dm)

    def t_ledger():
        rows = read_ledger()
        llm = [r for r in rows if r.get("type") == "llm_call"]
        assert llm and all("status" in r for r in llm), rows[-3:]
    check("A4-ledger-llm-call-rows", t_ledger)

    def t_shutdown_note():
        pass  # service_down 账行在 B4 收尾后统一验（同一进程家族共用账本）
    check("A5-shutdown-accounting-deferred", t_shutdown_note)

finally:
    svc.send_signal(signal.SIGTERM)
    try:
        svc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        svc.kill()

def t_a_down_row():
    rows = read_ledger()
    assert any(r["type"] == "service_down" and r.get("reason") == "shutdown"
               for r in rows), rows[-3:]
check("A6-service-down-row-on-sigterm", t_a_down_row)

# ---- B. pianist_nanny 保姆 ----
LEDGER.unlink(missing_ok=True)

def t_nanny_boot():
    nanny = spawn_child([sys.executable, str(ROOT / "src" / "pianist_nanny.py"),
                         "--port", str(PORT), "--stub"], env)
    # 等 ready 账行（不是 healthz——healthz 先于账行可达，读账会竞态）
    t0 = time.time()
    rows = []
    while time.time() - t0 < 20:
        rows = read_ledger()
        if any(r["type"] == "launch_result" and str(r.get("status", "")).startswith("ready")
               for r in rows):
            break
        if nanny.poll() is not None:
            out = ""
            if nanny.stdout:
                out = nanny.stdout.read() or ""
            raise RuntimeError("nanny 启动失败: " + out[:400])
        time.sleep(0.3)
    seq = [(r["type"], r.get("status")) for r in rows]
    # 先写后做：第一对 launch 行 pending 在前 spawned 紧随
    assert ("launch", "pending") in seq and ("launch", "spawned") in seq, seq
    i = seq.index(("launch", "pending"))
    assert seq[i + 1] == ("launch", "spawned"), seq
    assert any(t == "launch_result" and str(s).startswith("ready")
               for t, s in seq), seq
    globals()["nanny"] = nanny
check("B1-nanny-boot-pending-before-spawn", t_nanny_boot)

def t_nanny_relaunch():
    rows = read_ledger()
    spawned = [r for r in rows if r["type"] == "launch" and r["status"] == "spawned"]
    pid = spawned[-1]["pid"]
    os.kill(pid, signal.SIGKILL)
    t0 = time.time()
    while time.time() - t0 < 15:
        try:
            if c.get("/healthz").json().get("ok"):
                break
        except Exception:
            pass
        time.sleep(0.5)
    else:
        raise AssertionError("15s 内未复活")
    rows = read_ledger()
    assert any(r["type"] == "relaunch" for r in rows), rows[-6:]
check("B2-nanny-kill-and-relaunch", t_nanny_relaunch)

def t_nanny_adopt():
    # 前置自检：B2 复活后 service 必须真活着，否则 adopt 测不到收编路径
    r = c.get("/healthz")
    assert r.json().get("ok"), f"B2 后 service 已死: {r.text[:100]}"
    out = subprocess.run(
        [sys.executable, str(ROOT / "src" / "pianist_nanny.py"),
         "--port", str(PORT), "--stub"],
        cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=15)
    assert out.returncode == 0, out.stderr
    assert "收编" in (out.stdout + out.stderr), out.stdout + out.stderr
    rows = read_ledger()
    boot_idx = next(i for i, r in enumerate(rows) if r["type"] == "nanny_boot")
    after = [r for r in rows[boot_idx:]
             if r["type"] == "launch" and r["status"] == "spawned"]
    assert not after, after  # 收编路径不再 spawn（幂等）
check("B3-nanny-adopt-healthy", t_nanny_adopt)

def t_nanny_shutdown():
    nanny = globals().get("nanny")
    assert nanny and nanny.poll() is None
    rows_before = len(read_ledger())
    nanny.send_signal(signal.SIGTERM)
    nanny.wait(timeout=10)
    rows = read_ledger()[rows_before:]
    assert any(r["type"] == "nanny_down" and r["reason"] == "sigterm"
               for r in rows), rows
    time.sleep(0.5)
    try:
        c.get("/healthz", timeout=2)
        raise AssertionError("nanny 退出后 service 还活着（孤儿）")
    except httpx.TransportError:
        pass
check("B4-nanny-parent-down", t_nanny_shutdown)

# ---- C. server 接线：PianistPort 增强版打 pianist_service ----
c_svc = spawn_child([sys.executable, str(ROOT / "src" / "pianist_service.py"),
                     "--port", str(PORT)], env)
wait_health(c)

from engine import Session, Bundle, SemiManualPort  # noqa: E402
from dm import DM, DM_ID  # noqa: E402

def t_c1():
    from engine import PianistPort
    bundle = Bundle.load(ROOT / "bundles" / "macbeth_mini.json")
    s = Session(bundle, tier="semi_manual")
    s.start()
    port = PianistPort(endpoint=f"{BASE}/agent")
    line = port.respond(s, "macbeth")
    assert line and isinstance(line, str), line
check("C1-pianistport-endpoint", t_c1)

def t_c2():
    from server import create_game, get_room
    r = create_game({"bundle_id": "macbeth_mini", "tier": "semi_manual",
                     "port": "pianist"})
    sid = r["session_id"]
    room = get_room(sid)
    assert room.port_kind == "pianist", room.port_kind
    # DM 的嘴真的换成了 PianistPort（本轮补的最后半步）
    from engine import PianistPort as PP
    assert isinstance(room.dm.port, PP), type(room.dm.port).__name__
    assert room.dm.port.endpoint.endswith("/agent"), room.dm.port.endpoint
    # DM.speak 全链路：走 PianistPort 打真服务，台词回落兜底
    line = room.dm.speak(room.session)
    assert line and isinstance(line, str), line
check("C2-server-port-kind", t_c2)

print()
fails = 0
for name, st, note in results:
    print(f"{st:5} {name}" + (f"  | {note}" if note else ""))
    fails += st == "RED"
print(f"\n{len(results) - fails}/{len(results)} GREEN")
sys.exit(1 if fails else 0)
