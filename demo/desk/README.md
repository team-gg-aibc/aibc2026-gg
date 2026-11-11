# 문의 답변 창구 시연 화면 (3판)

시민이 휴대폰에서 문의와 **민원 장소**를 함께 접수하면, 담당자 화면(서울 3D 지도가 화면 전체이고 문의 목록 · 답변 초안이 그 위에 떠 있음)에 들어오고, 서울시 조례 6종의 근거 조항이 붙은 **답변 초안**이 자동으로 만들어진다. 담당자가 고쳐 승인하면 시민 화면에 답이 간다. 시민이 지정한 접수 위치를 엔진에 넘기므로 근거 조항 · 소관 부서 · 처리 기관에 「이 위치 기준」이 붙고(처음 문의 50건은 글만 넘겨 붙지 않음), 담당자는 「위치 바로잡기」로 위치를 고쳐 다시 찾을 수 있다. 같은 글을 다른 장소에서 접수한 두 문의는 나란히 견줘 볼 수 있다(「같은 질문 · 다른 장소 · 다른 답」).

- 담당자 화면: `http://127.0.0.1:8770/` (→ `desk.html`)
- 시민 화면: `http://127.0.0.1:8770/citizen.html` (휴대폰 너비로 연다. `?scene=a` 시민 1 · 서울숲, `?scene=b` 시민 2 · 뚝섬한강공원)

**가상 표시**: 처음 상태의 문의 50건은 실제 글 30건(공개 게시판 글의 요지 18 · 기관 자주 묻는 질문 12, 이름 · 전화 · 차량번호 없음)과 가상 문의 20건(NVIDIA Nemotron-Personas-Korea, CC BY 4.0을 바탕으로 만든 14건 + 팀이 쓴 6건)이다. 목록 · 카드에 출처(「공개 게시판 글(요지)」 · 「기관 자주 묻는 질문」 · 「가상 문의」 · 「가상 문의(팀이 쓴 글)」)가 늘 보이고, 가상 문의 출처와 「지도의 문의 자리는 시연용으로 놓은 대략 위치」는 화면 오른쪽 아래 작은 회색 글씨로 늘 보인다. 담당자 화면은 여러 담당자에게 간 문의를 한 화면에 모아 보인 것이다.

## 띄우는 법 (레포 맨 위에서)

엔진까지 실제로 부르기 — 한 줄(엔진은 `engine/README.md` 「설치」의 가상 환경 파이썬, `.env`에 업스테이지 열쇠가 있어야 한다):

```bash
OPENBLAS_NUM_THREADS=1 ENGINE_CONFIG=eval/configs/pm-flow2-v7.json .venv/bin/python demo/desk/engine_trace.py & python3 demo/desk/server.py
```

엔진 없이 미리 받은 답으로만(영상 · 발표용) — 한 줄:

```bash
DESK_ENGINE=saved python3 demo/desk/server.py
```

그다음 브라우저에서 http://127.0.0.1:8770 을 연다. 지도 · 글꼴은 인터넷(CDN)에서 받는다. 끝낼 때는 Ctrl+C(엔진을 `&`로 띄웠으면 `kill %1`).

| 설정(환경 변수) | 값 | 뜻 |
|---|---|---|
| `DESK_ENGINE` | `live`(기본) · `saved` | 시민 문의 · 위치 바로잡기에서 엔진을 그때 부를지, 미리 받은 답만 쓸지 |
| `DESK_LOC` | `demo`(기본) · `real` | 시민 화면 「현재 위치」: 장면마다 미리 정한 자리(영상용, 오른쪽 아래에 「위치는 시연용으로 정한 자리입니다」) · 휴대폰 위치 기능. 시민 화면 주소의 `?loc=demo` · `?loc=real`이 이 값보다 앞선다 |
| `DESK_ENGINE_URL` | 기본 `http://127.0.0.1:8000` | 엔진 주소. 채점 서버 주소(`/ask`까지 적어도 됨)로 바꿔도 돈다 |
| `DESK_PORT` · `DESK_STATE` | 기본 8770 · `demo/desk/runtime/state.json` | 둘을 함께 띄울 때만 바꾼다 |

