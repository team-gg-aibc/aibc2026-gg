"""평가셋(eval/questions_*.json · eval/stress_*.json) 자동 점검. 원문은 eval/source/*.json(fetch_source.py가 받은 2026-10-01 기준판).

python3 eval/check.py            점검 결과만 보여 준다 (파일 이름을 주면 그 파일만: python3 eval/check.py questions_parking.json)
python3 eval/check.py --write    걸린 문항의 note에 「[사람 확인: 자동 점검] …」을 새로 적는다(지난번 자동 표시는 지우고 다시 씀)
python3 eval/check.py --selftest 점검기 자체 시험

점검하는 것
- 형식: 키 8개(id · type · question · gold · answer_key · note · made_by · checked_by), 유형 이름, id 중복.
  말투를 고친 문항은 question 바로 뒤에 원래 질문 question_orig를 두고 note에 「말투 바꿈」을 쓴다.
  questions_* 문항은 맨 끝에 split(dev · holdout), stress_* 문항은 맨 끝에 tags(극한 종류 목록)를 둔다
- gold: 모든 라벨이 원문에 실제로 있는 조 · 항 · 별표인가. 함정은 [], 결합형은 근거 묶음 2개 이상
- 조건 판단: answer_key가 「네」 또는 「아니요」로 시작하나
- 함정이 아닌 문항: answer_key의 숫자와 「」로 감싼 핵심어가 gold 조항 원문에 있나
- 함정: note의 「점검 핵심어: a, b」가 6종 원문 어디에도 없나
- 질문이 조문을 그대로 베꼈나(띄어쓰기 빼고 20자 넘게 같으면)
회색지대(note에 [회색지대])는 정답을 아직 정하지 않았으므로 숫자 · 핵심어 점검을 건너뛴다. tags에 「계산」이 있으면 숫자 점검만 건너뛴다(계산한 값은 원문에 없다).
- 계산식(calc, 10-30 추가): 계산 문항의 answer_key 바로 뒤에 둔 식 목록(예: ["250*8*60/5"]). 코드가 다시 계산해서
  결과가 answer_key에 있는지, 식의 수가 gold 원문이나 질문에 있는지 본다(12 이하 정수와 24 · 60 · 100 · 365는 상식 상수로 둔다)
- 섞인 질문(tags, 10-30 추가): gold가 있어도 note의 「점검 핵심어」(답할 수 없는 부분의 낱말)가 6종에 없는지 본다

python3 eval/check.py --traps    함정(gold [], 회색지대 빼고)마다 질문 + 점검 핵심어로 6종 전체를 검색(킷 rag.py와 같은 글자 2개 단위 BM25)해
                                 상위 3개를 eval/verify/trap_scan.json에 쓰고, 점검 핵심어와 비슷한 말이 상위 조항에 있으면 보여 준다
"""
import ast
import json
import math
import operator
import re
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

HERE = Path(__file__).parent
KEYS = ["id", "type", "question", "gold", "answer_key", "note", "made_by", "checked_by"]
ORDER = KEYS[:3] + ["question_orig"] + KEYS[3:5] + ["calc"] + KEYS[5:] + ["split", "tags"]  # question_orig = 말투를 고치기 전 질문(검수자가 비교)
SPLITS = ["dev", "holdout"]
TAGS = ["말투", "조건 여러 개", "계산", "3단 결합", "항 없는 조", "별표 계산", "함정 변형", "프롬프트 인젝션",
        "섞인 질문", "없는 조 번호", "틀린 전제", "기준 시점", "시연"]  # 뒤의 넷은 10-30 동규 몫 함정(stress_common.json), 「시연」은 demo_*.json
TYPES = ["단순 조회", "조건 판단", "여러 조항 결합", "근거 없음 (함정)"]  # 스타터 킷 sample_questions.json과 같은 이름
TRAP = TYPES[3]
AUTO = "[사람 확인: 자동 점검]"
GRAY = "[회색지대]"
MANUAL = "[사람 확인]"  # 문항을 쓴 사람(AI 포함)이 직접 단 표시
REF = re.compile(r"제\s*\d+\s*(조(의\s*\d+)?|항|호)|별표\s*\d*(의\s*\d+)?")
COPY_LIMIT = 20


def squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}


UNIT = {"억": 10**8, "천만": 10**7, "백만": 10**6, "만": 10**4, "천": 10**3}
FREE = set(range(13)) | {24, 60, 100, 365}  # 계산식에 원문 없이 써도 되는 상식 상수(석 달 · 두 칸 · 60분 · 100분의 …)


def values(text: str) -> set[float]:
    """글 속의 수(조 · 항 · 호 번호는 빼고). 「10만원」은 10과 100000 둘 다. ponytail: 「2만 1천」 같은 합친 수는 식에서 따로 더한다."""
    out = set()
    for m in re.finditer(r"(\d[\d,]*(?:\.\d+)?)\s*(억|천만|백만|만|천)?", REF.sub(" ", text)):
        n = float(m.group(1).replace(",", ""))
        out |= {n, n * UNIT[m.group(2)]} if m.group(2) else {n}
    return out


OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
       ast.Pow: operator.pow, ast.USub: operator.neg}
FUNCS = {"ceil": math.ceil, "floor": math.floor, "round": round, "min": min, "max": max}


def evaluate(expr: str) -> tuple[float, list[float]]:
    """(값, 식에 쓴 수들). 사칙연산 · 거듭제곱 · ceil · floor · round · min · max만 계산한다(eval을 쓰지 않음)."""
    used = []

    def ev(n):
        if isinstance(n, ast.Constant) and type(n.value) in (int, float):
            used.append(n.value)
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in OPS:
            return OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in OPS:
            return OPS[type(n.op)](ev(n.operand))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in FUNCS and not n.keywords:
            return FUNCS[n.func.id](*map(ev, n.args))
        raise ValueError(f"계산식에 쓸 수 없는 것: {ast.unparse(n)}")

    return ev(ast.parse(expr, mode="eval").body), used


def has(found: float, pool: set[float]) -> bool:
    return any(math.isclose(found, v, rel_tol=1e-9, abs_tol=1e-6) for v in pool)


def check_calc(q: dict, gold_text: str) -> tuple[list[str], list[str]]:
    """(형식 오류, 사람이 볼 것). 결과가 answer_key에 있나, 식의 수가 gold 원문 · 질문에 있나."""
    exprs = q["calc"]
    if not isinstance(exprs, list) or not exprs or not all(isinstance(e, str) and e.strip() for e in exprs):
        return ["calc는 계산식 글의 목록이어야 해요"], []
    key, source = values(q["answer_key"]), values(gold_text + " " + q["question"]) | FREE
    errors, review = [], []
    for expr in exprs:
        try:
            result, used = evaluate(expr)
        except (ValueError, SyntaxError, ZeroDivisionError, TypeError) as e:
            errors.append(f"계산식 {expr}: {e}")
            continue
        if not has(result, key):
            review.append(f"계산식 {expr} = {result:g}이(가) answer_key에 없음")
        stray = [f"{u:g}" for u in used if not has(u, source)]
        if stray:
            review.append(f"계산식 {expr}의 수 {', '.join(stray)}이(가) gold 원문 · 질문에 없음")
    return errors, review


def keyword_hits(note: str, units: dict[str, str]) -> list[str] | None:
    """note의 「점검 핵심어: a, b」 가운데 6종 원문에 나오는 것. 「점검 핵심어」가 없으면 None."""
    found = re.search(r"점검 핵심어:\s*([^\n·]+)", note)
    if not found:
        return None
    review = []
    for word in [w.strip() for w in found.group(1).split(",") if w.strip()]:
        hits = [label for label, t in units.items() if squash(word) in squash(t)]
        hits = [h for h in hits if not any(o.startswith(h + " ") for o in hits)]  # 조와 그 항이 같이 걸리면 항만
        if hits:
            review.append(f"함정 핵심어 「{word}」가 원문에 있음: {', '.join(hits[:3])}")
    return review


