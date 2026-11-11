"""실패 모아 보기: 그 주기 릴리스(results-c<주기>)에 올린 실행들을 받아 틀린 문항을 원인 · 단계 · 실험별로 모은다.

  python3 eval/failures.py --cycle 2              → eval/results/failures/c2.md(한 장) · c2.csv(틀린 문항 전부)
  python3 eval/failures.py --cycle 2 1            여러 주기를 함께(예: 2주기 실험 + 1주기 릴리스 rc-c1)
  python3 eval/failures.py --files <x.jsonl.gz> …  받지 않고 가진 파일로
  python3 eval/failures.py --selftest             키 · 네트워크 없이
올리는 법은 eval/share.py. 받으려면 gh(GitHub CLI) 로그인이 필요하다. holdout · 처음 보는 문항(fresh) 실행은 올리지 않으니 여기에도 없고,
받은 것에 섞여 있어도 모으지 않는다.

- 실패 = 점수가 1이 아닌 문항(부분 점수 포함). 원인은 점수 틀(run.py)이 채점할 때 붙인 것을 큰 갈래로 모은다(compare.py와 같은 규칙).
- 단계: 정답이 후보에 없음 → 검색, 후보에 있는데 잘못 고름 → 고르기 · 답 쓰기, 확인 불가 · 오류 · 시간 초과로 끝남 → 흐름이 멈춘 단계,
  함정에 답함 → 판정(판정을 끈 실행은 출력), 그 밖 → 출력.
- 고정 실패: 같은 설정(설정 지문 · 엔진 코드 지문 · 문항 지문이 모두 같은 실행)을 두 번 이상 재서, 매번 같은 원인으로 틀린 문항.
  흔들림이 아니라 약점이라 먼저 본다.
- 온톨로지 빈칸 후보: 단순 규칙으로 표시만 한다. 판단은 사람이 하고, 고칠 때는 원문 근거로 고친다(평가셋 문항에 맞추지 않는다).
  「같은 조 다른 항」 = 엔진이 고른 조항(정답이 후보에 없으면 후보까지)이 정답과 같은 조의 다른 항이다.
  「관할 밖 낱말」 = 질문에 자치구 · 다른 시도 · 「○○법」 · 시행령 · 시행규칙이 있다.
"""
import argparse
import csv
import io
import re
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import share
from board import LAWS
from compare import bucket
from run import BROKEN, CAUSES, KST, MISPICK, NOT_IN, RESULTS, TRAP_ANSWERED, TYPES, match, private

OUT = RESULTS / "failures"
STAGE = {NOT_IN: "검색", MISPICK: "고르기 · 답 쓰기"}
# 관할 밖 꼴: #25 질문 게이트(engine/gate.py, 병합 전)와 같은 꼴. 게이트가 병합되면 거기서 가져온다.
DISTRICTS = ("종로 중 용산 성동 광진 동대문 중랑 성북 강북 도봉 노원 은평 서대문 마포 양천 강서 구로 금천 "
             "영등포 동작 관악 서초 강남 송파 강동").split()
OUTSIDE = re.compile(r"(?<![가-힣])(?:%s)구" % "|".join(sorted(DISTRICTS, key=len, reverse=True))
                     + r"|(?<![가-힣])(?:부산|대구|인천|광주|대전|울산|세종|경기|강원|충청북|충청남|충북|충남|전라북|전라남|전북|전남"
                       r"|경상북|경상남|경북|경남|제주)"
                     + r"|[가-힣]{2,}(?<!방)(?<!불)(?<!헌)법(?![인령원규정칙])|시행령|시행규칙")
COLUMNS = ["주기", "실험", "실행", "문항", "유형", "조례", "점수", "원인", "까닭", "단계", "고정 실패", "온톨로지 빈칸 후보",
           "엔진 인용", "정답 조항", "질문"]


def short(label):
    return label.replace("서울특별시 ", "").replace(" 조례", "")


