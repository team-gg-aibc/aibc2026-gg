"""근거 고르기 · 답 쓰기: Solar 한 번 부름으로 근거 번호를 고르고 답을 쓴다(킷 그대로).

계획 문서의 `select.py`다. `select`는 파이썬 표준 모듈 이름이라 겹치지 않게 이 이름으로 했다.
모델은 근거 「번호」만 고른다. 조항 표기(citation) · 링크 · 시행일은 코드가 조각 라벨에서 붙인다(contract.py).
"""
import json
import re

from . import upstage, whole

DISTRICT = re.compile(r"서울특별시\s*\S+구\s")      # 「OO구」 자치구 조례 인용 막기

# 프롬프트는 고쳐 쓰지 않고 새 판을 더한다. 설정 칸 answer_prompt에 판 이름을 쓴다.
PROMPTS = {
    "v1": """너는 서울특별시 조례 질의응답 도우미다.
규칙:
- 반드시 아래 [근거]에 적힌 내용만으로 답한다. 근거에 없는 내용은 추측하지 않는다.
- 답은 일반 시민이 이해할 수 있는 쉬운 말로 2~4문장으로 쓴다. 금액·비율·나이 같은 숫자는 그대로 쓴다.
- 답에 실제로 쓴 근거의 번호를 evidence_ids에 넣는다. 여러 조항을 함께 썼다면 모두 넣는다.
- 근거로 답할 수 없으면 found를 false로 한다.
- 자치구(OO구) 조례나 규칙은 근거로 쓰지 않는다.
결과는 JSON으로 낸다.""",
    # #27 조례 통째로 읽기용: 근거가 조례 전체라 번호를 이웃 항으로 잘못 다는 일이 많았다(dev 판정 거절 +44, 11-09)
    "w1": """너는 서울특별시 조례 질의응답 도우미다. [근거]에는 조례 하나의 원문이 조 · 항 순서대로 모두 들어 있다.
규칙:
- 반드시 아래 [근거]에 적힌 내용만으로 답한다. 근거에 없는 내용은 추측하지 않고, 조문에 없는 계산이나 추론(예: 「최대 몇 년」)을 덧붙이지 않는다.
- 답은 일반 시민이 이해할 수 있는 쉬운 말로 2~4문장으로 쓴다. 금액·비율·나이 같은 숫자는 그대로 쓴다.
- 답의 문장마다 그 내용이 실제로 적힌 근거를 찾아 모두 넣는다. 고르기 전에 그 근거의 조 · 항 이름과 본문을 다시 확인한다. 이웃한 항과 헷갈리지 않는다.
- 고른 근거에 없는 내용은 답에 쓰지 않는다. 질문과 관계없는 조항은 넣지도 쓰지도 않는다.
- 원칙과 예외 · 단서(「다만」, 「~하는 때에는 ~만」)가 따로 있으면 둘 다 확인하고 함께 넣는다.
- 근거로 답할 수 없으면 found를 false로 한다.
- 자치구(OO구) 조례나 규칙은 근거로 쓰지 않는다.
결과는 JSON으로 낸다.""",
}

SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "law_answer",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "found": {"type": "boolean"},
                "answer": {"type": "string"},
                "evidence_ids": {"type": "array", "items": {"type": "integer"}},
            },
            "required": ["found", "answer", "evidence_ids"],
            "additionalProperties": False,
        },
    },
}


# #27 whole_cite="label": 번호 대신 [근거]에 적힌 조항 이름을 그대로 적게 한다. 코드는 목록에 있는 이름만 받는다
SCHEMA_LABEL = {
    "type": "json_schema",
    "json_schema": {
        "name": "law_answer_labels",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "found": {"type": "boolean"},
                "answer": {"type": "string"},
                "evidence_labels": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["found", "answer", "evidence_labels"],
            "additionalProperties": False,
        },
    },
}


def context(hits):
    return "\n\n".join(f"[근거 {i}] {h['label']}\n{h['text']}" for i, h in enumerate(hits, 1))


def select_and_write(question, hits, cfg, calls=None):
    """돌려주는 것: found · answer · evidence_ids(모델이 고른 번호) · used(번호에 맞는 조각, 자치구 라벨 뺌)."""
    if cfg["whole_ordinance"]:   # #27: 검색 후보 대신 조례 원문 전체
        hits = whole.expand(hits, cfg)
    by_label = cfg["whole_ordinance"] and cfg["whole_cite"] == "label"
    system = PROMPTS[cfg["answer_prompt"]]
    if by_label:
        system += "\n근거는 번호가 아니라 [근거 i] 옆에 적힌 조항 이름(예: 「서울특별시 주차장 설치 및 관리 조례 제7조 제3항」)을 글자 그대로 evidence_labels에 넣는다."
    raw = upstage.chat(
        [{"role": "system", "content": system},
         {"role": "user", "content": f"[근거]\n{context(hits)}\n\n[질문]\n{question}"}],
        cfg, calls, response_format=SCHEMA_LABEL if by_label else SCHEMA)
    out = json.loads(raw)
    ids = whole.label_ids(out.get("evidence_labels", []), hits) if by_label else out.get("evidence_ids", [])
    used = [hits[i - 1] for i in ids if 1 <= i <= len(hits)]
    used = [h for h in used if not DISTRICT.search(h["label"])]
    return {"found": bool(out.get("found")), "answer": out.get("answer", ""), "evidence_ids": ids, "used": used}
