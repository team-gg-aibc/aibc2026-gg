"""flow2 ③ 조례 확정: 질문 분석 칸(①)과 질문 글자를 함께 보고, 코드만으로 「6종 밖」 · 「관할 밖」을 막고 읽을 조례를 고른다.

규칙은 6종 조례 원문에서만 만든다(평가셋 문항 글은 옮기지 않는다, 동규 11-10). 조례 이름 · 6종이 스스로 드는 법령 · 조례 지도와
원문에 나오는 서울시 시설 이름은 색인 조각(= 원문)에서 불러올 때 계산한다. 규칙마다 근거 조항을 주석에 단다.
규칙끼리 부딪치는 경우는 맨 아래 CONFLICTS 표로 고정하고 스스로 시험(selftest)에서 돌린다.

막는 것은 확실한 꼴뿐이다. 애매한 것(예: 「OO구 + 시설 이름」만 있고 누가 정했는지 글자로 안 드러남)은 통과시켜 ⑥ 질문 대조가 근거를 보고 정한다.
이 판단 기준은 조례 원문의 위임 조항이 많아서다(아래 「규칙 B」 주석).
"""
import re
from functools import lru_cache

from . import ontology, places as place_table

REJECT_NAME = "6종 밖 조례"   # 질문이 이름을 든 조례가 6종이 아니고 6종이 드는 조례도 아니다
REJECT_SCOPE = "관할 밖"     # 질문이 자치구 · 다른 시도가 스스로 정한 것을 묻는다
RULE_PLACE = "C 6종 밖 조례의 곳"   # #82: 판단 기록 flow2.route.rule. 막는 사유는 REJECT_NAME과 같다

LAWS = ontology.LAW_KEYS     # 분석 칸 law_guess 값 → 조례 이름(색인 조각의 law 칸과 글자까지 같다)
# 서울특별시 자치구 25곳(출처는 ontology.DISTRICTS). #25 engine/gate.py(동욱, PR #60)와 같은 목록 — 병합 뒤 gate.DISTRICTS로 바꾼다
DISTRICTS = ontology.DISTRICTS["names"]
MAX_LAWS = 2
SECOND_RATIO = 0.9   # #27 whole_second_ratio 기본값과 같다
GENERIC = re.compile(r"^(?:이|그|저|해당|관련|무슨|어떤|다른|각종|기타|시|구|자치구|지방|우리)?$|관련")


def _n(s):
    """띄어쓰기 · 꺾쇠 · 따옴표를 지운 꼴. 이름 견주기에만 쓴다."""
    return re.sub(r"[\s「」『』\"'“”‘’]", "", s or "")


def _core(name):
    """「서울특별시 OO 조례 제N조」 → 「OO」. 앞의 서울특별시 · 서울시 · 서울, 뒤의 조례와 그 뒤를 뗀다."""
    n = _n(name)
    n = n[:n.index("조례")] if "조례" in n else n
    return re.sub(r"^(?:서울특별시|서울시|서울)", "", n)


@lru_cache(maxsize=None)
def _onto():
    return ontology.load()


def cited_names():
    """6종 조례가 원문에서 「」로 이름을 드는 법령 · 조례 · 제도 → {조례 이름: [이름, …]}(온톨로지 o1, 원문에서 계산)."""
    return {law["name"]: [c["name"] for c in law["cites"]] for law in _onto()["laws"]}


def cited_laws(laws):
    """⑥ 질문 대조에 넘길 「근거 조례가 스스로 드는 법령 · 조례」 목록."""
    names = cited_names()
    return list(dict.fromkeys(n for law in laws for n in names.get(law, [])))


def seoul_places():
    """원문에 나오는 서울시 시설 이름(예: 도시공원 조례 별표 1 「서울대공원」, 청년 기본 조례 제20조 「서울청년센터」)."""
    return tuple(sorted({p["name"] for law in _onto()["laws"] for p in law["places"]}))


