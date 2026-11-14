# 팀 GG — 서울시 조례 Q&A 엔진 (2026 AI 부트캠프 경진대회 · 업스테이지 주제)

시민 · 공무원의 일상 질문에 서울특별시 조례 6종(주차장 · 동물보호 · 자전거 · 도시공원 · 청년 · 금연, 2026-10-01 시행본 기준)에서 근거 조항을 찾아 답하는 API다. 응답은 대회 규격 네 칸 JSON이다.

```json
POST /ask  {"question": "장애인 주차요금 감면되나요?"}

{"answer": "네, 장애인이 타면 주차요금이 80% 할인됩니다.",
 "citation": ["서울특별시 주차장 설치 및 관리 조례 제7조 제1항"],
 "source_url": "https://www.law.go.kr/...",
 "effective_date": "2026-10-01"}
```

근거를 찾지 못하면 `"answer"`가 「확인 불가」로 시작하고 `"citation"`은 비어 있다.

## 쓰는 모델

모두 업스테이지 모델이다: 답 · 판정 `solar-pro4`, 질문 임베딩 `solar-embedding-2-query`(조문 임베딩 `solar-embedding-2-passage`는 미리 만들어 `engine/data/`에 커밋했다). 그 밖의 모델은 엔진에 없다.

## 실행 방법

파이썬 3.10~3.13(3.12 권장). 레포 맨 위 폴더에서:

```bash
python3 -m venv .venv
.venv/bin/pip install -r engine/requirements.txt
cp .env.example .env          # UPSTAGE_API_KEY= 뒤에 키를 넣는다(값은 올리지 않는다)
```

한 문항:

```bash
.venv/bin/python -m engine.pipeline "경차 주차요금 할인돼요?" eval/configs/release.json
```

채점 API 서버(대회에 낸 판):

```bash
ENGINE_CONFIG=eval/configs/release.json .venv/bin/uvicorn engine.server:app --host 0.0.0.0 --port 8000
```

- 워커는 하나로 띄운다(`--workers`를 주지 않는다). 문항마다 75초에 마감하고, 어떤 오류에도 HTTP 200과 네 칸 JSON으로 답한다.
- `GET /health`의 `settings`가 띄운 설정의 지문이다.
- 공개 예시 문항을 동시 2문항으로 불러 보기: `.venv/bin/python eval/run.py --url http://localhost:8000/ask --split kit --workers 2`

윈도우는 `.venv\Scripts\python`을 쓰고, 나머지 차이는 `engine/README.md` 「윈도우에서 다른 것」에 있다.

## 환경 변수

| 이름 | 쓰는 곳 | 없으면 |
|---|---|---|
| `UPSTAGE_API_KEY` | 엔진(답 · 판정 · 질문 임베딩) | 키워드 검색만 돌고 답은 「확인 불가」 |
| `ENGINE_CONFIG` | 채점 서버가 읽을 설정 파일(제출 판은 `eval/configs/release.json`) | 출발 판(`engine/config.py` 기본값) |
| `ENGINE_LOG_DIR` | 채점 서버의 문항별 판단 기록 폴더 | `logs/` (빈 값이면 남기지 않음) |
| `LAW_OC` | 조례 원문을 다시 받을 때만(`eval/fetch_source.py`) | 엔진 실행에는 필요 없다(원문은 레포에 있다) |

키는 `.env`(레포 맨 위)나 환경 변수로만 준다. 값은 코드 · 로그 · 기록 어디에도 남기지 않는다.

## 재현

- 점수 재기: `.venv/bin/python eval/run.py --config eval/configs/release.json --split dev --repeat 2` (dev 693문항, 두 번)
- 지난 실행이 같은 결과인지(키 없이): `.venv/bin/python eval/run.py --check eval/runs/<실행 요약>.json`
- 릴리스 기록: `eval/releases/` · `docs/engine/releases.md`. 재는 순서와 기록 남기는 법은 `docs/engine/reproducibility.md`.
- 키 없이 도는 스스로 시험: `.venv/bin/python -m engine.contract --selftest`, `.venv/bin/python -m engine.flow2.flow --selftest`

## 폴더

| 위치 | 무엇 |
|---|---|
| `engine/` | 엔진(검색 → 질문 분석 → 조례 확정 → 조례 읽기 · 답 쓰기 → 구절 관문 → 질문 대조 → 출력). 자세히는 `engine/README.md` · `docs/engine/flow2.md` |
| `eval/` | 평가셋 · 점수 재는 도구 · 실험 설정(`eval/configs/`) |
| `docs/` | 기획 · 규칙(`docs/engine/scoring-rules.md`) · 결정 · 회의 |
| `demo/` | 시연 화면 |
