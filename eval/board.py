"""리더보드 · 실험 기록 만들기: eval/runs/*.json(실행 요약)을 모아 docs/engine/leaderboard.md · experiments.md를 다시 쓴다.

  python3 eval/board.py                              지금 폴더의 실행 요약으로 두 문서를 다시 쓴다
  python3 eval/board.py --from-branches 'origin/*'   원격 브랜치들(병합 전 실험 포함)의 실행 요약까지 모아 화면에만 보인다.
                                                     파일을 쓰지 않는다. 먼저 git fetch origin. 브랜치 칸이 붙는다
두 문서는 손으로 고치지 않는다. PR끼리 충돌하면 main을 받은 뒤 이 명령을 다시 돌린다(같은 실행 파일이면 늘 같은 표).
결론(채택 · 버림 · 보류)은 그 실행 파일의 "conclusion" 칸에 적고 다시 돌린다.
"""
import argparse
import fnmatch
import json
import subprocess
from collections import defaultdict

from run import CAUSES, ROOT, RUNS, WEIGHTS, cycle_of

DOCS = ROOT / "docs" / "engine"
LAWS = {"parking": "주차장", "park": "도시공원", "smoking": "금연", "animal": "동물보호", "bicycle": "자전거",
        "youth": "청년", "common": "공통", "kit": "킷 예시"}
CYCLES = {0: "0주기 · 출발 판 (11/6~11/7)", 1: "1주기 · 탐색 (11/7~11/8)", 2: "2주기 · 탐색 (11/9~11/10)",
          3: "3주기 · 탐색 (11/11~11/12)", 4: "4주기 · 수렴 (11/13~11/14)", 5: "5주기 · 수렴 (11/15~11/16)",
          6: "동결 뒤 (11/17~)"}
HEAD = ("> `python3 eval/board.py`가 `eval/runs/`의 실행 요약 {n}개로 만든다. 손으로 고치지 않는다. "
        "규칙: [재현 규칙](reproducibility.md)")


def avg(xs):
    """반복 실행의 숫자를 평균한다(dict는 칸마다). None이 섞이면 None."""
    if isinstance(xs[0], dict):     # 칸이 빠진 반복(틀린 원인 0개 등)은 0으로 본다
        keys = list(dict.fromkeys(k for x in xs for k in x))
        return {k: avg([x.get(k, 0) for x in xs]) for k in keys}
    if any(x is None for x in xs) or not isinstance(xs[0], (int, float)) or isinstance(xs[0], bool):
        return xs[0] if all(x == xs[0] for x in xs) else None
    return round(sum(xs) / len(xs), 2)


def local_runs():
    return [(json.loads(p.read_text(encoding="utf-8")), None) for p in sorted(RUNS.glob("*.json"))]


def git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True).stdout


def branch_runs(pattern):
    """원격 브랜치들의 eval/runs/*.json을 git에서 바로 읽는다(작업 폴더는 건드리지 않음). main에도 있는 파일은 main으로 적는다."""
    refs = [r for r in git("for-each-ref", "--format=%(refname:short)", "refs/remotes/").split()
            if "/" in r and not r.endswith("/HEAD") and fnmatch.fnmatchcase(r, pattern)]   # git의 *는 /를 못 넘어서 여기서 맞춘다
    seen, out = set(), []
    for ref in sorted(refs, key=lambda r: (not r.endswith("/main"), r)):
        for path in git("ls-tree", "--name-only", ref, "eval/runs/").split():
            if path.endswith(".json") and path not in seen:
                seen.add(path)
                out.append((json.loads(git("show", f"{ref}:{path}")), ref))
    return out