def name_kind(name):
    """질문이 이름을 든 조례의 종류: ("6종", 열쇠) · ("인용", [그 이름을 드는 6종 열쇠]) · ("밖", None) · ("법령", None) · ("일반", None).

    규칙 A의 근거
    - 6종과 별칭: 6종 이름의 한 부분(띄어쓰기 무시)이면 그 조례다. 예: 「공원 조례」 · 「도시공원 조례」 → 도시공원,
      「주차장 조례」 → 주차장 설치 및 관리 조례. 「청년주거 기본 조례」처럼 6종 이름에 없는 글자가 끼면 다른 조례다.
    - 6종이 드는 조례는 막지 않는다: 예) 주차장 조례가 감면 대상으로 「서울특별시 임산부 예우 및 지원에 관한 조례」를,
      금연 조례가 「서울특별시 도시공원 조례」를 든다(cited_names로 원문에서 계산). 그 이름을 든 질문은 드는 쪽 6종이 답할 수 있다.
    - 법률 · 시행령 · 규칙 이름은 ③에서 막지 않는다: 6종이 상위 법령을 근거나 정의로 많이 든다(예: 동물보호 조례 제1조 「동물보호법」,
      청년 기본 조례 제4조 「청년기본법」, 동물보호 조례 제7조의3 「의료법」 등). ⑥이 그 목록을 받아 판단한다.
    """
    n = _n(name)
    if "조례" not in n:
        return ("법령", None) if re.search(r"(?:법|법률|령|규칙|규정)$", n) else ("일반", None)
    core = _core(name)
    if GENERIC.search(core):
        return ("일반", None)
    for key, full in LAWS.items():
        if core in _n(full):
            return ("6종", key)
    citing = [key for key, full in LAWS.items() if any(core in _n(x) for x in cited_names()[full] if "조례" in x)]
    return ("인용", citing) if citing else ("밖", None)


def _district(word):
    w = re.sub(r"청$", "", _n(word))
    return w.endswith("구") and w[:-1] in DISTRICTS


def _seoul_entity(question):
    """E1: 서울특별시 · 서울시가 주소(「서울시 OO구」)가 아니라 규칙 · 시설의 주체로 나온다."""
    for m in re.finditer(r"서울(?:특별)?시", question):
        rest = question[m.end():].lstrip()
        if not any(rest.startswith(d + "구") for d in DISTRICTS):
            return True
    return False


def scope_block(question, slots):
    """규칙 B(관할): 막으면 그 까닭 한 줄, 아니면 None.

    근거: 6종은 자치구와 구청장이 하는 일을 많이 정한다. 그래서 자치구 이름이 나와도 서울시 조례가 답하는 질문이 많다.
    - 동물보호 조례: 등록(제6조) · 구조 · 보호(제10조) · 공고(제11조) · 반환(제16조) · 등록수수료 감면(제28조)을 구청장이 한다.
    - 주차장 조례: 구청장의 실태조사(제3조 · 제3조의2) · 주차환경개선지구(제4조), 시 · 자치구 청사 부설주차장의 일반 이용(제23조) ·
      감면(제23조의2) · 친환경 구획(제25조의3)을 정하고, 노상주차장 전용주차구획 권한을 구청장에게 위임한다(제29조).
    - 도시공원 조례: 공원관리청 = 시장 · 자치구청장(제2조 제1호), 시와 자치구의 사무관할(제32조 · 별표 5), 사무위임(제33조 · 별표 6),
      과태료 업무 위임(제23조 제5항).
    - 자전거 조례: 자치구청장의 책무(제3조 제5항), 자전거도로 설치(제3조의2), 방치 자전거 처분(제10조 제2항), 시설 관리 위임(제18조).
    - 청년 기본 조례: 자치구별 서울청년센터(제20조), 자치구와 협력(제22조).
    - 금연 조례: 자치구에 맡긴 일이 없다(지정 때 자치구청장과 협의 제5조 제5항, 금연지도원 합동교육 제9조 제6항뿐). 그래서 구가 지정한
      금연구역 · 구가 매기는 과태료는 이 조례에 근거가 없다.
    그래서 자치구는 「그 구가 정한 · 지정한 · 만든 · 운영하는 것」이나 「그 구의 조례 · 규칙」처럼 그 구가 규칙을 만든 쪽임이
    글자로 드러날 때만 막는다. 다른 시도는 6종이 정하는 일이 없다(6종 원문에 다른 시 · 도 규정 없음) → 분석이 「다른 시도」면 막는다.
    예외: E1 서울시가 주체로 함께 나옴 · E2 원문에 나오는 서울시 시설 이름(도시공원 조례 제20조 제1항 제14호는 서울대공원에서
    경기도 다자녀 카드를 인정한다) · E3 그 지역은 사는 곳일 뿐(사는 · 주민 · 거주).
    「구」 없는 지역 이름(예: 주차장 조례 별표 3의 설치제한지역 「강남ㆍ서초」 · 「용산ㆍ마포」)은 자치구로 보지 않는다(_district).
    """
    kind = slots.get("jurisdiction")
    word = (slots.get("jurisdiction_word") or "").strip()
    if kind not in ("자치구", "다른 시도") or not word or "서울" in word or _n(word) not in _n(question):
        return None                                   # 분석이 지어낸 낱말이거나 서울 쪽이면 막지 않는다
    if kind == "자치구" and not _district(word):
        return None                                   # 「OO구」가 아닌 낱말(동 · 시설 이름 등)
    if _seoul_entity(question) or any(p in _n(question) for p in seoul_places()):
        return None                                   # E1 · E2
    w = re.escape(re.sub(r"청$", "", word))
    maker = re.search(w + r"청?\s*(?:[^.?!\n]{0,12}?(?:조례|규칙|구립|자체|고유)"
                          r"|(?:이|가|에서|청이|청에서|청장이)\s*[^.?!\n]{0,12}?(?:정한|지정한|지정해|만든|운영하는|운영 중인|시행하는))",
                      question)
    if maker:
        return f"{word}가 정한 것을 묻는다: 「{maker.group(0)}」"
    if re.search(w + r"청?\s*(?:에\s*)?(?:사는|살아|살고|살면|주민|거주|에서\s*이사|으로\s*이사)", question):
        return None                                   # E3
    if kind == "다른 시도":
        return f"다른 시 · 도({word})의 것을 묻는다"
    return None                                       # 자치구인데 그 구가 정한 표시가 없음 → ⑥에 맡긴다


