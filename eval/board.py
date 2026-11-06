"""리더보드 · 실험 기록 만들기: eval/runs/*.json(실행 요약)을 모아 docs/engine/leaderboard.md · experiments.md를 다시 쓴다.

  python3 eval/board.py                              지금 폴더의 실행 요약으로 두 문서를 다시 쓴다
  python3 eval/board.py --from-branches 'origin/*'   원격 브랜치들(병합 전 실험 포함)의 실행 요약까지 모아 화면에만 보인다.
                                                     파일을 쓰지 않는다. 먼저 git fetch origin. 브랜치 칸이 붙는다
두 문서는 손으로 고치지 않는다. PR끼리 충돌하면 main을 받은 뒤 이 명령을 다시 돌린다(같은 실행 파일이면 늘 같은 표).
결론(채택 · 버림 · 보류)은 그 실행 파일의 "conclusion" 칸에, 배운 점 세 줄은 "lesson" 칸에 적고 다시 돌린다.
  python3 eval/board.py --tree                       가설 나무 docs/engine/tree.json · tree.html도 만든다(배분일, gh 필요)
"""
import argparse
import fnmatch
import json
import re
import subprocess
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from run import CAUSES, KST, ROOT, RUNS, WEIGHTS, cycle_of

DOCS = ROOT / "docs" / "engine"
LAWS = {"parking": "주차장", "park": "도시공원", "smoking": "금연", "animal": "동물보호", "bicycle": "자전거",
        "youth": "청년", "common": "공통", "kit": "킷 예시"}
CYCLES = {0: "0주기 · 출발 판 (11/6~11/7)", 1: "1주기 · 탐색 (11/7~11/8)", 2: "2주기 · 탐색 (11/9~11/10)",
          3: "3주기 · 탐색 (11/11~11/12)", 4: "4주기 · 수렴 (11/13~11/14)", 5: "5주기 · 수렴 (11/15~11/16)",
          6: "동결 뒤 (11/17~)"}
DEFAULT = ('**재는 법 기본값**: 채택 판단은 **dev 전체**로 하고, 켠 판 · 끈 판을 **각각 두 번 이상** 잰다(`python3 eval/run.py --config <설정> --split dev --repeat 2`). 100문항 표본은 빠른 확인용으로만 쓴다(흔들림이 2.5~4.9점이라 채택 판단에 쓰지 않는다). dev 전체 한 판은 약 10분, 기록 비용 약 $0.38이다. 실제 콘솔 차감은 그 6할쯤이라 한 판 약 $0.2다(11-06 기준).')
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
            "lesson": next((r["lesson"] for r in rs if r.get("lesson")), []),
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