def bigrams(text: str) -> list[str]:
    t = squash(text)
    return [t[i:i + 2] for i in range(len(t) - 1)]


def searcher(units: dict[str, str]):
    """6종 전체의 가장 작은 단위(항이 있는 조는 항)를 킷 rag.py와 같은 글자 2개 단위 BM25(k1=1.2, b=0.75)로 찾는 함수."""
    leaves = [label for label in units if not any(o.startswith(label + " 제") for o in units)]
    docs = [Counter(bigrams(label + " " + units[label])) for label in leaves]
    df = Counter(g for d in docs for g in d)
    avg = sum(sum(d.values()) for d in docs) / len(docs)

    def top(query: str, k: int = 3) -> list[tuple[str, float]]:
        scores = []
        for label, d in zip(leaves, docs):
            ln, s = sum(d.values()), 0.0
            for g in set(bigrams(query)) & set(d):
                idf = math.log(1 + (len(docs) - df[g] + 0.5) / (df[g] + 0.5))
                s += idf * d[g] * 2.2 / (d[g] + 1.2 * (0.25 + 0.75 * ln / avg))
            scores.append((label, round(s, 2)))
        return sorted(scores, key=lambda x: -x[1])[:k]

    return top


def load_sources() -> dict[str, str]:
    """인용 라벨 → 그 단위의 원문. 조 라벨은 조 전체, 항 라벨은 그 항과 호, 별표 라벨은 별표 전체."""
    units = {}
    for path in sorted((HERE / "source").glob("*.json")):
        src = json.loads(path.read_text(encoding="utf-8"))
        for a in src["articles"]:
            units[a["cite"]] = a["text"]
            for p in a.get("paragraphs", []):
                units[p["cite"]] = p["text"] + " " + " ".join(f"{i['no']}. {i['text']}" for i in p["items"])
        for x in src["annexes"]:
            units[x["cite"]] = x["text"]
    return units