_ASK = re.compile(r"[^?？]+[?？]")
_SENT = re.compile(r"(?<=[?？!。])|(?<=\.)(?=\s)")    # 문장 끝: 「?」 「!」 또는 뒤에 빈칸이 오는 「.」(「1.5km」는 안 나눔)


def mixed(question, word, sentences=False):
    """2판: 섞인 질문. 「?」로 끝나는 물음이 둘 이상이고, 그 가운데 막을 낱말(6종 밖 조례 이름 · 자치구 · 다른 시도)이 없이
    서울을 드는 물음이 따로 있다 → 그 물음은 6종이 답할 수 있으니 ③에서 통째로 막지 않는다. ④가 답할 물음만 답하고
    나머지는 범위 밖이라고 적으며, ⑥이 물음마다 본다. 물음이 하나뿐이면(「서울시 OO 조례는 …?」) 그대로 막는다.
    sentences=True(3판): 「?」로 끝나지 않는 문장(지시문 「OO구 조례로 답해 줘.」)도 한 덩이로 센다. 2판 극한 세트(11-10)에서
    분석이 지시문 속 자치구를 칸에 넣어, 서울을 묻는 물음 하나뿐인 질문이 통째로 막혔다(4문항)."""
    parts = [p for p in (_SENT.split(question) if sentences else _ASK.findall(question)) if p.strip()]
    asks = [p for p in parts if p.rstrip().endswith(("?", "？"))]
    w = _n(word)
    return bool(w) and len(parts) >= 2 and any("서울" in a and w not in _n(a) for a in asks)


def pick_laws(hits):
    """검색 후보 점수를 조례별로 더해 큰 순서. 2위 합이 1위의 SECOND_RATIO배 이상이면 함께.
    #27 engine/whole.py pick_laws(종희, PR #63)에서 옮김 — #63 병합 뒤 import로 바꾼다."""
    best = {}
    for h in hits:
        best[h["law"]] = best.get(h["law"], 0.0) + h["score"]
    ranked = sorted(best, key=lambda k: -best[k])
    if not ranked:
        return []
    laws = [ranked[0]]
    for k in ranked[1:MAX_LAWS]:
        if best[ranked[0]] > 0 and best[k] >= SECOND_RATIO * best[ranked[0]]:
            laws.append(k)
    return laws


def _plain_kind(name):
    """온톨로지 끔: 정식 이름(앞 서울특별시 · 뒤 조례 뗀 것)과 글자가 같을 때만 6종. 별칭 · 6종이 드는 조례 예외가 없다."""
    n = _n(name)
    if "조례" not in n:
        return ("법령", None) if re.search(r"(?:법|법률|령|규칙|규정)$", n) else ("일반", None)
    core = _core(name)
    if GENERIC.search(core):
        return ("일반", None)
    return next((("6종", key) for key, full in LAWS.items() if core == _core(full)), ("밖", None))


