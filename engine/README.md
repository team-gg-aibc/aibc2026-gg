# engine — 서울특별시 조례 6종 질의응답 엔진

스타터 킷(커밋 `8866d0e`: 받은 그대로 + 없어진 groundedness-check 대신 solar-pro4 판정)을 옮겨 단계별 파일로 나눈 판이다. 동작은 킷과 같다. 이 판이 모든 실험의 **출발 판**이고, 실험은 `eval/configs/`의 설정 파일로 스위치를 켜서 잰다(규칙은 `docs/engine/reproducibility.md`).

## 설치

파이썬 3.10~3.13. 레포 맨 위 폴더에서:

```bash
python3 -m venv .venv && .venv/bin/pip install -r engine/requirements.txt
```

키는 레포 맨 위 `.env`의 `UPSTAGE_API_KEY` 하나다(`.env.example`을 복사). git worktree에서 돌리면 원래 레포 폴더의 `.env`도 읽는다. **키가 없어도 키워드 검색은 돈다.** 키 값은 어디에도 출력하지 않는다.

## 돌리기

| 하려는 것 | 명령 (레포 맨 위 폴더에서) |
|---|---|
| 한 문항 돌려 보기 (응답 + 판단 기록) | `.venv/bin/python -m engine.pipeline "경차 주차요금 할인돼요?"` |
| 설정 파일로 한 문항 | `.venv/bin/python -m engine.pipeline "질문" eval/configs/baseline.json` |
| 채점 API 서버 | `ENGINE_CONFIG=eval/configs/baseline.json .venv/bin/uvicorn engine.server:app --port 8000` |
| 색인 다시 만들기 (조각 글을 바꿨을 때) | `.venv/bin/python -m engine.build_index` (키가 있어야 임베딩까지 만든다) |
| 별표 다시 읽기 (거의 안 씀) | `.venv/bin/python -m engine.parse_annex` (키 필요, Document Parse 비용) |

파일을 직접(`python3 engine/server.py`) 돌리지 말고 `-m engine.…`으로 돌린다. 엔진 파일들이 패키지 안에서 서로를 부른다.

## 실험 · 점수 · 리더보드

| 하려는 것 | 명령 · 문서 |
|---|---|
| 내 컴퓨터가 팀과 같은 결과를 내나 (키 없이, 2초) | `python3 eval/run.py --check eval/runs/<키워드 dev 실행>.json` (파일 이름은 재현 규칙 1절) |
| 실험 하나 재기 | 설정 파일 `eval/configs/<이슈>-<이름>.json`을 만들고 `python3 eval/run.py --config <설정 파일>` |
| 리더보드 · 실험 기록 다시 만들기 | `python3 eval/board.py` → [리더보드](../docs/engine/leaderboard.md) · [실험 기록](../docs/engine/experiments.md) |
| 탐색 모드(1~3주기: 90초 조건 없이, 문항당 300초까지) | 설정에 `"explore": true, "timeout_sec": 300` (바탕: `eval/configs/explore.json`) |
| 문항마다 단계별 입력 · 프롬프트 · 모델 출력 · 시간 · 토큰 보기 | 끝까지 잰 실행이 `eval/results/<실행>.html`을 만든다. 문항 하나는 `python3 eval/trajectory.py <실행> <문항 id>` |
| 병합 전 브랜치들의 결과까지 한 표로 (배분일) | `git fetch origin` 뒤 `python3 eval/board.py --from-branches 'origin/*'` (화면에만) |
| 가설이 실험 · 배운 점을 거쳐 다음 가설로 가는 나무 (배분일) | `python3 eval/board.py --tree` → `docs/engine/tree.html`. **로컬에서 보기: `open docs/engine/tree.html`**(데이터가 안에 있어 인터넷 없이 열리고, 화면 폭에 맞춰 움직인다). 디스코드 그림용 정적 보기는 주소 뒤에 `?snapshot=1`(모든 가지 펼침, 폭 1200, 옆 칸 없음) |
| 기준과 문항마다 견주기 (버린 실험도) | `python3 eval/compare.py <실행>` → `docs/engine/compare/<실행>.md` |
| 규칙(실험 하나 = 설정 파일 하나, 고정한 것 · 흔들리는 것, 기록 · 비교 · 색인 바꾸기 · 크레딧) | [재현 규칙](../docs/engine/reproducibility.md) |

## 릴리스 만들기

제출하는 것은 실험 하나가 아니라 **채택된 실험을 모두 켠 판**이다. 그 판의 설정이 릴리스 설정 `eval/configs/release.json`이고, 채점 서버는 이 파일을 읽는다(`ENGINE_CONFIG=eval/configs/release.json`). 배분일에 PM 쪽이 만들어 PR 「릴리스 N주기」로 넣는다. 기록: [릴리스](../docs/engine/releases.md).

