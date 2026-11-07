"""가져간 이슈는 PM이 「회수」하기 전까지 담당만 손대게 한다(docs/work-method.md 1절 「일찍 끝나면」 · 5절, 동규 11-08).

.github/workflows/claims.yml이 이벤트마다 부른다. 무료 플랜 비공개 레포라 브랜치 보호 · 룰셋을 못 써서(API 403) 서버에서 되돌리고 알린다.
- 이슈(담당 바뀜 · 「가져감」 · 「회수」 댓글): 이슈 기록(timeline)을 처음부터 다시 놓아 「맞는 담당」을 셈하고 지금 담당을 거기에 맞춘다.
  이벤트 하나만 뒤집지 않고 기록 전체로 셈해서, 바꾸기(빼고 더하기)도 거의 동시에 온 두 「가져감」(먼저 쓴 쪽)도 같은 답이 나온다.
  「가져감」은 이번 주기에 맡은 실험의 끝 보고가 있어야 받는다. 거절 · PM 확인은 댓글 표시로 남겨 다시 판정하지 않는다.
  PM이 「회수」하면 그 이슈를 가리키는 열린 PR에 바로 댓글과 실패 상태(claims · 회수)를 남긴다.
- PR(검사 이름 claims): 첫 줄 이슈의 담당 · PM이 연 PR과 담당 · PM의 push만 통과한다. 원래 담당이 연 PR은 새 담당 · PM이 이어 간다.
표준 라이브러리와 GITHUB_TOKEN REST만 쓴다. `python3 claims.py --selftest`로 가짜 이벤트를 돌려 본다.
"""
import contextlib
import datetime as dt
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
# 판정이 남지 않은 「가져감」과 PR에 아직 안 남긴 「회수」는 한 시간 안의 것만 처리한다(병합 전 · 실패한 실행의 일을 뒤늦게 되짚지 않게).
FRESH = dt.timedelta(hours=1)
KST = dt.timezone(dt.timedelta(hours=9))
# 2일 주기 (첫날, 둘째 날 = 마감). docs/schedule.md 「엔진 실험 주기」 · GG비서 CYCLES와 같다.
CYCLES = [((11, 7), (11, 8)), ((11, 9), (11, 10)), ((11, 11), (11, 12)), ((11, 13), (11, 14)), ((11, 15), (11, 16))]
LINK = re.compile(r"(Closes|Fixes|Refs) #(\d+)")
HOLD = "claims · 회수"  # 「회수」 때 PR 커밋에 다는 실패 상태. 새 커밋에는 없어서 새 담당이 push하면 풀린다
# ponytail: 이슈마다 다른 「가져갈 수 있는 조건」(예: 「종희가 #24 끝 보고를 올린 뒤에만」)은 판정하지 않는다. 사람과 PM이 본다.

TAKEN = "@{who} 이 일은 {owners} 님이 맡고 있어요. PM이 「회수」하기 전에는 가져갈 수 없어요."
NOT_SPARE = "@{who} PM이 배정하는 이슈예요. 「예비」 라벨이 붙고 담당이 없는 이슈만 「가져감」으로 가져갈 수 있어요."
NO_REPORT = "@{who} 맡은 실험 #{n}의 끝 보고를 먼저 올려 주세요. 끝 보고를 올린 사람만 예비를 가져가요(올린 뒤 「가져감」을 다시 써요)."
NEED_PM = "@{who} 님을 담당으로 지정했어요. {issues}의 마감이나 끝 보고를 읽지 못해 PM 확인 필요예요 @" + PM + "."
PM_ONLY = "@{who} 담당은 PM만 바꿀 수 있어서 되돌렸어요. 바꿔야 하면 이 이슈에 까닭을 쓰고 PM에게 알려 주세요."
GIVE_BACK = "@{who} 담당을 스스로 빼면 되돌려요. 반납은 이 이슈에 까닭을 쓰고 PM에게 알려 주세요(PM이 「회수」하면 비워져요)."
RECALL = "@{who} 「회수」는 PM만 할 수 있어요. 아무것도 바꾸지 않았어요."
STOP = "PM이 회수함 — 새 담당이 정해질 때까지 이 PR은 멈춤. 원래 담당의 브랜치 · 커밋은 이어받기에 쓰니 지우지 않아요."
STOP_TO = "PM이 회수함 — 새 담당 {heirs} 님이 이어서 push할 때까지 이 PR은 멈춤. 원래 담당의 브랜치 · 커밋은 이어받기에 쓰니 지우지 않아요."


