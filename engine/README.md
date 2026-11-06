# engine — 서울특별시 조례 6종 질의응답 엔진

스타터 킷(커밋 `8866d0e`: 받은 그대로 + 없어진 groundedness-check 대신 solar-pro4 판정)을 옮겨 단계별 파일로 나눈 판이다. 동작은 킷과 같다. 이 판이 모든 실험의 **출발 판**이고, 실험은 `eval/configs/`의 설정 파일로 스위치를 켜서 잰다(규칙은 `docs/engine/reproducibility.md`).

## 설치 (처음 한 번)

1. **파이썬 3.10~3.13**(3.12를 권한다). `python3 --version`(윈도우는 `py -0`)으로 판을 본다. 맥에 기본으로 깔린 3.9와 Homebrew 최신 3.14로는 설치가 막힌다. 3.9는 고정한 패키지 판을 못 깔고, 3.14는 고정한 numpy 2.2.6의 설치 파일이 없다. 그럴 때는 python.org에서 3.12를 깔고 아래 `python3` 자리에 `python3.12`(윈도우는 `py -3.12`)를 쓴다.
2. 레포를 받고 가상 환경을 만든다(설치는 1분 안쪽):

```bash
git clone https://github.com/team-gg-aibc/aibc2026-gg.git
cd aibc2026-gg
python3 -m venv .venv
.venv/bin/pip install -r engine/requirements.txt
```

3. **이 뒤의 명령은 모두 가상 환경의 파이썬으로 돌린다.** 맥은 `.venv/bin/python`, 윈도우는 `.venv\Scripts\python`이다. 이 문서 · 재현 규칙 · 이슈에 `python3 eval/…`로 적힌 명령도 이것으로 돌린다. 그냥 `python3`로 돌리면 `No module named 'requests'`가 난다.
4. 키: `.env.example`을 `.env`로 복사하고(`cp .env.example .env`) `UPSTAGE_API_KEY=` 뒤에 자기 업스테이지 콘솔 키를 붙인다(크레딧은 각자 신청, 결정 10-26). 엔진은 이 칸 하나만 쓴다. git worktree에서 돌리면 원래 레포 폴더의 `.env`도 읽는다. **키가 없어도 키워드 검색은 돈다.** 키 값은 어디에도 출력하지 않는다.

## 처음 해 보기 (5분, 약 2센트)

처음 받은 컴퓨터에서 위에서부터 차례로 돌린다. 맥 기준이고, 윈도우는 아래 「윈도우에서 다른 것」 표대로 바꾼다.

```bash
.venv/bin/python eval/run.py --check eval/runs/20261106-201622-baseline-dev.json
.venv/bin/python -m engine.pipeline "경차 주차요금 할인돼요?"
.venv/bin/python eval/run.py --config eval/configs/baseline.json --split dev --sample 20 --repeat 2
.venv/bin/python eval/compare.py <두 번째 실행 이름> --base <첫 번째 실행 이름>
.venv/bin/python eval/board.py --tree
open docs/engine/tree.html
```

| 단계 | 되면 이렇게 보인다 |
|---|---|
| ① 재현 점검 (키 없이, 2초) | 마지막 줄이 `결론: ✅ 같은 결과`. 그 위 점검 표에서 이름에 「참고」가 붙은 줄과 「파이썬」 줄은 「다름」이어도 된다 |
| ② 한 문항 (키 필요, 6초) | 답 · 인용 · 원문 주소 · 시행일 4칸과 판단 기록 |
| ③ dev 20문항 두 번 (키 필요, 45초쯤, 2센트쯤) | 실행 이름 두 개(`…-baseline-dev-n20-r1` · `…-r2`)와 「흔들림」 폭. 20문항은 맛보기라 폭이 20점을 넘기도 한다. 채택 판단은 dev 전체로 한다(재현 규칙 3절) |
| ④ 비교 | `docs/engine/compare/<두 번째 실행 이름>.md`. 설정과 코드가 같은 두 실행이라 「모두 흔들림」 경고가 붙는다 |
| ⑤ 리더보드 · 나무 | `docs/engine/leaderboard.md` · `experiments.md` · `tree.html`이 바뀌고 나무 화면이 열린다. gh가 없으면 경고 한 줄 뒤 이슈 · PR 상태 없이 그린다 |

- 표본은 12문항 이상으로 뽑는다. 10문항 이하면 함정 문항이 빠져 가중 점수가 None이 된다.
- 연습한 결과는 올리지 않는다. 끝나면 `git restore docs/engine` 뒤 `git clean -f eval/runs docs/engine/compare`로 되돌린다. 처음 받은 폴더라서 지워지는 것은 연습 결과뿐이다(아직 커밋 안 한 실험 결과가 있는 폴더에서는 쓰지 않는다).

