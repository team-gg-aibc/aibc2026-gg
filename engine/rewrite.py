"""용어 사전 (#26): 시민 말을 조례 용어로 바꾼 낱말을 키워드 검색어 뒤에 더한다. 모델을 부르지 않는다(호출 0).

- 원래 질문은 그대로 두고 조례 용어를 덧붙인다(원래 질문 + 조례 용어). 의미 검색(임베딩)은 원래 질문만 쓴다.
- 항목마다 출처를 단다: dev 문항 id(그 문항에서 시민 말과 정답 조항 용어가 어긋남) 또는 조례 조항 라벨.
  출처가 dev가 아닌 문항(holdout 등)이면 혼자 시험이 실패한다(holdout을 보고 사전을 만들지 않는다).
- 덧붙이는 조례 용어는 모두 조례 원문(engine/data/chunks_*.json)에 있는 낱말이어야 한다(혼자 시험이 검사).
- 설정 칸 term_dict: False(끔, 기본) · True(키워드 검색어에 조례 용어를 더함).

혼자 시험 (키 없이): python -m engine.rewrite --selftest
바뀐 검색어 보기:   python -m engine.rewrite "서울 따릉이 싸게 탈 수 있어요?"
"""
import re

# (시민 말 정규식, 더할 조례 용어, 출처)
ENTRIES = [
    # 동물보호
    (r"떠돌이|버려진|유기견|유기묘|길\s*잃은", "유기동물 구조 보호", "animal-S032 animal-S039 animal-S042"),
    (r"보호소", "동물보호센터", "animal-S029 animal-S037"),
    (r"강아지|반려견|애완견", "반려동물", "animal-S016"),
    (r"(?:강아지|개|반려견).{0,15}등록|등록.{0,15}(?:강아지|개|반려견)", "등록대상동물", "animal-S016 animal-S019"),
    (r"칩", "무선식별장치", "animal-S017 animal-C066"),
    (r"등록비", "등록수수료", "animal-S019 animal-C066"),
    (r"병원.{0,15}등록|등록.{0,15}병원", "등록대행자", "animal-S017 animal-S019"),
    (r"사나운|사납|공격성", "기질평가", "animal-C020"),
    (r"소변|대변|오줌|똥", "배설물", "animal-C014"),
    (r"스티커|들어와도", "출입안내 표시 다중이용시설", "animal-C018"),
    (r"때려|때리|떼어\s*놓", "피학대동물 학대", "animal-C040"),
    (r"못\s*키우|맡아\s*줄\s*사람", "사육포기 인수", "animal-S048 animal-M023"),
    (r"고기", "도축", "animal-C046"),
    (r"장부|확인하고", "출입 검사", "animal-C051"),
    (r"화장터", "동물장묘시설", "animal-C069 animal-S069"),
    (r"데려와\s*키우|데려가는|데려오|데려올", "입양 분양", "animal-S042 animal-C032 animal-S045"),
    (r"잃어버|돌려주", "반환 소유자", "animal-C036 animal-M016"),
    # 자전거
    (r"따릉이", "공공자전거", "bicycle-S001 bicycle-C027 bicycle-C028"),
    (r"세워\s*두는\s*곳|세우는\s*곳|세울\s*곳|거치대|세워\s*두는\s*자리", "자전거주차장", "bicycle-S010 bicycle-M003 bicycle-S039"),
    (r"보험", "단체보험", "bicycle-S035"),
    (r"애가\s*셋|아이가\s*셋|세\s*아이|다둥이", "다자녀", "bicycle-C032 park-C028 parking-M016"),
    # 공통: 요금 · 벌
    (r"할인|깎아|싸게|공짜|면제", "감면", "bicycle-C029 bicycle-C032 park-C027"),
    (r"벌금|딱지", "과태료", "park-S028 park-S030 parking-S062"),
    (r"돈\S*\s*(?:다\s*)?돌려", "환불", "park-C018 park-C019 parking-C032"),
    (r"안내판", "표지 표시", "parking-S029 parking-S025 smoking-S009"),
    (r"몇\s*번\s*모여|한\s*번\s*모여|모여요", "회의 개최", "park-S040 animal-S012 youth-S017"),
    (r"대신해", "직무 대행", "park-S038 park-S039"),
    # 도시공원
    (r"매점", "공원시설 위탁", "park-S007 park-S018 park-S020"),
    (r"자릿세|땅\s*쓰는|땅을\s*쓰|쓰는\s*돈|쓰는\s*값", "점용료 사용료", "park-S018 park-S019 park-S021 park-S051"),
    (r"술\s*마시|술을\s*마시", "음주 금주구역", "park-S027 park-S031"),
    (r"숲\s*체험|행사", "자연생태교육 문화활동", "park-S010"),
    (r"전봇대", "전주", "park-S051"),
    # 주차장
    (r"길가", "노상주차장", "parking-C008 parking-S007 parking-S023 parking-C032"),
    (r"짐\s*내리", "하역주차구획", "parking-S024 parking-S025 parking-M010"),
    (r"안\s*내고|그냥\s*가\s*버리|그냥\s*나온", "가산금", "parking-S007 parking-M026"),
    (r"주차\s*빌딩", "주차전용건축물", "parking-S019"),
    (r"주차장\s*부지|딸린\s*시설|편의점", "노외주차장 부대시설", "parking-S030 parking-C038 parking-C039"),
    (r"경차|모닝", "경형자동차", "parking-S010 parking-M002"),
    (r"임신", "임산부", "parking-C015"),
    (r"구청\s*주차장", "공공기관 부설주차장", "parking-C045 parking-C046 parking-C047"),
    (r"개방|열어\s*줄|열면서", "일반 이용에의 제공", "parking-C045 parking-C046"),
    (r"빌려|빌리", "융자", "parking-C057 parking-C058 parking-S058"),
    (r"친환경차|전기차", "환경친화적 자동차 전용주차구획", "parking-S050"),
    (r"차\s*세울\s*자리|주차\s*형편", "주차환경개선지구", "parking-C003 parking-M030"),
    (r"운영하는\s*사람|관리하는\s*사람", "주차장 관리자", "parking-S014"),
    # 금연
    (r"담배\s*(?:피우면|피우는\s*게)?\s*안\s*되는\s*곳|담배\s*못\s*피우는", "금연구역", "smoking-C007 smoking-C009 smoking-S008"),
    (r"단속하는\s*분|단속원", "금연지도원", "smoking-S018 smoking-C021 smoking-S019"),
    # 청년
    (r"장기\s*계획|큰\s*계획|5년짜리", "기본계획", "youth-S005 youth-C005 animal-S005"),
    (r"해마다\s*(?:세우|따로)", "시행계획", "youth-C007 animal-S005"),
    (r"빚|사채|독촉", "금융", "youth-C037 youth-M018"),
    (r"월세|고시원|자취|집\s*지원", "주거", "youth-C032 youth-C033 youth-C035"),
    (r"공연|전시|관람권", "문화", "youth-C040"),
    (r"차리", "창업", "youth-S034"),
    (r"학원비|자격증|공부할\s*기회", "능력개발 교육", "youth-C028 youth-S029"),
    (r"일자리|취업", "고용", "youth-M018 youth-S035"),
    (r"청년\s*모임", "청년단체", "youth-M010 youth-S050"),
    (r"청년\s*공간", "청년시설", "youth-S046"),
]
_RX = [(re.compile(p), terms, src) for p, terms, src in ENTRIES]