def base_of(gs, g):
    """리더보드 「출발 판 대비」의 기준: 같은 표(같은 문항)의 출발 판 가운데 엔진 코드 지문이 같은 것, 없으면 가장 최근 것.
    검색만 잰 실행은 같은 검색 방식(keyword · hybrid)끼리."""
    bases = sorted((b for b in gs if b["name"] == "baseline" and b["table"] == g["table"] and b["full"] == g["full"]
                    and (g["full"] or b["search"] == g["search"])), key=lambda b: b["created"])
    return next((b for b in reversed(bases) if b["code_hash"] == g["code_hash"]), bases[-1] if bases else None)


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
           "그 실행을 돌린 컴퓨터에만 있다(`eval/results/`는 git에 안 올림). **비교** = 기준과 문항마다 견준 문서(`eval/compare.py`)로, "
           "커밋돼 있어 GitHub에서 열린다.", "",
           DEFAULT, "", "**가설 나무**(가설 → 실험 → 다음 가설): 로컬에서 보기 `open docs/engine/tree.html`(배분일에 `python3 eval/board.py --tree`로 다시 만든다).", ""]
    full = [g for g in gs if g["full"] and g["split"] != "holdout"]
    if not full:
        out += ["아직 없음. 키를 넣고 `python3 eval/run.py --split dev`(출발 판)와 "
                "`python3 eval/run.py --sample 100 --repeat 3`(흔들림 폭)을 돌린 뒤 이 명령을 다시 돌린다.", ""]
    tables = sorted({g["table"] for g in full}, key=lambda t: (t[0] != "dev", t[1] or 0, t[0]))
    for t in tables:
        rows = sorted([g for g in full if g["table"] == t], key=lambda g: -(g["m"]["weighted"] or 0))
        band, band_note = noise(gs, t)
        out += [f"### {label(rows[0])} (문항 지문 `{t[3]}`)", "",
                f"흔들림 폭: {num(band, '점')}{band_note}", "",
                f"| 순위 | {bh}주기 | 실험 | 이슈 | 가중 | 출발 판 대비 | 흔들림 | 단순 | 조건 | 결합 | 함정 | 과잉 포기 | 인용 수 | 지연 95% | 비용 | 반복 | 궤적 | 코드 · 평가셋 | 날짜 |",
                f"|---|{bs}---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for i, g in enumerate(rows, 1):
            m = g["m"]
            base = base_of(gs, g)
            delta = None if base is None or base is g or None in (m["weighted"], base["m"]["weighted"]) \
                else round(m["weighted"] - base["m"]["weighted"], 1)
            d, flag = mark(delta, band) if base is not g else ("기준", "—")
            spread = f" ({min(g['w']):.1f}~{max(g['w']):.1f})" if len(g["w"]) > 1 else ""
            cost = "—" if g["cost"] is None else f"${g['cost']:.2f}"
            out.append(f"| {i} | {cell(g)}{g['cycle']} | {name(g)} | {g['issue']} | **{num(m['weighted'])}**{spread} | {d} | {flag} | "
                       + " | ".join(num(m["by_type"].get(k)) for k in WEIGHTS)
                       + f" | {num(m['over_abstain'])} | {num(m['citations_per_answer'], digits=2)} | {num(m['latency_p95'], '초')} | "
                       f"{cost} | {g['repeats']} | {links(g)} | {g['code']} · {g['eval']} | {g['date']} |")
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
           "- " + DEFAULT,
           "- 결론은 그 실행 파일(`eval/runs/<실행>.json`)의 `\"conclusion\"`에 「채택 · 버림 · 보류 — 한 줄 이유」로 적고 `python3 eval/board.py`를 다시 돌린다. 채택 · 버림은 동규가 정한다.",
           "- 「검색만」 줄의 단순 · 조건 · 결합은 근거 정확도가 아니라 검색 적중률(top-k)이다. 「(탐색)」은 90초 조건 없이 잰 실행이다.",
           "- 주기는 설정 파일의 `cycle`, 없으면 실행한 날짜로 정한다(계획 0절 표).",
           "- 배운 점은 버림 · 보류여도 실행 요약의 `\"lesson\"`에 세 줄로 적는다: ① 무엇이 좋아지고 나빠졌나(종류 · 원인) ② 왜 그런 것 같나 "
           "③ 다음에 해 볼 것. 버림 · 보류 실험의 배운 점은 맨 아래 「배운 점 모음」에 모인다. 배분일에는 그것부터 읽고 다음 가설을 고른다."]
    for cycle in sorted({g["cycle"] for g in gs}):
        out += ["", f"## {CYCLES.get(cycle, f'{cycle}주기')}", "",
                ("| 브랜치 " if br else "") + "| 날짜 | 이슈 | main · 평가셋 커밋 | 켠 스위치 | 묶음(문항) | 단순 | 조건 | 결합 | 함정 | 가중 | 과잉 포기 | 인용 수 | 지연 95% | 비용 | 결론 | 배운 점 |",
                ("|---" if br else "") + "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
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
                       + " | ".join(cells) + f" | {cost} | {g['conclusion']} | {' / '.join(g['lesson'])} |")
    kept = [g for g in gs if g["conclusion"].startswith(("버림", "보류"))]
    out += ["", "## 배운 점 모음 (버림 · 보류 실험)", "",
            "버린 실험도 배운 것은 남긴다. 배분일에 이 절부터 읽고 다음 가설을 고른다(일하는 방식 4절)."]
    for g in kept:
        out += ["", f"### {name(g)} {g['issue']} · {g['cycle']}주기 · {label(g)}", "", f"- 결론: {g['conclusion']}"]
        out += [f"- {x}" for x in g["lesson"]] or ["- 배운 점: 아직 없음(실행 요약의 `lesson`에 세 줄을 적는다)"]
        if (DOCS / "compare" / f"{g['run_id']}.md").exists():
            out.append(f"- 문항별 비교: [compare/{g['run_id']}.md](compare/{g['run_id']}.md)")
    if not kept:
        out += ["", "아직 없음."]
    return "\n".join(out) + "\n"


