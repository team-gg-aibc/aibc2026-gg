"""출력 꼴: 대회 응답은 4칸 JSON(answer · citation · source_url · effective_date).

citation · source_url · effective_date는 코드가 조각 라벨과 원문 정보에서 채운다(모델이 쓰지 않음).
마지막 출구 검사(필드 · 꼴 · 인용 허용 목록 · 상한)는 #22 출력 규격 강제(동욱) 몫이다.
"""
UNKNOWN = {"answer": "확인 불가", "citation": [], "source_url": "", "effective_date": ""}


def unknown():
    return dict(UNKNOWN)


def build(answer, used):
    """used: 답에 쓴 조각들(순서대로). 인용은 순서를 지키며 겹침을 뺀다. 링크 · 시행일은 첫 조각의 조례 것."""
    citation = list(dict.fromkeys(h["label"] for h in used))
    first = used[0]
    return {"answer": answer, "citation": citation,
            "source_url": first["source_url"], "effective_date": first["effective_date"]}