def problems(q: dict, units: dict[str, str]) -> tuple[list[str], list[str]]:
    """(형식 오류, 사람이 볼 것). 형식 오류는 파일을 고쳐야 하고, 사람이 볼 것은 note에 남긴다."""
    keys = list(q)
    if not set(KEYS) <= set(keys) <= set(ORDER) or keys != [k for k in ORDER if k in q]:
        return [f"키는 {ORDER} 가운데 이 순서로(필수 {KEYS}): {keys}"], []
    errors, review = [], []
    if "split" in q and q["split"] not in SPLITS:
        errors.append(f"split은 {SPLITS} 중 하나여야 해요")
    tags = q.get("tags", [])
    if "tags" in q and (not tags or not set(tags) <= set(TAGS)):
        errors.append(f"tags는 {TAGS} 가운데 하나 이상이어야 해요")
    if ("question_orig" in q) != ("말투 바꿈" in q["note"]):
        errors.append("question_orig가 있으면 note에 「말투 바꿈」, 없으면 둘 다 없어야 해요")
    if q["type"] not in TYPES:
        errors.append(f"유형 이름이 틀려요: {q['type']}")
    gold = q["gold"]
    if not isinstance(gold, list) or any(not isinstance(g, list) or not g or not all(isinstance(x, str) for x in g) for g in gold):
        return errors + ["gold는 [[라벨, …], …] 꼴이어야 해요"], review
    if not q["question"].strip() or not q["answer_key"].strip() or not q["made_by"].strip():
        errors.append("question · answer_key · made_by는 비울 수 없어요")
    note = q["note"].split(AUTO)[0]  # 지난번 자동 표시는 점검 재료가 아니다
    gray = GRAY in note
    if q["type"] == TRAP and gold:
        errors.append("근거 없음(함정)의 gold는 []여야 해요")
    if q["type"] != TRAP and not gold:
        errors.append("함정이 아니면 gold가 있어야 해요")
    if q["type"] == "여러 조항 결합" and len(gold) < 2:
        errors.append("여러 조항 결합은 gold 묶음이 2개 이상이어야 해요")
    if q["type"] == "조건 판단" and not re.match(r"^(네|아니요)\b", q["answer_key"]):
        errors.append("조건 판단의 answer_key는 「네」 또는 「아니요」로 시작해야 해요")
    missing = [x for g in gold for x in g if x not in units]
    if missing:
        errors.append(f"원문에 없는 라벨: {missing}")
    if errors or gray:
        return errors, review
    if gold:
        text = " ".join(units[x] for g in gold for x in g)
        flat = squash(text)
        lost = [] if "계산" in tags else sorted(numbers(REF.sub(" ", q["answer_key"])) - numbers(text), key=len)
        if "calc" in q:
            calc_errors, calc_review = check_calc(q, text)
            errors += calc_errors
            review += calc_review
            done = {evaluate(e)[0] for e in q["calc"]} if not calc_errors else set()
            lost = [n for n in lost if not has(float(n), done)]  # 계산식이 만든 수는 원문에 없어도 된다
        if "섞인 질문" in tags:
            hits = keyword_hits(note, units)
            if hits is None:
                errors.append("섞인 질문 note에 「점검 핵심어: a, b」가 없어요")
            review += hits or []
        if lost:
            review.append(f"answer_key의 숫자 {', '.join(lost)}이(가) gold 원문에 없음")
        terms = [t for t in re.findall(r"「([^」]+)」", q["answer_key"]) if squash(t) not in flat]
        if terms:
            review.append(f"핵심어 {', '.join(terms)}이(가) gold 원문에 없음")
        m = SequenceMatcher(None, squash(q["question"]), flat, autojunk=False)
        size = m.find_longest_match(0, len(squash(q["question"])), 0, len(flat)).size
        if size > COPY_LIMIT:
            review.append(f"질문이 조문을 {size}자 그대로 옮김(시민 말투로 고치기)")
    else:
        hits = keyword_hits(note, units)
        if hits is None:
            errors.append("함정 note에 「점검 핵심어: a, b」가 없어요")
        review += hits or []
    return errors, review


def scan_traps(questions: list[dict], units: dict[str, str]) -> tuple[dict, list[tuple[str, str, str]]]:
    """함정(gold [], 회색지대 빼고)마다 질문 + 점검 핵심어로 6종 전체 검색 상위 3개.
    점검 핵심어가 원문에 그대로는 없지만 그 글자쌍의 3분의 2 이상이 상위 조항 하나에 있으면 「비슷한 말」로 돌려준다
    (예: 「개방시간」 → 도시공원 조례 제5조 제1항의 「개방 관리」 · 「이용시간」)."""
    top = searcher(units)
    found, near = {}, []
    for q in questions:
        note = q["note"].split(AUTO)[0]
        if q["gold"] or GRAY in note:
            continue
        m = re.search(r"점검 핵심어:\s*([^\n·]+)", note)
        words = [w.strip() for w in m.group(1).split(",") if w.strip()] if m else []
        found[q["id"]] = top(q["question"] + " " + " ".join(words))
        for label, _ in found[q["id"]]:
            flat = squash(units[label])
            for w in words:
                grams = set(bigrams(w))
                if len(grams) > 1 and not re.search(r"\d", w) and squash(w) not in flat and 3 * sum(g in flat for g in grams) >= 2 * len(grams):
                    near.append((q["id"], w, label))
    return found, near


