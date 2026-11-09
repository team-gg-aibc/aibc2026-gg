"""점수 재는 틀: 실험 하나(설정 파일 하나)를 평가셋 묶음에 돌려 점수 · 틀린 원인 · 비용을 낸다.

  python3 eval/run.py --split dev                     키가 없으면 검색 적중률만 (크레딧 0)
  python3 eval/run.py --config eval/configs/<실험>.json --split dev            끝까지 (키 필요)
  python3 eval/run.py --config eval/configs/baseline.json --sample 100 --repeat 3   흔들림 폭
  python3 eval/run.py --check eval/runs/<실행>.json   재현 점검: 같은 조건으로 다시 돌려 그때 결과와 견줌
  python3 eval/run.py --url http://localhost:8000/ask --split kit   서버로 (응답만, 틀린 원인은 못 나눔)
  python3 eval/run.py --selftest

결과: eval/runs/<실행>.json(요약, 리더보드 재료, 남길 것만 커밋) · eval/results/<실행>.jsonl(문항별) · <실행>.html(문항마다
단계별 궤적 화면). eval/results/는 git에 안 올린다. holdout은 요약만 남긴다. 비용 상한은 기본으로 없다(동규 11-06).
리더보드 · 실험 기록은 python3 eval/board.py, 기준과 문항별 비교는 python3 eval/compare.py. 규칙은 docs/engine/reproducibility.md.
"""
import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import re
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine import answer, config, contract, pipeline, retrieve, upstage, verify  # noqa: E402

EVAL = ROOT / "eval"
RUNS, RESULTS = EVAL / "runs", EVAL / "results"
BASELINE = "eval/configs/baseline.json"
KST = timezone(timedelta(hours=9))
TYPES = {"단순 조회": "단순", "조건 판단": "조건", "여러 조항 결합": "결합", "근거 없음 (함정)": "함정"}
WEIGHTS = {"단순": 3, "조건": 3, "결합": 3, "함정": 2}          # 킷 예시 비율
FIELDS = {"answer", "citation", "source_url", "effective_date"}
LIMIT_SEC = 90                                                  # 대회 제한, 넘으면 0점
NOT_IN = "정답이 후보에 없음"
MISPICK = "후보에 있는데 잘못 고름"
REJECTED_OK = "판정이 맞는 답을 거절"
ABSTAIN = "답이 있는데 확인 불가"
TRAP_ANSWERED = "함정에 답함"
TIMEOUT = "시간 초과"
BROKEN = "오류 · 형식"
CAUSES = [NOT_IN, MISPICK, REJECTED_OK, ABSTAIN, TRAP_ANSWERED, TIMEOUT, BROKEN]
# 실험 주기(계획 0절 표): 이 시각 전에 만든 실행은 이 주기. 설정 파일에 "cycle"이 있으면 그 값을 쓴다.
CYCLE_ENDS = [("2026-11-07T19:00", 0), ("2026-11-09T00:00", 1), ("2026-11-11T00:00", 2), ("2026-11-13T00:00", 3),
              ("2026-11-15T00:00", 4), ("2026-11-17T00:00", 5)]


def cycle_of(created):
    """만든 시각(KST, ISO 꼴)으로 주기를 정한다. 동결(11/17) 뒤는 6."""
    return next((c for end, c in CYCLE_ENDS if created[:16] < end), 6)

# ---- 킷 채점식 그대로 (스타터 킷 check.py: 항까지 맞으면 1, 조까지 0.5, 별표 인용도 정답) ----
CITE = re.compile(r"(서울특별시.*?(?:조례|규칙))\s*(제\d+조(?:의\d+)?|별표\s*\d*|별도\s*\d+)\s*(제\d+항)?")


def parse(c):
    m = CITE.search(c.replace(chr(0xA0), " "))   # 줄바꿈 없는 공백(NBSP)을 보통 공백으로
    if not m:
        return None
    return re.sub(r"\s+", "", m.group(1)), re.sub(r"\s+", "", m.group(2)), m.group(3)


def match(pred, gold):
    p, g = parse(pred), parse(gold)
    if not p or not g or p[0] != g[0] or p[1] != g[1]:
        return 0.0
    return 1.0 if g[2] is None or p[2] == g[2] else 0.5


def score_citation(preds, gold):
    """gold: [[대안1, 대안2], [다음 필수 근거], ...]"""
    if not gold:
        return None
    return sum(max((match(p, a) for p in preds for a in alts), default=0.0) for alts in gold) / len(gold)