def expand(question):
    """(키워드 검색어, 더한 조례 용어 목록). 맞는 항목이 없으면 원래 질문 그대로."""
    added = []
    for rx, terms, _ in _RX:
        if rx.search(question):
            added += [t for t in terms.split() if t not in added and t not in question]
    return (f"{question} {' '.join(added)}" if added else question), added


def _selftest():
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    split = {q["id"]: q.get("split") for f in sorted((root / "eval").glob("questions_*.json"))
             for q in json.loads(f.read_text(encoding="utf-8"))}
    corpus = "".join(re.sub(r"\s+", "", c["label"] + c["text"])
                     for f in sorted((root / "engine" / "data").glob("chunks_*.json"))
                     for c in json.loads(f.read_text(encoding="utf-8")))
    for p, terms, src in ENTRIES:
        for s in src.split():
            assert split.get(s) == "dev", f"출처가 dev 문항이 아님(holdout 금지): {s} ({p})"
        for t in terms.split():
            assert t in corpus, f"조례 원문에 없는 용어: {t} ({p})"
    q, added = expand("서울 따릉이 애가 셋인데 싸게 탈 수 있어요?")
    assert added == ["공공자전거", "다자녀", "감면"], added
    assert expand("서울시 공영주차장 경형자동차 감면은?")[1] == [], "맞는 항목이 없으면 그대로"
    print(f"rewrite 혼자 시험: 통과 (항목 {len(ENTRIES)}개)")


if __name__ == "__main__":
    import sys
    if sys.argv[1:2] == ["--selftest"]:
        _selftest()
    else:
        print(expand(" ".join(sys.argv[1:])))
