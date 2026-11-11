"""기록 모으는 곳: 실행의 문항별 기록(eval/results/<실행>.jsonl)을 줄여 그 주기의 GitHub Release(results-c<주기>)에 올린다.

  python3 eval/share.py <실행> [<실행> …]   올린다. 같은 실행을 다시 올리면 바꿔치기한다
  python3 eval/share.py <실행> --dry-run     올리지 않고 eval/results/shared/c<주기>/에 만들기만 (크기 · 되살리기 확인)
  python3 eval/share.py --selftest           키 · 네트워크 없이 스스로 시험
<실행>은 실행 이름(eval/runs/<실행>.json)이나 eval/results/<실행>.jsonl 경로다(다른 worktree에 있어도 된다).
주기는 실행 요약의 experiment.cycle이다. 올리려면 gh(GitHub CLI) 로그인이 필요하다. 모은 실패 보기: python3 eval/failures.py --cycle <주기>.

줄이기: 문항 둘 이상이 같이 보낸 긴 줄(조례 조각 · 시스템 프롬프트)을 지문(sha256 앞 12자리)으로 바꾸고, 그 글은 출처와 함께
파일 첫 줄에 한 번만 둔다. 질문 · 모델 출력 · 단계 · 사유 · 토큰 · 시간은 그대로다. load()로 되살리면 원래 기록과 같다.
거부: holdout · 처음 보는 문항(fresh) 실행 · holdout 문항이 하나라도 든 실행 · 끝까지 잰 실행이 아닌 것 · 열쇠처럼 보이는 글이 든 것.
집 폴더 경로의 사용자 이름은 ~로 가린다.
"""
import argparse
import gzip
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from run import EVAL, RESULTS, ROOT, RUNS, answer, config, private, verify

SHARED = RESULTS / "shared"
MIN_LINE = 32          # 이보다 짧은 줄은 그대로 둔다(지문 표시 {"blob": …}가 24자라)
SECRET = re.compile(r"up_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|Bearer\s+[A-Za-z0-9._-]{16,}"
                    r"|UPSTAGE_API_KEY\s*=|LAW_OC\s*=|[?&]OC=\w")
# 집 폴더 경로(맥 · 리눅스 /Users/이름, 윈도 C:\Users\이름 — jsonl 글에서는 역슬래시가 두 개). 주소 속 …/home/…은 건드리지 않는다
HOME = re.compile(r"(?<![\w.:/-])/(?:Users|home)/[^/\s\"'\\]+|[A-Za-z]:(?:\\\\|/)Users(?:\\\\|/)[^\\/\s\"']+")


def tag(cycle):
    return f"results-c{cycle}"


def messages(rows):
    """chat 호출로 보낸 메시지(dict)마다 (행 번호, 메시지)."""
    for i, r in enumerate(rows):
        for c in (r.get("trace") or {}).get("calls", []):
            if c.get("kind") == "chat":
                for m in c.get("sent") or []:
                    yield i, m


def sources():
    """알려진 고정 글의 줄 → 출처. 사람이 읽는 표시일 뿐 되살리기에는 안 쓴다(글은 파일 안에 있다)."""
    known = [(f"answer.PROMPTS {k}", v) for k, v in answer.PROMPTS.items()] + [("answer.PREFILTER_PROMPT", answer.PREFILTER_PROMPT)]
    known += [(f"verify.PROMPTS {k}", v) for k, v in verify.PROMPTS.items()]
    for f in sorted(config.DATA.glob("chunks_*.json")):
        known += [(f"조각 {c['label']}", c["text"]) for c in json.loads(f.read_text(encoding="utf-8"))]
    out = {}
    for name, text in known:
        for ln in text.splitlines():
            if name not in out.setdefault(ln, []):
                out[ln].append(name)
    return {ln: " · ".join(ns[:3]) + (f" 외 {len(ns) - 3}" if len(ns) > 3 else "") for ln, ns in out.items()}