# ---- 문항 고르기 ----
def load(split):
    """회색지대(정답 꼴 미정)는 뺀다. kit = 스타터 킷 예시 11문항. para = 조례 원문에서 새로 쓴 바꿔 말한 질문(PM 별도 실험 일반화 확인, eval/para_*.json)."""
    pattern = {"dev": "questions_*.json", "holdout": "questions_*.json", "stress": "stress_*.json",
               "kit": "kit_questions.json", "para": "para_*.json"}[split]
    qs = [q for f in sorted(EVAL.glob(pattern)) for q in json.loads(f.read_text(encoding="utf-8"))]
    return [q for q in qs if "[회색지대]" not in q.get("note", "")
            and (split not in ("dev", "holdout") or q.get("split") == split)]


def sample(qs, n, seed):
    """유형 비율대로, 문항 id의 해시 순서로 n개. 같은 n · seed면 어느 컴퓨터에서나 같은 문항."""
    if not n or n >= len(qs):
        return qs
    by = defaultdict(list)
    for q in qs:
        by[q["type"]].append(q)
    quota = {t: n * len(v) / len(qs) for t, v in by.items()}
    take = {t: int(x) for t, x in quota.items()}
    for t in sorted(quota, key=lambda t: (take[t] - quota[t], t))[:n - sum(take.values())]:
        take[t] += 1
    key = lambda q: hashlib.sha256(f"{seed}:{q['id']}".encode()).hexdigest()  # noqa: E731
    picked = {q["id"] for t, v in by.items() for q in sorted(v, key=key)[:take[t]]}
    return [q for q in qs if q["id"] in picked]


def law(q):
    return q["id"].split("-")[0] if "-" in q["id"] else "kit"


# ---- 한 문항 ----
def grade(q, resp, tr, sec, err, cfg):
    """대회 규칙으로 채점하고 틀린 원인을 붙인다. tr(판단 기록)이 있으면 엔진을 직접 부른 것."""
    timeout = tr is not None and sec > cfg["timeout_sec"]
    if timeout:                       # 서버라면 이때 「확인 불가」로 답한다(server.py)
        resp, sec = contract.unknown(), cfg["timeout_sec"]
    shape = isinstance(resp, dict) and set(resp) == FIELDS and isinstance(resp["answer"], str) \
        and isinstance(resp["citation"], list) and all(isinstance(c, str) for c in resp["citation"])
    unknown = shape and resp["answer"].startswith("확인 불가") and resp["citation"] == []
    fmt_ok = shape and (unknown or (str(resp["source_url"]).startswith("http")
                                    and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(resp["effective_date"])) is not None))
    slow = sec > LIMIT_SEC
    late = slow and not cfg["explore"]   # 탐색 모드는 90초를 넘어도 점수에서 빼지 않는다(시간은 기록만)
    broken = bool(err) or not fmt_ok or (tr is not None and tr["reason"] == pipeline.ERROR)
    if q["gold"]:
        score = 0.0 if err or late or not fmt_ok else score_citation(resp["citation"], q["gold"])
    else:
        score = 1.0 if unknown and not err and not late else 0.0
    cand = None
    if tr is not None and tr["candidates"] and q["gold"]:
        cand = score_citation([c["label"] for c in tr["candidates"]], q["gold"])
    cause = None
    if score < 1:
        if timeout or late:
            cause = TIMEOUT
        elif broken:
            cause = BROKEN
        elif not q["gold"]:
            cause = TRAP_ANSWERED
        elif unknown:
            draft = tr and tr["draft"] and score_citation(tr["draft"]["citation"], q["gold"])
            if tr and tr["reason"] == pipeline.REJECTED and draft:
                cause = REJECTED_OK
            elif cand == 0:
                cause = NOT_IN
            elif tr and tr["reason"] == pipeline.REJECTED and tr["draft"]:
                cause = MISPICK               # 후보에 정답이 있었는데 틀린 근거를 골랐고, 판정이 그 답을 버림
            else:
                cause = f"{ABSTAIN} ({tr['reason']})" if tr else ABSTAIN
        elif cand is not None:
            cause = MISPICK if score < cand else NOT_IN
        else:
            cause = "틀림 (판단 기록 없음)"
    return {"id": q["id"], "type": q["type"], "law": law(q), "question": q["question"], "gold": q["gold"],
            "answer_key": q.get("answer_key", ""), "score": score, "cand": cand, "unknown": unknown,
            "fmt_ok": fmt_ok, "slow": slow, "late": late, "timeout": timeout, "error": err or (tr and tr["error"]),
            "sec": round(sec, 3), "cause": cause, "response": resp, "trace": tr}