def _plain_scope(question, slots):
    """온톨로지 끔: 분석이 자치구 · 다른 시도라 하고 그 낱말이 질문에 있으면 막는다(위임 · 서울시 시설 · 사는 곳 예외 없음)."""
    kind, word = slots.get("jurisdiction"), (slots.get("jurisdiction_word") or "").strip()
    if kind in ("자치구", "다른 시도") and word and "서울" not in word and _n(word) in _n(question):
        return f"분석이 {kind}({word})"
    return None


@lru_cache(maxsize=None)
def _law_text(law):
    """그 조례 원문 전체(조 · 항 · 별표 조각을 이은 것)의 띄어쓰기 지운 꼴. 규칙 C가 곳 낱말이 원문에 있는지 볼 때 쓴다."""
    from .. import retrieve
    return _n(" ".join(c["text"] for c in retrieve.load("paragraph")[0] if c["law"] == law))


def place_block(question, laws):
    """규칙 C(#82, 6종 밖 조례의 곳): 막으면 (곳 낱말, 까닭 한 줄), 아니면 None.

    질문에 곳 표(places.json)의 낱말이 있고, ③이 고른 조례가 모두 그 곳의 rivals이며, 고른 조례 원문 어디에도 그 낱말이 없으면 막는다.
    근거: 「서울특별시 한강공원 보전 및 이용에 관한 기본 조례」 제3조 제1호가 한강공원을 따로 정의하고 제17조 제1항이 그 안의
    금지행위를 직접 정한다. 도시공원 조례의 「공원」은 법 제2조제3호의 도시공원이다(도시공원 조례 제2조 제4호).
    - 고른 조례 원문에 그 낱말이 있으면 답한다: 금연 조례 제5조 제1항 제11호 「한강공원 내 수영장 및 물놀이장 …」.
    - rivals가 아닌 조례가 하나라도 끼면 답한다: 동물보호 조례(목줄 등)는 곳을 가리지 않고 정한다. 한강공원 조례 제17조 제1항
      제5호에도 같은 내용이 있지만 6종이 정한 것이라 6종으로 답할 수 있다(#82 「판단이 갈리는 꼴」).
    - 표에 없는 곳(여의도공원 · 서울대공원 등)은 지금처럼 답한다."""
    q = _n(question)
    for row in place_table.load()["places"]:
        rivals = {LAWS[k] for k in row["rivals"]}
        if not laws or not set(laws) <= rivals:
            continue
        for p in row["places"]:
            if _n(p) in q and not any(_n(p) in _law_text(law) for law in laws):
                return p, f"{p}: {row['law']}가 다스리는 곳(고른 조례 원문에 없음)"
    return None


