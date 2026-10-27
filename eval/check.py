"""평가셋(eval/questions_*.json) 자동 점검. 원문은 eval/source/*.json(fetch_source.py가 받은 2026-10-01 기준판).

python3 eval/check.py            점검 결과만 보여 준다 (파일 이름을 주면 그 파일만: python3 eval/check.py questions_parking.json)
python3 eval/check.py --write    걸린 문항의 note에 「[사람 확인: 자동 점검] …」을 새로 적는다(지난번 자동 표시는 지우고 다시 씀)
python3 eval/check.py --selftest 점검기 자체 시험

점검하는 것
- 형식: 키 8개(id · type · question · gold · answer_key · note · made_by · checked_by), 유형 이름, id 중복
- gold: 모든 라벨이 원문에 실제로 있는 조 · 항 · 별표인가. 함정은 [], 결합형은 근거 묶음 2개 이상
- 조건 판단: answer_key가 「네」 또는 「아니요」로 시작하나
- 함정이 아닌 문항: answer_key의 숫자와 「」로 감싼 핵심어가 gold 조항 원문에 있나
- 함정: note의 「점검 핵심어: a, b」가 6종 원문 어디에도 없나
- 질문이 조문을 그대로 베꼈나(띄어쓰기 빼고 20자 넘게 같으면)
회색지대(note에 [회색지대])는 정답을 아직 정하지 않았으므로 숫자 · 핵심어 점검을 건너뛴다.
"""
import json
import re
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

HERE = Path(__file__).parent
KEYS = ["id", "type", "question", "gold", "answer_key", "note", "made_by", "checked_by"]
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
    if list(q) != KEYS:
        return [f"키가 {KEYS} 순서와 달라요: {list(q)}"], []
    errors, review = [], []
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
        lost = sorted(numbers(REF.sub(" ", q["answer_key"])) - numbers(text), key=len)
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
        found = re.search(r"점검 핵심어:\s*([^\n·]+)", note)
        if not found:
            errors.append("함정 note에 「점검 핵심어: a, b」가 없어요")
        else:
            for word in [w.strip() for w in found.group(1).split(",") if w.strip()]:
                hits = [label for label, t in units.items() if squash(word) in squash(t)]
                hits = [h for h in hits if not any(o.startswith(h + " ") for o in hits)]  # 조와 그 항이 같이 걸리면 항만
                if hits:
                    review.append(f"함정 핵심어 「{word}」가 원문에 있음: {', '.join(hits[:3])}")
    return errors, review


def main(write: bool) -> int:
    units = load_sources()
    only = [a for a in sys.argv[1:] if not a.startswith("--")]
    files = [p for p in sorted(HERE.glob("questions_*.json")) if not only or p.name in only]
    seen, counts, flagged, grays, manual, failed = Counter(), Counter(), [], [], [], False
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
            if errors:
                failed = True
                print(f"✗ {path.name} {q.get('id')}: {' / '.join(errors)}")
            counts[(path.stem.removeprefix("questions_"), q.get("type"))] += 1
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
    covered = {x for questions in loaded.values() for q in questions for g in q.get("gold") or [] for x in g}
    leaves = [label for label, _ in units.items() if not any(other.startswith(label + " 제") for other in units)]
    marked = len({qid for qid, _ in manual} | {qid for qid, _ in flagged})
    print(f"\n문항 {sum(counts.values())}개 · 사람 확인 {marked}개(자동 점검 {len(flagged)} · 쓴 사람이 단 것 {len(manual)}) · 회색지대 {len(grays)}개 · gold가 닿지 않은 조 · 항 · 별표 {len([x for x in leaves if x not in covered])}개 / {len(leaves)}개")
    for (name, typ), n in sorted(counts.items()):
        print(f"  {name:8} {typ}: {n}")
    for qid, review in flagged:
        print(f"  자동 점검 {qid}: {' / '.join(review)}")
    for qid, note in manual:
        print(f"  쓴 사람 표시 {qid}: {note}")
    for qid in grays:
        print(f"  회색지대 {qid}")
    if "--uncovered" in sys.argv:
        print("\n".join(f"  안 닿음 {x}" for x in leaves if x not in covered))
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
    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    sys.exit(main("--write" in sys.argv))