def stage(r):
    t, c = r.get("trace") or {}, bucket(r["cause"])
    if c in STAGE:
        return STAGE[c]
    if not t:
        return "모름(서버로 잰 실행)"
    if t.get("reason") and t.get("steps"):
        return list(t["steps"])[-1]
    return "판정" if c == TRAP_ANSWERED and "판정" in t.get("steps", {}) else "출력"


def picked(r):
    """엔진이 낸 인용. 확인 불가로 끝났으면 판정 전 답의 인용. 꼴이 깨진 인용(글이 아닌 것)은 뺀다."""
    for x in (r.get("response"), (r.get("trace") or {}).get("draft")):
        cites = x.get("citation") if isinstance(x, dict) else None
        if isinstance(cites, list) and any(isinstance(c, str) for c in cites):
            return [c for c in cites if isinstance(c, str)]
    return []


def gaps(r):
    out = []
    pool = picked(r) + ([c["label"] for c in (r.get("trace") or {}).get("candidates", [])] if bucket(r["cause"]) == NOT_IN else [])
    if any(max((match(p, a) for p in pool for a in alts), default=0) == 0.5 for alts in r["gold"]):
        out.append("같은 조 다른 항")
    words = sorted({m.group(0) for m in OUTSIDE.finditer(r["question"])})
    if words:
        out.append("관할 밖 낱말: " + ", ".join(words))
    return " · ".join(out)


def sets(runs):
    """같은 설정끼리 묶는다(설정 지문 · 엔진 코드 지문 · 문항 지문). → {묶음 이름: [(요약, 기록)…]} 만든 순서대로."""
    by = defaultdict(list)
    for s, rows in sorted(runs, key=lambda x: x[0]["created"]):
        by[(s["settings_hash"], s["env"]["code_hash"], s["env"]["questions_hash"])].append((s, rows))
    names = Counter(rs[0][0]["experiment"]["name"] for rs in by.values())
    return {(rs[0][0]["experiment"]["name"] if names[rs[0][0]["experiment"]["name"]] == 1
             else f"{rs[0][0]['experiment']['name']} ({rs[0][0]['group'][:15]})"): rs for rs in by.values()}


def fixed(rs):
    """두 번 이상 잰 묶음에서 매번 같은 원인으로 틀린 문항 → {문항: 원인}."""
    if len(rs) < 2:
        return {}
    causes = defaultdict(list)
    for _, rows in rs:
        for r in rows:
            causes[r["id"]].append(bucket(r["cause"]) if r["cause"] else None)
    return {i: cs[0] for i, cs in causes.items() if len(cs) == len(rs) and cs[0] and len(set(cs)) == 1}


def table(head, rows):
    esc = lambda x: str(x).replace("|", "\\|").replace("\n", " ")  # noqa: E731
    return ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(map(esc, r)) + " |" for r in rows]