def ask(q, cfg, mode, url):
    if mode == "retrieval":
        calls = []
        ks = sorted({1, 3, cfg["top_k"], 10, 20})
        labels = [h["label"] for h in retrieve.retrieve(q["question"], cfg, calls, k=max(ks))]
        return {"id": q["id"], "type": q["type"], "law": law(q), "gold": q["gold"], "labels": labels[:cfg["top_k"]],
                "hits": {str(k): score_citation(labels[:k], q["gold"]) for k in ks}, "calls": calls}
    t0 = time.perf_counter()
    if url:
        import requests
        try:
            r = requests.post(url, json={"question": q["question"]}, timeout=LIMIT_SEC)
            resp, err = r.json(), (None if r.status_code == 200 else f"HTTP {r.status_code}")
        except Exception as e:  # noqa: BLE001
            resp, err = {}, type(e).__name__
        return grade(q, resp, None, time.perf_counter() - t0, err, cfg)
    resp, tr = pipeline.answer(q["question"], cfg)
    return grade(q, resp, tr, time.perf_counter() - t0, None, cfg)


def calls_of(row):
    return row["calls"] if "calls" in row else (row["trace"] or {}).get("calls", [])


def execute(qs, cfg, mode, url, workers, max_cost):
    """문항을 나란히 돌린다. max_cost(달러)를 주면 쓴 돈이 그것을 넘을 때 남은 문항을 건너뛰고 None을 남긴다(기본은 상한 없음)."""
    lock, stop, spent, done = threading.Lock(), threading.Event(), [0.0], [0]

    def one(q):
        if stop.is_set():
            return None
        row = ask(q, cfg, mode, url)
        with lock:
            spent[0] += upstage.cost_usd(calls_of(row)) or 0.0
            done[0] += 1
            if max_cost is not None and spent[0] > max_cost:
                stop.set()
            if done[0] % 50 == 0 or done[0] == len(qs):
                print(f"  {done[0]}/{len(qs)} 문항, ${spent[0]:.3f}", flush=True)
        return row

    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(one, qs))


# ---- 요약 ----
def pct(xs):
    xs = list(xs)
    return round(100 * sum(xs) / len(xs), 1) if xs else None


def nearest_rank(sorted_xs, p):
    return sorted_xs[max(0, math.ceil(p * len(sorted_xs)) - 1)] if sorted_xs else None


def summarize(rows, mode, top_k):
    if mode == "retrieval":
        rows = [r for r in rows if r["gold"]]
        return {"n": len(rows), "hit": {k: pct(r["hits"][k] for r in rows) for k in rows[0]["hits"]} if rows else {},
                "by_type": {TYPES[t]: pct(r["hits"][str(top_k)] for r in rows if r["type"] == t)
                            for t in TYPES if any(r["type"] == t for r in rows)},
                "by_law": {k: pct(r["hits"][str(top_k)] for r in rows if r["law"] == k)
                           for k in sorted({r["law"] for r in rows})}}
    gold = [r for r in rows if r["gold"]]
    by_type = {TYPES[t]: pct(r["score"] for r in rows if r["type"] == t) for t in TYPES if any(r["type"] == t for r in rows)}
    secs = sorted(r["sec"] for r in rows)
    answered = [r for r in rows if r["fmt_ok"] and not r["unknown"]]
    causes = Counter(r["cause"] for r in rows if r["cause"])
    return {"n": len(rows), "n_gold": len(gold), "n_trap": len(rows) - len(gold),
            "weighted": round(sum(WEIGHTS[k] * by_type[k] for k in WEIGHTS) / sum(WEIGHTS.values()), 1)
            if all(by_type.get(k) is not None for k in WEIGHTS) else None,
            "by_type": by_type, "trap": by_type.get("함정"),
            "by_law": {k: pct(r["score"] for r in gold if r["law"] == k) for k in sorted({r["law"] for r in gold})},
            "over_abstain": pct(r["unknown"] for r in gold),
            "citations_per_answer": round(sum(len(r["response"]["citation"]) for r in answered) / len(answered), 2)
            if answered else None,
            "retrieval_hit": pct(r["cand"] for r in gold if r["cand"] is not None),
            "format_errors": sum(not r["fmt_ok"] for r in rows), "late": sum(r["late"] for r in rows),
            "over_90s": sum(r["slow"] for r in rows),
            "timeouts": sum(r["timeout"] for r in rows), "errors": sum(bool(r["error"]) for r in rows),
            "latency_p50": nearest_rank(secs, 0.5), "latency_p95": nearest_rank(secs, 0.95),
            "latency_max": secs[-1] if secs else None,
            "causes": dict(sorted(causes.items(), key=lambda kv: -kv[1]))}