def login(user):
    return (user or {}).get("login")


def mention(owners):
    return " · ".join("@" + o for o in owners)


def when(stamp):
    return dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def heirs(body):
    """「회수 @아이디」 첫 줄의 @들(새 담당). 「회수」만 쓰면 빈 목록."""
    return re.findall(r"@([A-Za-z0-9-]+)", body.strip().splitlines()[0])


def issue_due(body, year):
    """이슈 본문 「- 마감: 11/12(목) 21:00」 줄의 날짜. GG비서 issue_due와 같은 규칙(취소선은 빼고 그 줄의 첫 날짜). 없으면 None."""
    m = re.search(r"^\s*[-*]\s*(?:\*\*)?마감(?:\*\*)?\s*[:：](.*)$", body or "", re.M)
    for month, day in re.findall(r"(\d{1,2})/(\d{1,2})", re.sub(r"~~.*?~~", "", m[1])) if m else []:
        try:
            return dt.date(year, int(month), int(day))
        except ValueError:  # 13/40처럼 없는 날짜
            continue
    return None


def cycle_of(day):
    """그날이 든 주기 (첫날, 둘째 날). 첫 주기 전이면 첫 주기, 마지막 주기 뒤면 None. GG비서 cycle_of와 같다."""
    return next(((dt.date(day.year, *a), dt.date(day.year, *b)) for a, b in CYCLES if day <= dt.date(day.year, *b)), None)


def report_kinds(body):
    """보고 댓글 첫 줄(「**[보고] 끝 · 세션 끝**」 꼴)의 종류들. GG비서 read_reports와 같은 규칙이라 「세션 끝」은 「끝」이 아니다."""
    m = re.match(r"\s*\**\s*\[보고\]\s*([^*\n]+)", body or "")
    return {k.strip() for k in re.split(r"[·,/]", m[1]) if k.strip()} if m else set()


def replay(events, judge=None):
    """기록을 차례로 다시 놓아 (맞는 담당, 남길 안내, 한 번이라도 맞는 담당이었던 사람)을 낸다. 같은 기록이면 몇 번을 돌려도 같은 답이다.
    judge(who, at, key)는 판정이 아직 남지 않은 「가져감」을 판정해 (받나, 안내)를 낸다. 없으면 받는다(PR 검사에서 읽기만 할 때)."""
    owners, spare, notes, ever = [], False, [], set()
    marks = "\n".join(said(events))
    for e in events:
        kind, actor, at = e.get("event"), login(e.get("actor")), e.get("created_at", "")
        old = at < SINCE
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
                owners = heirs(text)
            elif text.startswith("회수"):
                notes.append(RECALL.format(who=actor))
        if claimer and claimer not in owners:  # 이미 자기 담당이면 조용히 넘어간다
            key = f"{kind}-{e.get('id') or at}"  # 판정 표시(claims:no · claims:check)의 열쇠
            if owners:
                notes.append(TAKEN.format(who=claimer, owners=mention(owners)))
            elif not spare:
                notes.append(NOT_SPARE.format(who=claimer))
            elif f"<!-- claims:no:{key} -->" not in marks:  # 앞서 거절한 「가져감」은 그대로 거절
                took, note = True, None
                if judge and f"<!-- claims:check:{key} -->" not in marks:
                    took, note = judge(claimer, at, key)
                if note:
                    notes.append(note)
                if took:
                    owners = [claimer]
        ever.update(owners)
    return owners, notes, ever


def end_report(api, now, n):
    """이슈 n의 「가져감」 판정(1절 「일찍 끝나면」): 이번 주기에 맡은 실험(열림 · 예비 아님 · 마감이 이번 주기)마다
    그 사람의 끝 보고가 있어야 받는다. 마감이나 보고를 못 읽으면 막지 않고 받은 뒤 PM 확인을 부른다.
    거절 · PM 확인은 댓글 표시로 남아 다시 판정하지 않는다."""
    def judge(who, at, key):
        if who == PM or now - when(at) > FRESH:
            return True, None  # PM은 묻지 않고, 한 시간 넘게 판정이 없던 것은 되짚지 않는다
        try:
            missing, unclear = report_gaps(api, who, at, n)
        except urllib.error.URLError:
            missing, unclear = None, ["맡은 이슈 목록"]
        if missing:
            return False, NO_REPORT.format(who=who, n=missing) + f" <!-- claims:no:{key} -->"
        if unclear:
            return True, NEED_PM.format(who=who, issues=" · ".join(unclear)) + f" <!-- claims:check:{key} -->"
        return True, None
    return judge


