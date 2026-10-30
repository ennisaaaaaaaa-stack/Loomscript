#!/usr/bin/env python3
"""pianist 保姆进程——conductor 拉起纪律的 Loomscript 移植（先写后做）。

家宅 conductor 的四条纪律，砍到 demo 需要的形状：
  1. 先写后做：spawn 前 pending 行落盘——孩子中途死，至少「它启动过」
     有账（09-28 事故：launch 行收工后才记，分身死整行蒸发）。
  2. 死亡两路入账：孩子被信号杀（wait 回填 exit/signal）与保姆自身
     SIGTERM（parent-down）都落死因。
  3. 同解释器钉子：spawn 用 sys.executable——爹用哪个 python 儿子就
     用哪个，不依赖 shebang/PATH（钉子钉儿子）。
  4. 死了重拉：监控环 child.wait() 返回即重拉；启动期死（30s 内无
     healthz）退出码 1 不无限循环——拉不起来要喊人，不能自己空转。

砍掉的：part 池/漫游/自学习/热点扫描/spoor（10/28 拍板：演出运行时
全确定性，不装自学习自驱动）。

用法：python3 src/pianist_nanny.py [--port 8741] [--stub] [--check-only]
"""
import argparse
import datetime
import json
import os
import pathlib
import signal
import subprocess
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
JOBS_DIR = ROOT / "loom_jobs" / "pianist"
LEDGER = JOBS_DIR / "pianist_ledger.jsonl"
SERVICE = ROOT / "src" / "pianist_service.py"

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=8741)
ap.add_argument("--stub", action="store_true")
ap.add_argument("--check-only", action="store_true",
                help="只做健康检查后退出（0=健康 1=不健康）")
args = ap.parse_args()

JOBS_DIR.mkdir(parents=True, exist_ok=True)


def now():
    return datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"


def ledger(row: dict):
    row = {"ts": now(), **row}
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def healthy() -> bool:
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{args.port}/healthz", timeout=3) as r:
            return json.load(r).get("ok") is True
    except Exception:
        return False


def wait_ready(child, tag: str, timeout_s: float = 30) -> bool:
    """就绪判据是 healthz 应答，不是 spawn 成功。启动期死=退出码1喊人。"""
    for _ in range(int(timeout_s / 0.5)):
        if healthy():
            ledger({"type": "launch_result", "pid": child.pid,
                    "status": f"ready{tag}"})
            return True
        if child.poll() is not None:
            ledger({"type": "launch_result", "pid": child.pid,
                    "status": f"died_at_boot{tag}", "exit": child.returncode})
            print(f"[nanny] pianist 启动期死亡 exit={child.returncode}——"
                  f"拉不起来要喊人，不空转", file=sys.stderr)
            sys.exit(1)
        time.sleep(0.5)
    ledger({"type": "launch_result", "pid": child.pid,
            "status": f"ready_timeout{tag}"})
    print(f"[nanny] {timeout_s}s 内 healthz 未就绪，放弃", file=sys.stderr)
    sys.exit(1)


def spawn(tag: str):
    """先写后做：pending 行 → spawn → pid 回填同文件。"""
    ledger({"type": "launch", "pid": None, "status": "pending", "tag": tag})
    env = {**os.environ, "PIANIST_PORT": str(args.port),
           "PIANIST_STUB": "1" if args.stub else ""}
    child = subprocess.Popen(  # 同解释器钉子
        [sys.executable, str(SERVICE), "--port", str(args.port)],
        env=env, cwd=str(ROOT),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ledger({"type": "launch", "pid": child.pid, "status": "spawned", "tag": tag})
    return child


if args.check_only:
    sys.exit(0 if healthy() else 1)

# 已有健康实例 → 收编不重启（幂等；两个保姆拉同一个端口只会打架）
if healthy():
    ledger({"type": "nanny_boot", "note": "service already healthy, adopt"})
    print(f"[nanny] {args.port} 已有健康 pianist，收编不重启")
    sys.exit(0)

child = spawn("boot")
print(f"[nanny] 拉起 pianist pid={child.pid} port={args.port} stub={args.stub}")
wait_ready(child, "")

_shutting_down = False


def sigterm(signum, frame):
    """死法二：保姆自身被停（systemd stop/Ctrl-C）——孩子先杀，账先落。"""
    global _shutting_down
    _shutting_down = True
    try:
        if child and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
                ledger({"type": "launch_result", "pid": child.pid,
                        "status": "parent-down", "exit": child.returncode})
            except subprocess.TimeoutExpired:
                child.kill()
                ledger({"type": "launch_result", "pid": child.pid,
                        "status": "parent-down", "signal": "SIGKILL"})
        ledger({"type": "nanny_down", "reason": "sigterm"})
    except Exception as e:  # 尽力退出（conductor 同款）
        print(f"[nanny] sigterm best-effort: {e}", file=sys.stderr)
    sys.exit(0)


signal.signal(signal.SIGTERM, sigterm)
signal.signal(signal.SIGINT, sigterm)

# 监控环：死了重拉（7.3 死后拉起；重拉也走先写后做+就绪确认）
RELAUNCH_MAX = 10  # 防 fork 炸弹闸：连续重拉上限，超了退出喊人
relaunches = 0
while True:
    code = child.wait()
    if _shutting_down:
        ledger({"type": "launch_result", "pid": child.pid,
                "status": "stopped_by_parent", "exit": code})
        break
    relaunches += 1
    if relaunches > RELAUNCH_MAX:
        ledger({"type": "nanny_giveup", "reason":
                f"relaunch>{RELAUNCH_MAX}", "last_exit": code})
        print(f"[nanny] 连续重拉 {RELAUNCH_MAX} 次仍在死，放弃喊人",
              file=sys.stderr)
        sys.exit(1)
    ledger({"type": "relaunch", "reason": f"exit={code}",
            "attempt": relaunches})
    print(f"[nanny] pianist 死了 exit={code}，重拉（{relaunches}/{RELAUNCH_MAX}）",
          file=sys.stderr)
    time.sleep(1)
    child = spawn(f"-relaunch{relaunches}")
    wait_ready(child, f"-relaunch{relaunches}")