def reduce(rows, src=None):
    """rows의 메시지 글에서 여러 행이 같이 보낸 긴 줄을 {"blob": 지문}으로 바꾼다(rows를 고친다). 돌려주는 것: 지문 → {text, from}."""
    seen = {}
    for i, m in messages(rows):
        if isinstance(m.get("content"), str):
            for ln in m["content"].splitlines(keepends=True):
                if len(ln) >= MIN_LINE:
                    seen.setdefault(ln, set()).add(i)
    fixed = {ln for ln, s in seen.items() if len(s) > 1}
    src = sources() if src is None else src
    blobs = {}
    for _, m in messages(rows):
        if not isinstance(m.get("content"), str):
            continue
        parts = []
        for ln in m["content"].splitlines(keepends=True):
            if ln in fixed:
                h = hashlib.sha256(ln.encode("utf-8")).hexdigest()[:12]
                if blobs.setdefault(h, {"text": ln, "from": src.get(ln.rstrip("\r\n"), "")})["text"] != ln:
                    raise ValueError(f"지문 {h}가 두 줄에 겹친다")
                parts.append({"blob": h})
            elif parts and isinstance(parts[-1], str):
                parts[-1] += ln
            else:
                parts.append(ln)
        if any(isinstance(p, dict) for p in parts):
            m["content"] = parts
    return blobs


def restore(rows, blobs):
    for _, m in messages(rows):
        if isinstance(m.get("content"), list):
            m["content"] = "".join(p if isinstance(p, str) else blobs[p["blob"]]["text"] for p in m["content"])
    return rows


def lines(text):
    """jsonl 줄 나누기. splitlines()는 글 속 U+2028 같은 문자에서도 끊어서 \n으로만 나눈다."""
    return [ln for ln in text.split("\n") if ln]


def dumps(rows):
    """run.py가 eval/results/<실행>.jsonl을 쓰는 꼴 그대로."""
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def pack(summary, text, src=None):
    rows = [json.loads(ln) for ln in lines(text)]
    blobs = reduce(rows, src)
    head = {"share": 1, "summary": summary, "blobs": blobs}
    return gzip.compress((json.dumps(head, ensure_ascii=False) + "\n" + dumps(rows)).encode("utf-8"), 9, mtime=0)


def unpack(data):
    """→ (실행 요약, 되살린 문항별 기록)."""
    head, *rest = lines(gzip.decompress(data).decode("utf-8"))
    head = json.loads(head)
    return head["summary"], restore([json.loads(ln) for ln in rest], head["blobs"])


def load(path):
    return unpack(Path(path).read_bytes())


def holdout_ids():
    return {q["id"] for f in EVAL.glob("questions_*.json") for q in json.loads(f.read_text(encoding="utf-8"))
            if q.get("split") == "holdout"}


def refuse(summary, text):
    """올리면 안 되는 까닭(없으면 None)."""
    kind = private(summary)
    if kind:
        return f"{kind} 실행은 올리지 않습니다(보고 고치지 않게: holdout은 계획 5-1절, 처음 보는 문항 fresh는 decisions 11-11)."
    bad = sorted({json.loads(ln)["id"] for ln in lines(text)} & holdout_ids())
    if bad:
        return f"holdout 문항 {len(bad)}개가 들어 있습니다(예: {bad[:3]}). 올리지 않습니다."
    if summary["args"]["mode"] != "full":
        return "끝까지 잰 실행만 올립니다(검색만 잰 실행은 요약 eval/runs/로 충분)."
    key = config.api_key()
    blob = json.dumps(summary, ensure_ascii=False) + text
    m = SECRET.search(blob)
    if (key and key in blob) or m:
        return "열쇠처럼 보이는 글이 있습니다" + (f"(「{m.group(0)[:12]}…」)" if m else "") + ". 지우고 다시 재세요."
    return None


def locate(arg):
    """실행 이름이나 파일 경로 → (실행 이름, 요약 경로, 문항별 기록 경로). 경로를 주면 그 eval/ 폴더에서 찾는다."""
    p = Path(arg)
    run_id = p.name.removesuffix(".json").removesuffix(".jsonl")
    base = p.parent.parent if p.suffix in (".json", ".jsonl") else EVAL
    summary = next((f for f in (base / "runs" / f"{run_id}.json", RUNS / f"{run_id}.json") if f.exists()), None)
    return run_id, summary, base / "results" / f"{run_id}.jsonl"