def links(g):
    """리더보드 칸: 궤적 화면(그 실행을 돌린 컴퓨터에만) · 비교 문서(커밋돼 있으면 GitHub에서 열림)."""
    out = f"[보기](../../eval/results/{g['run_id']}.html)"
    if (DOCS / "compare" / f"{g['run_id']}.md").exists():
        out += f" · [비교](compare/{g['run_id']}.md)"
    return out


# ---- 가설 나무: python3 eval/board.py --tree → docs/engine/tree.json · tree.html (배분일에 오케스트레이터가 돌린다) ----
PEOPLE = {"동규": "#2a78d6", "동욱": "#008300", "종희": "#eda100", "건영": "#e87ba4"}   # GG비서 대시보드(gg-bot CHART_COLORS)와 같은 색
STATUS = {"채택": "#0ca30c", "보류": "#fab219", "버림": "#d03b3b", "진행 중": "#52514e", "대기": "#898781"}  # dataviz 상태 색, 늘 글자와 함께


def plan_table(text, heading):
    """plan.md에서 heading 절의 첫 표를 [{칸 이름: 값}]으로 읽는다."""
    lines = text.split(heading, 1)[1].split("\n")
    start = next(i for i, line in enumerate(lines) if line.startswith("| "))
    cells = lambda line: [c.strip() for c in line.strip().strip("|").split(" | ")]  # noqa: E731
    head, rows = cells(lines[start]), []
    for line in lines[start + 2:]:
        if not line.startswith("|"):
            break
        rows.append(dict(zip(head, cells(line))))
    return rows


def repo_url():
    try:
        return git("remote", "get-url", "origin").strip().removesuffix(".git").replace("git@github.com:", "https://github.com/")
    except (OSError, subprocess.CalledProcessError):
        return "https://github.com/team-gg-aibc/aibc2026-gg"


def gh_json(*args):
    """GitHub 이슈 · PR 상태. gh가 없거나 실패하면 빈 목록(나무는 그려지고 상태는 실행 요약만으로 정한다)."""
    try:
        return json.loads(subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60, check=True).stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        print("⚠ gh로 이슈 · PR 상태를 못 읽었다. 상태는 실행 요약만으로 정한다.")
        return []


def read_plan(text):
    """가설(2-1) · 후보(2-3) · 1주기 배정(4-1)을 마디 목록으로. 부모 칸: 「출발 판」 또는 「가설 N」."""
    nodes = []
    for r in plan_table(text, "### 2-1."):
        who = re.search(r"(동규|동욱|종희|건영)\s*(\d)주기", r.get("1주기 담당 · 이슈", ""))
        issue = re.search(r"#(\d+)", r.get("1주기 담당 · 이슈", ""))
        what = r["가설 (무엇을 바꾸면)"]
        nodes.append({"num": r["#"], "kind": "hypothesis", "title": what.split(":")[0].replace("**", "").strip(),
                      "what": what.replace("**", ""), "expect": r.get("어떤 지표가 얼마나 (어림)", ""),
                      "issue": int(issue.group(1)) if issue else None, "owner": who.group(1) if who else None,
                      "cycle": int(who.group(2)) if who else None, "parent": r.get("부모") or "출발 판"})
    for r in plan_table(text, "### 2-3."):
        what = r["후보"].replace("**", "")
        nodes.append({"num": r["#"], "kind": "candidate", "title": re.sub(r"\(.*?\)", "", what.split(":")[0]).strip(),
                      "what": what, "expect": r.get("기대", ""), "issue": None, "owner": None, "cycle": None,
                      "parent": r.get("부모") or "출발 판"})
    known = {n["issue"] for n in nodes} | {20, 21, 31}                  # 뼈대 · 점수 틀은 뿌리, 채점 서버는 실험이 아니다
    for r in plan_table(text, "### 4-1."):
        for issue, title in re.findall(r"\[#(\d+)\]\([^)]*\)\s*([^(,\[]+)", r.get("이슈 (마감)", "")):
            if int(issue) not in known:
                nodes.append({"num": f"#{issue}", "kind": "hypothesis", "title": title.strip(), "what": title.strip(),
                              "expect": "", "issue": int(issue), "owner": r["사람"], "cycle": 1, "parent": "출발 판"})
    return nodes