def report_gaps(api, who, at, n):
    """그 사람의 이번 주기 실험(가져가려는 이슈 n은 빼고) 가운데 끝 보고가 없는 첫 이슈 번호와, 마감을 못 읽은 이슈들(#번호)."""
    day = when(at).astimezone(KST).date()
    cycle, unclear = cycle_of(day), []
    for it in api("GET", f"/issues?assignee={who}&state=open&per_page=100"):
        if it["number"] == n or "pull_request" in it or SPARE in [lb["name"] for lb in it.get("labels") or []]:
            continue
        due = issue_due(it.get("body"), day.year)
        if due is None:
            unclear.append(f"#{it['number']}")
        elif cycle and cycle[0] <= due <= cycle[1] and not any(
                e.get("event") == "commented" and login(e.get("actor")) == who and e.get("created_at", "") <= at
                and "끝" in report_kinds(e.get("body")) for e in timeline(api, it["number"])):
            return it["number"], unclear
    return None, unclear


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


def settle_issue(api, n, now):
    """처리 직전에 기록과 담당을 다시 읽어, 기록대로 셈한 담당에 맞추고 아직 안 단 안내를 단다. 「회수」는 PR에도 남긴다."""
    events = timeline(api, n)
    owners, notes, _ = replay(events, end_report(api, now, n))
    current = assignees(api, n)
    add, drop = [o for o in owners if o not in current], [a for a in current if a not in owners]
    if add:
        api("POST", f"/issues/{n}/assignees", {"assignees": add})
    if drop:
        api("DELETE", f"/issues/{n}/assignees", {"assignees": drop})
    say(api, n, notes, events)
    hold_prs(api, n, events, now)
    print(f"#{n} 담당 {current} → {owners}")


def hold_prs(api, n, events, now):
    """PM의 「회수」(한 시간 안)를, 그보다 먼저 열려 이 이슈를 가리키는(첫 줄 Closes/Fixes/Refs #n) 열린 PR에 바로 남긴다:
    댓글 한 번과 그 PR 커밋의 실패 상태(claims · 회수). 새 담당이 push한 새 커밋에는 이 상태가 없다. 브랜치 · 커밋은 건드리지 않는다."""
    recalls = [e for e in events if e.get("event") == "commented" and login(e.get("actor")) == PM
               and (e.get("body") or "").strip().startswith("회수") and now - when(e["created_at"]) <= FRESH]
    if not recalls:
        return
    for pr in api("GET", "/pulls?state=open&per_page=100"):
        m = LINK.match(first_line(pr.get("body")))
        if not m or int(m[2]) != n:
            continue
        pr_events = timeline(api, pr["number"])
        for r in recalls:
            to = heirs(r["body"])
            line = (STOP_TO.format(heirs=mention(to)) if to else STOP) + f" <!-- claims:stop:{r.get('id') or r['created_at']} -->"
            if pr["created_at"] < r["created_at"] and line not in said(pr_events):
                say(api, pr["number"], [line], pr_events)
                api("POST", f"/statuses/{pr['head']['sha']}",
                    {"state": "failure", "context": HOLD, "description": "PM이 회수함 — 새 담당이 push할 때까지 멈춤"})


