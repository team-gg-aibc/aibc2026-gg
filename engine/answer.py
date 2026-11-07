"""근거 고르기 · 답 쓰기: Solar 한 번 부름으로 근거 번호를 고르고 답을 쓴다(킷 그대로).

계획 문서의 `select.py`다. `select`는 파이썬 표준 모듈 이름이라 겹치지 않게 이 이름으로 했다.
모델은 근거 「번호」만 고른다. 조항 표기(citation) · 링크 · 시행일은 코드가 조각 라벨에서 붙인다(contract.py).
"""
import json
import re

from . import upstage

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
    # #24 후보 넓히기: 후보가 많아졌을 때(10~20개) 고르는 법을 더 적는다. 근거는 점수 높은 순, 같은 조의 항은 붙어 있다.
    "v2": """너는 서울특별시 조례 질의응답 도우미다.
[근거]는 검색 점수가 높은 것부터 놓여 있고, 같은 조의 여러 항은 붙어 있다. 질문과 상관없는 근거도 섞여 있다.
규칙:
- 반드시 아래 [근거]에 적힌 내용만으로 답한다. 근거에 없는 내용은 추측하지 않는다.
- 먼저 질문에 직접 답하는 근거를 고른다. 원칙 조항과 함께 예외 · 단서 · 감면 · 중복 제한처럼 답을 바꾸는 조항이 있으면 그것도 고른다.
- 질문과 상관없는 근거는 고르지 않는다. 같은 조라도 답에 쓰지 않은 항은 넣지 않는다.
- 답은 일반 시민이 이해할 수 있는 쉬운 말로 2~4문장으로 쓴다. 금액·비율·나이 같은 숫자는 그대로 쓴다.
- 답에 실제로 쓴 근거의 번호를 evidence_ids에 넣는다. 여러 조항을 함께 썼다면 모두 넣는다.
- 근거로 답할 수 없으면 found를 false로 한다.
- 자치구(OO구) 조례나 규칙은 근거로 쓰지 않는다.
결과는 JSON으로 낸다.""",
}

# #24 방식 ②: 답을 쓰기 전에 후보 가운데 질문과 관련 있는 것만 추린다(Solar 한 번).
PREFILTER_PROMPT = """너는 서울특별시 조례 검색 결과를 거르는 도우미다.
[후보] 가운데 [질문]에 답하는 데 필요한 조항의 번호만 relevant_ids에 넣는다.
- 질문에 직접 답하는 조항, 그리고 예외 · 단서 · 감면 · 중복 제한처럼 답을 바꿀 수 있는 조항을 넣는다.
- 질문과 상관없는 조항은 넣지 않는다. 관련 있는 것이 없으면 빈 목록을 낸다.
결과는 JSON으로 낸다."""

PREFILTER_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "relevant_candidates",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {"relevant_ids": {"type": "array", "items": {"type": "integer"}}},
            "required": ["relevant_ids"],
            "additionalProperties": False,
        },
    },
}

ARTICLE = re.compile(r"^(.*?(?:제\d+조(?:의\d+)?|별표\s*\d*))")


def article_of(label):
    """「… 제7조 제3항」 → 「… 제7조」. 별표는 「… 별표 1」까지. 꼴이 다르면 라벨 그대로."""
    m = ARTICLE.match(label)
    return m.group(1) if m else label


def cap_per_article(hits, n):
    """같은 조의 항은 점수 순으로 n개까지만 남긴다(n이 0이면 그대로). 남은 순서는 점수 순 그대로."""
    if not n:
        return hits          # 같은 목록을 그대로 돌려줘야 출발 판에서 번호를 되돌리지 않는다(select_and_write)
    seen, out = {}, []
    for h in hits:
        a = article_of(h["label"])
        if seen.get(a, 0) < n:
            seen[a] = seen.get(a, 0) + 1
            out.append(h)
    return out


def group_by_article(hits):
    """같은 조의 항을 붙여 놓는다. 덩어리 순서는 그 조에서 가장 먼저(점수 높게) 나온 항의 순서, 덩어리 안은 점수 순."""
    groups = {}
    for h in hits:
        groups.setdefault(article_of(h["label"]), []).append(h)
    return [h for g in groups.values() for h in g]


def prefilter(question, hits, cfg, calls=None):
    """방식 ②: 관련 있는 후보만 점수 순으로 prefilter_keep개까지. 하나도 안 고르면 원래 순서의 앞 prefilter_keep개."""
    raw = upstage.chat(
        [{"role": "system", "content": PREFILTER_PROMPT},
         {"role": "user", "content": f"[후보]\n{context(hits)}\n\n[질문]\n{question}"}],
        cfg, calls, response_format=PREFILTER_SCHEMA)
    ids = sorted({i for i in json.loads(raw).get("relevant_ids", []) if 1 <= i <= len(hits)})
    keep = [hits[i - 1] for i in ids] or list(hits)
    return keep[:cfg["prefilter_keep"]]


def shown(question, hits, cfg, calls=None):
    """답 쓰기에 보여 줄 후보: 같은 조 개수 제한 → (②면) 추리기 → (켜면) 조 단위로 묶기. 모두 끄면 hits 그대로(출발 판)."""
    out = cap_per_article(hits, cfg["max_per_article"])
    if cfg["select_mode"] == "prefilter":
        out = prefilter(question, out, cfg, calls)
    elif cfg["select_mode"] != "direct":
        raise ValueError(f"select_mode는 direct · prefilter 중 하나: {cfg['select_mode']!r}")
    if cfg["group_by_article"]:
        out = group_by_article(out)
    return out

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
    """돌려주는 것: found · answer · evidence_ids · used(번호에 맞는 조각, 자치구 라벨 뺌).

    evidence_ids는 검색 후보(hits) 기준 번호다. #24 스위치로 보여 준 목록의 순서가 바뀌어도
    판단 기록의 후보(candidates)와 번호가 맞게 되돌린다. 모델이 낸 번호는 보여 준 목록 범위 안의 것만 쓴다.
    """
    view = shown(question, hits, cfg, calls)
    raw = upstage.chat(
        [{"role": "system", "content": PROMPTS[cfg["answer_prompt"]]},
         {"role": "user", "content": f"[근거]\n{context(view)}\n\n[질문]\n{question}"}],
        cfg, calls, response_format=SCHEMA)
    out = json.loads(raw)
    picked = [view[i - 1] for i in out.get("evidence_ids", []) if isinstance(i, int) and 1 <= i <= len(view)]
    pos = {id(h): n for n, h in enumerate(hits, 1)}
    ids = [pos[id(h)] for h in picked] if view is not hits else list(out.get("evidence_ids", []))
    used = [h for h in picked if not DISTRICT.search(h["label"])]
    return {"found": bool(out.get("found")), "answer": out.get("answer", ""), "evidence_ids": ids, "used": used}
