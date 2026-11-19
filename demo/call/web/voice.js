// 음성 통화. 서버 스위치(CALL_VOICE=1)가 켜졌을 때만 서버가 상담 화면에 이 파일을 끼운다. 끄면 불리지 않고, 화면은 main과 같다.
// 전화 한 통 = 방 하나(/api/voice/…, demo/call/voice/hub.py). 방에는 두 쪽이 붙는다.
//   소리 쪽(caller): 마이크 소리를 0.25초 토막으로 올리고, 읽어 줄 말을 받아 튼다. 휴대폰은 dial.html이 이쪽만 한다. 나중에 전화 회선이 이 자리에 온다.
//   화면 쪽(desk):   전화를 받고, 받아쓴 글을 받아 적기 칸에 올리고, 확정된 말을 지금의 통화 길(citizen → /api/turn)에 그대로 넣고, 화면이 띄운 질문을 읽어 달라고 넘긴다.
// 위치 좁히기 · 질문 고르기는 건드리지 않는다. call.js의 것(ui · S · V · citizen · turnReq · queue …)을 그대로 불러 쓴다.
// 질문을 누가 말하나(서버 CALL_VOICE_ASK, 주소 ?ask=): ai = 화면이 띄운 질문을 읽어 준다 · agent = 상담사가 직접 말한다(읽어 주지 않는다. 한 기기 마이크면 상담사가 말하는 동안 스페이스를 누르고 있는다)
// 대본을 음성 길로(?mic=script · 단추): 가짜 받아쓰기면 대본 글을 소리 대신 흘리고, 진짜 받아쓰기면 시민 역 소리 파일(web/voice/citizen/, tts_lines.py --citizen)을 마이크 대신 실제 속도로 보낸다
// 주소 옵션(점검 · 녹화용): ?mic=script 열자마자 대본을 음성 길로 · ?quiet=1 아무 소리도 틀지 않는다(글 길이만큼 기다림)
'use strict';
(() => {
  const Q = new URLSearchParams(location.search), QUIET = Q.get('quiet') === '1';
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const fast = () => (typeof SPEED === 'number' ? SPEED : 1);
  const esc = (x) => String(x ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));      // 휴대폰 화면에는 call.js가 없다
  const mmss = (ms) => `${String(Math.floor(ms / 60000)).padStart(2, '0')}:${String(Math.floor(ms / 1000) % 60).padStart(2, '0')}`;
  // 화면 글은 문구 파일(docs/content/A-05_통화위치좁히기.md 「음성 통화」 절)에서만 가져온다. 왼쪽 = 이 파일 안의 이름, 오른쪽 = 문구 표의 항목
  const NAMES = { here: '단추 · 이 기기 마이크', phone: '단추 · 휴대폰으로 걸기', script: '단추 · 대본을 음성 길로', pick: '단추 · 받기', hang: '단추 · 끊기',
    fake: '받아쓰기 · 가짜', elevenlabs: '받아쓰기 · 일레븐랩스', whisper: '받아쓰기 · 이 컴퓨터 안', rtzr: '받아쓰기 · 리턴제로',
    listen: '상태 · 듣는 중', speak: '상태 · 읽어 주는 중', wait: '상태 · 거는 사람 기다림', ring: '상태 · 전화 옴', over: '상태 · 통화 끝', down: '상태 · 받아쓰기 끊김',
    hold: '상태 · 상담사가 말하는 중', agent: '상태 · 상담사가 직접 묻는 통화', taken: '상태 · 상담사가 넘겨받음', approve: '상태 · 접수 확인 기다림', heard: '상태 · 들어온 소리',
    link: '안내 · 휴대폰 주소', nomic: '안내 · 마이크 못 씀', noline: '안내 · 민원인 역 소리 없음', code: '안내 · 접근 코드', badcode: '안내 · 접근 코드 틀림', full: '안내 · 통화 꽉 참', shaky: '상태 · 연결 불안정', lost: '상태 · 연결 끊김',
    dialName: '휴대폰 · 이름', dialLead: '휴대폰 · 안내', noroom: '휴대폰 · 주소 없음', off: '휴대폰 · 꺼짐', dial: '휴대폰 · 전화 걸기', calling: '휴대폰 · 연결 중', talking: '휴대폰 · 통화 중', say: '휴대폰 · 말할 글', send: '휴대폰 · 말하기', micOn: '휴대폰 · 마이크 켜기', agentName: '휴대폰 · 상담사', meName: '휴대폰 · 나',
    left: '휴대폰 · 남은 글자', toolong: '휴대폰 · 입력 칸 넘침', notsent: '휴대폰 · 못 보냄', busy: '휴대폰 · 다른 통화 중', nodesk: '휴대폰 · 받을 사람 없음' };
  const T = {};
  function loadText(doc) {      // 문구 표 → T. 표에 없는 이름은 [이름]으로 보여 빠진 글을 바로 알아보게(call.js의 K와 같은 버릇)
    const t = (((doc && doc.sections && doc.sections['음성 통화']) || {}).tables || []).find((x) => x.head[0] === '항목'), rows = t ? Object.fromEntries(t.rows.map((r) => [r[0], r[1]])) : {};
    for (const [k, n] of Object.entries(NAMES)) T[k] = rows[n] ?? `[${n}]`;
  }

  async function vapi(path, body, raw) {
    const r = await fetch('/api/voice/' + path, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': raw ? 'application/octet-stream' : 'application/json' }, body: raw ? body : JSON.stringify(body) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw Object.assign(new Error(d.error || r.status), { status: r.status });
    return d;
  }
  const failText = (e) => (e.status === 403 ? T.badcode : e.status === 429 ? T.full : T.over);      // 서버는 오류 종류만 준다. 화면 글은 문구 파일에서
  // 망이 잠깐 끊긴 것(응답 없음 · 5xx · 408 · 429)은 간격을 늘려 다시 한다. 끝난 통화(404) · 막힘(403 · 413 · 415)은 바로 그만둔다
  const shaky = (e) => !e.status || e.status >= 500 || e.status === 408 || e.status === 429;
  const backoff = (k, ms) => sleep(Math.min(3000, ms * 2 ** k));
  const SHAKY_MS = 3000, LOST_MS = 60000;      // 이만큼 이어서 안 되면 「연결이 불안정합니다」 · 통화를 마친다(방은 서버에서 90초 동안 남는다)
  async function again(fn, ms = 15000) {      // 한 번 보내는 요청(친 글 · 상담사 말 넘기기 · 받기): ms 넘게 안 되면 마지막 오류를 던진다
    for (let k = 0, t0 = Date.now(); ; k++) {
      try { return await fn(); } catch (e) { if (!shaky(e) || Date.now() - t0 > ms) throw e; await backoff(k, 300); }
    }
  }
  function fitInput(el, max, out, T0) {      // 입력 칸 자 수: 남은 글자를 보이고, 붙여 넣은 글이 넘쳐 잘리면 그렇게 알린다(조용히 자르지 않게)
    const draw = (cut) => { out.textContent = cut ? fillT(T0.toolong, { N: max.toLocaleString() }) : fillT(T0.left, { N: (max - el.value.length).toLocaleString() }); out.classList.toggle('warn', !!cut); };
    el.maxLength = max;
    el.addEventListener('paste', (ev) => { const add = (ev.clipboardData && ev.clipboardData.getData('text')) || ''; const cut = el.value.length - (el.selectionEnd - el.selectionStart) + add.length > max; setTimeout(() => draw(cut), 0); });
    el.addEventListener('input', (ev) => { if (ev.inputType !== 'insertFromPaste') draw(false); });
    draw(false);
    return () => draw(false);
  }
  const fillT = (s, o) => String(s ?? '').replace(/\{([^}]+)\}/g, (m, k) => (o[k] ?? m));      // 휴대폰 화면에는 call.js의 fill이 없다

  // ---- 읽어 주기: 미리 만든 파일(서버 web/voice/tts/) → 기기에 든 읽어 주기(CALL_VOICE_TTS=browser일 때만) → 소리 없이 글 길이만큼 기다림
  const player = new Audio();
  let interrupt = () => {};      // 넘겨받기: 지금 읽는 말을 그 자리에서 끝낸다
  function speakOut(text, info) { return new Promise((done) => { interrupt = done; speakOn(text, info).then(done); }); }
  async function speakOn(text, info) {
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
  // 연결음(거는 쪽): 440Hz + 480Hz를 1초 울리고 2초 쉰다. 모델이 아니라 소리 두 줄이다. ?quiet=1이면 내지 않는다. 돌려주는 것 = 그치는 함수
  function ringback() {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (QUIET || !AC) return () => {};
    const c = new AC(), g = c.createGain(), beep = () => { const n = c.currentTime; g.gain.setValueAtTime(0.07, n); g.gain.setValueAtTime(0, n + 1); };
    g.gain.value = 0; g.connect(c.destination);
    for (const f of [440, 480]) { const o = c.createOscillator(); o.frequency.value = f; o.connect(g); o.start(); }
    beep();
    const t = setInterval(beep, 3000);
    return () => { clearInterval(t); c.close().catch(() => {}); };
  }

  // ---- 소리 쪽: 마이크 → 서버, 읽어 줄 말 → 스피커. 상담 화면이 받기 전과 읽어 주는 동안에는 마이크 소리를 0으로 보낸다(연결음 · 제 목소리를 받아쓰지 않게, 줄은 살아 있게)
  function Caller(room, info, on) {
    let ctx = null, stream = null, chunks = [], alive = true, seen = 0, played = 0, picked = false, speaking = false, tape = null, tape0 = 0, sent = 0, cut = 0;      // tape: 마이크 대신 보낼 소리(16kHz)
    const me = { hold: false }, todo = [];
    async function mic() {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
      ctx = new (window.AudioContext || window.webkitAudioContext)();
      const node = ctx.createScriptProcessor(4096, 1, 1);      // ponytail: 낡은 길(ScriptProcessor)이지만 파일 하나로 어디서나 돈다. 소리가 끊기면 AudioWorklet으로
      node.onaudioprocess = (e) => {
        const f = e.inputBuffer.getChannelData(0), o = new Int16Array(f.length);
        if (picked && !speaking && !me.hold) for (let i = 0; i < f.length; i++) o[i] = Math.max(-1, Math.min(1, f[i])) * 32767;
        chunks.push(o);
      };
      ctx.createMediaStreamSource(stream).connect(node); node.connect(ctx.destination);      // 나가는 소리는 0이다(이어야 onaudioprocess가 돈다)
      return ctx.sampleRate;      // 기기의 표본화 주파수를 그대로 알린다(서버가 맞춘다)
    }
    async function loop() {
      const POLL = info.poll_ms || 250;
      let bad = 0, k = 0, warned = false;
      while (alive) {
        if (tape) {      // 마이크 대신: 흐른 시간만큼(실제 속도) 소리 파일을 보내고, 없으면 조용한 소리를 보낸다(받아쓰기가 말끝을 알게)
          const due = Math.round((performance.now() - tape0) / 1000 * 16000) - sent, o = new Int16Array(Math.max(0, due));
          o.set(tape.q.subarray(0, o.length)); tape.q = tape.q.subarray(o.length); sent += o.length; chunks.push(o);
        }
        const n = chunks.reduce((s, c) => s + c.length, 0), all = new Int16Array(n);
        let at = 0; for (const c of chunks) { all.set(c, at); at += c.length; }
        chunks = [];
        try {
          const d = ctx || tape ? await vapi(`audio?room=${room}&says=${seen}&played=${played}`, all.buffer, true)
            : await vapi(`poll?room=${room}&says=${seen}&played=${played}`);      // 글로만 붙었으면 소리를 올리지 않는다(본문 없는 GET)
          if (warned) on('steady');
          bad = 0; k = 0; warned = false; me.busy = d.busy;
          if (d.picked && !picked) { picked = true; on('picked'); }
          if (d.cut > cut) { cut = d.cut; todo.length = 0; player.pause(); if (window.speechSynthesis) speechSynthesis.cancel(); interrupt(); }      // 상담사가 넘겨받음: 읽던 말 · 남은 말을 버린다
          for (const s of d.says) { seen = s.n; todo.push(s); }
          if (d.down) on('down');
        } catch (e) {
          if (!alive) return;
          if (!shaky(e)) { stop(); on('over'); return; }
          bad = bad || Date.now();
          if (!warned && Date.now() - bad > SHAKY_MS) { warned = true; on('shaky'); }
          if (Date.now() - bad > LOST_MS) { stop(); on('lost'); return; }
          await backoff(k++, POLL); continue;
        }
        await sleep(POLL);
      }
    }
    async function mouth() {      // 읽어 줄 말을 온 순서대로 하나씩
      while (alive) {
        const s = todo.shift();
        if (!s) { await sleep(80); continue; }
        if (info.direct) { on('speak', s.text); played = s.n; on('listen', s.text); continue; }      // 직접 통화(배포 판): 읽어 주지 않고 글로만 바로 보인다
        speaking = true; on('speak', s.text);
        await speakOut(s.text, info);
        speaking = false; played = s.n; on('listen', s.text);
      }
    }
    function stop() { alive = false; if (stream) stream.getTracks().forEach((t) => t.stop()); if (ctx) ctx.close().catch(() => {}); }
    return Object.assign(me, {
      async start(useMic, useTape, textOnly) {
        let rate = 16000;
        if (useMic) rate = await mic();
        if (useTape) { tape = { q: new Int16Array(0) }; tape0 = performance.now(); }
        await vapi(textOnly ? `join?room=${room}&text=1` : `join?room=${room}&rate=${Math.round(rate)}`, {});      // 글로만 붙으면 받아쓰기를 열지 않는다
        loop(); mouth();
      },
      async enableMic() { const rate = await mic(); await vapi(`join?room=${room}&rate=${Math.round(rate)}`, {}); },      // 글로 하던 통화에 마이크를 더한다
      text: (t) => { const id = Math.random().toString(36).slice(2); return again(() => vapi(`text?room=${room}`, { text: t, id })); },      // 민원인이 친 글 한 줄(다시 보내도 서버가 한 번만 받는다)
      fake: (text) => vapi(`fake?room=${room}`, { text }),      // 가짜 받아쓰기일 때: 이 글을 「말한다」
      async line(text) {      // 진짜 받아쓰기일 때: 이 글의 시민 역 소리를 마이크 대신 보낸다 → 없으면 false
        const r = await fetch('/api/voice/line?text=' + encodeURIComponent(text));
        if (!r.ok || !tape) return false;
        const b = await r.arrayBuffer(), pcm = new Int16Array(b.slice(44));      // 우리가 만든 wav(머리 44바이트, 16kHz 한 줄기)
        const q = new Int16Array(tape.q.length + pcm.length); q.set(tape.q); q.set(pcm, tape.q.length); tape.q = q;
        return true;
      },
      hangup() { stop(); return vapi(`end?room=${room}`, {}).catch(() => {}); },      // 끊는다(상대 쪽도 곧 안다)
      stop,
    });
  }

  // ---- 휴대폰 화면(dial.html): 소리 쪽(민원인). 전화 걸기 → 연결음 → (상담 화면이 받으면) 통화 중 00:12 → 끊기
  //   글을 치면 통화로 들어가고(받아쓰기를 거치지 않음), 상담사 말(질문 · 조례 답 · 끝인사)은 이 화면의 대화창에 글로 뜬다. 마이크는 「마이크로도 말하기」를 눌렀을 때만.
  //   직접 통화(배포 판)에서는 주소에 방이 없어도 건다: 방이 「기다림」으로 열리고, 직접 통화를 켠 상담 화면이 와서 받는다. 읽어 주지 않는다.
  async function dialPage(info) {
    const $ = (id) => document.getElementById(id), log = $('d-log');
    let room = (Q.get('room') || '').replace(/[^0-9a-f]/g, '');
    const btn = $('d-call'), set = (cls, line) => { document.body.dataset.call = cls; $('d-state').textContent = shaking ? T.shaky : line; btn.textContent = cls === 'idle' || cls === 'over' ? T.dial : T.hang; };
    let c = null, t0 = 0, tick = 0, quietRing = () => {}, shaking = false, nopick = 0, redraw = () => {};
    $('d-name').textContent = T.dialName; $('d-lead').textContent = room || info.direct ? T.dialLead : T.noroom; $('d-stt').textContent = info.direct ? '' : T[info.stt];
    $('d-text').placeholder = T.say; $('d-send').textContent = T.send; $('d-mic').textContent = T.micOn;
    set('idle', ''); btn.disabled = true;      // 누르는 일을 다 붙인 뒤(맨 아래)에 켠다: 망이 느리면 먼저 켜진 단추의 첫 누름이 버려졌다(배포 세션 11/19)
    if (info.direct) {      // 직접 통화: 표(쿠키)를 받는다. 접근 코드가 있으면 묻는다
      const d = await fetch('/api/direct/info').then((r) => r.json()).catch(() => ({}));
      if (d.on && !d.pass) {
        const r = await fetch('/api/direct/enter', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code: d.code ? (window.prompt(T.code) || '') : '' }) });
        if (!r.ok) { btn.disabled = true; return set('over', T.code); }
      }
      redraw = fitInput($('d-text'), d.input_max || 1000, $('d-left'), T);      // 직접 통화: 입력 칸 1,000자(서버는 한 차례 2,000자까지 읽는다)
    }
    function bubble(who, text) { log.insertAdjacentHTML('beforeend', `<li class="${who}"><b>${esc(who === 'me' ? T.meName : T.agentName)}</b><span>${esc(text)}</span></li>`); log.scrollTop = log.scrollHeight; return log.lastElementChild; }
    function over(line) { quietRing(); clearInterval(tick); clearTimeout(nopick); c = null; shaking = false; set('over', `${line || T.over}${t0 ? ' · ' + mmss(Date.now() - t0) : ''}`); t0 = 0; $('d-form').hidden = true; $('d-left').hidden = true; $('d-mic').hidden = true; if (info.direct) room = ''; requestAnimationFrame(() => { log.scrollTop = log.scrollHeight; }); }      // 끝나면 위 그림이 다시 커져 마지막 말이 밀리니 한 번 더 내린다
    btn.onclick = async () => {
      if (c) { const x = c; c = null; x.hangup(); return over(); }
      log.innerHTML = ''; $('d-said').textContent = '';
      if (!room) { try { room = (await vapi('room', { from: 'phone' })).room; } catch (e) { return set('over', failText(e)); } }      // 직접 통화: 상담 화면이 와서 받는다
      const mine = c = Caller(room, info, (s, text) => {
        if (c !== mine) return;      // 이미 끊은 통화의 소식
        if (s === 'picked') { quietRing(); clearTimeout(nopick); t0 = Date.now(); tick = setInterval(() => set('on', `${T.talking} ${mmss(Date.now() - t0)}`), 500); set('on', `${T.talking} 00:00`); $('d-form').hidden = false; $('d-left').hidden = !info.direct; $('d-mic').hidden = !info.direct || info.stt === 'fake'; $('d-text').focus(); }
        else if (s === 'speak') { if (info.direct) bubble('agent', text); else $('d-said').textContent = text; }
        else if (s === 'over') over();
        else if (s === 'lost') over(T.lost);
        else if (s === 'shaky' || s === 'steady') { shaking = s === 'shaky'; set(document.body.dataset.call, t0 ? `${T.talking} ${mmss(Date.now() - t0)}` : T.calling); }      // 망이 잠깐 끊김: 통화는 그대로 두고 다시 잇는다
        else if (s === 'down') $('d-said').textContent = T.down;
      });
      if (info.direct) nopick = setTimeout(() => { if (c === mine && !t0) { c = null; mine.hangup(); over(mine.busy ? T.busy : T.nodesk); } }, (info.pick_sec || 20) * 1000);      // 아무도 안 받으면 끝없이 기다리지 않는다
      quietRing = ringback(); set('ring', T.calling);      // 누른 자리에서 연결음을 시작한다(휴대폰은 누른 뒤에만 소리를 허락한다)
      try { await mine.start(!info.direct, false, info.direct); } catch { if (c === mine) over(T.nomic); }      // 직접 통화는 글로만 붙는다(마이크는 나중에 고를 수 있다)
    };
    $('d-form').onsubmit = (ev) => {      // 답을 기다리는 동안에도 보낸다(상담 화면이 모아 두었다 합쳐 읽는다)
      ev.preventDefault();
      const v = $('d-text').value.trim();
      if (v && c) { const li = bubble('me', v); c.text(v).catch(() => { li.classList.add('fail'); li.insertAdjacentHTML('beforeend', `<i>${esc(T.notsent)}</i>`); }); $('d-text').value = ''; redraw(); }
    };
    $('d-mic').onclick = async () => { if (!c) return; try { await c.enableMic(); $('d-mic').disabled = true; } catch { $('d-said').textContent = T.nomic; } };
    btn.disabled = !room && !info.direct;
  }

  function lawSay(text) {      // 상담사가 소리 내 읽거나 말풍선에 올리는 조례 답: 첫 문장이 문구 파일의 「읽어 줄 때 빼는 첫 문장 끝」(「…에 신고하면 됩니다」 꼴)으로 끝나고 뒤에 문장이 남으면 그 문장을 뺀다(동규 11/19). 조례 칸 글 · 저장된 답 · 엔진은 그대로 · direct.js에 같은 것
    const ends = String(K('일의 종류와 갈림')['읽어 줄 때 빼는 첫 문장 끝']).split('·').map((x) => x.trim()).filter((x) => x && !x.startsWith('['));
    const m = String(text || '').match(/^([^.!?]*[.!?])\s+(\S[\s\S]*)$/);
    return m && ends.some((x) => m[1].slice(0, -1).trim().endsWith(x)) ? m[2] : text;
  }

  // ---- 상담 화면: 화면 쪽(+ 이 기기 마이크 · 대본이면 소리 쪽도 함께)
  function deskPage(info) {
    const ASK = Q.get('ask') === 'agent' || Q.get('ask') === 'ai' ? Q.get('ask') : info.ask;
    const st = { room: null, caller: null, alive: false, how: '', since: 0, played: 0, heard: 0, joined: false, picked: false, text: '', gapT: 0, busy: false, spoken: null, state: '', link: '', ask: ASK, taken: false, approved: false, waitApprove: false };
    document.head.insertAdjacentHTML('beforeend', '<style>#t-mic button.on{background:var(--ink);color:var(--panel-solid)}#notice{user-select:all;word-break:break-all}body.voice-wait #lines .ring{display:none}</style>');
    document.querySelector('header.top').insertAdjacentHTML('beforeend', '<span class="lab" id="voice-box" role="status"></span><div class="seg" role="group" id="t-mic" aria-label="음성 통화"></div>');
    const bar = document.getElementById('t-mic'), box = document.getElementById('voice-box');
    const ringing = () => st.alive && st.joined && !st.picked;
    function draw() {
      bar.innerHTML = st.alive ? (ringing() ? `<button type="button" class="on" data-mic="pick">${esc(T.pick)}</button>` : '') + `<button type="button"${ringing() ? '' : ' class="on"'} data-mic="hang">${esc(T.hang)}</button>`
        : (window.DIRECT ? [['here', T.here]] : [['here', T.here], ['phone', T.phone]].concat(SCRIPTS[ui.scene] ? [['script', T.script]] : [])).map(([id, name]) => `<button type="button" data-mic="${id}">${esc(name)}</button>`).join('');      // 직접 통화(배포 판)는 방문자의 마이크만
      box.textContent = st.state ? `${T[info.stt]} · ${st.state}` + (st.heard ? ` · ${T.heard.replace('{초}', st.heard.toFixed(1))}` : '') + (st.ask === 'agent' && st.alive && !st.taken ? ` · ${T.agent}` : '') : '';
      document.body.classList.toggle('voice-wait', st.alive && !st.joined);      // 거는 사람이 들어오기 전에는 「전화가 왔습니다」를 보이지 않는다
      const link = st.alive && st.how === 'phone' && !st.joined ? `${T.link}: ${location.origin}/dial.html?room=${st.room}` : '';      // 거는 사람이 들어올 때까지 받아 적기 칸의 알림 자리에
      if (link !== st.link) { ui.notice = st.link = link; renderTalk(); }
      emit();
    }
    function emit() {      // 화면 요소(누가 말하는 중 · 넘겨받기 · 접수 전 확인)가 받는 상태: window의 'voice:state' 사건 + body의 data-voice-speaker(56번 13절)
      const speaker = !st.alive ? '' : st.busy ? 'ai' : st.caller && st.caller.hold ? 'agent' : ui.typing && ui.typing.who === '시민' ? 'caller' : '';
      document.body.dataset.voiceSpeaker = speaker;
      window.dispatchEvent(new CustomEvent('voice:state', { detail: { speaker, alive: st.alive, picked: st.picked, how: st.how, ask: st.ask, taken: st.taken, waitingApproval: st.waitApprove, state: st.state } }));
    }
    function say(s) { st.state = s; draw(); }
    function onEvent(e) {      // 받아쓴 글: 도중 글은 받아 적기 칸에 흐르고, 확정 글 뒤 잠깐 조용하면 한 차례로 끊어 통화 길에 넣는다
      if (e.typed && window.DIRECT) return window.DIRECT.said(e.text, 'type');      // 휴대폰에서 친 글: 직접 통화 길로 바로(합치기는 그쪽이 한다)
      clearTimeout(st.gapT);
      if (window.DIRECT) window.DIRECT.heard();      // 직접 통화: 말하는 동안은 읽지 않게 알린다
      if (e.final) { st.text = `${st.text} ${e.text}`.trim(); st.gapT = setTimeout(commit, info.gap_ms / fast()); }
      ui.typing = { who: '시민', text: e.final ? st.text : `${st.text} ${e.text}`.trim() }; renderTyping(); emit();
    }
    function commit() {
      const t = st.text; st.text = ''; st.spoken = null;      // 같은 질문이 다시 떠도 읽어 주게
      if (t && st.alive) { if (window.DIRECT) window.DIRECT.said(t, 'voice'); else queue(() => citizen(t, 'voice')); }      // 직접 통화(배포 판)면 차례는 direct.js가 다룬다
    }
    async function poll2() {
      const POLL = info.poll_ms || 250;
      let bad = 0, k = 0;
      while (st.alive) {
        try {
          const d = await vapi(`desk?room=${st.room}&since=${st.since}`);
          if (st.shaky) { st.shaky = false; say(st.picked ? T.listen : T.ring); }
          bad = 0; k = 0;
          st.since = d.next; st.played = d.played; st.heard = d.heard_sec;
          if (d.joined && !st.joined) { st.joined = true; if (st.how === 'phone' && !window.DIRECT) say(T.ring); else pickup(); }      // 직접 통화는 AI 상담이라 바로 받는다      // 휴대폰이 걸어 오면 「받기」를 기다린다. 한 기기면 바로 받는다
          if (d.down) say(T.down);
          if (st.picked) d.events.forEach(onEvent);
          if (st.joined && d.caller_quiet > (info.caller_gone_sec || 75)) return hang(T.lost);      // 휴대폰이 끊기 없이 사라짐(창을 닫음 · 망이 오래 끊김): 이 탭이 다음 통화를 받게
          draw();
        } catch (e) {
          if (!st.alive) return;
          if (!shaky(e)) return hang(T.over);
          bad = bad || Date.now();
          if (!st.shaky && Date.now() - bad > SHAKY_MS) { st.shaky = true; say(T.shaky); }      // 통화는 그대로 두고 다시 잇는다
          if (Date.now() - bad > LOST_MS) return hang(T.lost);
          await backoff(k++, POLL); continue;
        }
        await sleep(POLL);
      }
    }
    function pickup() {
      if (!st.alive || st.picked) return;
      st.picked = true; say(T.listen);
      again(() => vapi(`pick?room=${st.room}`, {})).catch(() => {});
      if (!window.DIRECT) drive(); else window.DIRECT.greet();      // 직접 통화에서는 읽어 주지 않는다(상담사 말은 direct.js가 대화창에 올리고 휴대폰에 넘긴다)
    }
    function terms() {      // 지금 나올 법한 지명: 질문의 보기 · 가능성이 큰 곳 · 이미 나온 단서. 받아쓰기가 미리 알려 주기를 받으면 쓴다(일레븐랩스 keyterms)
      const q = ui.askQ, names = [].concat(q ? q.options.map((o) => o.label) : [], ((V && V.cands) || []).map((c) => c.name), S ? S.turns.flatMap((t) => cluesOf(t).map((c) => c.label || '')) : []);
      return [...new Set(names.flatMap((n) => String(n).split(/ · | ~ /)).map((n) => n.trim()).filter((n) => n.length >= 2 && n.length <= 20))].slice(0, 50);
    }
    async function agentSay(text) {      // 통화 글에 적고(지금 물을 말은 바꾸지 않는다), 소리 쪽에 읽어 달라고 넘기고, 다 읽을 때까지 기다린다
      st.busy = true; say(T.speak);
      await queue(() => turnReq({ line: { who: '상담사', text, via: 'voice' } }));
      try {
        const { n } = await vapi(`ask?room=${st.room}`, { text, terms: terms() }), t0 = Date.now(), cap = (5000 + text.length * 300) / fast();
        while (st.alive && !st.taken && st.played < n && Date.now() - t0 < cap) await sleep(100);
      } catch { /* 방이 닫혔으면 poll2가 끊는다 */ }
      st.busy = false; if (st.alive && !st.taken) say(T.listen); else emit();
    }
    const citizenSays = (text) => (info.stt === 'fake' ? st.caller.fake(text).then(() => true) : st.caller.line(text));      // 대본의 시민 줄: 가짜면 글로, 진짜 받아쓰기면 시민 역 소리로
    async function drive() {      // 화면이 띄운 것을 차례로 읽는다: 인사 → (조례 답) → 질문 … → 맺음말. 단추 · 되돌리기로 질문이 바뀌어도 바뀐 것을 읽는다
      const C = K('통화 글');
      ui.t0 = Date.now();
      if (st.ask === 'agent') return;      // 상담사가 직접 묻는 꼴: 읽어 주지 않는다. 화면이 띄운 질문은 상담사가 읽은 것으로 보고, 시민의 말이 들어올 때 통화 글에 적힌다(글로 넣을 때와 같다)
      await agentSay(C['인사']);
      while (st.alive && !st.taken) {
        await sleep(150);
        if (ui.pending || st.busy || st.text || ui.typing || !V) continue;
        if (V.matter && V.matter.ask && V.engine && !ui.answered) {      // 시민이 규정을 물었으면 조례 답을 한 번 읽는다(대본 재생과 같은 순서)
          ui.answered = true;
          while (st.alive && V.engine && V.engine.status === 'running') { await sleep(400); await poll(); }
          await agentSay(V.engine && (V.engine.say || V.engine.answer) ? lawSay(V.engine.say || V.engine.answer) : K('일의 종류와 갈림')['엔진 확인 불가 말']);
          continue;
        }
        if (V.confirmed) {
          if (window.VOICE.needApproval && !st.approved) { if (!st.waitApprove) { st.waitApprove = true; say(T.approve); } continue; }      // 접수 전 상담사 확인(화면 요소가 VOICE.needApproval을 켰을 때만): 누르기 전에는 「전달하겠습니다」를 읽지 않는다
          st.waitApprove = false;
          await agentSay(V.summary.to ? fill(C['맺음말'], { '넘길 곳': V.summary.to.replace(/ · /g, ', ') }) : C['맺음말 넘길 곳 모름']);
          ui.ended = true; renderTalk();      // 「넘김」은 상담사가 고른다(대본 재생처럼 대신 고르지 않는다)
          return hang(T.over);
        }
        const q = ui.askQ, key = q && `${q.id}|${q.say}`;
        if (q && key !== st.spoken) {
          st.spoken = key;
          await agentSay(q.say);
          if (st.how === 'script' && st.alive && !st.taken && ui.askQ === q) { const a = SCRIPTS[ui.scene][q.id]; if (!a) return hang(C['대본에 없는 질문']); if (!(await citizenSays(a))) return hang(T.noline); }
        } else if (st.how === 'script' && !q && !S.turns.length && !st.said1) { st.said1 = true; if (!(await citizenSays(SCRIPTS[ui.scene]['처음']))) return hang(T.noline); }      // 인사 뒤 첫 말
      }
    }
    async function start(how) {
      if (st.alive) return;
      let code = sessionStorage.getItem('voice-code') || '';
      if (info.code && !code) { code = window.prompt(T.code) || ''; sessionStorage.setItem('voice-code', code); }
      if (!window.DIRECT) resetCall();      // 직접 통화에서는 글로 하던 통화를 이어 말로 할 수 있게 지우지 않는다
      try { st.room = (await vapi('room', { code })).room; } catch (e) { sessionStorage.removeItem('voice-code'); return say(failText(e)); }
      Object.assign(st, { alive: true, how, since: 0, played: 0, heard: 0, joined: false, picked: false, text: '', busy: false, spoken: null, said1: false, caller: null, ask: ASK, taken: false, approved: false, waitApprove: false });
      say(how === 'phone' ? T.wait : T.listen);
      if (how !== 'phone') {
        st.caller = Caller(st.room, info, (s) => { if (s === 'down') say(T.down); });
        try { await st.caller.start(how === 'here', how === 'script' && info.stt !== 'fake'); } catch { return hang(T.nomic); }
      }
      poll2();
    }
    function takeover() {      // 상담사가 통화를 넘겨받는다: AI가 읽던 말을 소리 쪽에서 끊고, 이 통화의 나머지는 상담사가 직접 묻는 꼴로 간다. 받아쓰기는 계속 흐른다
      if (!st.alive || st.taken) return;
      st.taken = true; st.ask = 'agent'; st.busy = false;
      vapi(`cut?room=${st.room}`, {}).catch(() => {});
      say(T.taken);
    }
    async function watch() {      // 직접 통화: 휴대폰이 걸어 와 기다리는 통화를 이 화면이 받는다(한 화면만 받는다). 통화가 없을 때만
      for (;;) {
        await sleep(1500);
        if (st.alive) continue;
        const d = await vapi('waiting').catch(() => ({ rooms: [] }));
        for (const rid of d.rooms || []) {
          if (!(await vapi(`claim?room=${rid}`, {}).then(() => true, () => false))) continue;      // 다른 화면이 먼저 받음
          resetCall(); if (window.DIRECT) window.DIRECT.st.posted.clear();
          Object.assign(st, { room: rid, alive: true, how: 'phone', since: 0, played: 0, heard: 0, joined: false, picked: false, text: '', busy: false, spoken: null, said1: false, caller: null, ask: ASK, taken: false, approved: false, waitApprove: false });
          say(T.ring); poll2();
          break;
        }
      }
    }
    function hang(why) {
      if (!st.alive) return;
      st.alive = false; clearTimeout(st.gapT);
      if (st.caller) st.caller.stop();
      vapi(`end?room=${st.room}`, {}).catch(() => {});
      ui.typing = null; if (ui.t0 && !ui.t1) ui.t1 = Date.now(); if (st.picked) ui.ended = true;
      renderTalk(); say(why || T.over);
    }
    bar.addEventListener('click', (ev) => { const b = ev.target.closest('button'); if (!b) return; ev.stopPropagation(); const m = b.dataset.mic; if (m === 'hang') hang(); else if (m === 'pick') pickup(); else start(m); });
    document.addEventListener('click', (ev) => {      // 받아 적기 칸의 「전화가 왔습니다 · 받기」가 걸려 온 음성 통화를 받게(걸려 온 통화가 없으면 원래대로 대본 재생)
      if (ringing() && ev.target.closest('[data-act="play"]')) { ev.stopPropagation(); ev.preventDefault(); pickup(); }
      else if (ev.target.closest('[data-scene]')) setTimeout(draw, 0);      // 장면을 바꾸면 「대본을 음성 길로」 단추가 그 장면에 맞게
    }, true);
    const hold = (down) => (ev) => {      // 상담사가 직접 묻는 꼴 · 한 기기 마이크: 상담사가 말하는 동안 스페이스를 누르고 있으면 그 소리는 받아쓰지 않는다
      if (ev.code !== 'Space' || st.ask !== 'agent' || !st.alive || !st.caller || ev.target.tagName === 'INPUT') return;
      ev.preventDefault();
      if (st.caller.hold !== down) { st.caller.hold = down; say(down ? T.hold : T.listen); }
    };
    document.addEventListener('keydown', hold(true)); document.addEventListener('keyup', hold(false));
    Object.assign(window.VOICE, { st, start, hang, pickup, takeover, approve() { st.approved = true; emit(); },
      relay(text) { if (st.alive && st.room) { const room = st.room; st.relayQ = (st.relayQ || Promise.resolve()).then(() => again(() => vapi(`ask?room=${room}`, { text }))).catch(() => {}); } } });      // 차례를 지켜 하나씩(망이 끊기면 다시)      // 화면 요소 · 점검이 쓰는 자리(56번 13절). relay = 상담사 말을 휴대폰 화면에 글로 넘긴다(직접 통화)
    Object.defineProperty(window.VOICE, 'ask', { get: () => st.ask, configurable: true });      // 지금 질문을 누가 말하나(넘겨받으면 agent)
    draw();
    if (window.DIRECT) watch();
    if (Q.get('mic')) start(Q.get('mic'));
  }

  window.VOICE = Object.assign({ needApproval: false }, window.VOICE);      // 화면 요소가 접수 전 확인을 쓰면 true로(56번 13절. 이 파일보다 먼저 켜 둬도 남는다). 아래에서 나머지 자리를 채운다
  (async () => {
    const info = await fetch('/api/voice/info').then((r) => (r.ok ? r.json() : null)).catch(() => null);
    if (typeof citizen !== 'function') {      // 휴대폰 화면: 문구를 직접 받는다
      loadText(await fetch('/api/text').then((r) => r.json()).then((t) => t.text).catch(() => null));
      if (!info || !info.on) { document.getElementById('d-lead').textContent = T.off; return; }      // 스위치가 꺼져 있으면 휴대폰 화면만 그 사실을 알린다
      return dialPage(info);
    }
    if (!info || !info.on) return;
    while (!window.CALL) await sleep(50);      // call.js가 시작을 다 마친 뒤에(그 전의 통화는 call.js가 한 번 더 비운다)
    loadText(DOC);
    deskPage(info);
  })();
})();