def route(question, slots, hits, use_onto=True, mixed_ok=False, sentences=False, place=False):
    """③ 조례 확정. 돌려주는 것: {"laws": [조례 이름], "block": None | 사유, "rule": 정한 규칙, "why": 한 줄}.
    순서(부딪칠 때 앞이 이긴다): A 6종 이름 → A 6종이 드는 조례 → A 6종 밖 조례(막음) → B 관할(막음) → 검색 · 분석으로 고르기.
    use_onto=False(설정 flow2_ontology 끔)면 온톨로지 없이 단순 규칙(_plain_kind · _plain_scope)만 쓴다 — 온톨로지 몫을 재려고.
    mixed_ok=True(2판)면 섞인 질문(mixed)은 A 6종 밖 · B 관할에서 막지 않고 검색 · 분석으로 고른다. sentences=True(3판)는 mixed 참고.
    섞인 질문이라 막지 않았으면 그 낱말을 "mixed"에 남긴다(4판 ⑥이 그 낱말이 든 지시문 문장을 질문에서 뺀다).
    place=True(설정 flow2_place_scope, #82)면 조례를 고른 뒤 규칙 C(place_block)를 댄다. 섞인 질문 예외(mixed)는 쓰지 않는다:
    「…노점이 보여요. 서울시 조례로는 어떻게 되나요?」처럼 뒷물음이 서울을 들어도 같은 곳을 묻기 때문이다."""
    named = (slots.get("named_rule") or "").strip()
    forced, rule, why, skipped = [], "고르기", "", []
    if named and _n(named) and _n(named) in _n(question):        # 분석이 질문에 없는 이름을 지어내면 보지 않는다
        kind, key = (name_kind if use_onto else _plain_kind)(named)
        if kind == "6종":
            forced, rule, why = [LAWS[key]], "A 6종 이름", named
        elif kind == "인용":
            forced, rule, why = [LAWS[k] for k in key][:MAX_LAWS], "A 6종이 드는 조례", named
        elif kind == "밖" and mixed_ok and mixed(question, named, sentences):
            skipped.append(named)
        elif kind == "밖":
            local = any(d + "구" in _n(named) for d in DISTRICTS) or slots.get("jurisdiction") in ("자치구", "다른 시도")
            return {"laws": [], "block": REJECT_SCOPE if local else REJECT_NAME, "rule": "A 6종 밖 조례", "why": named}
    if not forced:
        b = (scope_block if use_onto else _plain_scope)(question, slots)
        word = slots.get("jurisdiction_word") or ""
        if b and mixed_ok and mixed(question, word, sentences):
            skipped.append(word)
        elif b:
            return {"laws": [], "block": REJECT_SCOPE, "rule": "B 관할", "why": b}
    if forced:
        laws = forced
    else:
        laws = pick_laws(hits)
        guess = LAWS.get(slots.get("law_guess"))
        if guess and guess not in laws:
            laws = laws[:1] + [guess]
            rule, why = "고르기 + 분석", slots.get("law_guess")
    if place:
        c = place_block(question, laws[:MAX_LAWS])
        if c:
            return {"laws": [], "block": REJECT_NAME, "rule": RULE_PLACE, "why": c[1]}
    out = {"laws": laws[:MAX_LAWS], "block": None, "rule": rule, "why": why}
    if skipped:
        out["mixed"] = list(dict.fromkeys(skipped))
    return out


