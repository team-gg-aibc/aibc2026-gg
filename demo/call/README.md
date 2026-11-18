# 통화로 위치 좁히기 (시연 화면)

120 상담사가 민원 통화 중에 보는 화면 하나다. 시민의 말이 들어올 때마다 지도 위의 후보 범위가 줄고, 다음에 물을 질문이 하나 뜬다.
위치가 정해지면 접수 카드에 넘길 곳과 찾아가는 말 · 번지수가 붙고, 조례 6종에 걸리는 일이면 엔진의 추천 답과 근거 조항이 같이 뜬다.
서비스 안에서 부르는 모델은 업스테이지 것뿐이다(단서 읽기 · 물음 간추리기 = Solar, 조례 답 = `engine/`).

- 통화는 팀이 쓴 가상 통화다. 실제 민원 · 실제 사람이 아니다. 접수 담당자는 이름표 「상담사 A」.
- 화면에 보이는 말과 통화 대본은 모두 `docs/content/A-05_통화위치좁히기.md`에 있다. 문구는 그 파일만 고친다.

## 띄우는 법 (레포 맨 위에서)

파이썬 3.10 이상과 numpy가 있으면 된다(엔진 가상 환경 `.venv`를 그대로 써도 된다).

```bash
OPENBLAS_NUM_THREADS=1 CALL_MODE=saved python3 demo/call/server.py
```

`http://127.0.0.1:8772` 을 연다. 저장된 답 방식이라 열쇠 · 엔진 호출 없이 돈다. 대본 장면의 Solar 읽기와 엔진 답은 `data/saved.json`에 받아 둔 실제 응답이다.

실제 호출(엔진 가상 환경, `.env`에 `UPSTAGE_API_KEY`):

```bash
OPENBLAS_NUM_THREADS=1 ENGINE_CONFIG=eval/configs/release.json .venv/bin/python demo/call/server.py
```

화면은 인터넷에서 지도 타일(OpenFreeMap), 지도 라이브러리(MapLibre, unpkg), 글꼴(Pretendard · 도현체, jsDelivr · Google Fonts)을 받는다. 서버는 바깥에서 받는 것이 없다.

| 환경 변수 | 뜻 | 기본 |
|---|---|---|
| `CALL_MODE` | `saved` 저장된 답 · `code` 모델 없이 코드만 · 그 밖은 실제 호출 | 실제 호출 |
| `CALL_PORT` | 포트 | 8772 |
| `CALL_MODEL` | 단서 읽기 · 물음 간추리기에 쓰는 Solar 모델 | solar-pro4 |
| `CALL_REPLAY_SEC` | 저장된 답 방식에서 엔진 답을 보이기 전 기다리는 최대 초 | 2 |
| `CALL_NO_ENGINE` | 값이 있으면 엔진을 부르지 않는다(가상 통화로 잴 때) | 없음 |
| `CALL_ON` · `CALL_OFF` | 질문 고르기 규칙을 켜고 끈다(견주어 잴 때만). 기본값은 `locate.py`의 `DEFAULT_ON` | 비움 |
| `CALL_SHOPS` · `CALL_NODES` · `CALL_TOILETS` · `CALL_PARKNAMES` · `CALL_RAMPS` | `0`이면 그 지명 자료를 읽지 않는다(넣기 전과 견줄 때) | 읽음 |
| `CALL_ALIAS_FILE` | 상담사가 저장한 별명 파일 | `data/aliases_local.json`(git 무시) |
| `CALL_TRIAL_FILE` | 사람이 해 보는 시험의 기록 파일 | `data/trials_local.jsonl`(git 무시) |

## 장면 주소

| 주소 | 장면 |
|---|---|
| `/?auto=cat_street` | 주택가 골목의 다친 고양이 → 번지수로 넘기기 (상도동, 조례 6종 안) |
| `/?auto=cat_park` | 공원 안의 다친 고양이 → 번지 없는 자리 (서울숲, 조례 6종 안) |
| `/?auto=roadkill` | 운전하다 본 고양이 사체 → 자동차전용도로 구간 (강변북로, 조례 6종 밖) |
| `/?auto=stray` · `vendor` · `pothole` | 화면 장면 단추에는 없는 대본(공원 유기견 · 공원 노점 · 길 파손) |

- `auto`를 주면 열자마자 대본을 재생한다. 그 밖의 주소 옵션: `?speed=3` 빠르게 · `?stop=<질문 이름>` 그 질문에서 멈춤 · `?tone=light` 밝은 화면.
- 「직접 통화」(키보드 `0`)에서는 서울의 아무 곳이나 글로 넣어 볼 수 있다. 예: 「마포구인데요, 스타벅스 앞 가로등이 꺼져 있어요」 → 「합정역 근처예요」.
- `?voice=1`(또는 「목소리」 단추)은 영상용이다. `web/voice/<장면>-<번호>.mp3`가 있으면 틀고, 없으면 소리 없이 글 길이만큼 기다린다. 음성 파일은 레포에 없다. 화면은 파일을 틀기만 하고 모델을 부르지 않는다. 브라우저 받아쓰기 · 읽어 주기는 쓰지 않는다.

## 점검