def gh(*args, check=True):
    try:
        r = subprocess.run(["gh", *args], cwd=ROOT, capture_output=True, text=True, timeout=600)
    except FileNotFoundError:
        sys.exit("✗ gh(GitHub CLI)가 없습니다. https://cli.github.com 에서 설치하고 gh auth login 하세요.")
    if check and r.returncode:
        sys.exit(f"✗ gh {' '.join(args[:2])} 실패: {(r.stderr or r.stdout).strip()[:300]}")
    return r


def upload(path, cycle):
    t = tag(cycle)
    if gh("release", "view", t, check=False).returncode:
        gh("release", "create", t, "--prerelease", "--title", f"{cycle}주기 문항별 기록",
           "--notes", f"eval/share.py가 올린 {cycle}주기 실행의 문항별 기록(<실행>.jsonl.gz). "
                      f"보는 법: python3 eval/failures.py --cycle {cycle}. holdout · 처음 보는 문항(fresh)은 올리지 않는다.")
    gh("release", "upload", t, str(path), "--clobber")


def share(arg, dry_run=False):
    run_id, sp, rp = locate(arg)
    if not sp or not rp.exists():
        sys.exit(f"✗ {run_id}: 요약(eval/runs/{run_id}.json)이나 문항별 기록({rp})이 없습니다. 그 실행을 돌린 컴퓨터에서 올리세요.")
    summary, text = json.loads(sp.read_text(encoding="utf-8")), rp.read_text(encoding="utf-8")
    why = refuse(summary, text)
    if why:
        sys.exit(f"✗ {run_id}: {why}")
    t0 = time.perf_counter()
    text, hidden = HOME.subn("~", text)
    data = pack(summary, text)
    back = unpack(data)[1]
    if back != [json.loads(ln) for ln in lines(text)]:
        sys.exit(f"✗ {run_id}: 되살린 기록이 원래와 다릅니다. 올리지 않습니다.")
    cycle = summary["experiment"]["cycle"]
    out = SHARED / f"c{cycle}" / f"{run_id}.jsonl.gz"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    mb = lambda n: f"{n / 1e6:.2f}MB"  # noqa: E731
    print(f"{run_id}: {mb(len(text.encode('utf-8')))} → {mb(len(data))} ({time.perf_counter() - t0:.1f}초) · 되살리기 같음"
          f"{' (바이트까지)' if dumps(back) == text else ''}" + (f" · 집 폴더 경로 {hidden}곳 가림" if hidden else ""))
    if not dry_run:
        t0 = time.perf_counter()
        upload(out, cycle)
        print(f"  → 릴리스 {tag(cycle)}에 올림 ({time.perf_counter() - t0:.1f}초)")
    return out