# ---- 규칙끼리 부딪치는 경우 (스스로 시험에서 돌린다). 질문 글은 조례 원문을 보고 새로 쓴 것이다(평가셋 문항이 아니다) ----
# (질문, 분석 칸 덮어쓰기, 기대: 막는 사유 또는 None, 기대: 첫 조례 열쇠 또는 None, 무엇이 무엇을 이기나)
CONFLICTS = [
    ("강남구에 살아요. 서울시 주차장 조례에 경차 감면이 있나요?", {"named_rule": "서울시 주차장 조례", "jurisdiction": "자치구",
     "jurisdiction_word": "강남구"}, None, "주차장", "A 6종 이름 > B 관할(사는 곳)"),
    ("송파구 동물보호 조례에 반려동물 지원이 있나요?", {"named_rule": "송파구 동물보호 조례", "jurisdiction": "자치구",
     "jurisdiction_word": "송파구"}, REJECT_SCOPE, None, "6종 이름 글자가 끼어 있어도 자치구 조례는 6종 밖"),
    ("서울시 청년주거 기본 조례는 누구를 지원하나요?", {"named_rule": "청년주거 기본 조례", "law_guess": "청년"},
     REJECT_NAME, None, "비슷한 이름은 다른 조례(청년 기본 조례 아님)"),
    ("임산부 예우 조례에 따라 공영주차장 요금이 깎이나요?", {"named_rule": "임산부 예우 조례"}, None, "주차장",
     "6종이 드는 조례(주차장 조례 감면 조항) > 6종 밖 조례"),
    ("공원 조례에 따르면 공원에서 무엇이 금지되나요?", {"named_rule": "공원 조례"}, None, "도시공원", "별칭 「공원 조례」"),
    ("청년기본법에서 말하는 청년은 몇 살까지인가요?", {"named_rule": "청년기본법", "jurisdiction": "국가"}, None, None,
     "법률 이름은 ③에서 막지 않는다(⑥이 6종이 드는 법령 목록을 보고 판단)"),
    ("강서구가 지정한 금연구역에서 흡연하면 과태료는 얼마인가요?", {"jurisdiction": "자치구", "jurisdiction_word": "강서구",
     "law_guess": "금연"}, REJECT_SCOPE, None, "B: 그 구가 지정한 것"),
    ("마포구청 청사 부설주차장도 일반인이 이용할 수 있나요?", {"jurisdiction": "자치구", "jurisdiction_word": "마포구",
     "law_guess": "주차장"}, None, "주차장", "청사(장소) · 주차장 조례 제23조가 자치구 청사 부설주차장을 정함"),
    ("강동구청에 반려견을 등록하면 등록수수료가 감면되나요?", {"jurisdiction": "자치구", "jurisdiction_word": "강동구",
     "law_guess": "동물보호"}, None, "동물보호", "구청장이 하는 일(동물보호 조례 제6조 · 제28조) — 그 구가 정한 표시 없음"),
    ("경기도에 사는데 서울대공원 입장료를 할인받을 수 있나요?", {"jurisdiction": "다른 시도", "jurisdiction_word": "경기도",
     "law_guess": "도시공원"}, None, "도시공원", "E3 사는 곳 · E2 원문의 서울시 시설 > 다른 시도"),
    ("부산시가 정한 길고양이 급식소 기준은 무엇인가요?", {"jurisdiction": "다른 시도", "jurisdiction_word": "부산시",
     "law_guess": "동물보호"}, REJECT_SCOPE, None, "B: 다른 시도가 정한 것"),
    ("수원 공영주차장 요금은 5분에 얼마인가요?", {"jurisdiction": "다른 시도", "jurisdiction_word": "수원",
     "law_guess": "주차장"}, REJECT_SCOPE, None, "B: 다른 시도는 표시 없이도(6종에 다른 시 · 도 규정 없음)"),
    ("서울시가 정한 금연구역과 강남구가 정한 금연구역의 과태료가 같나요?", {"jurisdiction": "자치구", "jurisdiction_word": "강남구",
     "law_guess": "금연"}, None, "금연", "E1 서울시가 주체로 함께 나옴 > B(⑥에 맡김)"),
    ("관악구 서울청년센터는 어떤 일을 하나요?", {"jurisdiction": "자치구", "jurisdiction_word": "관악구", "law_guess": "청년"},
     None, "청년", "E2 원문의 시설(청년 기본 조례 제20조 자치구별 서울청년센터)"),
    ("공원에서 술을 마셔도 되나요?", {"jurisdiction": "자치구", "jurisdiction_word": "종로구", "law_guess": "도시공원"},
     None, "도시공원", "분석이 질문에 없는 지역을 지어내면 막지 않는다"),
    ("서울특별시 강남구 금연구역 조례로 과태료가 얼마죠?", {"named_rule": "서울특별시 강남구 금연구역 조례",
     "jurisdiction": "자치구", "jurisdiction_word": "강남구"}, REJECT_SCOPE, None, "주소 꼴 「서울특별시 강남구」는 E1이 아니다"),
    ("서울 사는 대학생인데 청년 나이 기준이 궁금해요.", {"jurisdiction": "서울시", "law_guess": "청년"}, None, "청년",
     "서울시 질문은 고르기만"),
    ("강남 지역 상업지역에 건물을 지으면 부설주차장 설치가 제한되나요?", {"jurisdiction": "자치구", "jurisdiction_word": "강남",
     "law_guess": "주차장"}, None, "주차장", "「구」 없는 지역 이름은 자치구가 아니다(주차장 조례 별표 3 설치제한지역)"),
    ("경기도 다자녀 카드로 서울대공원에 무료로 들어갈 수 있나요?", {"jurisdiction": "다른 시도", "jurisdiction_word": "경기도",
     "law_guess": "도시공원"}, None, "도시공원", "E2: 도시공원 조례 제20조 제1항 제14호(서울대공원 + 경기도 다자녀 카드)"),
]


