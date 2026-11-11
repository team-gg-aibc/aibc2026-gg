"""flow2 실패 모으기 · 원인 나누기 — 실패로 진화하는 고리의 첫 판(동규 11-10).

입력: eval/results/<실행>.jsonl(문항별 판단 기록: 단계 · 사유 · 업스테이지 호출). trace-hub의 eval/failures.py 출력도 같은 줄 꼴이면 받는다.
출력: 같은 폴더 <실행>.failures.tsv(eval/results/는 git에 안 올림).
칸: 문항 · 유형 · 점수 · 단계 · 원인 후보 · 구절을 못 댄 대상 · 고른 조례 · 정답 조례 + 고칠 때 채우는 다섯 칸
(원인 · 원문 근거 조항 · 원문 구절 · 바꾼 것 · 회귀 목록).

울타리: 원인은 네 갈래(온톨로지 빈칸 · 프롬프트 · 검색 · 정답 애매). 코드는 후보만 붙인다. 고치는 것은 「온톨로지 빈칸」만이고,
근거는 조례 원문 글자여야 한다. 같은 조의 다른 항 · 같은 꼴의 다른 조례까지 보고 규칙으로 고친다(문항 하나만 맞추지 않는다).
바꾼 것은 ontology.json changes 칸에 남긴다. holdout은 보지 않는다(이정표에서 PM만).
쓰는 법: python -m engine.flow2.failures eval/results/<실행>.jsonl
"""
import csv
import json
import sys
from pathlib import Path

from .lawmap import LAWS

COLUMNS = ["id", "type", "score", "stage", "cause_hint", "unanchored_targets", "laws", "gold_laws",
           "cause", "evidence_label", "evidence_quote", "fix", "regression"]


def gold_laws(gold):
    names = sorted(LAWS.values(), key=len, reverse=True)
    return sorted({next((n for n in names if alt.replace(" ", "").startswith(n.replace(" ", ""))), "?")
                   for alts in gold or [] for alt in alts})


def classify(r):
    """(단계, 원인 후보). 실패가 아니면 None."""
    t = r.get("trace") or {}
    f = t.get("flow2") or {}
    reason, laws = t.get("reason"), (f.get("route") or {}).get("laws") or []
    if not r["gold"]:
        if r["score"] >= 1:
            return None
        return "함정에 답함", "온톨로지 빈칸(관할 · 다루는 대상) 또는 프롬프트(⑥ 판정)"
    if r["score"] >= 1:
        return None
    if reason in ("시간 초과", "오류"):
        return f"운영({reason})", "검색 · 운영"
    if reason in ("6종 밖 조례", "관할 밖"):
        return f"③ 막음({reason})", "온톨로지 빈칸(위임 · 별칭 · 인용 조례 예외) 또는 프롬프트(① 분석)"
    if laws and not set(gold_laws(r["gold"])) & set(laws):
        return "③ 조례 고르기", "검색 · 프롬프트(① law_guess) — 질문이 별칭을 썼으면 온톨로지 빈칸"
    if reason == "found 거짓":
        return "④ found 거짓", "프롬프트(④) 또는 정답 애매"
    if reason in ("근거 번호 없음", "구절 불일치"):
        return f"⑤ {reason}", "프롬프트(④ 라벨 · 구절 옮기기) — 코드 대조 규칙"
    if reason == "판정 거절":
        loose = [m["asked"] for m in (f.get("check") or {}).get("targets", []) if not m["ok"]]
        return "⑥ 판정 거절", "온톨로지 빈칸 후보(시민 말 ↔ 조례 말)" if loose else "프롬프트(⑥)"
    return "④ 인용(부분 · 다른 조항)", "프롬프트(④ 이웃 항 · 원칙과 예외) 또는 정답 애매"


def collect(path):
    rows = [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]
    out = []
    for r in rows:
        c = classify(r)
        if not c:
            continue
        f = (r.get("trace") or {}).get("flow2") or {}
        out.append({"id": r["id"], "type": r["type"], "score": r["score"], "stage": c[0], "cause_hint": c[1],
                    "unanchored_targets": " · ".join(m["asked"] for m in (f.get("check") or {}).get("targets", []) if not m["ok"]),
                    "laws": " · ".join((f.get("route") or {}).get("laws") or []),
                    "gold_laws": " · ".join(gold_laws(r["gold"])),
                    "cause": "", "evidence_label": "", "evidence_quote": "", "fix": "", "regression": ""})
    return out


def selftest():
    law = LAWS["주차장"]
    ok = {"id": "x", "type": "단순 조회", "score": 1.0, "gold": [[f"{law} 제7조 제1항"]], "trace": {}}
    assert classify(ok) is None
    trap = {"id": "t", "type": "근거 없음 (함정)", "score": 0.0, "gold": [], "trace": {"reason": None}}
    assert classify(trap)[0] == "함정에 답함"
    rej = dict(ok, score=0.0, trace={"reason": "판정 거절", "flow2": {"route": {"laws": [law]},
                                                                    "check": {"targets": [{"asked": "칩", "ok": False}]}}})
    assert classify(rej) == ("⑥ 판정 거절", "온톨로지 빈칸 후보(시민 말 ↔ 조례 말)")
    wrong = dict(ok, score=0.0, trace={"reason": None, "flow2": {"route": {"laws": [LAWS["도시공원"]]}}})
    assert classify(wrong)[0] == "③ 조례 고르기" and gold_laws(ok["gold"]) == [law]
    print("failures 스스로 시험: 통과")


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        selftest()
    elif len(sys.argv) == 2:
        rows = collect(sys.argv[1])
        dst = Path(sys.argv[1]).with_suffix(".failures.tsv")
        with open(dst, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, COLUMNS, delimiter="\t")
            w.writeheader()
            w.writerows(rows)
        from collections import Counter
        print(f"실패 {len(rows)}개 → {dst}")
        for k, v in Counter((r["stage"], r["cause_hint"]) for r in rows).most_common():
            print(f"  {v:3d}  {k[0]} · {k[1]}")
    else:
        print("쓰는 법: python -m engine.flow2.failures eval/results/<실행>.jsonl | --selftest")