| 하려는 것 | 명령 |
|---|---|
| 배분일 릴리스 (막 끝난 주기 N, 11/9면 1) | `python3 eval/release.py --cycle N` → 설정이 바뀌었으면 `eval/configs/release.json`을 쓰고 멈춘다 → 그 파일을 커밋 → 같은 명령을 다시 → API 연기 시험 · dev 전체 두 번(실행 이름 `release-cN`) · 계약 점검 · 기록(`eval/releases/rc-cN.json` · `docs/engine/releases.md` · 리더보드). 키 필요, 기록 비용 약 $0.8 · 25분 |
| 실행 요약에 「채택」이 없는 실험도 넣기 | 위 명령에 `--adopt eval/configs/<실험>.json` (여러 번 줄 수 있다) |
| 릴리스 설정이 채택 실험 · 마지막 기록과 맞나 (키 없이, 2초) | `python3 eval/release.py --check` |

- **들어가는 것**: 실행 요약(`eval/runs/*.json`)의 `conclusion`이 「채택」으로 시작하는 실험의 스위치다(그 주기까지). 합친 판에서 빼려면 그 실행의 `conclusion`을 바꾸고 다시 만든다. 같은 스위치를 다른 값으로 켠 실험이 둘이면 멈춘다(동규가 고른다). 탐색 모드 칸(`explore`, 탐색 실험의 `timeout_sec` 300)은 넣지 않는다. 릴리스는 늘 대회 조건(75초에 확인 불가, 90초 넘으면 0점)으로 잰다.
- **따로 재는 까닭**: 실험끼리 서로 영향을 줄 수 있다. 예를 들어 후보를 넓히면 판정이 거절하는 문항도 바뀐다. 그래서 합친 판을 dev 전체로 두 번 따로 잰다.
- **판정**: 계약 위반(네 칸 · 칸 자료형 · 확인 불가 꼴 · 인용이 색인 라벨이고 킷 채점식으로 읽히나 · 링크 · 시행일 꼴)이 0이고, 연기 시험(킷 예시 11 · 함정 3 · 빈 질문 · 아주 긴 질문 · 지시문 섞인 질문을 동시 10으로 보내 모두 HTTP 200 · 네 칸 · 90초 안, `/health` 설정 지문 같음)을 지나면 「통과」다. 지연은 1~3주기에 기록만 하고, 4~5주기부터 95%가 30초를 넘거나 가장 느린 것이 90초를 넘으면 막는다.
- 통과한 릴리스는 PR 「릴리스 N주기」가 병합된 main 커밋에 태그 `rc-cN`을 붙인다(동규 승인 뒤). 11/17 동결 판단 날의 릴리스(`rc-c5`)가 동결 후보이고, 11/18에 동규가 그 판으로 holdout을 한 번 잰다(재현 규칙 10절).
- 실험이 마무리되면 마지막으로 통과한 판(태그)을 채점 서버(#31)에 올린다. 서버는 `ENGINE_CONFIG=eval/configs/release.json`으로 그 판을 읽는다(레포 맨 위 폴더에서 띄운다. 설정 경로가 상대 경로라서). 올린 판이 맞는지는 `/health`의 `settings`가 [릴리스 기록](../docs/engine/releases.md)의 「설정 지문」과 같은지로 본다.
- 릴리스 설정 · 기록 · `releases.md`는 손으로 고치지 않는다. 문서만 다시 쓰려면 `python3 eval/release.py --docs`.

## 흐름과 파일

질문 받기 → 검색 → 근거 고르기 · 답 쓰기 → 판정 → 출력. 단계 하나 = 함수 하나이고(`pipeline.STAGES`), 경계는 LangGraph 노드와 같다. 새 단계는 `STAGES`에 끼운다.

| 파일 | 하는 일 | 주로 고치는 사람 |
|---|---|---|
| `config.py` | 스위치 · 설정(DEFAULTS = 출발 판), 설정 파일 읽기, 키 찾기. 이슈마다 자기 절(`# ---- #이슈 …`)에만 줄을 더한다 | 모두 (자기 절만) |
| `upstage.py` | 업스테이지 호출 한 곳, 429 재시도, 토큰 · 비용 기록(`PRICES`) | 동욱 (#22) |
| `retrieve.py` | 임베딩 + 키워드(BM25) 혼합 검색, 색인 지문 | 건영 (#23 · #26 · #28) |
| `answer.py` | 근거 고르기 · 답 쓰기(Solar 한 번), 프롬프트 판(`PROMPTS`). 계획 문서의 `select.py`다. `select`는 파이썬 표준 모듈 이름이라 겹치지 않게 했다 | 종희 (#24 · #27 · #29) |
| `verify.py` | 확인 불가 판정: ① 1위 의미 점수 문턱 ② solar-pro4 판정, 프롬프트 판(`PROMPTS`) | 동욱 (#30) |
| `contract.py` | 4칸 응답 꼴, 확인 불가 꼴 | 동욱 (#22) |
| `pipeline.py` | 흐름과 판단 기록 | 동규 (바꿀 땐 PM 리뷰) |
| `server.py` | 채점 API (`POST /ask`, `GET /health`) | 동욱 (#31) |
| `build_index.py` · `parse_annex.py` | 조각 · 임베딩 만들기, 별표 읽기 | 건영 (#23) |
| `data/` | 원문(`ordinances.json`), 별표 읽은 결과(`annex/`), 조각(`chunks_paragraph.json`), 조각 임베딩(`vectors_paragraph.npy`), 둘의 짝 지문(`index_paragraph.json`) | 색인을 바꾸는 이슈 |

## 판단 기록

`pipeline.answer(질문, 설정)`은 `(응답, 판단 기록)`을 돌려준다. 서버는 응답만 내보낸다.

| 칸 | 뜻 |
|---|---|
| `reason` | 확인 불가를 낸 까닭: `점수 낮음`(검증 ①) · `found 거짓` · `근거 번호 없음` · `판정 거절`(검증 ②) · `오류`. 답했으면 `null` |
| `error` | 오류 종류. 바깥 서비스 오류는 종류와 상태 번호만 남긴다(메시지에 키 일부가 섞일 수 있어서) |
| `retrieval` · `candidates` | 실제로 쓴 검색(`hybrid` · `keyword`)과 후보 라벨 · 점수(혼합 · 키워드 · 의미) |
| `evidence_ids` · `draft` · `verdict` | 모델이 고른 근거 번호, 판정 전 답, 판정 |
| `steps` · `sec` · `calls` | 단계별 · 전체 걸린 초, 업스테이지 호출마다 모델 · 토큰 · 초 |
| `settings` · `switches` · `models` · `prompts` · `index` | 설정 지문, 출발 판과 다른 스위치, 모델 이름, 프롬프트 판, 색인 지문 |

## 데이터 출처

- 킷이 받은 서울특별시 조례 6종 10/1 기준 판(판 번호 고정). 팀 레포 `eval/source/`와 견줘 조문 · 별표 글자 차이가 공백을 빼고 0이다(10-27 확인, `eval/README.md`). **조례는 다시 받지 않는다**(대회는 10/1 시행본 고정).
- 별표는 킷이 Document Parse로 읽은 결과(`data/annex/`, 10-27)를 쓴다. 원본 hwp는 `data/annex_files/`에 받게 되며 git에 올리지 않는다.
- 조각 528개와 임베딩(solar-embedding-2-passage, 1024차원)은 킷이 10-27에 만든 것을 그대로 커밋했다. 모두가 같은 임베딩을 쓰게 하려는 것이다(각자 만들면 실행마다 조금씩 달라진다). 키 없이 `build_index`를 다시 돌려도 조각 파일은 글자 하나 다르지 않게 나온다.

## 킷과 다른 곳

동작을 바꾸지 않는 것만 바꿨다.

- 설정을 환경 변수(`CHUNK_UNIT` · `USE_VERIFY` 등) 대신 설정 파일로 받는다. 단계 함수가 설정을 인자로 받는다.
- 점수가 똑같은 후보의 순서를 조각 번호 순으로 고정했다(`np.argsort(..., kind="stable")`). 킷의 정렬은 같은 점수의 순서가 컴퓨터 · numpy 판에 따라 달라질 수 있다. 1,161문항(실제 비슷한 세트 · 극한 세트 · 킷 예시)을 키 없이 견주면 top-6가 달라지는 문항은 극한 세트의 2문항(smoking-X002 · X027, 6위가 같은 점수)뿐이고, dev 숫자는 같다.
- 업스테이지 호출마다 토큰을 기록하고, 판단 기록을 돌려준다.
- 조각과 임베딩이 짝이 아니면(조각 글만 바꾸고 임베딩을 안 만든 경우) 혼합 검색을 멈춘다. 킷은 조용히 엇갈린 임베딩을 썼다.
- `.env`를 python-dotenv 없이 읽는다(없으면 조용히 키워드 검색만 도는 일을 막으려고).
