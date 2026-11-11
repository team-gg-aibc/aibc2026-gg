"""실험과 기준(출발 판 · 끈 판)을 문항마다 견줘, 무엇이 좋아지고 나빠졌는지 md 한 장으로 남긴다.

  python3 eval/compare.py <실행> [--base <기준 실행>]     → docs/engine/compare/<실행>.md (커밋한다)
  python3 eval/compare.py --selftest
- 문항별 결과(eval/results/)는 git에 안 올리니, 실험한 사람이 자기 컴퓨터에서 돌려 이 md를 브랜치에 커밋한다.
  버린 실험이어도 「결과만 PR」이 이 md를 main에 남긴다(재현 규칙 8절).
- 기준을 안 주면 리더보드의 「기준」 판(같은 문항 표의 출발 판 가운데 엔진 코드가 같은 것, 없으면 가장 최근 것)을 쓰되,
  이 컴퓨터에 문항별 결과가 있는 것만 고른다. 같은 문항(문항 지문)끼리만 견주고, holdout · 처음 보는 문항(fresh)은 견주지 않는다
  (이 md에는 질문과 정답 조항이 실리고 레포에 커밋된다).
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from board import LAWS, groups, local_runs
from run import CAUSES, RESULTS, ROOT, RUNS, TYPES, WEIGHTS, private

OUT = ROOT / "docs" / "engine" / "compare"
OK = "맞음"


def load(run):
    run_id = Path(run).name.removesuffix(".json").removesuffix(".jsonl")
    if not (RUNS / f"{run_id}.json").exists():
        sys.exit(f"✗ 실행 요약 eval/runs/{run_id}.json이 없습니다.")
    summary = json.loads((RUNS / f"{run_id}.json").read_text(encoding="utf-8"))
    if private(summary):
        sys.exit(f"✗ {private(summary)} 실행은 견주지 않습니다(보고 고치지 않게: holdout은 계획 5-1절, 처음 보는 문항 fresh는 decisions 11-11).")
    if summary["args"]["mode"] != "full":
        sys.exit("✗ 끝까지 잰 실행만 견줍니다(검색만 잰 실행은 리더보드의 적중률 표로 본다).")
    path = RESULTS / f"{run_id}.jsonl"
    if not path.exists():
        sys.exit(f"✗ {run_id}의 문항별 결과(eval/results/{run_id}.jsonl)가 이 컴퓨터에 없습니다. 그 실행을 돌린 컴퓨터에서 돌리세요.")
    return summary, {r["id"]: r for r in map(json.loads, path.read_text(encoding="utf-8").splitlines())}


def pick_base(gs, me, has_results):
    """리더보드 「기준」 판 고르기와 같은 규칙. 자기 묶음은 빼고, 문항별 결과가 있는 것만."""
    cands = sorted((g for g in gs if g["name"] == "baseline" and g["full"] and g["table"] == me["table"]
                    and g["group"] != me["group"] and has_results(g["run_id"])), key=lambda g: g["created"])
    same = [g for g in cands if g["code_hash"] == me["code_hash"]]
    return (same or cands)[-1]["run_id"] if cands else None


def cause(r):
    return r["cause"] or OK


def bucket(c):
    """「답이 있는데 확인 불가 (found 거짓)」처럼 까닭이 붙은 원인은 큰 원인으로 모은다."""
    return next((x for x in CAUSES if c.startswith(x)), c)


def candidates(r):
    if not r["gold"]:
        return "함정(정답 없음)"
    c = r.get("cand")
    return "모름" if c is None else "있음" if c == 1 else f"일부({c:g})" if c else "없음"


def final(r):
    t = r.get("trace") or {}
    if r["unknown"]:
        return f"확인 불가({t.get('reason') or r['cause'] or '—'})"
    return f"답함 · 인용 {len(r['response'].get('citation', []))}개"


def cites(t):
    """판정 전 답의 인용을 조례 이름 없이 짧게(예: 「동물보호 제5조 제12항」)."""
    c = (t.get("draft") or {}).get("citation") or []
    return " · ".join(x.replace("서울특별시 ", "").replace(" 조례", "") for x in c) or "—"


def suggest(ids, er, br):
    if not ids:
        return "없음"
    kinds = " · ".join(f"{k} {v}" for k, v in Counter(TYPES[er[i]["type"]] for i in ids).most_common())
    moves = " · ".join(f"{k} {v}" for k, v in Counter(f"{cause(br[i])} → {cause(er[i])}" for i in ids).most_common(3))
    return f"{len(ids)}문항(종류 {kinds}; 원인 {moves})"


def compare(es, er, bs, br, top=10):
    if es["env"]["questions_hash"] != bs["env"]["questions_hash"]:
        sys.exit("✗ 두 실행의 문항이 다릅니다(문항 지문이 다름). 같은 묶음 · 표본 · 씨앗으로 잰 기준을 주세요.")
    ids = sorted(set(er) & set(br))
    better = [i for i in ids if er[i]["score"] > br[i]["score"]]
    worse = sorted((i for i in ids if er[i]["score"] < br[i]["score"]), key=lambda i: (er[i]["score"] - br[i]["score"], i))
    em, bm = es["metrics"], bs["metrics"]
    exp = es["experiment"]
    sw = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in es["switches"].items()) or "출발 판"
    out = [f"# 비교: {es['run_id']}", "",
           f"> `python3 eval/compare.py {es['run_id']} --base {bs['run_id']}`가 만들었다. 손으로 고치지 않는다.", "",
           f"- 실험: **{exp['name']}** {exp.get('issue') or ''} · {exp.get('cycle', '—')}주기 · 켠 스위치 {sw} · 결론 {es.get('conclusion') or '—'}",
           f"- 기준: **{bs['experiment']['name']}** `{bs['run_id']}`",
           f"- 묶음: {es['args']['split']} {len(ids)}문항 (문항 지문 `{es['env']['questions_hash']}`)"]
    ec, bc = es["env"]["code_hash"], bs["env"]["code_hash"]
    if ec != bc:   # 기준 고르기는 같은 코드 판이 없으면 코드가 다른 출발 판도 고른다
        out.append(f"- ⚠ 두 실행의 엔진 코드가 다르다(코드 지문 `{bc}` → `{ec}`). 아래 차이에는 코드가 바뀐 몫도 섞여 있을 수 있다. "
                   "스위치 몫만 보려면 같은 코드로 돌린 끈 판을 `--base`로 준다.")
    elif es["settings_hash"] == bs["settings_hash"]:
        out.append("- ⚠ 두 실행의 설정과 엔진 코드가 같다. 아래 차이는 모두 흔들림(같은 설정을 다시 돌려 생긴 차이)이다.")
    out += ["", "## 한눈에", "", "| | 기준 | 실험 | 차이 |", "|---|---|---|---|"]
    rows = [("가중", bm.get("weighted"), em.get("weighted"))]
    rows += [(k, bm["by_type"].get(k), em["by_type"].get(k)) for k in WEIGHTS]
    rows += [("과잉 포기 %", bm.get("over_abstain"), em.get("over_abstain")),
             ("인용 수", bm.get("citations_per_answer"), em.get("citations_per_answer")),
             ("지연 95% (초)", bm.get("latency_p95"), em.get("latency_p95")), ("비용 $", bs.get("cost_usd"), es.get("cost_usd"))]
    for k, b, e in rows:
        d = "—" if None in (b, e) else f"{e - b:+.2f}".rstrip("0").rstrip(".")
        out.append(f"| {k} | {b} | {e} | {d} |")
    out += ["", f"좋아진 문항 {len(better)} · 나빠진 문항 {len(worse)} · 점수가 같은 문항 {len(ids) - len(better) - len(worse)}", "",
            "## 원인별 문항 수", "", "| 원인 | 기준 | 실험 | 차이 |", "|---|---|---|---|"]
    bc = Counter(bucket(cause(br[i])) for i in ids)
    ec = Counter(bucket(cause(er[i])) for i in ids)
    for c in [OK] + CAUSES:
        if bc[c] or ec[c]:
            out.append(f"| {c} | {bc[c]} | {ec[c]} | {ec[c] - bc[c]:+d} |")
    out += ["", "## 배운 점 첫 줄 제안", "",
            "실행 요약의 `lesson` 첫 줄(무엇이 좋아지고 나빠졌나)에 그대로 쓸 수 있다.", "",
            f"> 좋아짐 {suggest(better, er, br)} / 나빠짐 {suggest(worse, er, br)}"]
    for title, lst in (("좋아진 문항", better), ("나빠진 문항", worse)):
        out += ["", f"## {title} ({len(lst)})", ""]
        if lst:
            out += ["| 문항 | 종류 | 조례 | 점수 (기준 → 실험) | 원인 (기준 → 실험) |", "|---|---|---|---|---|"]
            out += [f"| {i} | {TYPES[er[i]['type']]} | {LAWS.get(er[i]['law'], er[i]['law'])} | {br[i]['score']:g} → {er[i]['score']:g} | "
                    f"{cause(br[i])} → {cause(er[i])} |" for i in (sorted(lst) if title == "좋아진 문항" else lst)]
        else:
            out.append("없음")
    out += ["", f"## 나빠진 문항 상위 {min(top, len(worse))}개 — 단계 요약", "",
            "점수가 많이 떨어진 순서다. 문항마다 단계별 전체(프롬프트 · 모델 출력)는 `python3 eval/trajectory.py <실행> <문항>`로 본다."]
    for i in worse[:top]:
        e, b = er[i], br[i]
        te, tb = e.get("trace") or {}, b.get("trace") or {}
        gold = " / ".join(" 또는 ".join(alts) for alts in e["gold"]) or "없음(함정)"
        out += ["", f"### {i} · {TYPES[e['type']]} · {LAWS.get(e['law'], e['law'])} · 점수 {b['score']:g} → {e['score']:g}", "",
                f"- 질문: {e['question']}", f"- 정답 조항: {gold}", "",
                "| 단계 | 기준 | 실험 |", "|---|---|---|",
                f"| 검색: 정답이 후보에 | {candidates(b)} | {candidates(e)} |",
                f"| 모델이 고른 인용(판정 전) | {cites(tb)} | {cites(te)} |",
                f"| 판정 | {tb.get('verdict') or '—'} | {te.get('verdict') or '—'} |",
                f"| 최종 | {final(b)} | {final(e)} |", "",
                f"- 실험의 답(판정 전): {((te.get('draft') or {}).get('answer') or '—')[:160]}"]
    return "\n".join(out) + "\n"


def selftest():
    def row(i, typ, score, cause, cand=1.0, gold=True):
        return {"id": i, "type": typ, "law": "parking", "question": "?", "gold": [["서울특별시 주차장 설치 및 관리 조례 제7조 제1항"]] if gold else [],
                "score": score, "cause": cause, "cand": cand if gold else None, "unknown": cause is not None and "확인 불가" in cause,
                "response": {"citation": []}, "trace": {"draft": {"citation": [], "answer": "답"}, "verdict": "grounded", "reason": None}}
    base = {"p-1": row("p-1", "단순 조회", 0.0, CAUSES[0], cand=0.0), "p-2": row("p-2", "조건 판단", 1.0, None),
            "p-3": row("p-3", "여러 조항 결합", 0.5, CAUSES[0], cand=0.5), "t-1": row("t-1", "근거 없음 (함정)", 1.0, None, gold=False)}
    exp = {"p-1": row("p-1", "단순 조회", 1.0, None), "p-2": row("p-2", "조건 판단", 0.0, f"{CAUSES[3]} (found 거짓)"),
           "p-3": row("p-3", "여러 조항 결합", 0.5, CAUSES[0], cand=0.5), "t-1": row("t-1", "근거 없음 (함정)", 0.0, CAUSES[4], gold=False)}
    meta = {"env": {"questions_hash": "q", "code_hash": "c"}, "settings_hash": "s", "switches": {}, "args": {"split": "dev"},
            "metrics": {"weighted": 1.0, "by_type": {}}, "cost_usd": 0.1, "conclusion": ""}
    es = dict(meta, run_id="e", experiment={"name": "exp", "issue": "#1", "cycle": 1}, switches={"top_k": 20}, settings_hash="x")
    bs = dict(meta, run_id="b", experiment={"name": "baseline"})
    page = compare(es, exp, bs, base)
    assert "좋아진 문항 1 · 나빠진 문항 2 · 점수가 같은 문항 1" in page
    assert f"| {CAUSES[3]} | 0 | 1 | +1 |" in page and f"| {OK} | 2 | 1 | -1 |" in page
    assert "### p-2 · 조건 · 주차장 · 점수 1 → 0" in page and "### t-1" in page and "### p-3" not in page
    assert page.index("### p-2") < page.index("### t-1")   # 같은 폭이면 문항 id 순
    assert "⚠" not in page                                              # 설정만 다르면 경고 없음
    same = dict(bs, settings_hash="x")
    assert "모두 흔들림" in compare(es, exp, same, base)                    # 설정 · 엔진 코드가 둘 다 같을 때만 흔들림
    for b in (same, bs):                                                # 코드가 다르면 흔들림이라 하지 않고 그 사실을 적는다
        other = compare(es, exp, dict(b, env={"questions_hash": "q", "code_hash": "d"}), base)
        assert "흔들림" not in other and "엔진 코드가 다르다(코드 지문 `d` → `c`)" in other
    try:
        compare(es, exp, dict(bs, env={"questions_hash": "다름"}), base)
        raise AssertionError("문항이 다른데 견줬다")
    except SystemExit:
        pass
    g = lambda gid, name, created, code="c", table="t": {"group": gid, "name": name, "full": True, "table": table,  # noqa: E731
                                                       "created": created, "code_hash": code, "run_id": gid + "-r1"}
    gs = [g("old", "baseline", "1"), g("new", "baseline", "3", code="d"), g("me", "x", "4"), g("other", "baseline", "2", table="u")]
    assert pick_base(gs, gs[2], lambda r: True) == "old-r1"            # 엔진 코드가 같은 출발 판 먼저
    assert pick_base(gs, gs[1], lambda r: True) == "old-r1"            # 자기 묶음은 뺀다
    assert pick_base(gs, gs[2], lambda r: r != "old-r1") == "new-r1"   # 문항별 결과가 없는 판은 건너뛴다

    from board import experiments                                      # 「배운 점 모음」에는 버림 · 보류 실험만

    def summ(gid, conclusion, lesson):
        return {"group": gid, "run_id": gid, "created": "2026-11-08T10:00:00+09:00", "conclusion": conclusion, "lesson": lesson,
                "experiment": {"name": gid, "issue": "#24", "cycle": 1}, "args": {"mode": "full", "split": "dev", "sample": None, "seed": 0},
                "settings": {"top_k": 20}, "switches": {"top_k": 20}, "cost_usd": 0.4,
                "env": {"questions_hash": "q", "code_commit": "abc", "code_dirty": False, "code_hash": "c", "eval_commit": "e",
                        "retrieval_used": ["hybrid"]},
                "metrics": {"n": 661, "weighted": 70.0, "by_type": {}, "by_law": {}, "over_abstain": 20.0,
                            "citations_per_answer": 1.5, "latency_p95": 6.0}}
    page = experiments(groups([(summ("top20", "버림 — 함정이 떨어짐", ["나빠짐 함정 3", "왜: 비슷한 조항을 억지로 고름", "다음: 함정 신호"]), None),
                               (summ("dict", "채택 — 올랐다", ["좋아짐 결합", "왜", "다음"]), None)]), 2)
    tail = page.split("## 배운 점 모음")[1]
    assert "### top20" in tail and "- 왜: 비슷한 조항을 억지로 고름" in tail and "### dict" not in tail
    assert "| 나빠짐 함정 3 / 왜: 비슷한 조항을 억지로 고름 / 다음: 함정 신호 |" in page
    print("selftest ok")


def main():
    ap = argparse.ArgumentParser(description="실험과 기준을 문항마다 견줘 docs/engine/compare/<실행>.md를 만든다")
    ap.add_argument("run", nargs="?", help="실험 실행(eval/runs/<실행>.json의 이름)")
    ap.add_argument("--base", help="기준 실행(기본: 리더보드의 「기준」 판 가운데 이 컴퓨터에 문항별 결과가 있는 것)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.run:
        sys.exit(__doc__)
    es, er = load(a.run)
    base = a.base
    if not base:
        gs = groups(local_runs())
        base = pick_base(gs, next(g for g in gs if g["group"] == es["group"]), lambda r: (RESULTS / f"{r}.jsonl").exists())
        if not base:
            sys.exit("✗ 같은 문항으로 잰 출발 판 가운데 이 컴퓨터에 문항별 결과가 있는 것이 없습니다. 같은 날 끈 판을 돌려 --base로 주세요.")
    bs, br = load(base)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{es['run_id']}.md"
    path.write_text(compare(es, er, bs, br), encoding="utf-8")
    print(f"{path.relative_to(ROOT)} (기준 {bs['run_id']})")


if __name__ == "__main__":
    main()