def report(runs, title, cmd):
    """→ (md 글, csv 글)."""
    groups = sets(runs)
    lines, records, stable = [], [], {name: fixed(rs) for name, rs in groups.items()}
    for name, rs in groups.items():
        for s, rows in rs:
            for r in rows:
                if r["cause"]:
                    records.append({"주기": s["experiment"]["cycle"], "실험": name, "실행": s["run_id"], "문항": r["id"],
                                    "유형": TYPES.get(r["type"], r["type"]), "조례": LAWS.get(r["law"], r["law"]), "점수": r["score"],
                                    "원인": bucket(r["cause"]), "까닭": (r.get("trace") or {}).get("reason") or "",
                                    "단계": stage(r), "고정 실패": "예" if r["id"] in stable[name] else "",
                                    "온톨로지 빈칸 후보": gaps(r), "엔진 인용": " · ".join(map(short, picked(r))),
                                    "정답 조항": " / ".join(" 또는 ".join(map(short, a)) for a in r["gold"]) or "없음(함정)",
                                    "질문": r["question"]})
    names = list(groups)
    cnt = Counter((x["실행"], key, x[key]) for x in records for key in ("원인", "단계"))
    per = lambda key, k, name: " · ".join(str(cnt[(s["run_id"], key, k)]) for s, _ in groups[name])  # noqa: E731  반복마다
    lines += [f"# {title}", "", f"> `{cmd}`가 만들었다({datetime.now(KST):%Y-%m-%d %H:%M}). 규칙은 `eval/failures.py` 맨 위. "
              "틀린 문항 전부는 같은 이름의 .csv에 있다. 「a · b」는 같은 설정을 반복해 잰 실행(r1 · r2 …)마다의 값이다.", "", "## 실행", ""]
    lines += table(["실험", "실행", "주기", "문항", "가중", "실패", "고정 실패", "설정 · 엔진 코드 지문"],
                   [[n, " · ".join(s["run_id"] for s, _ in rs), rs[0][0]["experiment"]["cycle"], rs[0][0]["metrics"]["n"],
                     " · ".join(str(s["metrics"]["weighted"]) for s, _ in rs),
                     " · ".join(str(sum(1 for r in rows if r["cause"])) for _, rows in rs),
                     len(stable[n]) if len(rs) > 1 else "— (한 번만 잼)",
                     f"{rs[0][0]['settings_hash']} · {rs[0][0]['env']['code_hash']}"] for n, rs in groups.items()])
    for key, title_, order in (("원인", "원인별", CAUSES), ("단계", "단계별", ["검색", "고르기 · 답 쓰기", "판정", "출력"])):
        seen = order + sorted({x[key] for x in records} - set(order))
        lines += ["", f"## {title_}", ""] + table([key] + names, [[k] + [per(key, k, n) for n in names]
                                                                for k in seen if any(x[key] == k for x in records)])
    lines += ["", "## 고정 실패", "", "같은 설정을 두 번 이상 재서 매번 같은 원인으로 틀린 문항이다."]
    for n, ids in stable.items():
        if not ids:
            continue
        first = {x["문항"]: x for x in records if x["실험"] == n and x["실행"] == groups[n][0][0]["run_id"]}
        lines += ["", f"### {n} — {len(ids)}문항 ({' · '.join(f'{k} {v}' for k, v in Counter(ids.values()).most_common())})", ""]
        lines += table(["문항", "원인", "단계", "온톨로지 빈칸 후보", "엔진 인용", "정답 조항", "질문"],
                       [[i, c, first[i]["단계"], first[i]["온톨로지 빈칸 후보"], first[i]["엔진 인용"], first[i]["정답 조항"],
                         first[i]["질문"]] for i, c in sorted(ids.items(), key=lambda kv: (CAUSES.index(kv[1]) if kv[1] in CAUSES else 99, kv[0]))])
    marked, fails = defaultdict(list), Counter(x["문항"] for x in records)
    for x in records:
        if x["온톨로지 빈칸 후보"]:
            marked[x["문항"]].append(x)
    lines += ["", "## 온톨로지 빈칸 후보", "", "단순 규칙으로 표시만 했다. 정말 빈칸인지는 원문을 보고 사람이 정한다. "
              "「틀린 실행」은 이 문항을 틀린 실행 수 / 모은 실행 수다.", ""]
    lines += table(["문항", "표시", "틀린 실행", "원인", "엔진 인용", "정답 조항", "질문"],
                   [[i, " · ".join(dict.fromkeys(p for x in xs for p in x["온톨로지 빈칸 후보"].split(" · "))),
                     f"{fails[i]}/{len(runs)}", " · ".join(sorted({x['원인'] for x in xs})),
                     xs[0]["엔진 인용"], xs[0]["정답 조항"], xs[0]["질문"]] for i, xs in sorted(marked.items())] or [["없음"] + [""] * 6])
    buf = io.StringIO()
    w = csv.DictWriter(buf, COLUMNS)
    w.writeheader()
    w.writerows(records)
    return "\n".join(lines) + "\n", buf.getvalue()


