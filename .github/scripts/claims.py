"""가져간 이슈는 PM이 「회수」하기 전까지 담당만 손대게 한다(docs/work-method.md 1절 「일찍 끝나면」 · 5절, 동규 11-08).

.github/workflows/claims.yml이 이벤트마다 부른다. 무료 플랜 비공개 레포라 브랜치 보호 · 룰셋을 못 써서(API 403) 서버에서 되돌리고 알린다.
- 이슈(담당 바뀜 · 「가져감」 · 「회수」 댓글): 이슈 기록(timeline)을 처음부터 다시 놓아 「맞는 담당」을 셈하고 지금 담당을 거기에 맞춘다.
  이벤트 하나만 뒤집지 않고 기록 전체로 셈해서, 바꾸기(빼고 더하기)도 거의 동시에 온 두 「가져감」(먼저 쓴 쪽)도 같은 답이 나온다.
- PR(검사 이름 claims): 첫 줄 이슈의 담당이거나 PM인 사람이 연 PR · push만 통과한다.
표준 라이브러리와 GITHUB_TOKEN REST만 쓴다. `python3 claims.py --selftest`로 가짜 이벤트를 돌려 본다.
"""
import contextlib
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request

from check_pr import first_line

PM = "Lumiere001"  # 바꾸면 claims.yml의 if도 같이 바꾼다
BOT = "github-actions[bot]"  # 이 스크립트가 GITHUB_TOKEN으로 바꾼 것은 이 이름으로 기록된다
SPARE = "예비"
# 동규 지시(11-08 01:00 KST). 이보다 앞선 담당 · 라벨 기록은 있는 그대로 믿고, 앞선 댓글은 명령으로 읽지 않는다.
SINCE = "2026-11-07T16:00:00Z"
# ponytail: 「가져갈 수 있는 조건」(누가 끝나야 가져가나)은 판정하지 않는다. 이슈 본문의 글이라 사람과 PM이 본다.

TAKEN = "@{who} 이 일은 {owners} 님이 맡고 있어요. PM이 「회수」하기 전에는 가져갈 수 없어요."
NOT_SPARE = "@{who} PM이 배정하는 이슈예요. 「예비」 라벨이 붙고 담당이 없는 이슈만 「가져감」으로 가져갈 수 있어요."
PM_ONLY = "@{who} 담당은 PM만 바꿀 수 있어서 되돌렸어요. 바꿔야 하면 이 이슈에 까닭을 쓰고 PM에게 알려 주세요."
GIVE_BACK = "@{who} 담당을 스스로 빼면 되돌려요. 반납은 이 이슈에 까닭을 쓰고 PM에게 알려 주세요(PM이 「회수」하면 비워져요)."
RECALL = "@{who} 「회수」는 PM만 할 수 있어요. 아무것도 바꾸지 않았어요."


def login(user):
    return (user or {}).get("login")


def mention(owners):
    return " · ".join("@" + o for o in owners)


def replay(events):
    """기록을 차례로 다시 놓아 (맞는 담당, 남길 안내, 한 번이라도 맞는 담당이었던 사람)을 낸다. 같은 기록이면 몇 번을 돌려도 같은 답이다."""
    owners, spare, notes, ever = [], False, [], set()
    for e in events:
        kind, actor, old = e.get("event"), login(e.get("actor")), e.get("created_at", "") < SINCE
        if actor == BOT and not old:
            continue  # 이 스크립트가 맞춘 결과라 셈에 넣지 않는다
        trusted = old or actor == PM
        who = login(e.get("assignee"))
        claimer = None
        if kind in ("labeled", "unlabeled") and trusted and e["label"]["name"] == SPARE:
            spare = kind == "labeled"
        elif kind == "assigned" and who and who not in owners:
            if trusted:
                owners.append(who)
            elif actor == who:
                claimer = who  # 스스로 담당 지정도 가져가기
            else:
                notes.append(PM_ONLY.format(who=actor))
        elif kind == "unassigned" and who in owners:  # 잘못 붙은 담당을 빼는 것은 맞는 쪽으로 가는 것이라 그냥 둔다
            if trusted:
                owners.remove(who)
            else:
                notes.append((GIVE_BACK if actor == who else PM_ONLY).format(who=actor))
        elif kind == "commented" and not old:
            text = (e.get("body") or "").strip()
            if text.startswith("가져감"):
                claimer = actor
            elif text.startswith("회수") and actor == PM:  # 「회수」는 비우고, 「회수 @아이디」(첫 줄)는 그 사람만
                owners = re.findall(r"@([A-Za-z0-9-]+)", text.splitlines()[0])
            elif text.startswith("회수"):
                notes.append(RECALL.format(who=actor))
        if claimer and claimer not in owners:  # 이미 자기 담당이면 조용히 넘어간다
            if owners:
                notes.append(TAKEN.format(who=claimer, owners=mention(owners)))
            elif not spare:
                notes.append(NOT_SPARE.format(who=claimer))
            else:
                owners = [claimer]
        ever.update(owners)
    return owners, notes, ever


