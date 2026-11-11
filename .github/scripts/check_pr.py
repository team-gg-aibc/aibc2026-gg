"""PR 제목과 본문이 CONTRIBUTING.md · PR 양식을 지키는지 검사한다.

늘 필수: 제목 앞머리, 첫 줄(Closes/Refs/티켓 없음), 「무엇이 좋아지나 · 검증 · 정리」.
화면 · 코드(app/)를 바꾼 PR만 필수: 「바로 확인 · Before / After · 이 흐름이 자연스러운가 · 화면 점검 · 흐름 다이어그램」.
CI에서는 환경 변수 PR_TITLE · PR_BODY · CHANGED_FILES_PATH로 받는다(본문을 명령에 직접 끼우지 않으려고).
`python3 check_pr.py --selftest`로 검사기 자체를 시험한다.
docs/PRD.md를 바꾼 PR은 docs/PRD-요약.md도 바꾸거나 본문에 「요약 영향 없음 — 이유」를 적는다(AGENTS.md 6절).
"""
import os
import re
import sys

TYPES = "feat|fix|docs|refactor|style|test|chore|ci"
PRD, PRD_SUMMARY = "docs/PRD.md", "docs/PRD-요약.md"
CORE = ["무엇이 좋아지나", "검증", "정리"]
SCREEN = ["바로 확인", "Before / After", "이 흐름이 자연스러운가", "화면 점검", "흐름 다이어그램"]


def sections(text: str) -> dict[str, str]:
    parts = re.split(r"^## (.+?)\s*$", text, flags=re.M)
    return {parts[i].strip(): parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def first_line(body: str) -> str:
    """HTML 주석을 뺀 본문에서 처음 나오는 글 있는 줄. claims.py도 이 줄로 PR의 이슈를 찾는다."""
    text = re.sub(r"<!--.*?-->", "", body or "", flags=re.S)
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def check(title: str, body: str, changed: list[str]) -> list[str]:
    errors = []
    screen_pr = any(path.startswith("app/") for path in changed)
    required = CORE + SCREEN if screen_pr else CORE
    if not re.match(rf"^({TYPES})(\([^)]+\))?: \S", title or ""):
        errors.append(f"PR 제목은 「{TYPES.replace('|', ' · ')}」 중 하나로 시작해야 해요. 예: feat: 검색 결과에 근거 조항 붙이기")
    text = re.sub(r"<!--.*?-->", "", body or "", flags=re.S)
    first = first_line(text)
    if not re.match(r"^((Closes|Refs) #\d+|티켓 없음 — \S)", first):
        errors.append("첫 줄은 「Closes #번호」, 「Refs #번호」, 「티켓 없음 — 이유」 중 하나여야 해요.")
    found = sections(text)
    for heading in required:
        content = found.get(heading)
        if content is None:
            why = " (app/의 화면 · 코드를 바꾼 PR이라 필요해요)" if heading in SCREEN else ""
            errors.append(f"「## {heading}」 절이 없어요{why}.")
        elif not content.strip():
            errors.append(f"「{heading}」 절이 비었어요. 해당이 없으면 「○○ 없음 — 이유」라고 써 주세요.")
        elif "<채우기" in content:
            errors.append(f"「{heading}」 절에 <채우기: …> 표시가 남아 있어요.")
    if PRD in changed and PRD_SUMMARY not in changed and not re.search(r"요약 영향 없음 — \S", text):
        errors.append(f"{PRD}를 바꿨는데 {PRD_SUMMARY}는 그대로예요. 요약의 해당 절도 고치거나, "
                      "요약에 영향이 없으면 본문에 「요약 영향 없음 — 이유」를 적어 주세요(AGENTS.md 6절).")
    return errors


def selftest() -> None:
    core = "".join(f"## {h}\n내용\n" for h in CORE)
    screen_filled = "".join(f"## {h}\n내용\n" for h in SCREEN)
    screen_blank = "".join(f"## {h}\n<채우기>\n" for h in SCREEN)
    docs = ["docs/PRD.md", "docs/PRD-요약.md"]
    app = ["app/page.tsx", "docs/PRD.md", "docs/PRD-요약.md"]
    # PRD만 바뀌면 요약도 바꾸거나 「요약 영향 없음 — 이유」(주석 안의 글은 안 침)
    prd_only = ["docs/PRD.md"]
    assert check("docs: PRD 고침", "Closes #3\n" + core, prd_only)
    assert check("docs: PRD 고침", "Closes #3\n<!-- 요약 영향 없음 — 오탈자 -->\n" + core, prd_only)
    assert check("docs: PRD 고침", "Closes #3\n" + core + "- 요약 영향 없음 — 오탈자만 고침\n", prd_only) == []
    assert check("docs: 요약 고침", "Closes #3\n" + core, ["docs/PRD-요약.md"]) == []
    assert check("docs: PRD 초안", "Closes #3\n" + core + screen_blank, docs) == []
    assert check("docs: PRD 초안", "티켓 없음 — 회의록\n" + core, docs) == []
    assert check("feat: 검색", "Closes #3\n" + core + screen_blank, app)
    assert check("feat: 검색", "Closes #3\n" + core + screen_filled, app) == []
    assert check("feat: 검색", "Closes #3\n" + core, app)
    assert check("검색 추가", "Closes #3\n" + core, docs)
    assert check("docs: x", "Fixes #3\n" + core, docs)
    assert check("docs: x", "Closes #3\n" + core.replace("## 검증\n내용", "## 검증\n"), docs)
    assert check("docs: x", "Closes #3\n" + core.replace("## 정리\n내용\n", ""), docs)
    assert check("docs: x", "Closes #3\n" + core.replace("## 검증\n내용", "## 검증\n<채우기: 확인한 것>"), docs)
    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    path = os.environ.get("CHANGED_FILES_PATH", "")
    changed = open(path, encoding="utf-8").read().split() if path else []
    problems = check(os.environ.get("PR_TITLE", ""), os.environ.get("PR_BODY", ""), changed)
    for p in problems:
        print(f"::error::{p}")
    sys.exit(1 if problems else 0)
