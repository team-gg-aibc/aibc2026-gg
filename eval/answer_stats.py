"""답 글 재는 틀 (#83): 문항별 기록의 답 글을 스타터 킷의 답변 기준으로 잰다. 모델을 부르지 않는다(키 없이, 몇 초).

  python3 eval/answer_stats.py <실행> [<실행> …]                      기록의 답 글 그대로
  python3 eval/answer_stats.py <실행> … --config <켠 판 설정 파일>     그 설정의 「답 첫머리」 단계(engine/flow2/flow.py lead)를
                                                                      기록에 대어 본 뒤를 나란히 (앞 = 기록, 뒤 = 대어 본 것)
  python3 eval/answer_stats.py --selftest
<실행>은 실행 이름이나 경로다: eval/results/<실행>.jsonl(잰 컴퓨터) · eval/results/shared/c<주기>/<실행>.jsonl.gz(기록 모으는 곳에서
받은 것, eval/share.py). holdout · 처음 보는 문항(fresh) 실행은 다루지 않는다.

꼭 내는 다섯 숫자(스타터 킷 README 채점 항목 표의 「답변 품질」 줄, 이슈 #83 「앞뒤 맥락」 ④의 표)
- ① 답한 것 가운데 답이 2~4문장인 비율, 1문장 · 5문장 이상인 답의 수. 문장은 마침표 · 물음표 · 느낌표 뒤 공백에서 자른다
- ② 정답 열쇠가 「네 · 아니요」로 시작하는 문항 중 답한 것에서, 답이 그렇게 시작하는 비율
- ② 그렇게 시작한 답의 결론이 정답 열쇠와 같은 비율
- ② 맞는 결론으로 시작한 답의 비율(답한 것 가운데)
- ④의 일부: 답 글에 엔진 안쪽 말(INNER)이 든 답의 수
더한 칸 둘(11-11 업스테이지 답. 재기만 한다)
- 「확인 불가」 답 가운데 뒤에 안내가 붙은 비율
- 인용한 답 가운데 「조례에는 정해져 있지 않다」(NOT_SET)와 「누가 정하는지 · 어디서 확인하는지」(WHERE)를 함께 말한 답의 수
--config를 주면 더 센다: 답 글이 바뀐 문항 · 인용 칸(인용 · 링크 · 시행일)이 바뀐 문항 · 함수가 건드린 「확인 불가」 답(둘 다 0이어야 한다),
붙인 낱말이 정답 열쇠와 어긋난 문항. 끈 판 설정(pm-flow2-v7.json)을 주면 바뀐 문항이 0이어야 한다(대어 보기가 기록을 그대로 되살리는지).
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

from run import RESULTS, config, contract, private   # eval/run.py: 엔진 경로도 여기서 잡힌다
from share import load as load_shared

from engine.flow2 import flow  # noqa: E402

SENT = re.compile(r"(?<=[.?!])\s+")
KEY = re.compile(r"네|아니요")                         # 정답 열쇠의 첫머리(「네.」 · 「아니요(원칙).」 …)
INNER = {"이 자료": re.compile(r"(?<![가-힣])이 자료"),     # ④ · ⑥에 보내는 글에만 있어야 할 말(「시장이 자료를」은 세지 않는다)
         **{w: re.compile(re.escape(w)) for w in ("[근거]", "[조항]", "※", "(조 번호)")}}
# ponytail: 낱말 맞추기라 어림이다(뜻은 못 읽는다). 고칠 때는 걸린 답을 읽어 보고 낱말을 더하거나, 모델 · 사람이 읽는 표본으로 바꾼다
NOT_SET = re.compile(r"(?:정해져|규정되어|규정돼|명시되어|명시돼|적혀|나와) 있지 않|(?:조례|조문|자료|6종)[가는]? (?:직접 |따로 )?정하지 않"
                     r"|(?:조례|조문|자료|6종)에는? 없")
WHERE = re.compile(r"확인(?:하세요|하시기|하셔야|하실 수|해 보|해야|이 필요)|문의|[이가] (?:따로 )?정(?:합니다|하도록)|규칙으로 정"
                   r"|에서 정(?:합니다|하고|하도록|한)")
CITE_FIELDS = ("citation", "source_url", "effective_date")


def read(arg):
    """실행 이름이나 경로 → (실행 이름, 문항별 기록)."""
    p = Path(arg)
    if not p.exists():
        p = next(iter([*RESULTS.glob(f"{arg}.jsonl"), *RESULTS.glob(f"shared/*/{arg}.jsonl.gz")]), None)
        if p is None:
            sys.exit(f"✗ {arg}: eval/results/에 문항별 기록이 없습니다(받는 법은 이슈 #83 「재는 법」 ①).")
    name = p.name.removesuffix(".gz").removesuffix(".jsonl")
    summary, rows = load_shared(p) if p.suffix == ".gz" else ({}, [json.loads(x) for x in p.read_text(encoding="utf-8").split("\n") if x])
    kind = private({**summary, "run_id": name})
    if kind:
        sys.exit(f"✗ {name}: {kind} 실행은 다루지 않습니다(보고 고치지 않는 묶음).")
    return name, rows


def is_unknown(resp):
    return resp["answer"].startswith("확인 불가") and resp["citation"] == []     # eval/run.py grade와 같은 뜻


def word(text):
    return "네" if text.startswith(("네", "예")) else "아니요"


def measure(rows, resps):
    """rows와 같은 순서의 응답 resps → 재는 칸마다 (분자, 분모) 또는 수."""
    said = [(r, x["answer"]) for r, x in zip(rows, resps) if not is_unknown(x)]
    unknown = [x["answer"] for x in resps if is_unknown(x)]
    n_sent = Counter(len([p for p in SENT.split(a.strip()) if p]) for _, a in said)
    keyed = [(KEY.match(r["answer_key"]).group(0), a) for r, a in said if KEY.match(r.get("answer_key") or "")]
    starts = [(k, word(a)) for k, a in keyed if flow.LEAD.match(a)]
    right = sum(k == w for k, w in starts)
    return {"2~4문장": (sum(v for k, v in n_sent.items() if 2 <= k <= 4), len(said)),
            "1문장 · 5문장 이상": (n_sent[1], sum(v for k, v in n_sent.items() if k >= 5)),
            "네 · 아니요로 시작": (len(starts), len(keyed)),
            "시작한 답의 결론이 열쇠와 같음": (right, len(starts)),
            "맞는 결론으로 시작": (right, len(keyed)),
            "안쪽 말이 든 답": {w: n for w, pat in INNER.items() if (n := sum(bool(pat.search(a)) for _, a in said))},
            "확인 불가 뒤 안내": (sum(a.strip() != "확인 불가" for a in unknown), len(unknown)),
            "정해져 있지 않다 + 어디서 확인": (sum(bool(NOT_SET.search(a) and WHERE.search(a)) for _, a in said), len(said))}


def replay(row, cfg):
    """기록의 「출력 직전」 상태에 flow.lead를 대고 출구 검사까지 돌린다 → (나갈 응답, lead 바로 뒤의 답 글, 판단 기록 lead 칸).
    확인 불가로 끝난 문항은 흐름이 이 단계에 오지 않는다. 그래도 함수가 건드리지 않는지 보려고 그 응답을 그대로 넣어 본다."""
    tr = row.get("trace") or {}
    if not tr.get("flow2"):                               # 새 흐름 기록이 아니면(지금 흐름 · 서버로 잰 실행) 댈 것이 없다
        return row["response"], row["response"]["answer"], None
    st = {"question": row["question"], "flow2": dict(tr["flow2"]),
          "draft": row["response"] if tr["reason"] or not tr["draft"] else tr["draft"]}
    flow.lead(st, cfg)
    return (contract.finalize(st["draft"], cfg) if cfg["exit_check"] else st["draft"]), st["draft"]["answer"], st["flow2"].get("lead")


def fmt(v):
    if isinstance(v, dict):
        return f"{sum(v.values())}" + (f" ({' · '.join(f'{k} {n}' for k, n in v.items())})" if v else "")
    a, b = v
    return f"{a} · {b}"


def pct(v):
    a, b = v
    return f"{100 * a / b:.1f}% ({a}/{b})" if b else f"- ({a}/{b})"


ROWS = [("① 2~4문장 (답한 것 가운데)", "2~4문장", pct), ("   1문장 · 5문장 이상", "1문장 · 5문장 이상", fmt),
        ("② 「네 · 아니요」로 시작 (열쇠가 그렇게 시작하고 답한 것 가운데)", "네 · 아니요로 시작", pct),
        ("② 시작한 답의 결론이 정답 열쇠와 같음", "시작한 답의 결론이 열쇠와 같음", pct),
        ("② 맞는 결론으로 시작 (답한 것 가운데)", "맞는 결론으로 시작", pct),
        ("④ 안쪽 말이 든 답", "안쪽 말이 든 답", fmt),
        ("＋ 「확인 불가」 답 가운데 뒤에 안내가 붙음", "확인 불가 뒤 안내", pct),
        ("＋ 「정해져 있지 않다」와 「어디서 확인」을 함께 말한 답 (인용한 답 가운데)", "정해져 있지 않다 + 어디서 확인", lambda v: f"{v[0]} (/{v[1]})")]


def report(name, rows, cfg=None, label=""):
    before = [r["response"] for r in rows]
    cols = [("앞(기록)" if cfg else "기록", measure(rows, before))]
    print(f"\n[{name}] {len(rows)}문항 · 답한 것 {sum(not is_unknown(x) for x in before)} · 확인 불가 {sum(map(is_unknown, before))}")
    if cfg:
        out = [replay(r, cfg) for r in rows]
        cols.append((f"뒤({label})", measure(rows, [o[0] for o in out])))
    print("| 재는 것 | " + " | ".join(c for c, _ in cols) + " |\n|---|" + "---|" * len(cols))
    for title, k, f in ROWS:
        print(f"| {title} | " + " | ".join(f(m[k]) for _, m in cols) + " |")
    if not cfg:
        return
    added = Counter(o[2]["word"] for o in out if o[2] and o[2]["word"])
    wrong = [r["id"] for r, o in zip(rows, out) if o[2] and o[2]["word"] and (m := KEY.match(r.get("answer_key") or "")) and m.group(0) != o[2]["word"]]
    print(f"- 답 글이 바뀐 문항 {sum(b['answer'] != o[0]['answer'] for b, o in zip(before, out))}"
          f" (결론 낱말을 붙임 {sum(added.values())}: 네 {added['네']} · 아니요 {added['아니요']})"
          f" · 인용 칸이 바뀐 문항 {sum(any(b[k] != o[0][k] for k in CITE_FIELDS) for b, o in zip(before, out))}"
          f" · 함수가 건드린 「확인 불가」 답 {sum(is_unknown(b) and o[1] != b['answer'] for b, o in zip(before, out))}")
    print(f"- 안 붙인 까닭: {dict(Counter(o[2]['skip'] for o in out if o[2] and o[2]['skip'])) or '없음'}")
    print(f"- 붙인 낱말이 정답 열쇠와 어긋난 문항 {len(wrong)}: {' · '.join(wrong) or '없음'}")


# ---- 스스로 시험 (문장은 조례 원문을 보고 새로 썼다: 청년 기본 조례 제3조 · 주차장 조례 제7조 · 도시공원 조례 이용료 반환) ----
def selftest():
    label = "서울특별시 청년 기본 조례 제3조"
    url, date = contract.sources(config.DEFAULTS["chunk_unit"])[label]

    def row(i, key, answer, word=None, q="스물여덟 살도 서울시 청년 정책 대상인가요?", reason=None):
        resp = contract.unknown() if reason else {"answer": answer, "citation": [label], "source_url": url, "effective_date": date}
        return {"id": f"t{i}", "question": q, "answer_key": key, "response": resp,
                "trace": {"reason": reason, "draft": None if reason else dict(resp), "flow2": {"read": {"conclusion": word}}}}

    rows = [row(1, "네. 19세 이상 39세 이하", "네, 청년에 해당합니다. 청년은 19세 이상 39세 이하입니다."),
            row(2, "네. 19세 이상 39세 이하", "스물여덟 살은 청년에 해당합니다.", "네"),
            row(3, "아니요. 39세 이하까지", "네, 마흔 살도 청년입니다. 조례가 그렇게 정합니다.", "네"),
            row(4, "「19세 이상 39세 이하」", "청년은 19세 이상 39세 이하의 사람입니다. 그 밖의 나이 기준은 이 자료에 없습니다.", "네", "서울시 조례가 정한 청년 나이는 몇 세부터 몇 세까지인가요?"),
            row(5, "100분의 50", "할인율은 조례에 정해져 있지 않습니다. 시장이 따로 정합니다. 하나. 둘. 셋.", "정보"),
            row(6, "확인 불가", "", "네", reason="found 거짓")]
    m = measure(rows, [r["response"] for r in rows])
    assert m["2~4문장"] == (3, 5) and m["1문장 · 5문장 이상"] == (1, 1), m
    assert m["네 · 아니요로 시작"] == (2, 3) and m["시작한 답의 결론이 열쇠와 같음"] == (1, 2) and m["맞는 결론으로 시작"] == (1, 3), m
    assert m["안쪽 말이 든 답"] == {"이 자료": 1} and m["확인 불가 뒤 안내"] == (0, 1) and m["정해져 있지 않다 + 어디서 확인"] == (1, 5), m
    off, on = dict(config.load(), flow="flow2", flow2_version=7), dict(config.load(), flow="flow2", flow2_version=7, flow2_lead="comma")
    assert [replay(r, off)[0] for r in rows] == [r["response"] for r in rows]            # 끈 판은 기록 그대로
    out = [replay(r, on) for r in rows]
    assert [o[2] and o[2]["word"] for o in out] == [None, "네", None, None, None, None], [o[2] for o in out]
    assert out[1][0]["answer"] == "네, 스물여덟 살은 청년에 해당합니다." and out[3][0]["answer"].endswith("서울시 조례 6종에 없습니다.")
    assert out[5][0] == contract.UNKNOWN and out[5][1] == "확인 불가"                    # 확인 불가 답은 그대로
    assert all(o[0][k] == r["response"][k] for r, o in zip(rows, out) for k in CITE_FIELDS)
    m = measure(rows, [o[0] for o in out])
    assert m["네 · 아니요로 시작"] == (3, 3) and m["맞는 결론으로 시작"] == (2, 3) and m["안쪽 말이 든 답"] == {}, m
    print("selftest ok")


def main():
    ap = argparse.ArgumentParser(description="답 글 재는 틀 (eval/answer_stats.py 맨 위 설명 참고)")
    ap.add_argument("runs", nargs="*", help="실행 이름 또는 문항별 기록 경로(.jsonl · .jsonl.gz)")
    ap.add_argument("--config", help="이 설정의 「답 첫머리」 단계를 기록에 대어 본 뒤를 나란히 낸다")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if not args.runs:
        ap.error("잴 실행을 주세요")
    cfg = config.load(args.config) if args.config else None
    for arg in args.runs:
        report(*read(arg), cfg, Path(args.config).stem if cfg else "")


if __name__ == "__main__":
    main()
