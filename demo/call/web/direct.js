// 직접 통화(배포 판). 서버 스위치 CALL_DIRECT=1일 때만 서버가 상담 화면에 이 파일을 끼운다. 끄면 불리지 않고, 화면은 main과 같다.
// 방문자가 민원인이 되어 글을 치거나 말하면(마이크는 음성 스위치를 함께 켤 때, voice.js가 받아쓴 마디를 이리로 넘긴다):
//   상담사 쪽은 화면으로만: 화면이 고른 「다음에 물을 말」을 상담사가 말한 것으로 대화창에 바로 올리고 다음 차례로 넘어간다(읽어 주지 않는다, 누르지 않아도 된다).
//   조례 답도 같은 꼴: 민원인이 조례를 물었으면 답이 올 때까지 기다렸다가 상담사 말로 올린다(「조례 근거 답」 칸에도 그대로 뜬다).
//   차례가 어긋나면: 답을 만드는 동안 들어온 말(친 글 · 받아쓴 마디)은 버리지도, 따로 답하지도 않는다. 모아 두었다가 이번 답은 버리고,
//     이번 말과 합쳐 그 차례를 처음부터 한 번에 다시 읽는다 → 결과가 「한 번에 다 말했을 때」와 같다. 늦게 오는 답은 call.js의 seq로 버린다.
// 위치를 읽는 규칙 · 서버의 읽기는 건드리지 않는다. call.js의 것(ui · S · V · seq · pollT · P · K · fill · turnReq · resetCall · render*)을 그대로 쓴다.
'use strict';
(() => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  let SETTLE = 3000;        // 받아쓴 말이 이만큼 멎어야 읽고 · 상담사 말을 올린다(말 중간 쉼으로 갈린 마디를 한 번에). 동규 11/19 「3초 정도」, 서버 CALL_DIRECT_SETTLE_MS로 바꾼다. 글은 보내기를 누르면 바로
  let SAID_MAX = 2000, INPUT_MAX = 1000;      // 서버가 한 차례에 읽는 자 수 · 입력 칸 자 수(서버 CALL_DIRECT_SAID_MAX · CALL_DIRECT_INPUT_MAX)
  let LAW_WAIT = 80000;   // 조례 답을 기다리는 가장 긴 때: 엔진 마감(75초, scoring-rules 4절)보다 조금 길게. 넘으면 「확인 불가」 말을 올리되, 늦게 온 답도 올린다(lateLaw)
  // 화면 글은 문구 파일(docs/content/A-05_통화위치좁히기.md 「직접 통화」 절)에서만
  const NAMES = { input: '입력 칸', send: '보내기', note: '안내', code: '접근 코드 묻기', badcode: '접근 코드 틀림', limit: '상한', failed: '읽지 못함', left: '남은 글자', toolong: '입력 칸 넘침', cut: '앞부분만 읽음' };
  const T = {};
  const st = { busy: false, buf: [], via: 'type', posted: new Set(), late: new Set(), lawT: {}, merged: 0, turns: 0, heard: 0 };      // posted = 조례 답을 실제로 올린 물음(답이 왔을 때만)
  const lawKey = () => (V && V.matter && V.matter.ask) || null;      // 민원인이 물은 규정 물음: 엔진이 찾는 동안에도 바뀌지 않는 열쇠

  function loadText(doc) {
    const t = (((doc && doc.sections && doc.sections['직접 통화']) || {}).tables || []).find((x) => x.head[0] === '항목'), rows = t ? Object.fromEntries(t.rows.map((r) => [r[0], r[1]])) : {};
    for (const [k, n] of Object.entries(NAMES)) T[k] = rows[n] ?? `[${n}]`;
  }
  async function japi(path, body) {
    const r = await fetch(path, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    return { ok: r.ok, d: await r.json().catch(() => ({})) };
  }
  function note(text) { ui.notice = text; renderTalk(); }
  function showBuf() { if (st.buf.length) { ui.typing = { who: '시민', text: st.buf.join(' ') }; renderTyping(); } }      // 모아 둔 말은 「치는 중」 말풍선으로 보인다(사라진 것처럼 보이지 않게)
  function heard() { st.heard = Date.now(); }      // voice.js가 받아쓴 글(도중 글 포함)이 올 때마다 부른다: 민원인이 말하는 중이다
  async function quiet() { while (Date.now() - st.heard < SETTLE && !st.buf.length) await sleep(100); }      // 민원인이 말하는 중이면 멎을 때까지(그새 마디가 들어오면 바로)
  function post(text) {      // 상담사 말: 대화창에(읽어 주지 않는다). 휴대폰으로 건 통화면 휴대폰 화면에도 글로 넘긴다
    if (window.VOICE && window.VOICE.relay) window.VOICE.relay(text);
    return turnReq({ line: { who: '상담사', text, via: 'direct' } });
  }
  function greet() { if (!S || !S.lines.length) { ui.t0 = Date.now(); return post(K('통화 글')['인사']); } }      // 전화를 받으면 상담사 인사
  function ask(text, via) {      // 민원인의 말을 통화에 넣는다. call.js citizen()과 같되, 화면의 질문을 상담사 줄로 먼저 적지 않는다(질문은 이 파일이 늘 먼저 올린다)
    if (!S) resetCall();
    if (!ui.t0) ui.t0 = Date.now();
    if (!S.lines.length) S.lines.push({ who: '상담사', text: K('통화 글')['인사'], via: 'auto' });
    return turnReq({ line: { who: '시민', text, via } });
  }

  // ---- 민원인의 말 한 마디(친 글 · 받아쓴 마디). 들어오는 대로 부르면 된다
  async function said(text, via = 'type') {
    text = String(text || '').trim();
    if (!text || ui.playing) return;      // 대본 재생 중에는 받지 않는다
    st.buf.push(text); st.via = via;
    if (st.busy) return showBuf();        // 답을 만드는 동안 들어온 말: 모아 둔다
    st.busy = true;
    try {
      if (via === 'voice') { heard(); showBuf(); while (Date.now() - st.heard < SETTLE) await sleep(100); }      // 말이 멎을 때까지 마디를 모은다
      while (st.buf.length) await turn();      // 상담사 말을 올리는 동안 또 들어온 말은 다음 차례(방금 올린 질문의 답)
    } finally { st.busy = false; }
  }
  async function turn() {
    if (ui.ended) { resetCall(); st.posted.clear(); st.late.clear(); st.lawT = {}; }      // 끝난 통화 뒤의 말은 새 통화로
    let text = st.buf.splice(0).join(' '), cut = false;
    for (;;) {
      const snap = { S: S && JSON.parse(JSON.stringify(S)), V, askQ: ui.askQ };      // 이 차례 앞의 상태: 합쳐 다시 읽을 때 돌아갈 자리
      st.turns++;
      cut = text.length > SAID_MAX;      // 서버는 앞 SAID_MAX자로 답한다. 보내는 글도 거기까지(합친 글이 아주 길어도 본문이 커지지 않게), 답한 뒤 알린다
      const ok = await ask(text.slice(0, SAID_MAX), st.via);      // ① 코드 읽기 → ② Solar 다시 읽기(실제 호출일 때)
      if (!ok) return fail();
      await waitLaw();
      await quiet();      // 답을 올리기 전에 민원인이 아직 말하는 중이면 그 마디를 기다렸다 합친다
      if (!st.buf.length) break;
      text = [text, ...st.buf.splice(0)].join(' ');      // 그동안 들어온 말: 이번 답은 버리고, 합쳐 그 차례를 처음부터 다시 읽는다
      st.merged++;
      seq++; clearTimeout(pollT);                         // 버린 차례의 늦은 답(엔진 기다림)은 받지 않는다
      S = snap.S; V = snap.V; ui.askQ = snap.askQ; ui.typing = null; renderAll();
      showBuf();
    }
    showBuf();
    await reply();
    if (cut) { const m = fill(T.cut, { N: SAID_MAX.toLocaleString() }); note(m); if (window.VOICE && window.VOICE.relay) window.VOICE.relay(m); }      // 조용히 자르지 않는다(이 차례의 다른 알림 뒤에 남게 마지막에)
  }
  async function waitLaw() {      // 조례를 물었고 엔진이 찾는 중이면 답이 올 때까지(그동안 말이 더 들어오면 멈추고 합치러 간다). 그동안 화면은 「답변을 생성하는 중」 그대로
    const key = lawKey();
    if (!key || !V.engine || V.engine.status !== 'running') return;
    st.lawT[key] = st.lawT[key] || Date.now();      // 기다림은 물음마다 처음 본 때부터 센다(차례가 합쳐져도 늘지 않게)
    while (V && V.engine && V.engine.status === 'running' && lawKey() === key && !st.buf.length && Date.now() - st.lawT[key] < LAW_WAIT) { await sleep(200); showBuf(); }
  }
  async function lateLaw(key) {      // 마감을 넘겨 안내를 올린 뒤에도 엔진 답이 오면 그 답을 올린다(같은 통화 · 끝나기 전에만)
    const sid = S && S.id;
    for (const t0 = Date.now(); Date.now() - t0 < 300000;) {
      await sleep(1000);
      if (!S || S.id !== sid || ui.ended || st.posted.has(key)) return;
      if (st.busy || lawKey() !== key || !V.engine) continue;
      if (V.engine.status === 'running') { await poll(); continue; }
      const e = V.engine;
      st.posted.add(key); st.busy = true;
      try { if (e.say || e.answer) await post(lawSay(e.say || e.answer)); while (st.buf.length) await turn(); } finally { st.busy = false; }      // 그새 들어온 말은 이어서 읽는다
      return;
    }
  }
  async function reply() {      // 상담사 말: (조례를 물었으면) 조례 답 → 다음에 물을 말, 위치를 확인받았으면 끝인사
    const M = K('일의 종류와 갈림'), C = K('통화 글'), e = V && V.engine, key = lawKey();
    if (key && e && !st.posted.has(key)) {
      if (e.status !== 'running') { st.posted.add(key); await post(e.say || e.answer ? lawSay(e.say || e.answer) : M['엔진 확인 불가 말']); }      // 답이 왔다(근거를 못 찾았으면 그 말)
      else if (Date.now() - (st.lawT[key] || Date.now()) >= LAW_WAIT && !st.late.has(key)) { st.late.add(key); await post(M['엔진 확인 불가 말']); lateLaw(key); }      // 마감을 넘김: 안내를 올리고 늦은 답은 따로
    }      // 아직 찾는 중이고 마감 전이면(말이 더 들어와 일찍 나온 차례) 조례 답은 다음 차례에
    if (V && V.confirmed) {
      await post(V.summary && V.summary.to ? fill(C['맺음말'], { '넘길 곳': V.summary.to.replace(/ · /g, ', ') }) : C['맺음말 넘길 곳 모름']);
      ui.ended = true; renderTalk();
      if (window.VOICE && window.VOICE.st && window.VOICE.st.alive) setTimeout(() => window.VOICE.hang(), 3000);      // 휴대폰 통화면 끝인사가 휴대폰에 닿을 틈을 두고 끊는다
    } else if (ui.askQ) await post(ui.askQ.say);
  }
  async function fail() {      // 서버가 받지 않았다: 상한 · 표 없음이면 그 글을, 아니면 「읽지 못함」
    st.buf.length = 0;
    const { d } = await japi('/api/direct/info');
    const m = !d.pass ? T.code : d.used >= d.max || d.left_all <= 0 ? T.limit : T.failed;
    note(m);
    if (window.VOICE && window.VOICE.relay) window.VOICE.relay(m);      // 휴대폰으로 건 통화면 휴대폰에도 같은 안내를
  }

  // ---- 화면: 대화창 아래 입력칸(새로 끼운다. call.js의 입력칸은 숨은 조작 화면 것이라 건드리지 않는다)
  function mount() {
    document.head.insertAdjacentHTML('beforeend', '<style>.d-note{display:flex;justify-content:space-between;gap:8px}#d-left{white-space:nowrap}.d-note .warn{color:var(--bad,#c0392b)}.d-say{display:flex;gap:6px}.d-say input{flex:1;min-width:0;padding:8px 10px;border-radius:8px;border:1px solid var(--line);background:var(--panel-solid);color:var(--ink);font-size:14px}.d-note{margin:0;color:var(--sub);font-size:11.5px}body.direct #k-ctl input,body.direct #k-ctl [data-act="send"],body.direct .ask .opts{display:none!important}</style>');
    document.querySelector('#talk footer').insertAdjacentHTML('afterbegin', `<form class="d-say" id="d-say"><input id="d-text" type="text" maxlength="${INPUT_MAX}" autocomplete="off" aria-label="${esc(T.input)}" placeholder="${esc(T.input)}"><button type="submit" class="primary">${esc(T.send)}</button></form><p class="d-note"><span>${esc(T.note)}</span><span id="d-left" aria-live="polite"></span></p>`);
    const el = document.getElementById('d-text'), out = document.getElementById('d-left');      // 남은 글자. 붙여 넣은 글이 넘쳐 잘리면 그렇게 알린다(조용히 자르지 않게)
    const left = (cut) => { out.textContent = cut ? fill(T.toolong, { N: INPUT_MAX.toLocaleString() }) : fill(T.left, { N: (INPUT_MAX - el.value.length).toLocaleString() }); out.classList.toggle('warn', !!cut); };
    el.addEventListener('paste', (ev) => { const add = (ev.clipboardData && ev.clipboardData.getData('text')) || ''; const cut = el.value.length - (el.selectionEnd - el.selectionStart) + add.length > INPUT_MAX; setTimeout(() => left(cut), 0); });
    el.addEventListener('input', (ev) => { if (ev.inputType !== 'insertFromPaste') left(false); });
    left(false);
    document.getElementById('d-say').addEventListener('submit', (ev) => {      // 답을 기다리는 동안에도 받는다(모아 두었다 합친다)
      ev.preventDefault();
      const el = document.getElementById('d-text'), v = el.value.trim();
      if (v) { el.value = ''; left(false); said(v, 'type'); }
    });
    document.addEventListener('click', (ev) => {      // 「전화가 왔습니다 · 받기」: 직접 통화에서는 상담사 인사를 올리고 입력칸으로
      if (ui.scene === 'free' && ev.target.closest('#lines [data-act="play"]')) {
        ev.stopPropagation(); ev.preventDefault();
        greet();
        document.getElementById('d-text').focus();
      }
    }, true);
  }

  window.DIRECT = { said, heard, greet, st };      // voice.js(받아쓴 마디) · 점검이 쓴다
  (async () => {
    const info = (await japi('/api/direct/info')).d;
    if (!info.on) return;
    SETTLE = info.settle_ms || SETTLE; SAID_MAX = info.said_max || SAID_MAX; INPUT_MAX = info.input_max || INPUT_MAX; LAW_WAIT = info.law_wait_ms || LAW_WAIT;
    while (!window.CALL) await sleep(50);      // call.js가 시작을 다 마친 뒤에(문구를 받은 뒤 참고 자료 · 상담 기록을 받고 통화를 한 번 더 비운다. 그 전에 시작하면 첫 말이 지워진다)
    loadText(DOC);
    document.body.classList.add('direct');
    if (!info.pass) {      // 표(쿠키)를 받는다. 접근 코드가 있으면 묻는다
      const r = await japi('/api/direct/enter', { code: info.code ? (window.prompt(T.code) || '') : '' });
      if (!r.ok) return note(T.badcode);
    }
    if (!P.get('scene') && !P.get('auto')) { ui.scene = 'free'; ui.input = 'type'; resetCall(); }      // 배포 판은 직접 통화로 연다(장면 단추 · 주소 옵션은 그대로)
    mount();
  })();
})();