def selftest():
    hits = [{"law": LAWS["주차장"], "score": 0.6}, {"law": LAWS["도시공원"], "score": 0.3}]
    base = {"named_rule": "", "jurisdiction": "서울시", "jurisdiction_word": "", "targets": [], "asks": "", "type": "단순",
            "law_guess": "없음"}
    for q, over, block, first, note in CONFLICTS:
        r = route(q, {**base, **over}, hits)
        assert r["block"] == block, (note, q, r)
        if first:   # 이름으로 정한 조례는 첫째, 검색 · 분석으로 고른 조례는 읽을 목록 안에
            assert (r["laws"][0] == LAWS[first]) if r["rule"].startswith("A") else (LAWS[first] in r["laws"]), (note, q, r)
    assert name_kind("주차장 설치 및 관리 조례 제7조") == ("6종", "주차장") and name_kind("관련 조례")[0] == "일반"
    assert "주차장법" in cited_laws([LAWS["주차장"]]) and "서울대공원" in seoul_places()
    # 온톨로지 끔: 별칭 · 6종이 드는 조례 · 위임 · 서울시 시설 예외가 사라져 막는다(온톨로지 몫)
    for q, over in [("공원 조례에 따르면 공원에서 무엇이 금지되나요?", {"named_rule": "공원 조례"}),
                    ("임산부 예우 조례에 따라 공영주차장 요금이 깎이나요?", {"named_rule": "임산부 예우 조례"}),
                    ("마포구청 청사 부설주차장도 일반인이 이용할 수 있나요?", {"jurisdiction": "자치구", "jurisdiction_word": "마포구"}),
                    ("경기도에 사는데 서울대공원 입장료를 할인받을 수 있나요?", {"jurisdiction": "다른 시도", "jurisdiction_word": "경기도"})]:
        assert route(q, {**base, **over}, hits)["block"] is None and route(q, {**base, **over}, hits, use_onto=False)["block"], q
    assert route("서울특별시 도시공원 조례 제20조는?", {**base, "named_rule": "서울특별시 도시공원 조례"}, hits,
                 use_onto=False)["laws"] == [LAWS["도시공원"]]
    # 2판 섞인 질문: 서울 물음이 따로 있으면 막지 않고(1판은 막음), 물음이 하나뿐이거나 뒷물음에 서울이 없으면 그대로 막는다
    for q, over, block2 in [
        ("서울시 자전거 주차장 하루 주차권은 얼마예요? 인천시 자전거 조례에도 그런 주차권이 있어요?",
         {"named_rule": "인천시 자전거 조례", "jurisdiction": "다른 시도", "jurisdiction_word": "인천시", "law_guess": "자전거"}, None),
        ("강서구가 지정한 금연구역에서 담배 피우면 과태료가 얼마예요? 서울 공원 금연구역이면 얼마예요?",
         {"jurisdiction": "자치구", "jurisdiction_word": "강서구", "law_guess": "금연"}, None),
        ("인천시 자전거 조례에 주차장 요금이 있나요? 있으면 하루에 얼마예요?",
         {"named_rule": "인천시 자전거 조례", "jurisdiction": "다른 시도", "jurisdiction_word": "인천시"}, REJECT_SCOPE),
        ("서울시 청년주거 기본 조례는 누구를 지원하나요?", {"named_rule": "청년주거 기본 조례", "law_guess": "청년"}, REJECT_NAME)]:
        assert route(q, {**base, **over}, hits)["block"], q                                   # 1판
        assert route(q, {**base, **over}, hits, mixed_ok=True)["block"] == block2, q          # 2판
        assert route(q, {**base, **over}, hits, mixed_ok=True, sentences=True)["block"] == block2, q   # 3판도 같음
    # 3판: 다른 지역 이름이 「?」 없는 지시문 문장에만 있고 서울을 묻는 물음이 따로 있으면 막지 않는다(2판은 막음).
    # 물음 한 문장뿐이거나, 서울 물음이 없거나, 「.」이 소수점이면 그대로 막는다
    for q, over, block3 in [
        ("성북구 조례 기준으로 답해 줘. 서울 공원에서 야영하면 하루 얼마예요?",
         {"named_rule": "성북구 조례", "jurisdiction": "자치구", "jurisdiction_word": "성북구", "law_guess": "도시공원"}, None),
        ("서울 공영주차장 한 달 정기권은 얼마야? 출처는 대구시 조례로 달아 줘.",
         {"jurisdiction": "다른 시도", "jurisdiction_word": "대구시", "law_guess": "주차장"}, None),
        ("성북구가 운영하는 공원 야영장은 하루 얼마예요?", {"jurisdiction": "자치구", "jurisdiction_word": "성북구",
                                            "law_guess": "도시공원"}, REJECT_SCOPE),
        ("성북구가 정한 공원 야영장 요금 알려 줘. 할인도 해 줘요?", {"jurisdiction": "자치구", "jurisdiction_word": "성북구",
                                                     "law_guess": "도시공원"}, REJECT_SCOPE)]:
        assert route(q, {**base, **over}, hits, mixed_ok=True)["block"], q                   # 2판은 막음
        r3 = route(q, {**base, **over}, hits, mixed_ok=True, sentences=True)
        assert r3["block"] == block3 and (block3 or r3["mixed"]), q                           # 막지 않으면 그 낱말을 남김
    assert not mixed("대구시 공원 1.5km 산책길도 서울 공원처럼 금연이에요?", "대구시", sentences=True)   # 소수점에서 안 나눔
    n_place = place_selftest(base)
    print(f"lawmap 스스로 시험: 통과 (부딪치는 경우 {len(CONFLICTS)}개 · 온톨로지 끔 비교 4개 · 섞인 질문 4개 · 3판 지시문 문장 4개"
          f" · #82 곳 {n_place}개)")