- 화면 밝기: 담당자 화면 맨 위 「밝은 화면 · 어두운 화면」 스위치 하나로 바꾼다(주소 `?tone=light` · `?tone=dark`도 됨, 고른 것은 브라우저에 남는다). 처음은 밝은 화면.
- 휴대폰 위치 기능(`real`)은 https 주소나 `localhost`에서만 열린다. 같은 와이파이의 휴대폰에서 `http://192.168.…`로 열면 위치를 묻지 않고 실패한다(그때 화면은 「지도에서 직접 지정」으로 이끈다). 영상은 `demo`로 찍는다.
- 「같은 질문 · 다른 장소」 장면의 오른쪽 카드(뚝섬한강공원 → 6종 밖 · 한강공원 조례)는 **장소 가리기(PR #82)** 엔진이 낸 답이다. main 엔진(`pm-flow2-v7.json`)은 한강공원 문의도 도시공원 조례로 답한다. 실제 호출로 이 장면을 보이려면 #82 브랜치에서 `ENGINE_CONFIG=eval/configs/82-place-scope.json`으로 엔진을 띄운다(그 밖에는 `DESK_ENGINE=saved`의 미리 받은 답이 그 엔진의 기록이다).

## 무엇이 실제 호출이고 무엇이 미리 받은 답인가

| 무엇 | 어떻게 도나 | 화면 표시 |
|---|---|---|
| 시민 화면에서 보낸 문의 | 화면 서버가 그때 엔진을 HTTP로 부른다(새 흐름 7판, 5~8초) | 카드 아래 「지금 만든 초안」 + 받은 시각 · 걸린 초 |
| 처음 상태의 문의 50건 | 미리 받은 답(`data/saved.json`). 모두 기록된 실제 실행 결과다: 새 흐름 7판 측정 기록(`_orch-tools/reports/문의세트/`의 real-out · virtual-7판-r1, 11-11) 36건, 같은 통로(`--save`)로 받은 새 흐름 7판 답 9건, 장소 가리기 실험판(#82)에 같은 통로로 넣은 기록 2건(P0 · P1), 「같은 장소, 다른 일」 장면 문의 3건(S01~S03)은 main 엔진에 같은 통로로 세 번씩 넣어 세 번 모두 같았던 기록의 첫 번째(11-12) | 「미리 만들어 둔 초안」(초안이 없는 6종 밖 · 조항 못 찾음은 「미리 받아 둔 결과」). #82 기록은 설명을 「시연을 위해 아직 반영 전인 「장소 가리기」 기능으로 미리 만들어 둔 초안입니다」로 바꿔 보인다. 두 시민 나란히 보기에도 칸마다 이 줄이 있다 |
| 위치 바로잡기 | 바로잡은 장소 이름을 글에 넣어 엔진을 다시 부른다(`saved`면 미리 받은 답에서 찾고, 없으면 「미리 받은 답이 없음」) | 바로잡기 전과 달라진 줄에 「바뀜」 |
| 엔진을 부르지 못함(꺼짐 · 90초 넘음 · 오류) | 카드가 「불러오지 못함」이 되고 「다시 시도」가 생긴다 | 맨 위 「초안 자동 작성 꺼짐」 |
| 고친 글 · 승인 · 위치 | 화면 서버에 저장된다(`runtime/state.json`, git에 넣지 않음). 승인 전 답은 시민 쪽 길(`/api/citizen/<번호>`)이 주지 않는다 | 시민 답의 「담당부서」는 「처리담당자(시연)」만(처리 기관 이름은 답 본문 안내에만). 「관련법령」은 국가법령정보센터 원문을 새 창으로 연다 |
| 엔진 안쪽 표시 | 엔진이 구절 · 답 글에 붙이는 「(※ 그 내용은 이 자료에 없다)」는 화면 서버가 지운다 | — |
| 소관 부서 · 처리 기관 | 엔진이 인용한 첫 조 · 항으로 `web/data/agencies.json`의 갈래를 찾고, 공원 · 주차장은 접수 위치의 「처리 장소」로 처리 기관을 한 번 더 좁힌다. 6종 밖 장소(한강공원)는 `data/places.json`의 「6종 밖」 줄 | 위치를 넘겨 받은 답(시민 접수 · 담당자 바로잡기)에만 「이 위치 기준」 |
| 원문 구절 · 링크 · 시행일 | 원문 구절은 엔진이 근거로 옮기고 엔진의 구절 관문이 원문과 글자를 대 본 것. 링크 · 시행일 · 조항 원문은 `engine/data/chunks_paragraph.json`에서 코드가 붙인다 | — |
| 초안의 문장 ↔ 조문 구절 짝 | 엔진 기록에 짝이 없어 화면이 글자 겹침(두 글자씩 묶어 겹치는 비율 0.2 이상)으로 짐작한다 | 「글자가 겹치는 정도로 짝지은 짐작입니다」 |
| 지난번에 승인한 답 | 같은 조항을 인용한 가장 최근 승인 답을 화면이 찾아 옆에 보인다(엔진은 승인한 답을 읽지 않는다) | 「이 답을 가져와 고치기」 |

## 접수 위치를 엔진에 넘기는 법

엔진은 글만 받는다. 그래서 화면 서버가 접수 위치를 글에 넣어 보낸다(엔진 코드는 고치지 않는다).

- 시민이 지정한 자리(또는 담당자가 바로잡은 자리)에서 0.9km 안에 아는 장소(`data/places.json`)가 있으면 그 이름을 쓴다. 주소 찾기 서비스는 쓰지 않는다.
- 글이 「이 공원에서 · 여기서 · 이곳에서 · 이 근처에서」로 시작하면 그 말을 「○○에서」로 바꾸고, 아니면 글 앞에 「○○에서 」를 붙인다. 글에 이미 그 이름이 있으면 그대로 보낸다.
- 예: 「이 공원에서 돗자리를 펴 놓고 …」 + 서울숲 → 「서울숲에서 돗자리를 펴 놓고 …」.
- 처음 상태의 50건은 기록한 글 그대로 보낸다(위치를 바로잡으면 위 규칙을 따른다).
- 서울 경계 밖의 위치는 서버가 받지 않는다(400).

## 화면 배치

- 담당자 화면: 서울 3D 지도(MapLibre + OpenFreeMap positron 바탕에 톤별로 다시 칠함)가 화면 전체. 맨 위 띠(기준 · 초안 자동 작성 상태 · 화면 밝기 · 칸 접기 · 시민 화면 열기), 왼쪽 「들어온 문의」(상태 칩 · 소관 부서 고르기), 오른쪽 「답변 초안」, 아래 「지도 표시」 범례. 지도는 서울 밖으로 나가지 않고, 가장 멀리 본 상태가 서울 전체가 칸에 가리지 않는 자리에 꽉 차는 정도다(창 크기 · 칸 접기가 바뀌면 다시 잰다). 공원 · 물은 면 색, 주차장은 「P」 점, 건물은 벽과 지붕을 다른 밝기로 칠한 3D, 고른 문의는 바닥 둥근 띠와 큰 번호 점.
- 시민 화면: 서울시 응답소 「시정일반 건의ㆍ질의」 작성 화면의 칸 · 순서 · 낱말. 「민원 장소」 줄은 시연에서 더한 칸(꼴은 서울톡 「현장민원 신청」). 위치를 고르는 지도는 평면(기울임 · 3D 건물 없음). 답이 오면 응답소 「공개 민원사례」 꼴로 보인다. 기관 이름 · 로고는 쓰지 않는다.
- 앞 판(2판) 화면 `web/index.html` · `app.js` · `style.css`와 그 문구 파일(`docs/content/A-01_답변화면.md` 등)은 지우지 않고 쓰지 않는다. 이 서버의 `/api`는 3판 꼴이라 앞 판 화면은 이 서버로 돌지 않는다.

## 화면 문구

- 원본은 `docs/content/A-01_답변창구-3판.md`(담당자 화면 · 카드) · `U-02_시민접수-3판.md`(시민 화면) 둘이다. 화면은 글자를 이 파일에서만 읽는다(`/api/text`). 파일을 고쳐 저장하면 새로고침 없이 1~2초 안에 화면이 바뀐다. `항목 | 보일 말` 표는 오른쪽만 고친다(왼쪽 이름으로 화면이 글을 찾는다).

## 파일

| 경로 | 내용 |
|---|---|
| `server.py` | 화면용 얇은 서버(표준 라이브러리만): 문의 저장 · 접수 위치 · 엔진 부르기 · 위치 바로잡기 · 고친 글과 승인 · 시민 쪽 답 · 처음 상태로 |
| `engine_trace.py` | 엔진 + 화면용 기록 길(`/ask/trace`). `/ask` · `/health`는 채점 서버 그대로 |
| `data/presets.json` | 처음 상태의 문의 50건(출처 · 접수 위치 · 승인 상태). 번호는 `_orch-tools/reports/문의세트/`의 번호, P0 · P1 · G01은 팀이 쓴 가상 문의. 승인 상태는 화면을 보이려고 정한 값 |
| `data/saved.json` | 미리 받은 엔진 답(글 → 응답 · 기록 · 만든 판). 다시 받기: 엔진을 띄운 뒤 `python3 demo/desk/server.py --save`(없는 글만, 모두 다시는 `--all`, 만든 판 이름은 `DESK_MADE_BY`) |
| `data/places.json` | 이름 있는 장소 23곳(대략 위치 · 구 · 처리 장소 · 6종 밖 조례)과 시연 장면 a · b의 자리 |
| `web/desk.html` · `desk.js` · `desk.css` | 담당자 화면 |
| `web/citizen.html` | 시민 화면 |
| `web/common.js` | 두 화면이 같이 쓰는 작은 도구(문구 꺼내기 · 서울 안 판정 · 가까운 장소) |
| `web/data/agencies.json` | 소관 부서 · 처리 기관 자료(조례 6종 × 문의 갈래 37). 원본: 소관 · 처리 기관 조사(2026-11-11, `_orch-tools/reports/소관-처리-기관/agencies.json`을 그대로 복사, 19:54 판) |
| `web/data/seoul.geojson` | 서울특별시 경계(지도에서 서울 밖을 가리고, 움직일 범위와 서울 안 판정에 씀). OpenStreetMap relation 2297418, Overpass API 2026-11-11 받음, 0.0004° 단순화 |

## 스스로 시험

```bash
python3 demo/desk/server.py --selftest
.venv/bin/python demo/desk/engine_trace.py --selftest
```

둘 다 엔진 · 인터넷 · 열쇠 없이 몇 초에 끝난다. 화면 눌러 보기 점검 기록은 `docs/test-log.md`.

## 데이터 출처 · 라이선스

- 가상 문의: NVIDIA Nemotron-Personas-Korea(CC BY 4.0)를 바탕으로 만듦
- 공개 문의 요지: 서울시설공단 주차 「시민의 소리」, 서울시 응답소 「공개 민원사례」, 기관 자주 묻는 질문(이름 · 연락처 · 번호 없음)
- 서울 경계: © OpenStreetMap contributors(ODbL)
- 한강공원 조례 · 소관 부서: 국가법령정보센터 「서울특별시 한강공원 보전 및 이용에 관한 기본 조례」 화면(https://www.law.go.kr/LSW/ordinInfoP.do?ordinSeq=2171805)
- 소관 부서 · 처리 기관(`web/data/agencies.json`): 국가법령정보센터 조례 · 「서울특별시 행정기구 설치 조례 시행규칙」(2026-09-11 시행), 서울시 · 서울시설공단 · 따릉이 · 미래한강본부 · 자치구 누리집의 공식 안내, 공개 답변 사례(2026-11-11 받음). 자료에 적힌 출처 주소 35곳:
  - https://www.law.go.kr/LSW/ordinInfoR.do
  - https://www.sisul.or.kr/open_content/main/introduce/found.jsp
  - https://www.sisul.or.kr/open_content/parking/
  - https://news.seoul.go.kr/traffic/archives/514606
  - https://www.sisul.or.kr/open_content/parking/parkingRefund/parkingRefundList.do?pgno=1063
  - https://www.law.go.kr/LSW/lsInfoR.do
  - https://www.sisul.or.kr/open_content/main/introduce/organization.jsp
  - https://news.seoul.go.kr/traffic/archives/26877
  - https://www.gwangjin.go.kr/portal/main/contents.do?menuNo=200622
  - https://news.seoul.go.kr/traffic/archives/1853
  - https://news.seoul.go.kr/traffic/archives/513697
  - https://www.junggu.seoul.kr/content.do?cmsid=14494
  - https://www.law.go.kr/LSW/ordinInfoP.do?ordinSeq=2147709
  - https://junggu.seoul.kr/content.do?cmsid=14424
  - https://news.seoul.go.kr/env/archives/563805
  - https://www.bikeseoul.com/app/use/moveUseMenuClauseInfo.do
  - https://www.bikeseoul.com/app/use/moveUseMenuInsurance.do
  - https://news.seoul.go.kr/traffic/archives/507121
  - https://news.seoul.go.kr/traffic/archives/512347
  - https://hangang.seoul.go.kr/www/contents/759.do?mid=509
  - https://news.seoul.go.kr/traffic/archives/507954
  - https://mediahub.seoul.go.kr/archives/977687
  - https://news.seoul.go.kr/welfare/archives/243465
  - https://mediahub.seoul.go.kr/archives/1024246
  - https://www.mapo.go.kr/site/health/content/health04030303
  - https://www.law.go.kr/LSW/flDownload.do?flSeq=144612525
  - https://news.seoul.go.kr/env/archives/category/animal-protection-news_c1/animal-welfare_c1/animal-registration
  - https://news.seoul.go.kr/env/archives/category/animal-protection-news_c1/animal-welfare_c1/animal-rescue
  - https://news.seoul.go.kr/env/archives/216413
  - https://news.seoul.go.kr/env/archives/559051
  - https://mediahub.seoul.go.kr/archives/2014727
  - https://news.seoul.go.kr/gov/archives/574771
  - https://news.seoul.go.kr/traffic/archives/518138
  - https://mediahub.seoul.go.kr/archives/2002479
  - https://mediahub.seoul.go.kr/archives/2017598
- 지도: © OpenFreeMap · © OpenMapTiles · © OpenStreetMap contributors(화면 오른쪽 아래 표시), MapLibre GL JS(BSD-3-Clause), 글꼴 Pretendard(OFL)
- 조례: 국가법령정보센터 자치법규 원문(2026-10-01 시행본 기준)