## 윈도우에서 다른 것

PowerShell 기준이다.

| 맥 | 윈도우 |
|---|---|
| `python3 -m venv .venv` | `py -3.12 -m venv .venv` |
| `.venv/bin/python` · `.venv/bin/pip` | `.venv\Scripts\python` · `.venv\Scripts\pip` |
| `cp .env.example .env` | `copy .env.example .env` 뒤 `notepad .env` |
| `open docs/engine/tree.html` | `start docs\engine\tree.html` |
| `ENGINE_CONFIG=eval/configs/baseline.json .venv/bin/uvicorn …` | `$env:ENGINE_CONFIG="eval/configs/baseline.json"` 뒤 `.venv\Scripts\uvicorn …` |
| `명령1 && 명령2` | 두 줄로 나눠 친다(윈도우에 기본으로 깔린 PowerShell 5.1은 `&&`를 모른다) |

- 파이썬은 python.org 설치 파일로 깔고 「Add python.exe to PATH」에 체크한다. `py -0`에 3.12가 보이면 된다.
- 터미널을 열 때마다 먼저 `$env:PYTHONUTF8=1`(cmd는 `set PYTHONUTF8=1`)을 친다. 한국어 윈도우는 글자를 cp949로 다뤄서, 결과를 파일로 넘기면 ✅ 같은 글자에서 멈추고 다른 프로그램의 한글 출력을 읽다 멈출 수 있다. 매번 치기 싫으면 `setx PYTHONUTF8 1`을 한 번 치고 터미널을 다시 연다.
- 가상 환경을 켜는 `Activate.ps1`은 실행 정책에 막힐 수 있다. 켜지 말고 위처럼 `.venv\Scripts\python`을 바로 부른다.
- 줄 끝: 레포의 `.gitattributes`가 윈도우에서도 줄 끝을 LF로 받게 한다. 이 파일이 들어오기 전에 윈도우에서 clone한 폴더는 ① 재현 점검에서 「엔진 코드 지문」 · 「색인 지문」이 「다름」으로 나온다. 그러면 새 폴더에 다시 clone한다.

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
| 내 컴퓨터가 팀과 같은 결과를 내나 (키 없이, 2초) | `python3 eval/run.py --check eval/runs/20261106-201622-baseline-dev.json` (재현 규칙 1절) |
| 실험 하나 재기 | 설정 파일 `eval/configs/<이슈>-<이름>.json`을 만들고 `python3 eval/run.py --config <설정 파일>` |
| 리더보드 · 실험 기록 다시 만들기 | `python3 eval/board.py` → [리더보드](../docs/engine/leaderboard.md) · [실험 기록](../docs/engine/experiments.md) |
| 탐색 모드(1~3주기: 90초 조건 없이, 문항당 300초까지) | 설정에 `"explore": true, "timeout_sec": 300` (바탕: `eval/configs/explore.json`) |
| 문항마다 단계별 입력 · 프롬프트 · 모델 출력 · 시간 · 토큰 보기 | 끝까지 잰 실행이 `eval/results/<실행>.html`을 만든다. 문항 하나는 `python3 eval/trajectory.py <실행> <문항 id>` |
| 병합 전 브랜치들의 결과까지 한 표로 (배분일) | `git fetch origin` 뒤 `python3 eval/board.py --from-branches "origin/*"` (화면에만. 큰따옴표는 윈도우 cmd에서도 된다) |
| 가설이 실험 · 배운 점을 거쳐 다음 가설로 가는 나무 (배분일) | `python3 eval/board.py --tree` → `docs/engine/tree.html`. **로컬에서 보기: `open docs/engine/tree.html`**(윈도우는 `start docs\engine\tree.html`. 데이터가 안에 있어 인터넷 없이 열리고, 화면 폭에 맞춰 움직인다). 디스코드 그림용 정적 보기는 주소 뒤에 `?snapshot=1`(모든 가지 펼침, 폭 1200, 옆 칸 없음) |
| 기준과 문항마다 견주기 (버린 실험도) | `python3 eval/compare.py <실행>` → `docs/engine/compare/<실행>.md` |
| 규칙(실험 하나 = 설정 파일 하나, 고정한 것 · 흔들리는 것, 기록 · 비교 · 색인 바꾸기 · 크레딧) | [재현 규칙](../docs/engine/reproducibility.md) |

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
