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


def context(hits):
    return "\n\n".join(f"[근거 {i}] {h['label']}\n{h['text']}" for i, h in enumerate(hits, 1))


def select_and_write(question, hits, cfg, calls=None):
    """돌려주는 것: found · answer · evidence_ids(모델이 고른 번호) · used(번호에 맞는 조각, 자치구 라벨 뺌)."""
    if cfg["whole_ordinance"]:   # #27: 검색 후보 대신 조례 원문 전체
        hits = whole.expand(hits, cfg)
    raw = upstage.chat(
        [{"role": "system", "content": PROMPTS[cfg["answer_prompt"]]},
         {"role": "user", "content": f"[근거]\n{context(hits)}\n\n[질문]\n{question}"}],
        cfg, calls, response_format=SCHEMA)
    out = json.loads(raw)
    ids = out.get("evidence_ids", [])
    used = [hits[i - 1] for i in ids if 1 <= i <= len(hits)]
    used = [h for h in used if not DISTRICT.search(h["label"])]
    return {"found": bool(out.get("found")), "answer": out.get("answer", ""), "evidence_ids": ids, "used": used}