def build_tree(plan_nodes, gs, issues, prs, repo, as_of, example=False):
    """마디: 뿌리(출발 판) → 가설 → 실험(실행 묶음) · 다음 가설. 숫자는 리더보드와 같은 함수(num · base_of · noise · mark)로 낸다."""
    gs = [g for g in gs if g["split"] != "holdout"]                     # holdout은 나무에 넣지 않는다
    state = {i["number"]: i["state"] for i in issues}
    linked = defaultdict(list)
    for pr in prs:
        for issue in re.findall(r"(?:Closes|Refs|Fixes) #(\d+)", pr.get("body") or ""):
            linked[int(issue)].append({"number": pr["number"], "state": pr["state"], "title": pr["title"], "url": pr["url"]})
    blob = f"{repo}/blob/main/docs/engine"

    def compare(g):
        return f"{blob}/compare/{g['run_id']}.md" if (DOCS / "compare" / f"{g['run_id']}.md").exists() else None

    def experiment(g, owner):
        base = base_of(gs, g)
        if g["full"]:
            band, score, metric = noise(gs, g["table"])[0], g["m"]["weighted"], "가중 점수"
            delta = None if base is None or base is g or None in (score, base["m"]["weighted"]) \
                else round(score - base["m"]["weighted"], 1)               # 리더보드와 같이 None이면 차이를 건너뛴다
            d, flag = mark(delta, band)
        else:
            k = str(g["top_k"])
            score, metric = g["m"]["hit"].get(k), f"검색 적중률 top-{k}"
            delta = None if base is None or base is g or None in (score, base["m"]["hit"].get(k)) \
                else round(score - base["m"]["hit"][k], 1)                 # 기준이 이 top-k를 안 쟀으면 0으로 보지 않고 건너뛴다
            d, flag = ("—" if delta is None else f"{delta:+.1f}"), "검색만"
        return {"id": f"e-{g['group']}", "kind": "experiment", "title": name(g), "label": label(g), "cycle": g["cycle"],
                "owner": owner, "status": next((s for s in ("채택", "버림", "보류") if g["conclusion"].startswith(s)), "진행 중"),
                "metric": metric, "score": num(score), "delta": d, "flag": flag, "conclusion": g["conclusion"],
                "lesson": g["lesson"], "repeats": g["repeats"], "date": g["date"], "code": g["code"], "compare": compare(g),
                "switches": ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in g["switches"].items()) or "출발 판",
                "children": []}

    byn = {}
    for n in plan_nodes:
        exps = [experiment(g, n["owner"]) for g in gs if n["issue"] and re.sub(r"\D", "", g["issue"]) == str(n["issue"])]
        decided = [e for e in exps if e["status"] != "진행 중"]
        status = decided[-1]["status"] if decided else "진행 중" if exps or n["owner"] else "대기"
        if n["issue"] and state.get(n["issue"]) == "CLOSED" and not decided:
            status = "버림"
        byn[n["num"]] = dict(n, id=("h-" if n["kind"] == "hypothesis" else "c-") + n["num"].lstrip("#"), status=status,
                             children=exps, issue_url=f"{repo}/issues/{n['issue']}" if n["issue"] else None,
                             issue_state=state.get(n["issue"]), prs=linked.get(n["issue"], []))
    bases = [g for g in gs if g["name"] == "baseline" and g["full"] and g["split"] == "dev" and not g["sample"]]
    b = bases[-1] if bases else None
    root = {"id": "root", "kind": "root", "title": "출발 판", "status": "채택", "children": [],
            "metric": "가중 점수", "score": num(b["m"]["weighted"]) if b else None, "label": label(b) if b else "아직 없음",
            "band": num(noise(gs, b["table"])[0]) if b else None, "date": b["date"] if b else "",
            "by_type": {k: num(b["m"]["by_type"].get(k)) for k in WEIGHTS} if b else {}, "compare": compare(b) if b else None,
            "links": {"리더보드": f"{blob}/leaderboard.md", "실험 기록": f"{blob}/experiments.md", "계획": f"{blob}/plan.md"}}
    later = {"id": "g-later", "kind": "group", "title": "다음 후보 (이슈 없음, 배분일에 고름)", "status": "대기", "children": []}
    order = lambda n: (n["cycle"] is None, n["cycle"] or 0, n["kind"] != "hypothesis", int(re.sub(r"\D", "", n["num"]) or 0))  # noqa: E731
    for n in sorted(byn.values(), key=order):
        parent = re.search(r"가설\s*(\d+)", n["parent"])
        (byn[parent.group(1)]["children"] if parent and parent.group(1) in byn
         else later["children"] if n["kind"] == "candidate" else root["children"]).append(n)
    if later["children"]:
        root["children"].append(later)
    return {"as_of": as_of, "example": example, "people": PEOPLE, "status": STATUS, "tree": root}