def git(*args):
    try:
        return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, encoding="utf-8", timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def code_hash(files):
    """코드 지문: 커밋 번호는 squash 병합 · rebase로 바뀌어도 파일 글자가 같으면 같다."""
    return config.digest({str(f.relative_to(ROOT)): hashlib.sha256(f.read_bytes()).hexdigest() for f in files})


def version(pkg):
    try:
        return importlib.metadata.version(pkg)
    except importlib.metadata.PackageNotFoundError:
        return None


def record(args, cfg, exp, qs, rows, mode, wall, run_id, group, rep):
    created = datetime.now(KST).isoformat(timespec="seconds")
    calls = [c for r in rows for c in calls_of(r)]
    cost = upstage.cost_usd(calls) if not args.url else None
    retrieval_used = sorted({r["trace"]["retrieval"] for r in rows if r.get("trace") and r["trace"]["retrieval"]})
    server = None
    if args.url:                      # 서버가 실제로 쓰는 설정은 /health로 확인한다(--config는 서버에 닿지 않음)
        import requests
        try:
            server = requests.get(args.url.rsplit("/", 1)[0] + "/health", timeout=10).json()
        except Exception as e:  # noqa: BLE001
            server = {"error": type(e).__name__}
        retrieval_used = ["서버"]
    if mode == "retrieval":
        retrieval_used = [retrieve.mode(cfg)]
        cand_labels = [[r["id"], r["labels"]] for r in rows]
    else:
        cand_labels = [[r["id"], [c["label"] for c in (r["trace"] or {}).get("candidates", [])]] for r in rows]
    return {
        "run_id": run_id, "group": group, "repeat": rep, "repeats": args.repeat,
        "created": created,
        "experiment": dict(exp, cycle=cycle_of(created) if exp.get("cycle") is None else exp["cycle"]), "conclusion": "",
        "lesson": [],   # 배운 점 세 줄(사람이 적는다): 무엇이 좋아지고 나빠졌나 / 왜 그런 것 같나 / 다음에 해 볼 것
        "args": {"config": args.config, "split": args.split, "sample": args.sample, "seed": args.seed,
                 "mode": mode, "url": args.url, "workers": args.workers},
        "settings": cfg, "settings_hash": config.digest(cfg),
        "switches": {k: v for k, v in cfg.items() if config.DEFAULTS.get(k) != v},
        "env": {"code_commit": git("rev-parse", "--short=7", "HEAD"),
                "code_hash": code_hash(sorted(ROOT.glob("engine/**/*.py")) + [ROOT / "engine/requirements.txt"]),
                "eval_code_hash": code_hash([Path(__file__).resolve()]),
                "code_dirty": bool(git("status", "--porcelain", "--", "engine", "eval/run.py", args.config)),
                "eval_commit": git("log", "-1", "--format=%h", "--", "eval/questions_*.json", "eval/stress_*.json",
                                   "eval/kit_questions.json"),
                "questions_hash": config.digest([[q["id"], q["type"], q["question"], q["gold"]] for q in qs]),
                "index": retrieve.fingerprint(cfg["chunk_unit"]), "retrieval_used": retrieval_used,
                "key_present": upstage.has_key(), "server": server, "python": platform.python_version(),
                "packages": {p: version(p) for p in ("numpy", "openai", "requests")},
                "platform": platform.platform(terse=True)},
        "metrics": summarize(rows, mode, cfg["top_k"]),
        "cost_usd": None if cost is None else round(cost, 4),
        "tokens": {k: sum(c[k] for c in calls) for k in ("in", "cached", "out")}, "calls": len(calls),
        "wall_sec": round(wall, 1),
        "hashes": {"retrieval": config.digest(cand_labels),
                   "answers": None if mode == "retrieval" else config.digest(
                       [[r["id"], r["unknown"], r["response"].get("citation") if isinstance(r["response"], dict) else None]
                        for r in rows])},
    }


