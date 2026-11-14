"""엔진 설정 한곳. 실험 하나 = 설정 파일 하나(`eval/configs/<이름>.json`).

- DEFAULTS가 지금 main의 판이다: 출발 판(스타터 킷 그대로 + 없어진 groundedness-check 대신 solar-pro4 판정) 위에
  배분일마다 채택한 실험의 스위치를 켠다(1주기 #22 · #24, 11/10). 끈 판(`eval/configs/baseline.json`)은 DEFAULTS 그대로다.
  설정 파일은 바꿀 값만 `engine` 칸에 적는다. 모르는 칸이 있으면 멈춘다(오타로 실험이 조용히 출발 판이 되지 않게).
- 이슈마다 아래 자기 절(주석)에만 줄을 더한다. 새 스위치의 기본값은 「출발 판과 같은 동작」으로 둔다.
- 프롬프트는 고쳐 쓰지 않고 새 판 이름을 더한다(`answer.PROMPTS`, `verify.PROMPTS`). 설정에는 판 이름만 쓴다.
- 키는 설정에 두지 않는다. 레포 맨 위 `.env`의 UPSTAGE_API_KEY만 읽고, 값은 어디에도 출력하지 않는다.
"""
import hashlib
import json
import os
import subprocess
from functools import lru_cache
from pathlib import Path

ENGINE = Path(__file__).resolve().parent
ROOT = ENGINE.parent
DATA = ENGINE / "data"

