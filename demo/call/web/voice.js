// 음성 통화. 서버 스위치(CALL_VOICE=1)가 켜졌을 때만 서버가 상담 화면에 이 파일을 끼운다. 끄면 불리지 않고, 화면은 main과 같다.
// 전화 한 통 = 방 하나(/api/voice/…, demo/call/voice/hub.py). 방에는 두 쪽이 붙는다.
//   소리 쪽(caller): 마이크 소리를 0.25초 토막으로 올리고, 읽어 줄 말을 받아 튼다. 휴대폰은 dial.html이 이쪽만 한다. 나중에 전화 회선이 이 자리에 온다.
//   화면 쪽(desk):   받아쓴 글을 받아 적기 칸에 올리고, 확정된 말을 지금의 통화 길(citizen → /api/turn)에 그대로 넣고, 화면이 띄운 질문을 읽어 달라고 넘긴다.
// 위치 좁히기 · 질문 고르기는 건드리지 않는다. call.js의 것(ui · S · V · citizen · turnReq · queue …)을 그대로 불러 쓴다.
// 주소 옵션(점검 · 녹화용): ?mic=script 열자마자 대본 글을 소리 대신 흘려 장면을 끝까지 · ?quiet=1 아무 소리도 틀지 않는다(글 길이만큼 기다림)
'use strict';
(() => {
  const Q = new URLSearchParams(location.search), QUIET = Q.get('quiet') === '1';
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const fast = () => (typeof SPEED === 'number' ? SPEED : 1);
  // 이 스위치가 켜졌을 때만 보이는 글. 본 화면에 올리기로 하면 문구 파일(docs/content/A-05_통화위치좁히기.md)로 옮긴다
  const T = { here: '이 기기 마이크로 통화', phone: '휴대폰으로 걸기', script: '대본을 음성 길로', hang: '끊기', fake: '받아쓰기: 가짜(대본 글 · 친 글)', rtzr: '받아쓰기: 리턴제로',
    listen: '듣는 중', speak: '읽어 주는 중', wait: '거는 사람을 기다리는 중', link: '휴대폰에서 이 주소를 엽니다', over: '통화가 끝났습니다', down: '받아쓰기가 끊겼습니다',
    nomic: '마이크를 쓸 수 없습니다. 브라우저의 마이크 허락과 https 주소인지 확인해 주세요.', code: '접근 코드', heard: '들어온 소리 {초}초',
    off: '음성 통화가 꺼져 있습니다.', dial: '전화 걸기', dialLead: '상담 화면의 통화에 이 휴대폰의 마이크로 들어갑니다.', noroom: '상담 화면에서 받은 주소로 열어 주세요.', say: '말할 글(가짜 받아쓰기)', send: '말하기' };

  async function vapi(path, body, raw) {
    const r = await fetch('/api/voice/' + path, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': raw ? 'application/octet-stream' : 'application/json' }, body: raw ? body : JSON.stringify(body) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.error || r.status);
    return d;
  }

  // ---- 읽어 주기: 미리 만든 파일(서버 web/voice/tts/) → 기기에 든 읽어 주기(CALL_VOICE_TTS=browser일 때만) → 소리 없이 글 길이만큼 기다림
  const player = new Audio();
  async function speakOut(text, info) {
    const quietMs = Math.min(9000, 600 + text.length * 95) / fast();
    if (QUIET) return sleep(quietMs);
    try {
      const r = await fetch('/api/voice/say?text=' + encodeURIComponent(text));
      if (r.ok) {
        player.src = URL.createObjectURL(await r.blob());
        return await new Promise((done) => { player.onended = player.onerror = done; player.play().catch(done); });
      }
    } catch { /* 파일이 없으면 다음 길로 */ }
    if (info.tts === 'browser' && window.speechSynthesis) {
      return new Promise((done) => {
        const u = new SpeechSynthesisUtterance(text);
        u.lang = 'ko-KR'; u.onend = u.onerror = done;
        setTimeout(done, 4000 + text.length * 300);      // 끝났다는 신호를 주지 않는 기기가 있다
        speechSynthesis.speak(u);
      });
    }
    return sleep(quietMs);
  }

  // ---- 소리 쪽: 마이크 → 서버, 읽어 줄 말 → 스피커. 읽어 주는 동안에는 마이크 소리를 0으로 보낸다(제 목소리를 받아쓰지 않게, 줄은 살아 있게)
  function Caller(room, info, on) {
    let ctx = null, stream = null, chunks = [], muted = false, alive = true, seen = 0, played = 0;
    const todo = [];
    async function mic() {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
      ctx = new (window.AudioContext || window.webkitAudioContext)();
      const node = ctx.createScriptProcessor(4096, 1, 1);      // ponytail: 낡은 길(ScriptProcessor)이지만 파일 하나로 어디서나 돈다. 소리가 끊기면 AudioWorklet으로
      node.onaudioprocess = (e) => {
        const f = e.inputBuffer.getChannelData(0), o = new Int16Array(f.length);
        if (!muted) for (let i = 0; i < f.length; i++) o[i] = Math.max(-1, Math.min(1, f[i])) * 32767;
        chunks.push(o);
      };
      ctx.createMediaStreamSource(stream).connect(node); node.connect(ctx.destination);      // 나가는 소리는 0이다(이어야 onaudioprocess가 돈다)
      return ctx.sampleRate;      // 기기의 표본화 주파수를 그대로 알린다(리턴제로는 8000~48000Hz를 받는다)
    }
    async function loop() {
      while (alive) {
        const n = chunks.reduce((s, c) => s + c.length, 0), all = new Int16Array(n);
        let at = 0; for (const c of chunks) { all.set(c, at); at += c.length; }
        chunks = [];
        try {
          const d = await vapi(`audio?room=${room}&says=${seen}&played=${played}`, all.buffer, true);
          for (const s of d.says) { seen = s.n; todo.push(s); }
          if (d.down) on('down');
        } catch { stop(); on('over'); return; }
        await sleep(250);
      }
    }
    async function mouth() {      // 읽어 줄 말을 온 순서대로 하나씩
      while (alive) {
        const s = todo.shift();
        if (!s) { await sleep(80); continue; }
        muted = true; on('speak', s.text);
        await speakOut(s.text, info);
        muted = false; played = s.n; on('listen', s.text);
      }
    }
    function stop() { alive = false; if (stream) stream.getTracks().forEach((t) => t.stop()); if (ctx) ctx.close().catch(() => {}); }
    return {
      async start(useMic) {
        let rate = 16000;
        if (useMic) rate = await mic();
        await vapi(`join?room=${room}&rate=${Math.round(rate)}`, {});
        loop(); mouth();
      },
      fake: (text) => vapi(`fake?room=${room}`, { text }),      // 가짜 받아쓰기일 때: 이 글을 「말한다」
      stop,
    };
  }

  // ---- 휴대폰 화면(dial.html): 소리 쪽만
  async function dialPage(info) {
    const $ = (id) => document.getElementById(id), room = (Q.get('room') || '').replace(/[^0-9a-f]/g, '');
    $('d-lead').textContent = room ? T.dialLead : T.noroom;
    $('d-stt').textContent = T[info.stt];
    const btn = $('d-call'); btn.textContent = T.dial; btn.disabled = !room;
    let c = null;
    btn.onclick = async () => {
      if (c) { c.stop(); c = null; btn.textContent = T.dial; $('d-state').textContent = T.over; return; }
      c = Caller(room, info, (s, text) => { $('d-state').textContent = { speak: T.speak, listen: T.listen, over: T.over, down: T.down }[s]; if (s === 'speak') $('d-said').textContent = text; if (s === 'over') { c = null; btn.textContent = T.dial; } });
      try { await c.start(true); } catch { $('d-state').textContent = T.nomic; c = null; return; }
      btn.textContent = T.hang; $('d-state').textContent = T.listen;
      $('d-fake').hidden = info.stt !== 'fake';
    };
    $('d-text').placeholder = T.say; $('d-send').textContent = T.send;
    $('d-fake').onsubmit = (ev) => { ev.preventDefault(); const v = $('d-text').value.trim(); if (v && c) { c.fake(v); $('d-text').value = ''; } };
  }

  // ---- 상담 화면: 화면 쪽(+ 이 기기 마이크 · 대본이면 소리 쪽도 함께)
  function deskPage(info) {
    const st = { room: null, caller: null, alive: false, how: '', since: 0, played: 0, heard: 0, joined: false, text: '', gapT: 0, busy: false, spoken: null, state: '', link: '' };
    document.head.insertAdjacentHTML('beforeend', '<style>#t-mic button.on{background:var(--ink);color:var(--panel-solid)}#notice{user-select:all;word-break:break-all}</style>');
    document.querySelector('header.top').insertAdjacentHTML('beforeend', '<span class="lab" id="voice-box" role="status"></span><div class="seg" role="group" id="t-mic" aria-label="음성 통화"></div>');
    const bar = document.getElementById('t-mic'), box = document.getElementById('voice-box');
    function draw() {
      bar.innerHTML = st.alive ? `<button type="button" class="on" data-mic="hang">${esc(T.hang)}</button>`
        : [['here', T.here], ['phone', T.phone]].concat(info.stt === 'fake' && SCRIPTS[ui.scene] ? [['script', T.script]] : []).map(([id, name]) => `<button type="button" data-mic="${id}">${esc(name)}</button>`).join('');
      box.textContent = st.state ? `${T[info.stt]} · ${st.state}` + (st.heard ? ` · ${T.heard.replace('{초}', st.heard.toFixed(1))}` : '') : '';
      const link = st.alive && st.how === 'phone' && !st.joined ? `${T.link}: ${location.origin}/dial.html?room=${st.room}` : '';      // 거는 사람이 들어올 때까지 받아 적기 칸의 알림 자리에
      if (link !== st.link) { ui.notice = st.link = link; renderTalk(); }
    }
    function say(s) { st.state = s; draw(); }
    function onEvent(e) {      // 받아쓴 글: 도중 글은 받아 적기 칸에 흐르고, 확정 글 뒤 잠깐 조용하면 한 차례로 끊어 통화 길에 넣는다
      clearTimeout(st.gapT);
      if (e.final) { st.text = `${st.text} ${e.text}`.trim(); st.gapT = setTimeout(commit, info.gap_ms / fast()); }
      ui.typing = { who: '시민', text: e.final ? st.text : `${st.text} ${e.text}`.trim() }; renderTyping();
    }
    function commit() {
      const t = st.text; st.text = ''; st.spoken = null;      // 같은 질문이 다시 떠도 읽어 주게
      if (t && st.alive) queue(() => citizen(t, 'voice'));
    }
    async function poll2() {
      while (st.alive) {
        try {
          const d = await vapi(`desk?room=${st.room}&since=${st.since}`);
          st.since = d.next; st.played = d.played; st.heard = d.heard_sec;
          if (d.joined !== st.joined) { st.joined = d.joined; if (d.joined) drive(); }
          if (d.down) say(T.down);
          d.events.forEach(onEvent);
          draw();
        } catch { return hang(T.over); }
        await sleep(250);
      }
    }
    async function agentSay(text) {      // 통화 글에 적고(지금 물을 말은 바꾸지 않는다), 소리 쪽에 읽어 달라고 넘기고, 다 읽을 때까지 기다린다
      st.busy = true; say(T.speak);
      await queue(() => turnReq({ line: { who: '상담사', text, via: 'voice' } }));
      try {
        const { n } = await vapi(`ask?room=${st.room}`, { text }), t0 = Date.now(), cap = (5000 + text.length * 300) / fast();
        while (st.alive && st.played < n && Date.now() - t0 < cap) await sleep(100);
      } catch { /* 방이 닫혔으면 poll2가 끊는다 */ }
      st.busy = false; if (st.alive) say(T.listen);
    }
    async function drive() {      // 화면이 띄운 것을 차례로 읽는다: 인사 → (조례 답) → 질문 … → 맺음말. 단추 · 되돌리기로 질문이 바뀌어도 바뀐 것을 읽는다
      const C = K('통화 글');
      ui.t0 = Date.now();
      await agentSay(C['인사']);
      while (st.alive) {
        await sleep(150);
        if (ui.pending || st.busy || st.text || ui.typing || !V) continue;
        if (V.matter && V.matter.ask && V.engine && !ui.answered) {      // 시민이 규정을 물었으면 조례 답을 한 번 읽는다(대본 재생과 같은 순서)
          ui.answered = true;
          while (st.alive && V.engine && V.engine.status === 'running') { await sleep(400); await poll(); }
          await agentSay((V.engine && (V.engine.say || V.engine.answer)) || K('일의 종류와 갈림')['엔진 확인 불가 말']);
          continue;
        }
        if (V.confirmed) {
          await agentSay(V.summary.to ? fill(C['맺음말'], { '넘길 곳': V.summary.to.replace(/ · /g, ', ') }) : C['맺음말 넘길 곳 모름']);
          ui.ended = true; renderTalk();      // 「넘김」은 상담사가 고른다(대본 재생처럼 대신 고르지 않는다)
          return hang(T.over);
        }
        const q = ui.askQ, key = q && `${q.id}|${q.say}`;
        if (q && key !== st.spoken) {
          st.spoken = key;
          await agentSay(q.say);
          if (st.how === 'script' && st.alive && ui.askQ === q) { const a = SCRIPTS[ui.scene][q.id]; if (a) st.caller.fake(a); else return hang(C['대본에 없는 질문']); }
        } else if (st.how === 'script' && !q && !S.turns.length && !st.said1) { st.said1 = true; st.caller.fake(SCRIPTS[ui.scene]['처음']); }      // 인사 뒤 첫 말
      }
    }
    async function start(how) {
      if (st.alive) return;
      let code = sessionStorage.getItem('voice-code') || '';
      if (info.code && !code) { code = window.prompt(T.code) || ''; sessionStorage.setItem('voice-code', code); }
      resetCall();
      try { st.room = (await vapi('room', { code })).room; } catch (e) { sessionStorage.removeItem('voice-code'); return say(String(e.message)); }
      Object.assign(st, { alive: true, how, since: 0, played: 0, heard: 0, joined: false, text: '', busy: false, spoken: null, said1: false, caller: null });
      say(how === 'phone' ? T.wait : T.listen);
      if (how !== 'phone') {
        st.caller = Caller(st.room, info, (s) => { if (s === 'down') say(T.down); });
        try { await st.caller.start(how === 'here'); } catch { return hang(T.nomic); }
      }
      poll2();
    }
    function hang(why) {
      if (!st.alive) return;
      st.alive = false; clearTimeout(st.gapT);
      if (st.caller) st.caller.stop();
      vapi(`end?room=${st.room}`, {}).catch(() => {});
      ui.typing = null; renderTalk(); say(why || T.over);
    }
    bar.addEventListener('click', (ev) => { const b = ev.target.closest('button'); if (!b) return; ev.stopPropagation(); if (b.dataset.mic === 'hang') hang(); else start(b.dataset.mic); });
    document.addEventListener('click', (ev) => { if (ev.target.closest('[data-scene]')) setTimeout(draw, 0); });      // 장면을 바꾸면 「대본을 음성 길로」 단추가 그 장면에 맞게
    window.VOICE = { st, start, hang };      // 점검용
    draw();
    if (Q.get('mic')) start(Q.get('mic'));
  }

  (async () => {
    const info = await fetch('/api/voice/info').then((r) => (r.ok ? r.json() : null)).catch(() => null);
    if (!info || !info.on) { const el = document.getElementById('d-lead'); if (el) el.textContent = T.off; return; }      // 스위치가 꺼져 있으면 휴대폰 화면만 그 사실을 알린다
    if (typeof citizen !== 'function') return dialPage(info);
    while (!DOC) await sleep(50);      // call.js가 문구를 다 받은 뒤에
    deskPage(info);
  })();
})();