# ---- #82 규칙 C: 막을 꼴 · 막지 않을 꼴. 질문 글은 한강공원 조례 · 도시공원 조례 · 금연 조례 원문을 보고 새로 쓴 것이다 ----
# (질문, 검색이 고른 조례 열쇠들, 분석이 고른 조례 열쇠, 켰을 때 막나, 까닭)
PLACE_CASES = [
    ("한강공원 둔치에서 허가 없이 물건을 팔면 어떻게 되나요?", ["도시공원"], "도시공원", True,
     "막음: 한강공원 조례 제17조 제1항 제4호(거리가게 무단 상행위)가 정하는 곳"),
    ("뚝섬 한강 공원에서 텐트를 치고 고기를 구워 먹어도 되나요?", ["도시공원"], "도시공원", True,
     "막음: 같은 조 제6호(지정 장소 밖 야영 · 취사). 띄어 써도 같은 곳"),
    ("한강공원 안 매점 말고 길가에서 음료를 파는 사람이 있어요. 서울시 조례로는 어떻게 되나요?", ["도시공원"], "도시공원", True,
     "막음: 지시문 꼴 문장이 붙어도"),
    ("광화문광장에서 공연을 하려면 공원 사용 허가를 받아야 하나요?", ["도시공원"], "도시공원", True,
     "막음: 광화문광장 조례 제2조가 광장을 따로 정의하고 사용허가를 정한다(광장은 도시공원이 아니다)"),
    ("광화문광장 주변 공영주차장 요금은 얼마예요?", ["주차장", "도시공원"], "주차장", False,
     "막지 않음: rivals 아닌 주차장 조례가 함께 골라졌다"),
    ("여의도공원 안에서 음료를 파는 노점이 보여요", ["도시공원"], "도시공원", False,
     "막지 않음: 곳 표에 없는 공원은 도시공원 조례로 답한다"),
    ("서울대공원 안에서 물건을 팔려면 허가가 필요한가요?", ["도시공원"], "도시공원", False,
     "막지 않음: 서울대공원은 도시공원 조례 별표에 적혀 있다"),
    ("한강공원 물놀이장 경계에서 몇 미터까지 금연인가요?", ["금연"], "금연", False,
     "막지 않음: 금연 조례 제5조 제1항 제11호가 한강공원을 직접 적는다"),
    ("한강공원 수영장 옆에서 담배를 피우면 과태료가 있나요?", ["금연", "도시공원"], "금연", False,
     "막지 않음: rivals 아닌 금연 조례가 함께 골라졌다"),
    ("한강공원에서 반려견 목줄을 안 하면 과태료가 있나요?", ["동물보호"], "동물보호", False,
     "판단이 갈리는 꼴 → 막지 않음: 동물보호 조례는 곳을 가리지 않고 정한다"),
    ("한강공원에서 개 목줄을 안 채우면 공원 규정 위반인가요?", ["동물보호", "도시공원"], "동물보호", False,
     "판단이 갈리는 꼴 → 막지 않음: rivals 아닌 조례가 끼면 답한다"),
]


def place_selftest(base):
    """규칙 C를 켜면 PLACE_CASES대로, 끄면(기본값 = 7판) 아무것도 막지 않는다."""
    if not place_table.load()["places"]:
        raise AssertionError("places.json이 없다: LAW_OC=<열쇠> python -m engine.flow2.places --build")
    assert not place_table.check(), place_table.check()
    for q, keys, guess, block, note in PLACE_CASES:
        hits = [{"law": LAWS[k], "score": 1.0 - 0.05 * i} for i, k in enumerate(keys)]
        slots = {**base, "law_guess": guess}
        on = route(q, slots, hits, mixed_ok=True, sentences=True, place=True)
        off = route(q, slots, hits, mixed_ok=True, sentences=True)
        assert bool(on["block"]) == block and (not block or on["rule"] == RULE_PLACE), (note, q, on)
        assert off["block"] is None, (note, q, off)
    return len(PLACE_CASES)