DEFAULTS = {
    # ---- #20 엔진 뼈대: 출발 판 (킷 그대로) ----
    "chat_model": "solar-pro4",
    "embed_passage": "solar-embedding-2-passage",   # 조각용 (색인 만들 때)
    "embed_query": "solar-embedding-2-query",       # 질문용
    "temperature": 0.0,
    "reasoning_effort": None,        # solar-pro4: None이면 추론 끔, "low" 이상이면 켬
    "chunk_unit": "paragraph",       # 색인 단위 (engine/data/chunks_<단위>.json)
    "top_k": 20,                     # 검색 후보 수 (출발 판 6 → 1주기 채택 #24)
    "hybrid_cos_weight": 0.7,        # 혼합 점수 = 이 값 × 의미 점수 + (1 − 이 값) × 키워드 점수
    "use_embedding": True,           # False면 키워드 검색만 (키가 없어도 키워드만 돈다)
    "use_verify": True,              # 검증 ① 점수 문턱 · ② solar-pro4 판정
    "min_score": 0.25,               # 1위 후보의 의미 점수가 이보다 낮으면 확인 불가
    "answer_prompt": "v2",           # answer.PROMPTS의 판 이름 (출발 판 v1 → 1주기 채택 #24)
    "verify_prompt": "v1",           # verify.PROMPTS의 판 이름
    "timeout_sec": 75,               # 넘으면 확인 불가로 답한다 (대회 제한 90초)
    "explore": False,                # 탐색 모드(1~3주기): 90초 넘어도 점수에서 빼지 않고 시간은 기록만. 상한은 timeout_sec(탐색 설정은 300)
    # ---- #22 출력 규격 강제 (동욱) ----
    "exit_check": True,              # (1주기 채택, 출발 판 False) 마지막 출구 검사: 어중간한 답 맞추기 · 색인 라벨만 · 겹침 빼기 · 링크 · 시행일은 첫 인용의 원문에서
    "max_citations": 4,              # 인용 개수 상한(exit_check가 켜졌을 때). None = 상한 없음(출발 판) → 1주기 채택 4
    "retry_budget": True,            # (1주기 채택, 출발 판 False) 429 · 5xx · 시간 초과 · 연결 오류만, 간격을 늘리며 마감 안에서 재시도(SDK 자체 재시도 끔). False = 킷 그대로
    "max_concurrent_calls": 6,       # 업스테이지 동시 호출 수 상한(프로세스 전체). None = 제한 없음(출발 판) → 1주기 채택 6
    "on_deadline": "unknown",        # 마감이 지났을 때: "unknown" = 확인 불가(킷), "draft" = 판정 전 답이 있으면 그것
    # ---- #23 조각 다듬기 (건영) ----
    # ---- #24 후보 넓히기 (종희) ----  후보 수 자체는 위 top_k(실험 10 · 15 · 20)
    "select_mode": "prefilter",      # (1주기 채택, 출발 판 "direct") "direct" = ① 후보를 그대로 주고 고르기 / "prefilter" = ② Solar 한 번으로 먼저 추린 뒤 답 쓰기
    "prefilter_keep": 8,             # ②에서 추린 뒤 답 쓰기에 넘길 최대 후보 수(점수 순)
    "prefilter_empty_abstain": True,  # (1주기 채택, 출발 판 False) ②에서 관련 후보가 하나도 없으면 True = 확인 불가로 끝냄 / False = 점수 순 앞 prefilter_keep개로 답 쓰기
    "max_per_article": 0,            # 같은 조(제○조)의 항을 후보에 몇 개까지 둘지. 0 = 제한 없음(출발 판)
    "group_by_article": True,        # (1주기 채택, 출발 판 False) True면 같은 조의 항을 한 덩어리로 묶어 보여 준다(덩어리 순서는 그 조의 가장 높은 점수 순)
    # ---- #25 질문 분석 게이트 (동욱) ----
    "gate": "off",                   # gate.py: "off" 출발 판 · "log" 기록만 · "on" 지시문 떼고 자치구 조례 · 규칙을 묻으면 확인 불가
    "question_fence": False,         # True면 답 쓰기에 질문을 <질문>…</질문>으로 감싸 넘긴다(질문 속 같은 표시는 지운다)
    # ---- #26 질문 다듬기 (건영) ----
    # ---- #27 조례 통째로 읽기 (종희) ----
    # ---- #28 원칙 · 예외 묶음 (건영) ----
    # ---- #29 답 형식 (종희) ----
    # ---- #30 확인 불가 신호등 (동욱) ----
    # ---- #82 다른 조례가 다스리는 곳 가리기 (동욱, 3주기) ----
    "flow2_place_scope": False,      # flow2만: True면 ③에서 곳 표(engine/flow2/places.json, 한강공원 등)의 곳을 묻는데 고른 조례가 모두 그 곳의 rivals이고 원문에 그 낱말이 없으면 확인 불가(lawmap 규칙 C). False = 7판과 같은 동작
    # ---- #83 답 첫머리에 결론 붙이기 (3주기, PM 쪽이 이어받음) ----
    "flow2_lead": "off",             # flow2만: "off" = 7판과 같은 동작 / "comma" = 출력 직전에 ④의 결론 칸(네 · 아니요)을 답 앞에 「네, …」로 붙이고 답 글의 안쪽 말 「이 자료」를 「서울시 조례 6종」으로 바꾼다 / "period" = 같은 동작인데 「네. …」로 끊어 붙인다. 붙이지 않는 답: 이미 그렇게 시작 · 결론 칸이 「정보」 · 첫 물음에 묻는 말(몇 · 얼마 · 누가 …)이 있음. 「확인 불가」 답은 건드리지 않는다(engine/flow2/flow.py lead)
    # ---- PM 별도 실험: 새 흐름 (동규, 설계는 공유 노트 「PM별도실험-설계-11-10」) ----
    "flow": "kit",                   # "kit" = 지금 흐름(pipeline.STAGES) / "flow2" = engine/flow2(질문 분석 → 조례 확정 → 조례 통째로 읽기 → 구절 관문 → 질문 대조)
    "flow2_ontology": True,          # flow2만: True = ③ · ⑥이 온톨로지(engine/flow2/ontology.json)를 씀, False = 단순 규칙(온톨로지 몫 재기)
    "flow2_version": 1,              # flow2만: 1 = 11-10 첫 판(a1 · r1 · c1) / 2 = 섞인 질문 부분 답 · 틀린 전제 바로잡기 · 행위 주체(a2 · r3 · c4, ③ 섞인 질문은 막지 않음) / 3 = 2판 + ④ 조건 대조 칸을 결론 앞에 · 지시문 · ⑤ 이름 · 괄호 글 대조 · ③ 지시문 문장 · ⑥ 조 번호 가리기(a2 · r4 · c4) / 4 = 3판 + ⑥ 조건 · 범위로 「아니요」인 답 · 「삭제」 답은 grounded, 지시문 문장 빼기(a2 · r4 · c6) / 5 = 3판 프롬프트 + 4판의 ⑥ 입력 정리(코드) + ⑥ targets 칸 빼기(a2 · r4 · c7) / 6 = 5판 + ④를 ①과 함께 미리 부르기(④에 질문 분석 줄 없음, a2 · r6 · c7) / 7 = 6판 + 상위 법령으로 넘기는 구절에 「이 자료에 없다」 표시(코드) · ⑥ 닫는 칸(a2 · r7 · c8)
    "flow2_hedge_sec": None,         # flow2만: 호출 하나가 이 초 안에 안 돌아오면 기다리면서 하나 더 부르고 먼저 온 것을 쓴다. 깨진 JSON 출력도 다시 부른다(많아야 세 번). None = 끔(1~4판)
    # ---- 흔들림 줄이기 (동규, 11-11 지시서 14) ----  같은 문의를 다시 넣으면 답이 바뀌는 문제
    "flow2_votes": None,             # flow2만: None = 끔(7판 그대로 단계마다 한 번 부름). {"analyze": 3, "read": 3, "check": 3}처럼 단계마다 부를 횟수를 적으면 같은 호출을 그만큼 나란히 부르고 결정(고를 조례 칸 · found · 근거 조항 · 판정)을 다수결로 정한다(flow.py 「흔들림 줄이기」). 적지 않은 단계는 한 번. "read_all": true를 더하면 ④의 근거는 과반 대신 「답한 표가 모두 든 조항만」
    "flow2_memo": None,              # flow2만: None = 끔(같은 문의도 매번 모델을 부른다). 파일 경로(레포 맨 위 기준, 예: "engine/data/flow2_memo.jsonl")를 적으면 모델 호출의 출력을 보낸 글의 지문별로 그 파일에 적어 두고, 같은 글을 다시 보내야 할 때 부르지 않고 그 출력을 쓴다 → 같은 문의에는 글자까지 같은 답(flow.py 「같은 글에는 같은 출력」). ":memory:"는 파일 없이
    # ---- 맡긴 내용을 묻는 질문 (동규, 11-11 업스테이지 답 1번) ----
    "flow2_handed": False,           # flow2만: False = 7판 그대로(⑥이 거절하면 확인 불가). True = ⑥이 거절했어도 판정 전 답이 「조례에 정해져 있지 않다」 꼴이고 ⑤를 지난 근거 조항 글에 조례가 스스로 맡기는 구절(「시장이 따로 정한다」 · 「규칙으로 정한다」 등)이 있고 답 글도 누가 정하는지 말하면 그 답을 낸다(코드만, 호출 수 그대로. flow.py 「맡긴 내용을 묻는 질문의 답 살리기」). "law" = True에 더해, 근거 조항이 내용을 다른 법령(「법 제○조」 · 「영 제○조」 · 「○○법」 · 6종이 드는 다른 서울시 조례)으로 넘기고 답 글이 그 법령에서 정한다고 말할 때도 답을 낸다(11-11 업스테이지 2차 답)
    # ---- PM 실험: 온톨로지로 근거 묶음 정리 (동규 11-11, engine/flow2/cite.py · links.py) ----
    "flow2_cite": None,              # flow2만: None = 7판 그대로 / "fill" = ⑥을 지난 답의 근거가 원문에서 가리키는 조항을 합쳐 3개까지 덧붙임(코드만) / "pick" = 온톨로지로 넓힌 후보에서 작은 호출 하나가 후보마다 직접 · 참고 · 무관을 골라 같은 조의 곁가지 항을 정리 / "pick+fill" = 둘 다. 답 글과 답함 · 확인 불가는 안 바꾼다
    # ---- #81 결합 질문의 근거를 빠짐없이 (종희) ----
    "flow2_read_asks": False,        # flow2만: True면 ④ 읽기가 r8-81을 쓴다(답 · 근거 전에 물음마다 조항 이름을 적는 칸 asks). False = 판이 고른 프롬프트(7판은 r7)
    "flow2_read_deleg": False,       # flow2만: True면 ④ 읽기가 r8-deleg를 쓴다(조항은 있는데 값 · 세부가 없거나 다른 법령에 넘긴 질문은 그 조항으로 답함, 11-11 받은 답). "topic"이면 r9-topic(r8-deleg + found 앞에 「묻는 일을 정한 조항」 칸 topic, 법률 용어 짝 포함. PM 11-14, flow2_read_asks와 함께 쓰지 않음). False = 판이 고른 프롬프트(7판은 r7)
    # ---- 업스테이지 기준 맞추기 (PM, 11-14 엔진 다시 엶. 점검 보고 「놓친 것」 1 · 2번) ----
    "flow2_check_gray": False,       # flow2만: True면 ⑥은 판이 고른 프롬프트(7판은 c8)를 먼저 하고, 그것이 거절한 「조례에 정해져 있지 않다 · 조례에 없다」 꼴 답만 c9-gray로 한 번 더 본다(④ topic 조항이 인용에 있을 때, 묻는 그 일을 정한 조항이 있고 값만 조례 밖이면 통과). 코드 판정 둘(flow.code_verdict). False = 7판과 같은 동작
    "flow2_plain": False,            # flow2만: True면 ⑥을 지난 답 글을 짧고 쉬운 말로 한 번 더 쓴다(호출 하나를 ⑥과 나란히, 프롬프트 w1, engine/flow2/plain.py). 인용 · 링크 · 시행일은 그대로, 숫자 · 결론이 바뀌면 원래 답. False = 7판과 같은 동작
    "unknown_guide": False,          # True면 「확인 불가」 답 뒤에 어디에 물으면 되는지 한 줄을 붙인다(contract.GUIDES, 11-11 받은 답: 확인 불가로 시작 + 빈 인용이면 정답). False = 킷 꼴 「확인 불가」 네 글자
}