def github(method, path, body=None):
    """GitHub REST 한 번. path는 /repos/<이 레포> 뒤."""
    req = urllib.request.Request(
        f"{os.environ.get('GITHUB_API_URL', 'https://api.github.com')}/repos/{os.environ['GITHUB_REPOSITORY']}{path}",
        data=None if body is None else json.dumps(body).encode(), method=method,
        headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json", "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.loads(res.read() or b"null")


def timeline(api, n):
    """이슈(PR도) 기록 전체. 담당 · 라벨 · 댓글이 일어난 차례대로."""
    events, page = [], 1
    while True:
        batch = api("GET", f"/issues/{n}/timeline?per_page=100&page={page}")
        events += batch
        if len(batch) < 100:
            return events
        page += 1


def said(events):
    """이 스크립트가 이미 단 댓글의 줄(같은 안내를 되풀이하지 않으려고)."""
    return {line for e in events if e.get("event") == "commented" and login(e.get("actor")) == BOT
            for line in (e.get("body") or "").splitlines()}


def say(api, n, lines, events):
    old = said(events)
    new = [line for line in dict.fromkeys(lines) if line not in old]
    if new:
        api("POST", f"/issues/{n}/comments", {"body": "\n\n".join(new)})


def assignees(api, n):
    """이슈 n의 지금 담당. 없는 이슈면 None."""
    try:
        return [login(a) for a in api("GET", f"/issues/{n}")["assignees"]]
    except urllib.error.HTTPError as err:
        if err.code == 404:
            return None
        raise


def settle_issue(api, n):
    """처리 직전에 기록과 담당을 다시 읽어, 기록대로 셈한 담당에 맞추고 아직 안 단 안내를 단다."""
    events = timeline(api, n)
    owners, notes, _ = replay(events)
    now = assignees(api, n)
    add, drop = [o for o in owners if o not in now], [a for a in now if a not in owners]
    if add:
        api("POST", f"/issues/{n}/assignees", {"assignees": add})
    if drop:
        api("DELETE", f"/issues/{n}/assignees", {"assignees": drop})
    say(api, n, notes, events)
    print(f"#{n} 담당 {now} → {owners}")


def pr_problems(api, event):
    """PR 검사: 첫 줄 이슈의 담당이거나 PM이 연 PR · push인가. 문제 문장 목록(비면 통과)."""
    pr, sender = event["pull_request"], login(event["sender"])
    m = re.match(r"(Closes|Fixes|Refs) #(\d+)", first_line(pr.get("body")))
    if not m:
        return []  # 「티켓 없음」처럼 이슈가 없는 PR
    n, author, sha = int(m[2]), login(pr["user"]), pr["head"]["sha"]
    owners, problems = assignees(api, n), []
    if owners is None:
        problems.append(f"PR 첫 줄의 #{n} 이슈를 찾을 수 없어요. 이슈 번호를 확인해 주세요.")
    else:
        ok = owners + [PM]
        whose = f"{mention(owners)} 님이 맡은 일이라" if owners else "아직 담당이 없어서"
        # 이어받기(5절): PM이 담당이 된 이슈는 원래 담당(한 번이라도 맞는 담당이었던 사람)이 연 PR에서 PM이 이어 간다
        handed = author not in ok and PM in owners and author in replay(timeline(api, n))[2]
        if author not in ok and not handed:
            problems.append(f"@{author} #{n} 이슈는 {whose} 이 PR은 담당이나 PM만 올릴 수 있어요. 첫 줄 번호가 맞으면 "
                            "이슈에서 PM에게 물어 주세요(「예비」 이슈는 「가져감」 댓글로 먼저 가져가요).")
        if event["action"] == "synchronize" and sender not in ok:
            problems.append(f"@{sender} #{n} 이슈는 {whose} 이 PR 브랜치에 push할 수 없어요(커밋 {sha[:7]}). "
                            f"담당이나 PM만 push해요. <!-- claims:push:{sha} -->")
    events = timeline(api, pr["number"])
    problems += [line for line in said(events) if f"claims:push:{sha}" in line]  # 남이 push한 커밋은 본문을 고쳐도 빨갛게 남긴다
    say(api, pr["number"], problems, events)
    return list(dict.fromkeys(problems))


def main(api, name, event):
    if name == "pull_request":
        problems = pr_problems(api, event)
        for p in problems:
            print("::error::" + re.sub(r"\s*<!--.*?-->", "", p))
        return 1 if problems else 0
    if "pull_request" not in event["issue"]:  # PR에 단 댓글은 다루지 않는다
        settle_issue(api, event["issue"]["number"])
    return 0


def selftest():
    A, B, C = "KIMDONGWOOK-KR1", "ParkjongE", "geonyeong325"

    def ev(kind, actor, at="2026-11-09T09:00:00Z", **x):
        return {"event": kind, "actor": {"login": actor}, "created_at": at, **x}

    def got(actor, who, at="2026-11-09T09:00:00Z"):
        return ev("assigned", actor, at, assignee={"login": who})

    def lost(actor, who):
        return ev("unassigned", actor, assignee={"login": who})

    def says(actor, body):
        return ev("commented", actor, body=body)

    spare = ev("labeled", PM, "2026-11-06T14:45:26Z", label={"name": SPARE})  # 규칙 전 PM이 붙인 「예비」

    class Fake:
        """가짜 GitHub: 이슈 번호마다 기록과 담당을 들고, 바꾼 것은 BOT 이름으로 기록에 이어 붙인다."""

        def __init__(self, events, assignees):
            self.events, self.assignees, self.posts = events, assignees, []

        def __call__(self, method, path, body=None):
            n = int(re.search(r"/issues/(\d+)", path)[1])
            if "/timeline" in path:
                return list(self.events.get(n, []))
            if n not in self.assignees:
                raise urllib.error.HTTPError(path, 404, "Not Found", None, None)
            if method == "GET":
                return {"assignees": [{"login": x} for x in self.assignees[n]]}
            if path.endswith("/comments"):
                self.posts.append(body["body"])
                self.events.setdefault(n, []).append(says(BOT, body["body"]))
                return {}
            for who in body["assignees"]:
                if method == "POST":
                    self.assignees[n].append(who)
                else:
                    self.assignees[n].remove(who)
                self.events.setdefault(n, []).append((got if method == "POST" else lost)(BOT, who))
            return {}

    def issue(events, now, runs=1):
        """이슈 1의 기록 · 지금 담당으로 runs번 돌려 (담당, 단 댓글)을 낸다."""
        api = Fake({1: list(events)}, {1: list(now)})
        for _ in range(runs):
            assert main(api, "issues", {"issue": {"number": 1}}) == 0
        return api.assignees[1], api.posts

    def taken(who, owner):
        return TAKEN.format(who=who, owners="@" + owner)

    # 가져가기: 성공 · 거절(담당 있음) · 거절(예비 아님) · 스스로 담당 지정 · 이미 자기 담당
    assert issue([spare, says(A, "가져감 — #22 끝 보고 올림")], []) == ([A], [])
    assert issue([spare, got(PM, A), says(B, "가져감")], [A]) == ([A], [taken(B, A)])
    assert issue([says(B, "가져감")], []) == ([], [NOT_SPARE.format(who=B)])
    # 「예비」는 PM이 붙인 것만 센다
    assert issue([ev("labeled", B, label={"name": SPARE}), says(B, "가져감")], []) == ([], [NOT_SPARE.format(who=B)])
    assert issue([spare, got(C, C)], [C]) == ([C], [])
    assert issue([spare, says(A, "가져감"), got(A, A)], [A]) == ([A], [])
    # 동시 두 명: 두 실행이 어느 차례로 돌든 먼저 쓴 A만 남고, B에게 안내는 한 번
    assert issue([spare, says(A, "가져감"), says(B, "가져감")], [], runs=2) == ([A], [taken(B, A)])
    api = Fake({1: [spare, says(A, "가져감")]}, {1: []})
    main(api, "issue_comment", {"issue": {"number": 1}})
    api.events[1] += [says(B, "가져감"), got(B, B)]  # A 실행이 끝난 뒤 B가 댓글도 달고 스스로 담당도 지정
    api.assignees[1].append(B)
    main(api, "issues", {"issue": {"number": 1}})
    assert (api.assignees[1], api.posts) == ([A], [taken(B, A)])
    # 회수: 「회수」(비우면 다시 가져갈 수 있다) · 「회수 @아이디」(첫 줄만) · PM 아닌 사람의 「회수」
    assert issue([spare, got(PM, A), says(PM, "회수\n주기 1이 끝나 비움")], [A]) == ([], [])
    assert issue([spare, got(PM, A), says(PM, "회수"), says(B, "가져감")], [A]) == ([B], [])
    assert issue([got(PM, A), says(PM, f"회수 @{C}\n@{A} 님 수고했어요")], [A]) == ([C], [])
    assert issue([got(PM, A), says(B, "회수")], [A]) == ([A], [RECALL.format(who=B)])
    # 담당 변경: PM 아닌 사람의 바꾸기(빼고 더하기) · 남 붙이기 · 스스로 빼기는 되돌리고, PM의 변경과 규칙 전 기록은 그대로
    assert issue([got(PM, A), lost(B, A), got(B, B)], [B]) == ([A], [PM_ONLY.format(who=B) + "\n\n" + taken(B, A)])
    assert issue([got(PM, A), got(B, C)], [A, C]) == ([A], [PM_ONLY.format(who=B)])
    assert issue([got(PM, A), lost(A, A)], []) == ([A], [GIVE_BACK.format(who=A)])
    assert issue([got(PM, A), lost(PM, A), got(PM, C)], [C]) == ([C], [])
    assert issue([got(A, A, "2026-11-07T10:43:24Z")], [A]) == ([A], [])
    # 「회수」 뒤에 늦게 닿은 이 스크립트의 바꿈은 셈에 넣지 않는다
    assert issue([got(PM, A), says(PM, "회수"), got(BOT, A)], [A]) == ([], [])
    # 같은 안내는 되풀이하지 않는다 · PR에 단 댓글은 다루지 않는다
    assert issue([got(PM, A), says(B, "회수")], [A], runs=3)[1] == [RECALL.format(who=B)]
    assert main(Fake({}, {}), "issue_comment", {"issue": {"number": 1, "pull_request": {}}}) == 0

    def pr(body, author, sender=None, action="opened", sha="a1" * 20, api=None):
        """PR 70 검사. 이슈 7은 A, 8은 A에게서 PM이 이어받음, 9는 PM 일에 B가 스스로 붙었다가 되돌려짐, 10은 PM이 A에게서 C로 넘김."""
        api = api or Fake({8: [got(PM, A), lost(PM, A), got(PM, PM)], 9: [got(PM, PM), got(B, B), lost(BOT, B)],
                           10: [got(PM, A), lost(PM, A), got(PM, C)]}, {7: [A], 8: [PM], 9: [PM], 10: [C], 70: []})
        event = {"action": action, "sender": {"login": sender or author},
                 "pull_request": {"number": 70, "body": body, "user": {"login": author}, "head": {"sha": sha}}}
        return main(api, "pull_request", event), api

    # PR: 통과(담당 · PM) · 티켓 없음 · 실패(작성자 다름, 댓글은 한 번) · 실패(push한 사람 다름, 그 커밋은 본문을 고쳐도 빨강)
    assert pr("<!-- 양식 안내 -->\nCloses #7\n## 무엇이 좋아지나", A)[0] == 0
    assert pr("Refs #7", PM)[0] == 0
    assert pr("티켓 없음 — 회의록", B)[0] == 0
    code, api = pr("Closes #7", B)
    assert code == 1 and len(api.posts) == 1 and api.posts[0].startswith(f"@{B} #7 이슈는 @{A} 님이 맡은 일이라")
    assert pr("Fixes #7", B, action="edited", api=api)[0] == 1 and len(api.posts) == 1
    code, api = pr("Closes #7", A, sender=B, action="synchronize")
    assert code == 1 and len(api.posts) == 1 and "claims:push:" + "a1" * 20 in api.posts[0]
    assert pr("Closes #7", A, action="edited", api=api)[0] == 1 and len(api.posts) == 1
    assert pr("Closes #7", A, action="synchronize", sha="b2" * 20, api=api)[0] == 0
    # 이어받기(5절): 원래 담당 A가 연 PR에 PM이 push하면 통과, 그 뒤 A가 push하면 실패 · 없는 이슈는 실패
    assert pr("Closes #8", A, sender=PM, action="synchronize")[0] == 0
    assert pr("Closes #8", A, action="synchronize")[0] == 1
    assert pr("Closes #9", B)[0] == 1  # 되돌려진 담당은 원래 담당이 아니다
    assert pr("Closes #10", A)[0] == 1  # PM이 다른 팀원에게 넘긴 이슈는 원래 담당의 PR도 막는다
    assert pr("Closes #99", A)[0] == 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        with contextlib.redirect_stdout(io.StringIO()):  # 가짜 이벤트의 ::error:: 줄이 Actions 오류 표시로 잡히지 않게
            selftest()
        print("selftest ok")
        sys.exit(0)
    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as f:
        sys.exit(main(github, os.environ["GITHUB_EVENT_NAME"], json.load(f)))