```bash
OPENBLAS_NUM_THREADS=1 python3 demo/call/check.py      # 저장된 답 서버를 띄워 대본 장면 · 단추만 · 대본에 없는 곳 · 별명 저장을 끝까지. 실패하면 종료 코드 1
python3 demo/call/locate.py                            # 위치 계산 스스로 시험
python3 demo/call/tools/sim_calls.py                   # 가상 통화 30통으로 횟수 · 확정한 점의 오차 · 넘길 곳 재기(코드만)
```

`check.py`는 포트 8779를 쓴다(`CALL_CHECK_PORT`로 바꿈). 열쇠 · 인터넷이 필요 없다.

## 어떻게 도나

한 번의 말이 들어오면 두 걸음으로 읽는다. 질문은 ①만으로 바로 뜬다.

| 걸음 | 누가 | 하는 일 |
|---|---|---|
| ① | 코드 (`gaz.py` · `locate.py`) | 지명 표에서 이름 찾기, 이름 뒤의 말로 「지났다 · 못 미쳤다 · 앞 · 근처 · 안 · 밖」 가리기, 후보 자리마다 가능성 고쳐 셈하기, 다음 질문 고르기 (수십 ms) |
| ② | Solar (`engine/upstage.py`를 거친다) | ①이 찾은 이름 후보와 질문의 보기를 받아 정해진 꼴(JSON)로 다시 읽기. 꼴이 틀리면 버리고 ①로 간다 (1~3초) |
| 뒤에서 | Solar → 엔진 | 일과 장소가 정해지면 통화를 한두 문장의 물음으로 간추려 엔진(`engine.pipeline.answer`)에 묻는다 (7~10초) |

- 넘길 곳은 `data/routes.json`의 표(일의 종류 × 장소 종류)로 정한다. 갈래마다 「확인」(공식 안내에서 봄) · 「추측」 표시가 있다.
- 서버는 통화 상태를 들고 있지 않다. 화면이 상태를 들고 있다가 `/api/turn`에 통째로 보낸다.

## 자료 출처

| 파일 | 출처 · 조건 |
|---|---|
| `data/seoul/places.tsv.gz` · `roads.json.gz` · `areas.json` · `park_things.tsv.gz` · `park_names.tsv.gz` · `ramps.tsv.gz` | © OpenStreetMap 기여자, ODbL 1.0 (BBBike 서울 추출본, 2026-11-08판). 줄인 표도 ODbL을 따른다(출처 표시 · 같은 조건) |
| `data/seoul/shops.tsv.gz` · `addrs.tsv.gz` | 공공데이터포털 15083033 「소상공인시장진흥공단_상가(상권)정보_20260930」, 이용허락범위 제한 없음 |
| `data/seoul/lamps.tsv.gz` | 공공데이터포털 가로등 위치 정보(15107934 서울특별시 · 15070592 광진구 · 15107876 영등포구 · 15062578 서대문구), 이용허락범위 제한 없음 |
| `data/seoul/park_toilets.tsv.gz` | 서울 열린데이터광장 OA-22586 서울시 공중화장실 위치정보, 공공누리 제1유형(출처 표시) |
| `data/seoul/road_nodes.tsv.gz` | 국가교통정보센터 표준노드링크(2026-11-11판) |
| `data/extra_places.json` | 지도 자료에 이름이 없어 팀이 손으로 더한 시연 장소 |
| `data/saved.json` | 대본 장면을 실제 호출로 돌려 받아 둔 Solar · 엔진 응답 |
| 지도 타일(화면) | © OpenFreeMap · © OpenMapTiles · © OpenStreetMap 기여자 (화면 아래에 표시) |

자료를 다시 만드는 스크립트는 `tools/osm_fetch.py` · `tools/build_*.py`다. 원본은 레포 밖 빈 폴더에 받고 레포에는 줄인 표만 둔다.

## 영상 제작용 도구 (서비스가 아님)

`tools/record_video.py`는 시연 영상을 만들 때만 손으로 돌린다. 대본 재생을 창 없는 크로미움으로 녹화하고(소리 끔) `web/voice/`의 음성 파일을 얹는다(playwright · ffmpeg, 모델을 부르지 않는다). `server.py` · `web/`은 이 도구를 부르지도 가져오지도 않는다. 음성 파일과 그것을 만드는 도구는 레포에 넣지 않는다.

그 밖의 `tools/`: `sim_calls.py` · `defect_set.py`(가상 통화로 재기), `human_test.py`(사람이 해 보는 시험 카드 · 채점, 결과는 레포 밖에 둔다).

## 알려진 한계

- 지도 자료(오픈스트리트맵 + 상가정보)에 없는 가게 · 건물은 못 알아듣는다. 자동차전용도로의 이정표 · 출구 번호도 없다.
- 넘길 곳 표 29갈래 가운데 공식 안내에서 확인한 것은 10갈래다. 나머지는 「추측」이고, 부서 이름은 구마다 다를 수 있다.
- 「바로 앞」 18m · 「근처」 100m 같은 거리 폭과 끝내는 기준은 실제 통화로 맞춘 값이 아니다(`locate.py` 맨 위).
- 소리가 같은 이름이 둘 이상인 길 · 역 · 다리는 다른 단서로 갈리기 전에는 확정하지 않는다.
- 통화 글은 콜센터의 받아 적기 도구가 만든 글을 넘겨받는다고 본다. 그 도구와 이어 본 적은 없고, 시연에서는 대본 재생 · 직접 입력으로 넣는다.
- 실제 접수 · 전달은 하지 않는다. 접수 카드의 진행 상태는 화면 안에서만 바뀐다.