def load(path=None):
    """설정 파일을 읽어 DEFAULTS 위에 덮는다. 돌려주는 dict에는 엔진 값만 있다."""
    cfg = dict(DEFAULTS)
    if path:
        over = json.loads(Path(path).read_text(encoding="utf-8")).get("engine", {})
        unknown = sorted(set(over) - set(DEFAULTS))
        if unknown:
            raise ValueError(f"{path}: config.py DEFAULTS에 없는 칸 {unknown} (오타인지, 스위치를 DEFAULTS에 더했는지 확인)")
        cfg.update(over)
    return cfg


def digest(obj, n=12):
    """설정 · 문항 묶음 같은 값의 지문. 같은 값이면 어느 컴퓨터에서나 같다."""
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:n]


def _env_files():
    yield ROOT / ".env"
    try:  # git worktree에서 돌리면 원래 레포 폴더의 .env도 본다
        common = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                capture_output=True, text=True, timeout=5).stdout.strip()
        if common:
            yield Path(common).parent / ".env"
    except (OSError, subprocess.SubprocessError):
        pass


@lru_cache(maxsize=None)
def _key_in_env_file():
    """.env는 한 번만 읽는다(문항마다 git을 띄우지 않게. 하위 프로세스가 동시 계산과 겹치면 멈출 수 있다)."""
    for f in _env_files():
        if f.is_file():
            for line in f.read_text(encoding="utf-8").splitlines():
                k, sep, v = line.strip().removeprefix("export ").partition("=")
                if sep and k.strip() == "UPSTAGE_API_KEY":
                    return v.strip().strip("'\"")
    return ""


def api_key():
    """환경 변수 → 레포 .env 순서로 찾는다. 값은 돌려주기만 하고 출력하지 않는다."""
    if os.environ.get("UPSTAGE_API_KEY") is not None:   # 빈 값으로 두면 「키 없이」로 돈다
        return os.environ["UPSTAGE_API_KEY"].strip()
    return _key_in_env_file()