def groups(runs):
    by = defaultdict(list)
    for r, branch in runs:
        by[r["group"]].append((r, branch))
    out = []
    for items in by.values():
        rs = [r for r, _ in items]
        r0, e = rs[0], rs[0]["env"]
        full = r0["args"]["mode"] == "full"
        cycle = r0["experiment"].get("cycle")
        out.append({
            "group": r0["group"], "branch": items[0][1], "name": r0["experiment"]["name"],
            "issue": r0["experiment"]["issue"] or "", "cycle": cycle_of(r0["created"]) if cycle is None else cycle,
            "conclusion": next((r["conclusion"] for r in rs if r["conclusion"]), ""), "full": full,
            "explore": bool(r0["settings"].get("explore")),
            "split": r0["args"]["split"], "sample": r0["args"]["sample"], "seed": r0["args"]["seed"],
            "table": (r0["args"]["split"], r0["args"]["sample"], r0["args"]["seed"], e["questions_hash"]),
            "n": r0["metrics"]["n"], "date": r0["created"][:10], "created": r0["created"], "run_id": r0["run_id"],
            "code": e["code_commit"] + (" ⚠수정" if e["code_dirty"] else ""), "code_hash": e["code_hash"],
            "eval": e["eval_commit"],
            "search": "/".join(e["retrieval_used"]), "switches": r0["switches"], "repeats": len(rs),
            "w": [r["metrics"]["weighted"] for r in rs if full and r["metrics"]["weighted"] is not None],
            "m": avg([r["metrics"] for r in rs]), "top_k": r0["settings"]["top_k"],
            "cost": None if any(r["cost_usd"] is None for r in rs) else round(sum(r["cost_usd"] for r in rs), 3),
        })
    return sorted(out, key=lambda g: g["created"])


def num(x, unit="", digits=1):
    return "—" if x is None else f"{x:g}{unit}" if isinstance(x, int) else f"{x:.{digits}f}{unit}"


def label(g):
    return g["split"] + (f" {g['sample']}문항 표본(씨앗 {g['seed']})" if g["sample"] else " 전체") + f" · {g['n']}문항"


def name(g):
    return g["name"] + (" (탐색)" if g["explore"] else "")


def mark(delta, band):
    if delta is None:
        return "—", "—"
    if band is None:
        return f"{delta:+.1f}", "폭 모름"
    if delta > 2 * band:
        return f"{delta:+.1f}", "✅ 폭의 2배 넘게 오름"
    if abs(delta) <= band:
        return f"{delta:+.1f}", "흔들림 안"
    return f"{delta:+.1f}", "↑ 흔들림 밖" if delta > 0 else "↓ 흔들림 밖"


def noise(gs, table):
    """흔들림 폭: 같은 표(같은 문항)에서 가장 최근 출발 판과 엔진 코드가 같은 출발 판 실행을 모두 모은 가중의 최대 − 최소.
    두 번이 안 되면 같은 묶음의 다른 표에서 같은 방법으로 잰 폭을 쓰고 그렇다고 적는다. 3번만 모으면 우연히 좁게 나올 수 있어서
    반복 묶음 하나가 아니라 같은 조건의 실행을 다 모은다."""
    def band(t):
        bases = sorted((g for g in gs if g["name"] == "baseline" and g["table"] == t and g["w"]), key=lambda g: g["created"])
        ws = [x for g in bases if g["code_hash"] == bases[-1]["code_hash"] for x in g["w"]] if bases else []
        return (round(max(ws) - min(ws), 1), len(ws)) if len(ws) > 1 else (None, 0)
    width, k = band(table)
    if width is not None:
        return width, f" (출발 판 {k}번)"
    for t in sorted({g["table"] for g in gs if g["split"] == table[0] and g["table"] != table}, key=lambda t: t[1] or 0):
        width, k = band(t)
        if width is not None:
            n = next(g["n"] for g in gs if g["table"] == t)
            return width, f" ({n}문항으로 {k}번 잰 폭)"
    return None, ""