def show(s):
    m, e = s["metrics"], s["env"]
    print(f"\n[{s['run_id']}] {s['args']['split']} {m['n']}문항 · {s['args']['mode']} · 검색 {'/'.join(e['retrieval_used'])}"
          f" · 코드 {e['code_commit']}{' (커밋 안 한 수정 있음)' if e['code_dirty'] else ''} · 평가셋 {e['eval_commit']}")
    if s["args"]["mode"] == "retrieval":
        print("  적중률 " + " · ".join(f"top-{k} {v}%" for k, v in m["hit"].items()))
        print("  유형별 top-%d: %s" % (s["settings"]["top_k"], " · ".join(f"{k} {v}%" for k, v in m["by_type"].items())))
    else:
        print(f"  가중 {m['weighted']} · " + " · ".join(f"{k} {v}" for k, v in m["by_type"].items())
              + f" · 과잉 포기 {m['over_abstain']}% · 인용 수 {m['citations_per_answer']}")
        print(f"  지연 95% {m['latency_p95']}초 · 형식 오류 {m['format_errors']} · 90초 넘음 {m.get('over_90s')}"
              + (" (탐색: 점수에서 안 뺌)" if s["settings"].get("explore") else "")
              + f" · 오류 {m['errors']} · 검색 적중률 {m['retrieval_hit']}%")
        if "causes" in m:                 # holdout은 틀린 원인을 남기지 않는다
            print(f"  틀린 원인: {m['causes']}")
    print("  조례별: " + " · ".join(f"{k} {v}" for k, v in m["by_law"].items()))
    print(f"  비용 {'모름(서버 호출)' if s['cost_usd'] is None else '$' + str(s['cost_usd'])} · 호출 {s['calls']}번 · {s['wall_sec']}초")


def prepare(args):
    cfg = config.load(ROOT / args.config)
    raw = json.loads((ROOT / args.config).read_text(encoding="utf-8"))
    exp = {"name": raw.get("name") or Path(args.config).stem, "issue": raw.get("issue", ""), "note": raw.get("note", ""),
           "cycle": raw.get("cycle"), "file": args.config, "file_sha": config.digest(raw)}
    for name, table in ((cfg["answer_prompt"], answer.PROMPTS), (cfg["verify_prompt"], verify.PROMPTS)):
        if name not in table:
            sys.exit(f"✗ 프롬프트 판 「{name}」이 없습니다. 있는 판: {sorted(table)}")
    mode = args.mode if args.mode != "auto" else ("full" if args.url or upstage.has_key() else "retrieval")
    if mode == "full" and not args.url and not upstage.has_key():
        sys.exit("✗ 끝까지 돌리려면 레포 맨 위 .env에 UPSTAGE_API_KEY가 있어야 합니다. 키 없이는 --mode retrieval.")
    if mode == "retrieval" and not upstage.has_key():
        print("· 키가 없어 검색 적중률만 잽니다(키워드 검색, 크레딧 0).")
    return cfg, exp, mode, sample(load(args.split), args.sample, args.seed)


