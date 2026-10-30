#!/usr/bin/env python3
"""服务层 HTTP 冒烟——真实起服、真实请求、真实 SSE。"""
import json
import subprocess
import sys
import threading
import time

import httpx

BASE = "http://127.0.0.1:8740"
results = []


def check(name, fn):
    try:
        fn()
        results.append((name, "GREEN", ""))
    except Exception as e:
        results.append((name, "RED", repr(e)[:200]))


proc = subprocess.Popen(
    [sys.executable, "src/server.py"],
    cwd="/home/ubuntu/loomscript",
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

try:
    # 等服务就绪
    c = httpx.Client(base_url=BASE, timeout=10)
    for _ in range(50):
        try:
            if c.get("/healthz").status_code == 200:
                break
        except Exception:
            time.sleep(0.2)
    else:
        raise RuntimeError("server did not come up")

    def full_flow():
        h = c.get("/healthz").json()
        assert h["ok"] and "macbeth_mini" in h["bundles"]

        r = c.post("/games", json={"bundle_id": "macbeth_mini"}).raise_for_status()
        r = c.post("/games", json={"bundle_id": "macbeth_mini"})
        assert r.status_code == 200, r.text
        g = r.json()
        sid = g["session_id"]
        assert g["snapshot"]["act_id"] == "A1"
        assert g["last_seq"] >= 0

        # 玩家说话
        r = c.post(f"/games/{sid}/say",
                   json={"character_id": "macbeth", "text": "今夜可有异象？"})
        assert r.status_code == 200, r.text
        evs = r.json()["events"]
        assert evs and evs[0]["type"] == "player_line" and evs[0]["channel"] == "main"

        # DM 指令：发卡 + 提议玩法
        r = c.post(f"/games/{sid}/dm", json={"action": "deal_cards", "character_id": "macbeth"})
        assert r.status_code == 200 and r.json()["events"], r.text
        r = c.post(f"/games/{sid}/dm", json={"action": "propose_play"})
        assert r.status_code == 200

        # 进场景 + 揭示
        scenes = ["A1S1", "A1S2"] if "A1S2" in json.dumps(g) else ["A1S1"]
        snap = g["snapshot"]
        for sc in scenes:
            r = c.post(f"/games/{sid}/scene", json={"scene_id": sc})
            assert r.status_code == 200, r.text
            r2 = c.post(f"/games/{sid}/say",
                        json={"character_id": "macbeth", "text": "继续"})
            assert r2.status_code == 200

        # 推幕到第二幕
        r = c.post(f"/games/{sid}/dm", json={"action": "advance_act"})
        assert r.status_code == 200, r.text
        snap2 = r.json()["snapshot"]
        assert snap2["act_id"] == "A2", snap2

        # events 补发接口
        r = c.get(f"/games/{sid}/events?after=-1")
        all_evs = r.json()
        assert any(e["type"] == "game_start" for e in all_evs)
        seqs = [e["seq"] for e in all_evs]
        assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs), "seq 不单调/重复"

        # agent_view 挂点（记忆层/pianist 用）
        r = c.get(f"/games/{sid}/view/banquo")
        assert r.status_code == 200
        v = r.json()
        blob = json.dumps(v, ensure_ascii=False)
        assert "弑王" not in blob and "杀死邓肯" not in blob, "banquo A1 泄密!"

        # dm_prompt 挂点
        r = c.get(f"/games/{sid}/dm_prompt")
        assert r.status_code == 200 and r.json()["role"] == "dm"

        # SSE：从当前队尾订阅，只等新事件（建局洪水不会触发提前退出）
        last_known = c.get(f"/games/{sid}/events?after=-1").json()[-1]["seq"]
        got = []

        def listen():
            with httpx.stream("GET", f"{BASE}/games/{sid}/stream?after={last_known}",
                              timeout=15) as sr:
                buf = ""
                for chunk in sr.iter_text():
                    buf += chunk
                    while "\n\n" in buf:
                        frame, buf = buf.split("\n\n", 1)
                        for ln in frame.splitlines():
                            if ln.startswith("data: "):
                                got.append(json.loads(ln[6:]))
                        if any(e["type"] == "player_line" for e in got):
                            return

        th = threading.Thread(target=listen, daemon=True)
        th.start()
        time.sleep(1.0)
        c.post(f"/games/{sid}/say", json={"character_id": "macbeth", "text": "SSE测试"})
        th.join(timeout=10)
        assert got, "SSE 没收到事件"
        types = [e["type"] for e in got]
        assert "player_line" in types, f"SSE 事件缺 player_line: {types}"
        sse_line = [e for e in got if e["type"] == "player_line"][0]
        assert sse_line["text"] == "SSE测试", sse_line

        # jsonl 落盘验证（用 SSE 测试之后重新拉的全量对账）
        all_evs = c.get(f"/games/{sid}/events?after=-1").json()
        p = f"/home/ubuntu/loomscript/sessions/{sid}.jsonl"
        with open(p, encoding="utf-8") as f:
            lines = [json.loads(x) for x in f if x.strip()]
        assert lines[0]["type"] == "game_start"
        assert len(lines) == len(all_evs), f"jsonl {len(lines)} != events {len(all_evs)}"

    check("http-full-flow", full_flow)
finally:
    proc.terminate()
    try:
        out, _ = proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
    print("--- server log tail ---")
    print((out or "")[-1500:])

print()
for n, s, msg in results:
    print(f"{s:6s} {n} {msg}")
sys.exit(0 if all(s == "GREEN" for _, s, _ in results) else 1)