def pr_problems(api, event):
    """PR 검사: 첫 줄 이슈의 담당 · PM이 연 PR이고 담당 · PM의 push인가. 문제 문장 목록(비면 통과)."""
    pr, sender, action = event["pull_request"], login(event["sender"]), event["action"]
    m = LINK.match(first_line(pr.get("body")))
    if not m:
        return []  # 「티켓 없음」처럼 이슈가 없는 PR
    n, author, sha = int(m[2]), login(pr["user"]), pr["head"]["sha"]
    owners, problems = assignees(api, n), []
    if owners is None:
        problems.append(f"PR 첫 줄의 #{n} 이슈를 찾을 수 없어요. 이슈 번호를 확인해 주세요.")
    else:
        ok = owners + [PM]
        whose = f"{mention(owners)} 님이 맡은 일이라" if owners else "아직 담당이 없어서"
        # 새로 열거나 다시 여는 사람은 지금 담당 · PM이어야 한다. 이미 있던 PR은 원래 담당(한 번이라도 맞는 담당이었던 사람)이 연 것이면
        # 새 담당 · PM이 이어 간다(5절 이어받기 · 「회수 @아이디」). 그때 누가 push하는지는 아래 push 검사가 본다.
        starting = action in ("opened", "reopened")
        opener = sender if starting else author
        if opener not in ok and (starting or author not in replay(timeline(api, n))[2]):
            problems.append(f"@{opener} #{n} 이슈는 {whose} 이 PR은 담당이나 PM만 올릴 수 있어요. 첫 줄 번호가 맞으면 "
                            "이슈에서 PM에게 물어 주세요(「예비」 이슈는 「가져감」 댓글로 먼저 가져가요).")
        if action == "synchronize" and sender not in ok:
            problems.append(f"@{sender} #{n} 이슈는 {whose} 이 PR 브랜치에 push할 수 없어요(커밋 {sha[:7]}). "
                            f"담당이나 PM만 push해요. <!-- claims:push:{sha} -->")
    events = timeline(api, pr["number"])
    problems += [line for line in said(events) if f"claims:push:{sha}" in line]  # 남이 push한 커밋은 본문을 고쳐도 빨갛게 남긴다
    say(api, pr["number"], problems, events)
    return list(dict.fromkeys(problems))