def run(args):
    cfg, exp, mode, qs = prepare(args)
    if args.split == "holdout":
        print("· holdout: 큰 이정표에서만 잽니다(계획 5-1절). 문항별 결과는 남기지 않습니다.")
    stamp = datetime.now(KST).strftime("%Y%m%d-%H%M%S")
    group = "-".join([stamp, re.sub(r"[^\w.-]+", "-", exp["name"]), args.split] + ([f"n{args.sample}"] if args.sample else []))
    out = []
    for rep in range(1, args.repeat + 1):
        run_id = group + (f"-r{rep}" if args.repeat > 1 else "")
        print(f"\n▶ {run_id}: {len(qs)}문항 · {mode}" + (f" · {args.url}" if args.url else ""))
        t0 = time.perf_counter()
        rows = execute(qs, cfg, mode, args.url, args.workers, args.max_cost)
        done = [r for r in rows if r is not None]
        if args.split != "holdout":
            RESULTS.mkdir(parents=True, exist_ok=True)
            with open(RESULTS / f"{run_id}.jsonl", "w", encoding="utf-8") as f:
                for r in done:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        if len(done) < len(rows):
            sys.exit(f"✗ 비용 상한 ${args.max_cost}를 넘어 {len(done)}/{len(rows)}문항에서 멈췄습니다. 요약은 남기지 않습니다.")
        s = record(args, cfg, exp, qs, done, mode, time.perf_counter() - t0, run_id, group, rep)
        if args.split == "holdout":
            s["metrics"].pop("causes", None)
        RUNS.mkdir(parents=True, exist_ok=True)
        (RUNS / f"{run_id}.json").write_text(json.dumps(s, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        show(s)
        if args.split != "holdout" and mode == "full":
            import trajectory
            print(f"  궤적 화면: {trajectory.write_html(s, done, RESULTS)}")
        out.append(s)
    if args.repeat > 1 and mode == "full":
        w = [s["metrics"]["weighted"] for s in out]
        print(f"\n흔들림: 가중 {w} → 폭 {round(max(w) - min(w), 1)}점" if None not in w
              else f"\n흔들림: 가중 {w} → 폭을 못 낸다(표본에 빠진 문항 종류가 있어 가중이 None. --sample을 키운다)")
    print("\n리더보드 · 실험 기록 다시 만들기: python3 eval/board.py")
    return out


def check(args):
    """재현 점검: 기록된 실행과 같은 조건으로 한 번 더 돌려 결과를 견준다. 새 결과는 eval/runs에 남기지 않는다."""
    old = json.loads(Path(args.check).read_text(encoding="utf-8"))
    for k in ("config", "split", "sample", "seed", "url"):
        setattr(args, k, old["args"][k])
    args.mode, args.repeat = old["args"]["mode"], 1
    if old["env"]["retrieval_used"] == ["keyword"]:
        os.environ["UPSTAGE_API_KEY"] = ""      # 그때처럼 키워드 검색으로 잰다(키가 있어도 크레딧 0)
    elif old["env"]["retrieval_used"] == ["hybrid"] and not upstage.has_key():
        sys.exit("✗ 그때는 혼합 검색(키 필요)으로 잰 실행입니다. 레포 맨 위 .env에 키를 넣고 다시 돌리세요.")
    cfg, exp, mode, qs = prepare(args)
    t0 = time.perf_counter()
    rows = execute(qs, cfg, mode, args.url, args.workers, args.max_cost)
    if any(r is None for r in rows):
        sys.exit("✗ 비용 상한을 넘어 멈췄습니다.")
    new = record(args, cfg, exp, qs, rows, mode, time.perf_counter() - t0, "check", "check", 1)
    print(f"\n재현 점검: {old['run_id']}\n| 항목 | 그때 | 지금 | |\n|---|---|---|---|")
    pairs = [("설정 지문", old["settings_hash"], new["settings_hash"]), ("설정 파일", old["experiment"]["file_sha"], new["experiment"]["file_sha"])]
    names = {"code_hash": "엔진 코드 지문", "eval_code_hash": "채점 코드 지문 (참고: eval/run.py)",
             "code_commit": "코드 커밋 (참고: squash 병합 뒤엔 달라도 됨)", "code_dirty": "커밋 안 한 수정",
             "eval_commit": "평가셋 커밋 (참고)", "questions_hash": "문항 지문", "index": "색인 지문",
             "retrieval_used": "검색", "python": "파이썬", "packages": "패키지"}
    pairs += [(names[k], old["env"].get(k), new["env"].get(k)) for k in names]
    for name, a, b in pairs:
        print(f"| {name} | {a} | {b} | {'같음' if a == b else '다름'} |")
    m0, m1 = old["metrics"], new["metrics"]
    if mode == "retrieval":
        same = old["hashes"]["retrieval"] == new["hashes"]["retrieval"]
        print(f"\n검색 결과(문항별 후보): {'모두 같음' if same else '다름'} · top-{cfg['top_k']} "
              f"{m0['hit'].get(str(cfg['top_k']))}% → {m1['hit'].get(str(cfg['top_k']))}%")
    else:
        runs = [json.loads(p.read_text(encoding="utf-8")) for p in RUNS.glob("*.json")]
        mates = [r["metrics"]["weighted"] for r in runs if r["group"] == old["group"]]
        band = max(mates) - min(mates) if len(mates) > 1 else None
        diff = round(m1["weighted"] - m0["weighted"], 1)
        same = band is not None and abs(diff) <= band
        print(f"\n가중 {m0['weighted']} → {m1['weighted']} ({diff:+}) · 그때 반복 폭 "
              f"{'모름 (--repeat 3로 먼저 재 두기)' if band is None else f'{band:.1f}점'} → "
              f"{'흔들림 안' if same else '흔들림 밖이거나 폭을 모름'}")
    print(f"\n결론: {'✅ 같은 결과' if same else '❌ 다름 — 위 표에서 다른 항목부터 맞추기'}")
    sys.exit(0 if same else 1)


# ---- 스스로 시험 ----
class _Fake:
    """가짜 업스테이지: 근거 1 · 3번을 고르고 grounded라고 판정한다. 「따릉이」가 든 질문은 근거 없음."""

    def __init__(self):
        mean = __import__("numpy").load(config.DATA / "vectors_paragraph.npy").mean(axis=0).tolist()
        ns = lambda **k: type("NS", (), k)  # noqa: E731
        usage = ns(prompt_tokens=1000, completion_tokens=50, prompt_tokens_details=ns(cached_tokens=200))

        def chat(**kw):
            if "검증자" in kw["messages"][0]["content"]:
                content = json.dumps({"verdict": "grounded"})
            else:
                found = "따릉이" not in kw["messages"][1]["content"]
                content = json.dumps({"found": found, "answer": "가짜 답", "evidence_ids": [1, 3] if found else []})
            return ns(choices=[ns(message=ns(content=content))], usage=usage)

        self.chat = ns(completions=ns(create=staticmethod(chat)))
        self.embeddings = ns(create=staticmethod(lambda model, input: ns(
            data=[ns(embedding=mean) for _ in input], usage=ns(prompt_tokens=10 * len(input)))))


def selftest():
    a, b = "서울특별시 주차장 설치 및 관리 조례 제7조 제1항", "서울특별시 주차장 설치 및 관리 조례 별표 1"
    assert score_citation([a], [[a]]) == 1.0
    assert score_citation(["서울특별시 주차장 설치 및 관리 조례 제7조 제3항"], [[a]]) == 0.5
    assert score_citation(["서울특별시 도시공원 조례 제7조 제1항"], [[a]]) == 0.0
    assert score_citation([b], [[b, a]]) == 1.0 and score_citation([a], [[a], [b]]) == 0.5
    assert score_citation(["서울특별시 금연환경 조성 및 간접흡연 피해방지조례 제2조"],
                          [["서울특별시 금연환경 조성 및 간접흡연 피해방지조례 제2조"]]) == 1.0

    qs = [{"id": f"x-{t}{i}", "type": t} for t in TYPES for i in range(25)]
    s0 = sample(qs, 20, 0)
    assert [q["id"] for q in s0] == [q["id"] for q in sample(qs, 20, 0)]
    assert Counter(q["type"] for q in s0) == {t: 5 for t in TYPES}
    assert {q["id"] for q in s0} != {q["id"] for q in sample(qs, 20, 1)}
    assert len(sample(qs, 7, 0)) == 7 and sample(qs, None, 0) == qs

    cfg = dict(config.load(), select_mode="direct")   # 가짜 업스테이지는 답 쓰기 한 번만 흉내 낸다(DEFAULTS의 #24 먼저 추리기는 끔)
    ok = {"answer": "네", "citation": [a], "source_url": "https://www.law.go.kr/x", "effective_date": "2026-10-01"}
    unk = contract.unknown()
    gold_q = {"id": "parking-C1", "type": "조건 판단", "question": "?", "gold": [[a]]}
    trap_q = {"id": "common-T1", "type": "근거 없음 (함정)", "question": "?", "gold": []}

    def tr(reason=None, cands=(a,), draft=None):
        return {"reason": reason, "error": None, "candidates": [{"label": c} for c in cands], "draft": draft}

    assert grade(gold_q, ok, tr(), 1, None, cfg)["cause"] is None
    wrong = dict(ok, citation=["서울특별시 주차장 설치 및 관리 조례 제9조 제1항"])
    assert grade(gold_q, wrong, tr(), 1, None, cfg)["cause"] == MISPICK
    assert grade(gold_q, wrong, tr(cands=("서울특별시 주차장 설치 및 관리 조례 제9조 제1항",)), 1, None, cfg)["cause"] == NOT_IN
    assert grade(gold_q, unk, tr(pipeline.NOT_FOUND), 1, None, cfg)["cause"] == f"{ABSTAIN} ({pipeline.NOT_FOUND})"
    assert grade(gold_q, unk, tr(pipeline.REJECTED, draft=ok), 1, None, cfg)["cause"] == REJECTED_OK
    assert grade(gold_q, unk, tr(pipeline.NOT_FOUND, cands=(b,)), 1, None, cfg)["cause"] == NOT_IN
    assert grade(gold_q, unk, tr(pipeline.REJECTED, draft=dict(ok, citation=[b])), 1, None, cfg)["cause"] == MISPICK
    assert grade(gold_q, dict(ok, citation=[7]), tr(), 1, None, cfg)["cause"] == BROKEN
    assert grade(trap_q, ok, tr(), 1, None, cfg)["cause"] == TRAP_ANSWERED
    r = grade(trap_q, ok, tr(), 80, None, cfg)          # 75초 넘으면 서버가 확인 불가로 답한다
    assert r["score"] == 1.0 and r["timeout"] and r["sec"] == 75
    assert grade(gold_q, ok, tr(), 80, None, cfg)["cause"] == TIMEOUT
    bad = grade(gold_q, {"answer": "네", "citation": [a]}, tr(), 1, None, cfg)
    assert bad["score"] == 0 and bad["cause"] == BROKEN and not bad["fmt_ok"]
    assert grade(gold_q, ok, None, 95, None, cfg)["late"]
    explore = dict(cfg, explore=True, timeout_sec=300)
    r = grade(gold_q, ok, tr(), 120, None, explore)                 # 탐색: 120초 걸려도 점수는 그대로, 시간만 기록
    assert r["score"] == 1.0 and r["slow"] and not r["late"] and r["cause"] is None
    assert cycle_of("2026-11-06T19:14:24+09:00") == 0 and cycle_of("2026-11-07T20:00:00+09:00") == 1
    assert cycle_of("2026-11-12T23:59:00+09:00") == 3 and cycle_of("2026-11-18T10:00:00+09:00") == 6

    rows = [grade(gold_q | {"type": t}, ok, tr(), 1, None, cfg) for t in list(TYPES)[:3]] + [grade(trap_q, unk, tr(), 1, None, cfg)]
    m = summarize(rows, "full", 6)
    assert m["weighted"] == 100.0 and m["over_abstain"] == 0.0 and m["citations_per_answer"] == 1.0
    m = summarize(rows[:3] + [grade(trap_q, ok, tr(), 1, None, cfg)], "full", 6)
    assert m["weighted"] == round(900 / 11, 1) and m["causes"] == {TRAP_ANSWERED: 1}
    assert nearest_rank(list(range(1, 101)), 0.95) == 95
    m.pop("causes")                     # holdout 요약(틀린 원인 없음)도 화면에 낼 수 있어야 한다
    show({"run_id": "selftest", "args": {"split": "holdout", "mode": "full"}, "settings": cfg, "metrics": m,
          "env": {"retrieval_used": ["hybrid"], "code_commit": "-", "code_dirty": False, "eval_commit": "-"},
          "cost_usd": 0.0, "calls": 0, "wall_sec": 0.0})

    old = upstage._client, upstage.has_key
    upstage._client, upstage.has_key = _Fake(), lambda: True
    try:
        kit = load("kit")
        rows = execute(kit, cfg, "full", None, 4, 1.0)
        assert len(rows) == 11 and all(r["fmt_ok"] for r in rows)
        m = summarize(rows, "full", 6)
        assert m["weighted"] is not None and m["errors"] == 0 and upstage.cost_usd([c for r in rows for c in calls_of(r)]) > 0
        stages = {c["stage"] for r in rows for c in r["trace"]["calls"]}
        assert stages == {"검색", "고르기 · 답 쓰기", "판정"} and all(c["sent"] for r in rows for c in r["trace"]["calls"])
        import trajectory
        page = trajectory.html_page({"run_id": "selftest", "metrics": m, "args": {"split": "kit"}, "cost_usd": 0.0}, rows)
        assert page.count("<details") == len(rows) and "근거 1" in page and "&lt;" not in page.split("<body>")[0]
    finally:
        upstage._client, upstage.has_key = old
    print("selftest ok")


def main():
    ap = argparse.ArgumentParser(description="점수 재는 틀 (eval/run.py 맨 위 설명 참고)")
    ap.add_argument("--config", default=BASELINE, help="실험 설정 파일 (기본: 출발 판)")
    ap.add_argument("--split", default="dev", choices=["dev", "holdout", "stress", "kit", "para"])
    ap.add_argument("--sample", type=int, help="유형 비율대로 뽑을 문항 수 (기본: 전부)")
    ap.add_argument("--seed", type=int, default=0, help="표본 뽑기 씨앗")
    ap.add_argument("--repeat", type=int, default=1, help="같은 설정 반복 횟수 (흔들림 폭)")
    ap.add_argument("--mode", default="auto", choices=["auto", "retrieval", "full"],
                    help="retrieval = 검색 적중률만, full = 끝까지. auto는 키가 있으면 full")
    ap.add_argument("--url", help="엔진 대신 서버 주소로 부르기 (예: http://localhost:8000/ask)")
    ap.add_argument("--workers", type=int, default=4, help="동시에 돌릴 문항 수")
    ap.add_argument("--max-cost", type=float, help="한 실행에 쓸 최대 달러(기본: 상한 없음, 동규 11-06). 넘으면 남은 문항을 건너뛴다")
    ap.add_argument("--check", help="재현 점검할 실행 요약 파일 (eval/runs/*.json)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        selftest()
    elif args.check:
        check(args)
    else:
        run(args)


if __name__ == "__main__":
    main()
