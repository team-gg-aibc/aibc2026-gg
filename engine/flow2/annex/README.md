# flow2 별표 (Document Parse enhanced HTML)

flow2(PM 별도 실험)만 쓰는 별표다. 킷 별표(`engine/data/annex/`, 건영 `parse_annex.py`)는 고치지 않았다. 펼치는 코드는 `engine/flow2/annex.py`다.

## 어떻게 읽었나 (2026-11-10, 동규 kd 키)

- 원본: 킷 사본 `starter-kit/data/annex_files/`의 hwp 10개. 킷이 10-27에 법제처에서 받은 것과 같은 파일이다.
- 요청: `POST https://api.upstage.ai/v1/document-digitization`
  - `model=document-parse`(응답 모델 `document-parse-260930`)
  - `mode=enhanced`
  - `output_formats=["html","markdown"]`
  - `coordinates=false`
- 저장: 응답의 `content.html`을 그대로 `<일련번호>_<별표>.html`에 둔다.
- 다시 부르는 코드는 레포에 두지 않았다. 바깥 서비스 호출은 `engine/upstage.py` 한 곳에서만 한다는 AGENTS.md 규칙 때문이다. `upstage.document_parse`에 `mode` 칸이 생기면 그것으로 다시 읽는다.
- 쪽수 17쪽, 비용 $0.51(쪽당 $0.03).

## 왜 이것을 골랐나 (세 가지 비교, 같은 날)

| 도구 | 비용(쪽당) | 공원입장료(도시공원 별표 1) | 주차요금표(주차장 별표 1) |
|---|---|---|---|
| A. 킷 DP standard 마크다운(10-27) | $0.01 | 「어 른 1회 청소년 1회 어린이 1회」와 금액 세 줄이 칸 하나로 뭉침 | 칸 살아 있음 |
| B. DP standard HTML | $0.01 | 칸 합치기는 살지만 칸 안 줄바꿈이 공백으로 뭉침(`<br>` 0개) | 칸 살아 있음 |
| **C. DP enhanced HTML** | $0.03 | 머리글 칸 `<th>`, 칸 안 줄바꿈 `<br/>` → 코드가 「어른 1회 · 3,000~6,000」로 짝지음 | 여러 층 열 머리글 + 행 머리글 `<th>` |
| D. Information Extract standard(칸 단위 JSON 스키마) | $0.04 | 「어 른 1회」와 「3,000~6,000」을 다른 칸으로만 냄(짝 사라짐), 표마다 스키마가 필요 | 행 · 열 경로까지 정확 |

- C는 10개 표 전부에서 `<th>`(합 80개)를 냈다. 칸 안 줄바꿈 `<br/>`도 53개 지켰다(B는 0).
- 값 글자는 모델이 다시 쓴 것이 아니라 문서에서 읽은 것이다(D는 모델이 칸을 다시 적는다).

## 펼친 꼴

```
- 공 원 별: 서울대공원 > 동물원 (식물원 포함) · 사용기준: 청소년 1회 · 금 액(원): 2,000~4,000
- 구 분: 1급지 · 노 상 주 차 장 > 1회주차시5분당: 500 · … · 노 외 주 차 장 > 월 정 기 권 > 야 간: 100,000
```

표가 아닌 머리 · 문단(비고, ※ 문장)은 그대로 둔다.