# ---- 스스로 시험 ----
def selftest():
    prompt = "너는 검증자다. 이 줄은 모든 문항의 시스템 프롬프트에 똑같이 들어가는 아주 긴 고정 글이라서 지문으로 바뀌어야 하는 줄이다.\n두 번째 줄"
    chunk = "① 시장은 이 조례에 따라 공영주차장의 주차요금을 감면할 수 있다. 다만, 감면 사유가 둘 이상이면 높은 하나만 적용한다. <개정 2025.1.3>"
    src = {chunk: "조각 서울특별시 주차장 설치 및 관리 조례 제7조 제1항"}

    def row(i, q):
        user = f"[근거]\n[근거 1] 서울특별시 주차장 설치 및 관리 조례 제7조 제1항\n{chunk}\n\n[질문]\n{q}"
        call = {"kind": "chat", "model": "solar-pro4", "in": 900, "cached": 0, "out": 12, "sec": 0.5,
                "sent": [{"role": "system", "content": prompt}, {"role": "user", "content": user}], "output": f"{{\"answer\": \"{q}\"}}",
                "stage": "판정"}
        return {"id": f"parking-S{i:03d}", "question": q, "cause": None, "score": 1.0, "sec": 1.2,
                "trace": {"reason": None, "steps": {"검색": 0.1}, "calls": [
                    {"kind": "embed", "model": "solar-embedding-2-query", "in": 9, "cached": 0, "out": 0, "sec": 0.1,
                     "sent": [q], "output": "1개 × 1024차원", "stage": "검색"}, call]}}

    long_q = "아주 긴 질문이지만 이 행에만 있으니 지문으로 바꾸지 않고 그대로 남아야 하는 글입니다. " * 2
    rows = [row(1, "경차 주차비 얼마나 깎아 줘요?"), row(2, long_q), row(3, "모닝 타면 할인돼요?"), {"id": "x", "trace": None}]
    text = dumps(rows)
    summary = {"args": {"split": "dev", "mode": "full"}, "experiment": {"cycle": 2}}
    data = pack(summary, text, src)
    assert data == pack(summary, text, src)                       # 같은 기록이면 같은 파일(바꿔치기해도 그대로)
    head, *rest = lines(gzip.decompress(data).decode("utf-8"))
    blobs, packed = json.loads(head)["blobs"], [json.loads(ln) for ln in rest]
    label = "[근거 1] 서울특별시 주차장 설치 및 관리 조례 제7조 제1항"          # 여러 행이 같이 보낸 줄만(질문 · 짧은 줄은 그대로)
    assert {b["text"].rstrip("\n") for b in blobs.values()} == {prompt.splitlines()[0], label, chunk}
    assert [b["from"] for b in blobs.values() if b["text"].startswith("①")] == [src[chunk]]
    sent = packed[1]["trace"]["calls"][1]["sent"]
    assert sent[0]["content"][0] == {"blob": hashlib.sha256((prompt.splitlines()[0] + "\n").encode()).hexdigest()[:12]}
    assert long_q in sent[1]["content"][-1] and packed[1]["question"] == long_q     # 질문은 그대로
    for a, b in zip(rows[:3], packed):                                               # 출력 · 단계 · 토큰 · 시간 그대로
        assert a["trace"]["calls"][0] == b["trace"]["calls"][0]
        assert all(a["trace"]["calls"][1][k] == b["trace"]["calls"][1][k] for k in ("output", "stage", "in", "out", "sec"))
    s, back = unpack(data)
    assert s == summary and dumps(back) == text                                      # 되살리면 바이트까지 같다

    hid = sorted(holdout_ids())[0]
    assert "holdout 문항" in refuse(summary, dumps([{"id": hid}]))
    assert "holdout 실행" in refuse(dict(summary, args={"split": "holdout", "mode": "full"}), text)
    assert "fresh 실행" in refuse(dict(summary, args={"split": "fresh", "mode": "full"}), text)       # 처음 보는 문항도 올리지 않는다
    assert "fresh 실행" in refuse(dict(summary, run_id="20261110-213655-x-fresh-r1"), text)            # 요약의 split 칸이 달라도 실행 이름으로
    assert "끝까지" in refuse(dict(summary, args={"split": "dev", "mode": "retrieval"}), text)
    assert "열쇠" in refuse(summary, dumps([{"id": "x", "error": "AuthenticationError up_" + "a1B2" * 8}]))
    assert refuse(summary, text) is None
    assert HOME.sub("~", '"FileNotFoundError: /Users/kim/aibc/x.py"') == '"FileNotFoundError: ~/aibc/x.py"'
    assert HOME.sub("~", '"https://example.com/home/a"') == '"https://example.com/home/a"'
    assert HOME.sub("~", json.dumps("OSError: C:\\Users\\kim\\aibc\\x.py")) == json.dumps("OSError: ~\\aibc\\x.py")
    assert locate("eval/results/20261110-0-a-dev-r1.jsonl")[2] == Path("eval/results/20261110-0-a-dev-r1.jsonl")
    print("selftest ok")


def main():
    ap = argparse.ArgumentParser(description="문항별 기록 올리기 (eval/share.py 맨 위 설명 참고)")
    ap.add_argument("runs", nargs="*", help="실행 이름 또는 eval/results/<실행>.jsonl 경로")
    ap.add_argument("--dry-run", action="store_true", help="올리지 않고 eval/results/shared/에 만들기만")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if not args.runs:
        ap.error("올릴 실행을 주세요")
    for r in args.runs:
        share(r, args.dry_run)


if __name__ == "__main__":
    main()