def write_tree(tree, out=DOCS):
    """tree.json(손으로 고치지 않음)과, 데이터를 안에 넣은 한 파일 화면 tree.html(인터넷 없이 열림)."""
    (out / "tree.json").write_text(json.dumps(tree, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    page = (ROOT / "eval" / "tree_template.html").read_text(encoding="utf-8")
    data = json.dumps(tree, ensure_ascii=False).replace("<", "\\u003c")   # JSON 이스케이프라 </script> · <!-- 둘 다 막히고 JSON.parse는 그대로 읽는다
    (out / "tree.html").write_text(page.replace("/*DATA*/null", data), encoding="utf-8")
    return out / "tree.html"


def selftest():
    plan = """### 2-1. 한 장 표
| # | 가설 (무엇을 바꾸면) | 어떤 지표가 얼마나 (어림) | 재는 법 | 크기 | 1주기 담당 · 이슈 | 부모 |
|---|---|---|---|---|---|---|
| 1 | 질문 다듬기: 시민 말을 조례 용어로 | 적중률 +5 | 끝까지 | 1일 | 다음 후보 · #26 | 가설 2 |
| 2 | 조각 다듬기: 꼬리표 떼기 | 적중률 +1 | 키 없이 | 1일 | 건영 1주기 · #23 | 출발 판 |

### 2-3. 다음 후보
| # | 후보 | 기대 | 크기 | 근거 | 부모 |
|---|---|---|---|---|---|
| 9 | **바깥 근거 대조**(동규 11-06): 6종 밖 법령 | 함정 ↑ | 2일 | 노트 22 | 출발 판 |

### 4-1. 1주기 배정
| 사람 | 이슈 (마감) | 왜 |
|---|---|---|
| 동욱 | [#22](https://x/22) 출력 규격 강제 (11/8), [#31](https://x/31) 채점 서버 | 서버 |
"""
    nodes = read_plan(plan)
    assert [(n["num"], n["parent"], n["owner"], n["cycle"]) for n in nodes] == [
        ("1", "가설 2", None, None), ("2", "출발 판", "건영", 1), ("9", "출발 판", None, None), ("#22", "출발 판", "동욱", 1)]
    assert nodes[2]["title"] == "바깥 근거 대조" and nodes[3]["title"] == "출력 규격 강제"

    def summ(gid, name, issue, w, conclusion="", created="2026-11-08T10:00:00+09:00"):
        return {"group": gid, "run_id": gid, "created": created, "conclusion": conclusion, "lesson": ["</script><b>x</b>", "<!-- <script> 주석"],
                "experiment": {"name": name, "issue": issue, "cycle": 1}, "args": {"mode": "full", "split": "dev", "sample": None, "seed": 0},
                "settings": {"top_k": 6}, "switches": {}, "cost_usd": 0.4,
                "env": {"questions_hash": "q", "code_commit": "abc", "code_dirty": False, "code_hash": "c", "eval_commit": "e",
                        "retrieval_used": ["hybrid"]},
                "metrics": {"n": 661, "weighted": w, "by_type": {}, "by_law": {}, "over_abstain": 20.0,
                            "citations_per_answer": 1.5, "latency_p95": 6.0}}
    runs = [summ("b1", "baseline", "#21", 68.0, created="2026-11-06T10:00:00+09:00"),
            summ("b2", "baseline", "#21", 69.0, created="2026-11-06T11:00:00+09:00"),
            summ("x", "23-chunks", "#23", 71.5, "채택 — 올랐다"), summ("y", "22-contract", "#22", 68.6),
            summ("z", "22-small", "#22", None)]                               # 가중이 None인 실행(빠진 문항 종류가 있는 표본 등)
    tree = build_tree(nodes, groups([(r, None) for r in runs]), [{"number": 26, "state": "OPEN"}],
                      [{"number": 40, "state": "OPEN", "title": "t", "url": "https://x/pr/40", "body": "Closes #23"}], "https://x", "now")
    root = tree["tree"]
    kids = {c["id"]: c for c in root["children"]}
    assert root["score"] == "69.0" and root["band"] == "1.0"                   # 가장 최근 출발 판 · 출발 판 두 번의 폭(리더보드와 같은 값)
    assert set(kids) == {"h-2", "h-22", "g-later"} and kids["g-later"]["children"][0]["id"] == "c-9"
    h2 = kids["h-2"]
    assert h2["status"] == "채택" and h2["prs"][0]["number"] == 40 and [c["id"] for c in h2["children"]] == ["e-x", "h-1"]
    e = h2["children"][0]
    assert (e["score"], e["delta"], e["flag"]) == ("71.5", "+2.5", "✅ 폭의 2배 넘게 오름")
    assert kids["h-22"]["status"] == "진행 중" and h2["children"][1]["status"] == "대기"
    z = kids["h-22"]["children"][1]                                     # 가중이 None이어도 멈추지 않고 차이를 「—」로
    assert (z["id"], z["score"], z["delta"], z["flag"]) == ("e-z", "—", "—", "—")
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        page = write_tree(tree, Path(d)).read_text(encoding="utf-8")
        raw = page.split('<script id="data" type="application/json">')[1].split("</script>")[0]
        assert "<" not in raw and page.count("</script>") == 2              # 배운 점 속 </script> · <!-- 가 화면 코드를 끊지 않는다
        assert json.loads(raw) == tree                                      # 브라우저 JSON.parse처럼 읽으면 그대로 돌아온다
    print("selftest ok")


def main():
    ap = argparse.ArgumentParser(description="리더보드 · 실험 기록 만들기 (eval/board.py 맨 위 설명 참고)")
    ap.add_argument("--from-branches", metavar="패턴", help="원격 브랜치 패턴(예: 'origin/*')의 실행 요약까지 모아 화면에만 보인다")
    ap.add_argument("--tree", action="store_true", help="가설 나무 docs/engine/tree.json · tree.html도 만든다(gh로 이슈 · PR 상태를 읽음)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
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
    if a.tree:
        repo = repo_url()
        issues = gh_json("issue", "list", "--repo", repo, "--state", "all", "--limit", "300", "--json", "number,state")
        prs = gh_json("pr", "list", "--repo", repo, "--state", "all", "--limit", "300", "--json", "number,state,title,body,url")
        tree = build_tree(read_plan((DOCS / "plan.md").read_text(encoding="utf-8")), gs, issues, prs, repo,
                          datetime.now(KST).strftime("%Y-%m-%d %H:%M"))
        print(f"가설 나무 → {write_tree(tree).relative_to(ROOT)} · tree.json")


if __name__ == "__main__":
    main()