def leaderboard(gs, n_runs):
    br = any(g["branch"] for g in gs)
    bh, bs = ("브랜치 | ", "---|") if br else ("", "")
    cell = (lambda g: f"{g['branch'] or '지금 폴더'} | ") if br else (lambda g: "")
    out = ["# 엔진 리더보드", "", HEAD.format(n=n_runs) + " · 기록 표: [실험 기록](experiments.md)", "",
           "## 끝까지 돌린 점수", "",
           "같은 문항끼리만 견준다(묶음 · 표본 · 문항 지문이 같은 표). 숫자는 % 점수다. **가중** = (3 × 단순 + 3 × 조건 + 3 × 결합 + 2 × 함정) ÷ 11. "
           "**출발 판 대비** = 같은 표의 출발 판(baseline, 코드 지문이 같은 것이 있으면 그것, 없으면 가장 최근 것)과의 가중 차이. "
           "**흔들림** = 출발 판을 같은 설정으로 여러 번 돌린 가중 폭과 견준 것. 채택 기준(계획 5-2절)은 「폭의 2배 넘게 오름」. "
           "**(탐색)** = 90초 조건 없이 잰 실행(1~3주기). **궤적** = 문항마다 단계별 입력 · 프롬프트 · 모델 출력을 보는 화면으로, "
           "그 실행을 돌린 컴퓨터에만 있다(`eval/results/`는 git에 안 올림).", ""]
    full = [g for g in gs if g["full"] and g["split"] != "holdout"]
    if not full:
        out += ["아직 없음. 키를 넣고 `python3 eval/run.py --split dev`(출발 판)와 "
                "`python3 eval/run.py --sample 100 --repeat 3`(흔들림 폭)을 돌린 뒤 이 명령을 다시 돌린다.", ""]
    tables = sorted({g["table"] for g in full}, key=lambda t: (t[0] != "dev", t[1] or 0, t[0]))
    for t in tables:
        rows = sorted([g for g in full if g["table"] == t], key=lambda g: -(g["m"]["weighted"] or 0))
        bases = sorted((g for g in rows if g["name"] == "baseline"), key=lambda g: g["created"])  # 오래된 것 → 최근 것
        band, band_note = noise(gs, t)
        out += [f"### {label(rows[0])} (문항 지문 `{t[3]}`)", "",
                f"흔들림 폭: {num(band, '점')}{band_note}", "",
                f"| 순위 | {bh}주기 | 실험 | 이슈 | 가중 | 출발 판 대비 | 흔들림 | 단순 | 조건 | 결합 | 함정 | 과잉 포기 | 인용 수 | 지연 95% | 비용 | 반복 | 궤적 | 코드 · 평가셋 | 날짜 |",
                f"|---|{bs}---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for i, g in enumerate(rows, 1):
            m = g["m"]
            base = next((b for b in reversed(bases) if b["code_hash"] == g["code_hash"]), bases[-1] if bases else None)
            delta = None if base is None or base is g or None in (m["weighted"], base["m"]["weighted"]) \
                else round(m["weighted"] - base["m"]["weighted"], 1)
            d, flag = mark(delta, band) if base is not g else ("기준", "—")
            spread = f" ({min(g['w']):.1f}~{max(g['w']):.1f})" if len(g["w"]) > 1 else ""
            cost = "—" if g["cost"] is None else f"${g['cost']:.2f}"
            out.append(f"| {i} | {cell(g)}{g['cycle']} | {name(g)} | {g['issue']} | **{num(m['weighted'])}**{spread} | {d} | {flag} | "
                       + " | ".join(num(m["by_type"].get(k)) for k in WEIGHTS)
                       + f" | {num(m['over_abstain'])} | {num(m['citations_per_answer'], digits=2)} | {num(m['latency_p95'], '초')} | "
                       f"{cost} | {g['repeats']} | [보기](../../eval/results/{g['run_id']}.html) | {g['code']} · {g['eval']} | {g['date']} |")
        laws = sorted({k for g in rows for k in g["m"]["by_law"]}, key=lambda k: (list(LAWS).index(k) if k in LAWS else 99, k))
        out += ["", "조례별 근거 정확도(함정 뺌):", "",
                "| 실험 | " + " | ".join(LAWS.get(k, k) for k in laws) + " |", "|---|" + "---|" * len(laws)]
        out += [f"| {name(g)} | " + " | ".join(num(g["m"]["by_law"].get(k)) for k in laws) + " |" for g in rows]
        out += ["", "틀린 원인(문항 수, 반복은 평균, 「답이 있는데 확인 불가」는 까닭별 합):", "",
                "| 실험 | 검색 적중률 | " + " | ".join(CAUSES) + " |", "|---|---|" + "---|" * len(CAUSES)]
        for g in rows:
            c = defaultdict(float)
            for k, v in (g["m"].get("causes") or {}).items():
                c[next((x for x in CAUSES if k.startswith(x)), CAUSES[-1])] += v or 0
            out.append(f"| {name(g)} | {num(g['m']['retrieval_hit'])} | " + " | ".join(f"{c.get(x, 0):g}" for x in CAUSES) + " |")
        out.append("")

    ret = sorted([g for g in gs if not g["full"]], key=lambda g: (g["split"], -(g["m"]["hit"].get(str(g["top_k"])) or 0)))
    out += ["## 검색 적중률 (키 없이도 잰다)", ""]
    out += ["정답 근거가 검색 후보 안에 드는 비율(함정 · 회색지대 뺌, 킷 채점식). 「유형별」은 실험의 후보 수(top-k) 기준.", "",
            f"| {bh}주기 | 실험 | 이슈 | 묶음 | 검색 | top-1 | top-3 | top-k | top-10 | top-20 | 단순 | 조건 | 결합 | 코드 · 평가셋 | 날짜 |",
            f"|{bs}---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"] if ret else \
        ["아직 없음. `python3 eval/run.py --split dev --mode retrieval`"]
    for g in ret:
        h, k = g["m"]["hit"], str(g["top_k"])
        out.append(f"| {cell(g)}{g['cycle']} | {name(g)} | {g['issue']} | {label(g)} | {g['search']} | {num(h.get('1'))} | {num(h.get('3'))} | "
                   f"**{num(h.get(k))}** (top-{k}) | {num(h.get('10'))} | {num(h.get('20'))} | "
                   + " | ".join(num(g["m"]["by_type"].get(t)) for t in ("단순", "조건", "결합")) + f" | {g['code']} · {g['eval']} | {g['date']} |")
    reps = [g for g in gs if len(g["w"]) > 1]
    out += ["", "## 흔들림 (같은 설정 반복)", ""]
    out += ["| 실험 | 묶음 | 가중 (회마다) | 폭 | 코드 |", "|---|---|---|---|---|"] + [
        f"| {name(g)} | {label(g)} | {' · '.join(f'{x:.1f}' for x in g['w'])} | {max(g['w']) - min(g['w']):.1f} | {g['code']} |"
        for g in reps] if reps else ["아직 없음. `python3 eval/run.py --sample 100 --repeat 3`"]
    hold = [g for g in gs if g["full"] and g["split"] == "holdout"]
    out += ["", "## holdout (요약만, 큰 이정표에서만)", ""]
    out += ["| 날짜 | 실험 | 가중 | 단순 | 조건 | 결합 | 함정 | 과잉 포기 | 코드 · 평가셋 |", "|---|---|---|---|---|---|---|---|---|"] + [
        f"| {g['date']} | {name(g)} | {num(g['m']['weighted'])} | " + " | ".join(num(g["m"]["by_type"].get(k)) for k in WEIGHTS)
        + f" | {num(g['m']['over_abstain'])} | {g['code']} · {g['eval']} |" for g in hold] if hold else ["아직 없음(11/18 동결 판에서 한 번)."]
    return "\n".join(out) + "\n"


def experiments(gs, n_runs):
    br = any(g["branch"] for g in gs)
    out = ["# 실험 기록", "", HEAD.format(n=n_runs) + " · 한눈에 비교: [리더보드](leaderboard.md)", "",
           "- 실험마다 켠 판과 끈 판을 **같은 main 커밋 · 같은 문항**으로 같은 날 잰다(계획 5-2절). 「켠 스위치」는 출발 판(`engine/config.py` DEFAULTS)과 다른 설정이다.",
           "- 결론은 그 실행 파일(`eval/runs/<실행>.json`)의 `\"conclusion\"`에 「채택 · 버림 · 보류 — 한 줄 이유」로 적고 `python3 eval/board.py`를 다시 돌린다. 채택 · 버림은 동규가 정한다.",
           "- 「검색만」 줄의 단순 · 조건 · 결합은 근거 정확도가 아니라 검색 적중률(top-k)이다. 「(탐색)」은 90초 조건 없이 잰 실행이다.",
           "- 주기는 설정 파일의 `cycle`, 없으면 실행한 날짜로 정한다(계획 0절 표)."]
    for cycle in sorted({g["cycle"] for g in gs}):
        out += ["", f"## {CYCLES.get(cycle, f'{cycle}주기')}", "",
                ("| 브랜치 " if br else "") + "| 날짜 | 이슈 | main · 평가셋 커밋 | 켠 스위치 | 묶음(문항) | 단순 | 조건 | 결합 | 함정 | 가중 | 과잉 포기 | 인용 수 | 지연 95% | 비용 | 결론 |",
                ("|---" if br else "") + "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for g in (g for g in gs if g["cycle"] == cycle):
            m = g["m"]
            sw = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in g["switches"].items()) or "출발 판"
            what = f"{name(g)} · {label(g)}" + (f" · {g['repeats']}회 평균" if g["repeats"] > 1 else "")
            cost = "—" if g["cost"] is None else f"${g['cost']:.2f}"
            if g["full"]:
                cells = [num(m["by_type"].get(k)) for k in WEIGHTS] + [num(m["weighted"]), num(m["over_abstain"]),
                                                                       num(m["citations_per_answer"], digits=2), num(m["latency_p95"], "초")]
            else:
                k = str(g["top_k"])
                what += f" · 검색만({g['search']}) top-{k} {num(m['hit'].get(k))}"
                cells = [num(m["by_type"].get(t)) for t in ("단순", "조건", "결합")] + ["—"] * 5
            out.append((f"| {g['branch'] or '지금 폴더'} " if br else "") + f"| {g['date']} | {g['issue']} | {g['code']} · {g['eval']} | {sw} | {what} | "
                       + " | ".join(cells) + f" | {cost} | {g['conclusion']} |")
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser(description="리더보드 · 실험 기록 만들기 (eval/board.py 맨 위 설명 참고)")
    ap.add_argument("--from-branches", metavar="패턴", help="원격 브랜치 패턴(예: 'origin/*')의 실행 요약까지 모아 화면에만 보인다")
    a = ap.parse_args()
    if a.from_branches:
        runs = branch_runs(a.from_branches)
        gs = groups(runs)
        print(experiments(gs, len(runs)) + "\n" + leaderboard(gs, len(runs)))
        print(f"브랜치 {len({b for _, b in runs})}개에서 실행 요약 {len(runs)}개를 읽었다(파일은 쓰지 않음). 최신으로 보려면 먼저 git fetch origin.")
        return
    runs = local_runs()
    gs = groups(runs)
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "leaderboard.md").write_text(leaderboard(gs, len(runs)), encoding="utf-8")
    (DOCS / "experiments.md").write_text(experiments(gs, len(runs)), encoding="utf-8")
    print(f"실행 요약 {len(runs)}개 → docs/engine/leaderboard.md · experiments.md")


if __name__ == "__main__":
    main()
