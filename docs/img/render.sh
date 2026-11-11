#!/usr/bin/env bash
# docs/img의 그림(PNG)을 원본 HTML에서 다시 만든다. 레포 맨 위 폴더에서: bash docs/img/render.sh
# 창을 띄우지 않는 크롬(headless)으로 찍는다. 글꼴 Do Hyeon · Pretendard가 깔려 있어야 한다.
# 인자를 주면 그 그림만 만든다: bash docs/img/render.sh engine-status
set -euo pipefail
cd "$(dirname "$0")"
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
PROFILE="$(mktemp -d)"   # 쓰던 크롬 창과 섞이지 않게 빈 프로필로 연다

shot() {  # shot <만들 PNG> <원본 HTML#장> <창 높이>
  "$CHROME" --headless=new --hide-scrollbars --force-device-scale-factor=1 --user-data-dir="$PROFILE" \
    --window-size="1080,$3" --screenshot="$PWD/$1" "file://$PWD/$2" >/dev/null 2>&1
  [ -s "$1" ] && echo "만듦: docs/img/$1"
}

want="${1:-all}"
if [ "$want" = all ] || [ "$want" = work-method ]; then
  for n in 1 2 3 4; do shot "work-method-$n.png" "work-method.html#p$n" 2340; done
fi
if [ "$want" = all ] || [ "$want" = engine-status ]; then
  shot "engine-status.png" "engine-status.html#p1" 2340
fi
if [ "$want" = all ] || [ "$want" = evaluation ]; then
  shot "evaluation.png" "evaluation.html#p1" 2340
fi