def main(write: bool) -> int:
    units = load_sources()
    only = [a for a in sys.argv[1:] if not a.startswith("--")]
    files = [p for p in sorted(HERE.glob("questions_*.json")) + sorted(HERE.glob("stress_*.json")) + sorted(HERE.glob("demo_*.json"))
             if not only or p.name in only]  # demo_* = 시연 질문(채점 점수에 넣지 않음), 형식은 극한 세트와 같다
    seen, counts, splits, flagged, grays, manual, failed = Counter(), Counter(), Counter(), [], [], [], False
    loaded = {}
    for path in files:
        try:
            loaded[path] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            failed = True
            print(f"✗ {path.name}: JSON 형식이 깨졌어요 ({e})")
    for path, questions in loaded.items():
        for q in questions:
            seen[q.get("id")] += 1
            errors, review = problems(q, units)
            need = "split" if path.name.startswith("questions_") else "tags"
            if need not in q:
                errors.append(f"이 파일 문항에는 {need} 칸이 있어야 해요")
            if not path.name.startswith("questions_") and "split" in q:
                errors.append("극한 세트에는 split을 두지 않아요")
            if errors:
                failed = True
                print(f"✗ {path.name} {q.get('id')}: {' / '.join(errors)}")
            counts[(path.stem.removeprefix("questions_"), q.get("type"))] += 1
            splits[q.get("split", "-")] += 1
            if GRAY in q.get("note", ""):
                grays.append(q["id"])
            if MANUAL in q.get("note", "").split(AUTO)[0]:
                manual.append((q["id"], q["note"].split(AUTO)[0].strip()))
            note = re.sub(rf"\s*{re.escape(AUTO)}[^\n]*", "", q.get("note", "")).strip()
            if review:
                flagged.append((q["id"], review))
                note = f"{note} {AUTO} {' / '.join(review)}".strip()
            if write and "note" in q:
                q["note"] = note
        if write:
            path.write_text(json.dumps(questions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for qid, n in seen.items():
        if n > 1:
            failed = True
            print(f"✗ id 중복: {qid} ({n}번)")
    covered = {x for path, questions in loaded.items() if path.name.startswith("questions_") for q in questions for g in q.get("gold") or [] for x in g}
    leaves = [label for label, _ in units.items() if not any(other.startswith(label + " 제") for other in units)]
    marked = len({qid for qid, _ in manual} | {qid for qid, _ in flagged})
    print(f"\n문항 {sum(counts.values())}개 · 사람 확인 {marked}개(자동 점검 {len(flagged)} · 쓴 사람이 단 것 {len(manual)}) · 회색지대 {len(grays)}개 · 실제 세트 gold가 닿지 않은 조 · 항 · 별표 {len([x for x in leaves if x not in covered])}개 / {len(leaves)}개")
    for (name, typ), n in sorted(counts.items()):
        print(f"  {name:15} {typ}: {n}")
    print("  " + " · ".join(f"{k} {v}" for k, v in sorted(splits.items())))
    for qid, review in flagged:
        print(f"  자동 점검 {qid}: {' / '.join(review)}")
    for qid, note in manual:
        print(f"  쓴 사람 표시 {qid}: {note}")
    for qid in grays:
        print(f"  회색지대 {qid}")
    if "--uncovered" in sys.argv:
        print("\n".join(f"  안 닿음 {x}" for x in leaves if x not in covered))
    if "--traps" in sys.argv:
        found, near = scan_traps([q for qs in loaded.values() for q in qs], units)
        out = HERE / "verify" / "trap_scan.json"
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps({"top3": found, "near": near}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"\n함정 {len(found)}개를 6종 전체에서 검색 → eval/verify/trap_scan.json · 점검 핵심어와 비슷한 말 {len(near)}건")
        for qid, word, label in near:
            print(f"  비슷한 말 {qid}: 「{word}」 ~ {label}")
    return 1 if failed else 0


def selftest() -> None:
    units = {"서울특별시 테스트 조례 제7조 제1항": "감면율은 100분의 80으로 한다. 경차는 5,000원", "서울특별시 테스트 조례 별표 1": "1급지 500"}
    base = dict(zip(KEYS, ["X-1", "단순 조회", "경차 얼마예요?", [["서울특별시 테스트 조례 제7조 제1항"]], "5,000원 「경차」", "", "ai", ""]))
    assert problems(base, units) == ([], [])
    assert problems({**base, "answer_key": "6,000원"}, units)[1]
    assert problems({**base, "answer_key": "5000원 「소형차」"}, units)[1]
    assert problems({**base, "answer_key": "제7조 제1항, 별표 1에 따라 5,000원"}, units) == ([], [])
    assert problems({**base, "gold": [["서울특별시 강남구 테스트 조례 제7조 제1항"]]}, units)[0]
    assert problems({**base, "type": "조건 판단", "answer_key": "5,000원"}, units)[0]
    assert problems({**base, "type": "조건 판단", "answer_key": "아니요, 5,000원"}, units) == ([], [])
    assert problems({**base, "type": "여러 조항 결합"}, units)[0]
    trap = {**base, "type": TRAP, "gold": [], "answer_key": "확인 불가", "note": "점검 핵심어: 헬멧, 안전모"}
    assert problems(trap, units) == ([], [])
    assert problems({**trap, "note": "점검 핵심어: 경차"}, units)[1]
    assert problems({**trap, "note": ""}, units)[0]
    assert problems({**trap, "note": f"{GRAY} 금액 없음"}, units) == ([], [])
    assert problems({**trap, "note": f"점검 핵심어: 헬멧 {AUTO} 함정 핵심어 「경차」가 원문에 있음"}, units) == ([], [])
    assert problems({**base, "question": "감면율은 100분의 80으로 한다. 경차는 5,000원인가요"}, units)[1]
    assert problems({k: base[k] for k in KEYS[:-1]}, units)[0]
    reworded = {k: base[k] for k in KEYS[:3]} | {"question_orig": "경차 할인돼요?"} | {k: base[k] for k in KEYS[3:]}
    assert problems({**reworded, "note": "말투 바꿈"}, units) == ([], [])
    assert problems(reworded, units)[0]
    assert problems({**base, "split": "dev"}, units) == ([], [])
    assert problems({**base, "split": "test"}, units)[0]
    assert problems({"split": "dev", **base}, units)[0]
    assert problems({**base, "tags": ["말투"]}, units) == ([], [])
    assert problems({**base, "tags": ["아무거나"]}, units)[0]
    assert problems({**base, "answer_key": "7,000원 「경차」", "tags": ["계산"]}, units) == ([], [])
    calc = lambda q, exprs: {k: exprs if k == "calc" else q[k] for k in ORDER if k in q or k == "calc"}  # noqa: E731
    two = {**base, "question": "경차 두 번이면요?", "answer_key": "10,000원"}
    assert problems(calc(two, ["5000*2"]), units) == ([], [])
    assert problems(two, units)[1]  # 계산식이 없으면 10000은 원문에 없는 수
    assert problems(calc(two, ["5000*3"]), units)[1]  # 결과가 answer_key에 없음
    assert problems(calc(two, ["7000+3000"]), units)[1]  # 식의 수가 원문 · 질문에 없음
    assert problems(calc(two, ["__import__('os')"]), units)[0]
    assert problems({**calc(two, ["5000*2"]), "calc": "5000*2"}, units)[0]
    assert values("과태료 10만원, 제7조 제1항") == {10.0, 100000.0}
    assert evaluate("ceil(70*3/100)") == (3, [70, 3, 100])
    mixed = {**base, "note": "점검 핵심어: 헬멧", "tags": ["섞인 질문"]}
    assert problems(mixed, units) == ([], [])
    assert problems({**mixed, "note": "점검 핵심어: 경차"}, units)[1]
    assert problems({**mixed, "note": ""}, units)[0]
    assert searcher(units)("경차 할인")[0][0] == "서울특별시 테스트 조례 제7조 제1항"
    near = scan_traps([{**trap, "question": "감면율로 따지면요?", "note": "점검 핵심어: 감면율로"}], units)[1]
    assert near == [("X-1", "감면율로", "서울특별시 테스트 조례 제7조 제1항")]
    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    sys.exit(main("--write" in sys.argv))