def main(api, name, event, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    if name == "pull_request":
        problems = pr_problems(api, event)
        for p in problems:
            print("::error::" + re.sub(r"\s*<!--.*?-->", "", p))
        return 1 if problems else 0
    if "pull_request" not in event["issue"]:  # PR에 단 댓글은 다루지 않는다
        settle_issue(api, event["issue"]["number"], now)
    return 0


def selftest():
    A, B, C = "member-a", "member-b", "member-c"
    NOW = when("2026-11-09T09:10:00Z")  # 11/9 18:10 KST, 2주기(11/9 · 11/10)

    def ev(kind, actor, at="2026-11-09T09:00:00Z", **x):
        return {"event": kind, "actor": {"login": actor}, "created_at": at, **x}

    def got(actor, who, at="2026-11-09T09:00:00Z"):
        return ev("assigned", actor, at, assignee={"login": who})

    def lost(actor, who):
        return ev("unassigned", actor, assignee={"login": who})

    def says(actor, body, at="2026-11-09T09:00:00Z"):
        return ev("commented", actor, at, body=body)

    spare = ev("labeled", PM, "2026-11-06T14:45:26Z", label={"name": SPARE})  # 규칙 전 PM이 붙인 「예비」

    class Fake:
        """가짜 GitHub: 번호마다 담당 · 기록(본문 · 예비 라벨 · 열린 PR도)을 들고, 바꾼 것은 BOT 이름으로 기록에 이어 붙인다."""

        def __init__(self, events, assignees, bodies=None, spares=(), pulls=(), down=False):
            self.events, self.assignees, self.bodies, self.spares, self.pulls = events, assignees, bodies or {}, spares, pulls
            self.down, self.posts, self.statuses = down, [], []

        def __call__(self, method, path, body=None):
            if path.startswith("/issues?"):  # 담당으로 찾기(들고 있는 이슈는 모두 열려 있다고 친다)
                if self.down:
                    raise urllib.error.URLError("down")
                who = re.search(r"assignee=([^&]+)", path)[1]
                return [{"number": k, "body": self.bodies.get(k, ""), "labels": [{"name": SPARE}] if k in self.spares else []}
                        for k, people in self.assignees.items() if who in people]
            if path.startswith("/pulls?"):
                return list(self.pulls)
            if path.startswith("/statuses/"):
                self.statuses.append((path.split("/")[2], body["state"]))
                return {}
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

    def run(api, n=1, name="issues"):
        assert main(api, name, {"issue": {"number": n}}, now=NOW) == 0
        return api

    def issue(events, now, runs=1):
        """이슈 1의 기록 · 지금 담당으로 runs번 돌려 (담당, 단 댓글)을 낸다."""
        api = Fake({1: list(events)}, {1: list(now)})
        for _ in range(runs):
            run(api)
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
    api = run(Fake({1: [spare, says(A, "가져감")]}, {1: []}), name="issue_comment")
    api.events[1] += [says(B, "가져감"), got(B, B)]  # A 실행이 끝난 뒤 B가 댓글도 달고 스스로 담당도 지정
    api.assignees[1].append(B)
    assert (run(api).assignees[1], api.posts) == ([A], [taken(B, A)])

    # 끝 보고(1절 「일찍 끝나면」): 이번 주기에 맡은 실험(예비 아님 · 마감 11/9 ~ 11/10)마다 끝 보고가 있어야 가져간다
    due = {22: "- 마감: 11/10(화) 24:00", 25: "- 마감: 11/10(화) 24:00", 31: "- 마감: 11/19(목) 24:00 (중간: 11/13(금) 18:00 빈 서버)",
           40: "마감 줄이 없는 본문"}

    def claim(mine, reports=(), who=A, at="2026-11-09T09:00:00Z", down=False):
        """who가 예비 이슈 1에 「가져감」. mine = who가 맡은 다른 이슈, reports = who가 이슈 22에 단 보고(8시)."""
        return run(Fake({1: [spare, says(who, "가져감", at)], 22: [says(who, r, "2026-11-09T08:00:00Z") for r in reports]},
                        {1: [], **{k: [who] for k in mine}}, bodies=due, spares={25}, down=down), name="issue_comment")

    api = claim([22], ["**[보고] 시작**", "**[보고] 끝 · 세션 끝**"])
    assert (api.assignees[1], api.posts) == ([A], [])
    # 남이 단 끝 보고 · 「가져감」 뒤에 올린 끝 보고는 세지 않는다
    for report in (says(B, "**[보고] 끝**", "2026-11-09T08:00:00Z"), says(A, "**[보고] 끝**", "2026-11-09T09:05:00Z")):
        api = run(Fake({1: [spare, says(A, "가져감")], 22: [report]}, {1: [], 22: [A]}, bodies=due), name="issue_comment")
        assert api.assignees[1] == [] and api.posts[0].startswith(NO_REPORT.format(who=A, n=22))
    api = claim([22], ["**[보고] 시작**", "**[보고] 세션 끝**"])  # 「세션 끝」은 끝 보고가 아니다
    assert api.assignees[1] == [] and len(api.posts) == 1 and api.posts[0].startswith(NO_REPORT.format(who=A, n=22))
    api.assignees[22] = [PM]  # 거절은 한 번 판정으로 남는다(그 뒤 A의 실험이 PM에게 넘어가도)
    assert (run(api, name="issue_comment").assignees[1], len(api.posts)) == ([], 1)
    api.assignees[22] = [A]
    api.events[22].append(says(A, "**[보고] 끝**", "2026-11-09T09:05:00Z"))
    api.events[1].append(says(A, "가져감 — 끝 보고 올림", "2026-11-09T09:06:00Z"))
    assert (run(api, name="issue_comment").assignees[1], len(api.posts)) == ([A], 1)  # 끝 보고를 올리고 다시 쓰면 그때 판정
    assert (claim([31]).assignees[1], claim([31]).posts) == ([A], [])  # 마감이 먼 일(서버)만 있으면 막지 않는다
    assert (claim([25]).assignees[1], claim([25]).posts) == ([A], [])  # 앞서 가져간 예비는 「맡은 실험」이 아니다
    for api, issues in ((claim([40]), "#40"), (claim([22], down=True), "맡은 이슈 목록")):  # 애매하면 지정하고 PM 확인
        assert api.assignees[1] == [A] and len(api.posts) == 1 and api.posts[0].startswith(NEED_PM.format(who=A, issues=issues))
        api.bodies[40], api.down = "- 마감: 11/10(화) 24:00", False  # 나중에 읽혀도 판정은 그대로(끝 보고가 없어도 빼지 않는다)
        assert (run(api, name="issue_comment").assignees[1], len(api.posts)) == ([A], 1)
    assert (claim([22], who=PM).assignees[1], claim([22], who=PM).posts) == ([PM], [])  # PM은 묻지 않는다
    api = claim([22], at="2026-11-09T07:00:00Z")  # 한 시간 넘게 판정이 없던 가져감(병합 전 등)은 되짚지 않는다
    assert (api.assignees[1], api.posts) == ([A], [])

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
    assert main(Fake({}, {}), "issue_comment", {"issue": {"number": 1, "pull_request": {}}}, now=NOW) == 0

    # 회수하면 바로: 그보다 먼저 열린, 이 이슈를 가리키는 열린 PR에 댓글 한 번 + 실패 상태. 회수 뒤에 연 PR · 다른 이슈 PR은 그대로
    pull = {"number": 70, "body": "Closes #1", "created_at": "2026-11-09T08:00:00Z", "head": {"sha": "a1" * 20},
            "user": {"login": A}}
    pulls = [pull, dict(pull, number=71, created_at="2026-11-09T09:30:00Z"), dict(pull, number=72, body="Closes #2")]
    api = run(run(Fake({1: [got(PM, A), says(PM, "회수")]}, {1: [A], 70: []}, pulls=pulls), name="issue_comment"))
    assert api.assignees[1] == [] and api.statuses == [("a1" * 20, "failure")]
    assert len(api.posts) == 1 and api.posts[0].startswith(STOP + " <!--")
    # 「회수 @C」 → 새 담당 C가 push한 새 커밋은 초록(실패 상태는 앞 커밋에만), 원래 담당 A가 push하면 빨강
    api = run(Fake({1: [got(PM, A), says(PM, f"회수 @{C}")]}, {1: [A], 70: []}, pulls=[pull]), name="issue_comment")
    assert api.assignees[1] == [C] and api.statuses == [("a1" * 20, "failure")]
    assert api.posts[0].startswith(STOP_TO.format(heirs="@" + C))
    push = {"action": "synchronize", "sender": {"login": C}, "pull_request": dict(pull, head={"sha": "c3" * 20})}
    assert main(api, "pull_request", push, now=NOW) == 0 and len(api.statuses) == 1
    assert main(api, "pull_request", dict(push, sender={"login": A}), now=NOW) == 1
    # 한 시간 넘은 「회수」는 PR에 뒤늦게 남기지 않는다(담당은 그대로 기록대로)
    api = run(Fake({1: [got(PM, A), says(PM, "회수", "2026-11-09T07:00:00Z")]}, {1: [A], 70: []},
                   pulls=[dict(pull, created_at="2026-11-09T06:00:00Z")]))
    assert (api.assignees[1], api.posts, api.statuses) == ([], [], [])

    def pr(body, author, sender=None, action="opened", sha="a1" * 20, api=None):
        """PR 70 검사. 이슈 7은 A, 8은 A에게서 PM이 이어받음, 9는 PM 일에 B가 스스로 붙었다가 되돌려짐, 10은 PM이 A에게서 C로 넘김."""
        api = api or Fake({8: [got(PM, A), lost(PM, A), got(PM, PM)], 9: [got(PM, PM), got(B, B), lost(BOT, B)],
                           10: [got(PM, A), lost(PM, A), got(PM, C)]}, {7: [A], 8: [PM], 9: [PM], 10: [C], 70: []})
        event = {"action": action, "sender": {"login": sender or author},
                 "pull_request": {"number": 70, "body": body, "user": {"login": author}, "head": {"sha": sha}}}
        return main(api, "pull_request", event, now=NOW), api

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
    # 이어받기(5절): 원래 담당 A가 연 PR에 PM이 push하면 통과, 그 뒤 A가 push하면 실패
    assert pr("Closes #8", A, sender=PM, action="synchronize")[0] == 0
    assert pr("Closes #8", A, action="synchronize")[0] == 1
    assert pr("Closes #9", B, action="edited")[0] == 1  # 되돌려진 담당은 원래 담당이 아니다
    # PM이 A에게서 C로 넘긴 이슈: A가 새 PR을 열면 실패, A의 PR에 C가 push하면 통과.
    # 담당을 직접 바꾸면 A의 PR은 다음 push 때 판정된다(바로 멈추려면 「회수」 댓글)
    assert pr("Closes #10", A)[0] == 1
    assert pr("Closes #10", A, sender=C, action="synchronize")[0] == 0
    assert pr("Closes #10", A, action="edited")[0] == 0
    assert pr("Closes #7", A, sender=B, action="reopened")[0] == 1  # 다시 여는 사람도 지금 담당 · PM이어야
    assert pr("Closes #99", A)[0] == 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        with contextlib.redirect_stdout(io.StringIO()):  # 가짜 이벤트의 ::error:: 줄이 Actions 오류 표시로 잡히지 않게
            selftest()
        print("selftest ok")
        sys.exit(0)
    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as f:
        sys.exit(main(github, os.environ["GITHUB_EVENT_NAME"], json.load(f)))