def download(cycle):
    """릴리스에 있는 것만 받는다(임시 폴더라 --dry-run으로 만든 로컬 파일이 섞이지 않는다). → [(요약, 기록)…]"""
    with tempfile.TemporaryDirectory() as d:
        r = share.gh("release", "download", share.tag(cycle), "--pattern", "*.jsonl.gz", "--dir", d, check=False)
        if r.returncode:
            sys.exit(f"✗ 릴리스 {share.tag(cycle)}를 받지 못했습니다(아직 아무도 안 올렸으면 없다): {r.stderr.strip()[:200]}")
        return [share.load(f) for f in sorted(Path(d).glob("*.jsonl.gz"))]


def main():
    ap = argparse.ArgumentParser(description="실패 모아 보기 (eval/failures.py 맨 위 설명 참고)")
    ap.add_argument("--cycle", type=int, nargs="+", help="주기 번호(여러 개 가능)")
    ap.add_argument("--files", nargs="+", help="받지 않고 이 파일들로 (<실행>.jsonl.gz)")
    ap.add_argument("--out", help="결과 파일 이름 앞부분 (기본: eval/results/failures/c<주기>)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if not (args.cycle or args.files):
        ap.error("--cycle이나 --files를 주세요")
    runs = [share.load(f) for f in args.files] if args.files else [x for c in args.cycle for x in download(c)]
    hold = share.holdout_ids()      # share.py가 이미 거부하지만, 손으로 올린 파일이 섞여도 holdout · 처음 보는 문항(fresh)은 보지 않는다
    skipped = [s["run_id"] for s, _ in runs if private(s)]
    if skipped:
        print(f"· 모으지 않은 실행 {len(skipped)}개(holdout · fresh, 보고 고치지 않는 묶음)")
    runs = [(s, [r for r in rows if r["id"] not in hold]) for s, rows in runs if not private(s)]
    if not runs:
        sys.exit("✗ 모을 실행이 없습니다.")
    tag = "-".join(f"c{c}" for c in args.cycle) if args.cycle else "files"
    stem = Path(args.out) if args.out else OUT / tag
    stem.parent.mkdir(parents=True, exist_ok=True)
    title = f"실패 모아 보기 — {' · '.join(f'{c}주기' for c in args.cycle)}" if args.cycle else "실패 모아 보기"
    md, table_csv = report(runs, title, "python3 eval/failures.py " + " ".join(sys.argv[1:]))
    stem.with_suffix(".md").write_text(md, encoding="utf-8")
    stem.with_suffix(".csv").write_text(table_csv, encoding="utf-8-sig")   # 엑셀에서 한글이 안 깨지게
    n = sum(1 for _ in csv.DictReader(io.StringIO(table_csv)))
    print(f"{len(runs)}개 실행 · 틀린 문항 {n}줄 → {stem.with_suffix('.md')} · {stem.with_suffix('.csv')}")


# ---- 스스로 시험 ----
def selftest():
    a7 = "서울특별시 주차장 설치 및 관리 조례 제7조 제1항"
    a73 = "서울특별시 주차장 설치 및 관리 조례 제7조 제3항"
    a9 = "서울특별시 주차장 설치 및 관리 조례 제9조 제1항"

    def row(i, cause, reason=None, cite=(), cands=(a7,), q="경차 주차비 깎아 줘요?", gold=((a7,),), steps=("받기", "검색", "고르기 · 답 쓰기", "판정")):
        return {"id": i, "type": "단순 조회" if gold else "근거 없음 (함정)", "law": "parking", "question": q, "gold": [list(g) for g in gold],
                "score": 0.0 if cause else 1.0, "cause": cause, "response": {"citation": list(cite)},
                "trace": {"reason": reason, "steps": {s: 0.1 for s in steps}, "candidates": [{"label": c} for c in cands], "draft": None}}

    assert bucket("답이 있는데 확인 불가 (found 거짓)") == "답이 있는데 확인 불가"
    assert stage(row("a", NOT_IN, "found 거짓", cands=(a9,))) == "검색"
    assert stage(row("a", MISPICK, cite=(a9,))) == "고르기 · 답 쓰기"
    assert stage(row("a", "판정이 맞는 답을 거절", "판정 거절")) == "판정"
    assert stage(row("a", "답이 있는데 확인 불가 (점수 낮음)", "점수 낮음", steps=("받기", "검색"))) == "검색"
    assert stage(row("a", "시간 초과", "시간 초과", steps=("받기", "검색", "고르기 · 답 쓰기"))) == "고르기 · 답 쓰기"
    assert stage(row("t", TRAP_ANSWERED, gold=())) == "판정" and stage(row("b", BROKEN)) == "출력"
    assert stage(dict(row("s", MISPICK), trace=None)) == "고르기 · 답 쓰기" and stage(dict(row("s", BROKEN), trace=None)).startswith("모름")

    assert gaps(row("a", MISPICK, cite=(a73,))) == "같은 조 다른 항"                      # 같은 조 다른 항을 고름
    assert gaps(row("a", NOT_IN, "found 거짓", cands=(a73, a9))) == "같은 조 다른 항"      # 후보에 같은 조 다른 항만
    assert gaps(row("a", MISPICK, cite=(a9,))) == "" and gaps(row("a", BROKEN, cite=(7,))) == ""
    assert gaps(row("t", TRAP_ANSWERED, q="강남구 공영주차장도 경차 할인돼요?", gold=())) == "관할 밖 낱말: 강남구"
    assert gaps(row("t", TRAP_ANSWERED, q="도로교통법상 자전거 음주 과태료는? 부산도 같나요?", gold=())) == "관할 밖 낱말: 도로교통법, 부산"
    for q in ("결제방법이 어떻게 돼요?", "불법 주차하면 과태료 얼마예요?", "집중구역에 자전거 세워도 돼요?", "구청장에게 신고해요?", "법인도 되나요?"):
        assert "관할" not in gaps(row("a", MISPICK, q=q)), q

    s = lambda run, sh="s1", w=70.0: {"run_id": run, "group": run[:-3], "created": run, "settings_hash": sh, "metrics": {"n": 3, "weighted": w},  # noqa: E731
                                      "env": {"code_hash": "c1", "questions_hash": "q1"}, "args": {"split": "dev"},
                                      "experiment": {"name": "27-whole", "cycle": 2}}
    r1 = [row("A", NOT_IN, "found 거짓", cands=(a9,)), row("B", MISPICK, cite=(a73,)), row("C", None), row("D", MISPICK, cite=(a9,))]
    r2 = [row("A", NOT_IN, "found 거짓", cands=(a9,)), row("B", None), row("C", None), row("D", "판정이 맞는 답을 거절", "판정 거절")]
    base = [row("A", NOT_IN, "found 거짓", cands=(a9,)), row("B", None), row("C", None), row("D", None)]
    runs = [(s("2-r1"), r1), (s("2-r2"), r2), (dict(s("1-r1", "s0"), experiment={"name": "release-c1", "cycle": 1}), base)]
    g = sets(runs)
    assert list(g) == ["release-c1", "27-whole"] and [x[0]["run_id"] for x in g["27-whole"]] == ["2-r1", "2-r2"]
    assert fixed(g["27-whole"]) == {"A": NOT_IN} and fixed(g["release-c1"]) == {}       # D는 두 번 다 틀렸지만 원인이 다르다
    md, table_csv = report(runs, "시험", "python3 eval/failures.py --selftest")
    assert "| 정답이 후보에 없음 | 1 | 1 · 1 |" in md and "### 27-whole — 1문항 (정답이 후보에 없음 1)" in md
    assert "| 검색 | 1 | 1 · 1 |" in md and "| 고르기 · 답 쓰기 | 0 | 2 · 0 |" in md
    rows = list(csv.DictReader(io.StringIO(table_csv)))
    assert len(rows) == 6 and [x["고정 실패"] for x in rows if x["실험"] == "27-whole" and x["문항"] == "A"] == ["예", "예"]
    assert {x["온톨로지 빈칸 후보"] for x in rows if x["문항"] == "B"} == {"같은 조 다른 항"}
    assert "| B | 같은 조 다른 항 | 1/3 | 후보에 있는데 잘못 고름 |" in md
    print("selftest ok")


if __name__ == "__main__":
    main()
