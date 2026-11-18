// 통화로 위치 좁히기: 상담사 화면. 글자는 /api/text(docs/content/A-05_통화위치좁히기.md)에서만, 값은 /api/turn · /api/view에서만 가져온다.
// 화면이 통화 상태(S)를 들고 있다가 서버에 통째로 보낸다. 시민의 말 한 마디는 두 번 간다: ① 코드가 읽은 것(바로 뜬다) → ② Solar가 다시 읽은 것(오면 갈아 끼운다).
// 지도 칠과 기울인 지도 맞추기는 3판 담당자 화면(desk.js)의 방식을 옮겼다.
// 주소 옵션(영상 · 점검용): ?auto=roadkill|stray 열자마자 대본 재생 · ?speed=3 빠르게 · ?stop=<질문 이름> 그 질문에서 멈춤 · ?tone=light
'use strict';
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fill = (s, o) => String(s ?? '').replace(/\{([^}]+)\}/g, (m, k) => (o[k] ?? m));
const P = new URLSearchParams(location.search);
const SPEED = Math.max(0.2, Number(P.get('speed')) || 1), STOP = P.get('stop');
const wait = (ms) => new Promise((r) => setTimeout(r, ms / SPEED));
const ll = (p) => [127.0 + p[0] / 88200, 37.55 + p[1] / 111000];      // 서버의 m 좌표(gaz.py) → 경도 · 위도
async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.error || r.status);
  return d;
}

let DOC = null, SCRIPTS = {}, MODE = 'live', META = {}, S = null, V = null, seq = 0, runId = 0, pollT = 0;
let REFS = { types: {}, refs: {} };      // 참고 자료 칸의 값(web/refs.json, tools/build_refs.py가 조례 원문 · 넘길 곳 표에서 뽑음)
let RECS = [], NEXTS = {};      // 상담 기록(/api/records): 예시 기록 + 이 화면에서 확인받은 통화. NEXTS = 지금 상태에서 고를 수 있는 상태
const TRIAL = (P.get('trial') || '').replace(/[^A-Za-z0-9가-힣_-]/g, '').slice(0, 20);      // 사람이 해 보는 시험의 번호(없으면 시험 단추가 뜨지 않는다)
const ui = { voice: P.get('voice') === '1', scene: P.get('auto') || P.get('scene') || '', input: 'script', playing: false, paused: false, ended: false, pending: false, reading: false, model: '',
             typing: null, notice: '', status: null, copied: '', ms: null, tone: P.get('tone') === 'dark' ? 'dark' : 'light',
             view: P.get('view') === 'records' ? 'records' : 'call', rec: P.get('rec') || null, recSt: 'all', recTo: '', recErr: '' };      // view: 통화 | 상담 기록(?view=records&rec=R01)
const tabs = {};
function K(section, head = '항목', col = 1) {   // 문구 표 꺼내기. 없는 이름은 [이름]으로 보여 빠진 글을 바로 알아보게
  const key = `${section}|${head}|${col}`;
  if (!tabs[key]) {
    const t = ((DOC.sections[section] || {}).tables || []).find((x) => x.head[0] === head);
    tabs[key] = new Proxy(t ? Object.fromEntries(t.rows.map((r) => [r[0], r[col]])) : {}, { get: (o, k) => (k in o ? o[k] : `[${String(k)}]`) });
  }
  return tabs[key];
}
const SIT = () => K('상황별 안내', '상황');
const callerNo = () => { const t = K('발신 번호', '장면'); return ui.scene in t ? t[ui.scene] : ''; };      // 장면마다 정해 둔 가상 번호(문구 파일, 가운데를 가린 꼴). 직접 통화는 없음
const scenes = () => ((DOC.sections['통화 장면'] || {}).tables || [{ rows: [] }])[0].rows.map(([id, name, desc]) => ({ id, name, desc }));

// ---- 상담 기록: 처리 상태 다섯 칸과 고를 수 있는 차례(서버 NEXT와 같은 표). 넘길 곳 · 조례는 서버가 표에서 채운 값만 보인다
const ST = ['filed', 'sent', 'doing', 'closed', 'recall'];      // 놓는 차례(마지막 칸이 넓다)
const stName = (s) => K('접수 카드')[{ filed: '접수됨', sent: '넘김', doing: '처리 중', recall: '현장 못 찾음', closed: '끝남' }[s]];
const stb = (s) => `<span class="stb st-${s}">${esc(stName(s))}</span>`;
const whyOff = (t, c) => K('상담 기록')[c === 'closed' ? '막힘 끝남' : { filed: '막힘 되돌림', sent: '막힘 처리 시작', doing: '막힘 넘기기 전', recall: '막힘 현장 전', closed: '막힘 넘기기 전' }[t]];
function radio5(name, cur, ok, why) {      // 선택지를 모두 보이고, 막힌 칸은 흐리게 + 까닭
  return `<div class="opts5">${ST.map((id) => { const can = ok(id), w = !can && cur !== id ? why(id) : '';
    return `<label class="${can ? '' : 'off'}${cur === id ? ' on' : ''}${id === 'recall' ? ' wide' : ''}"><input type="radio" name="${name}" value="${id}"${cur === id ? ' checked' : ''}${can ? '' : ' disabled'}>${esc(stName(id))}${w ? `<small>${esc(w)}</small>` : ''}</label>`; }).join('')}</div>`;
}
function ago(r) {
  const B = K('상담 기록'); if (r.ago) return r.ago;
  const m = Math.floor((Date.now() - r.at) / 60000);
  return m < 1 ? B['방금'] : m < 60 ? fill(B['분 전'], { 분: m }) : fill(B['시간 전'], { 시간: Math.floor(m / 60) });
}
const metres = (a, b) => Math.hypot((a[0] - b[0]) * 88200, (a[1] - b[1]) * 111000);
const recNo = (r) => RECS.length - RECS.indexOf(r);      // 번호 = 들어온 차례(오래된 것이 1)
const recShown = () => RECS.filter((r) => (ui.recSt === 'all' || r.status === ui.recSt) && (!ui.recTo || r.to === ui.recTo));
function nearRecs() {      // 좁힌 자리 둘레의 지난 기록(가까운 셋). 위치가 정해진 뒤에만
  // ponytail: 예시 기록만 본다 — 시연을 되풀이하면 이 화면에서 쌓은 시험 통화가 같은 자리(0m)로 세 줄을 채웠다(64번 P02). 실제 접수 기록과 이으면 모든 기록을 본다
  if (!V || !(V.done || V.confirmed) || !V.center) return [];
  const at = (V.pin && V.pin.at) || V.center, R = Number(K('상담 기록')['둘레 거리']) || 400;
  return RECS.filter((r) => r.sample && r.point).map((r) => ({ r, d: metres(r.point, at) })).filter((x) => x.d <= R).sort((a, b) => a.d - b.d).slice(0, 3);
}
async function loadRecords() { try { const d = await api('/api/records'); RECS = d.records; NEXTS = d.next; } catch { /* 기록 없이도 통화는 된다 */ } }
async function recPost(body) {      // 기록 쌓기 · 상태 바꾸기 · 처음 상태로. 받은 목록으로 갈아 끼운다
  try { const d = await api('/api/records', body); RECS = d.records; NEXTS = d.next; ui.recErr = ''; renderRecList(); return true; } catch { ui.recErr = K('상담 기록')['저장 실패']; return false; }
}
function openRec(id) { ui.view = 'records'; ui.rec = id; lastFit = ''; renderAll(); }

// ---- 통화 상태
function resetCall() {
  runId++; seq++; clearTimeout(pollT); voiceN = 0; ui.t0 = 0; ui.t1 = 0; ui.answered = false; ui.holdAns = false; ui.openSame = false; ui.askQ = null;
  S = { id: 'c' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6), lines: [], turns: [] };
  V = null;
  Object.assign(ui, { playing: false, paused: false, ended: false, pending: false, reading: false, model: '', typing: null, notice: '', status: null, copied: '', ms: null, fateOpen: undefined, cite: null,
    engT0: 0, reveal: null, lawOpen: false, lawCopied: '', pin: false });
  document.body.classList.remove('pinning');      // 찍기를 켠 채 새 통화로 가면 남던 것(64번 P07)
  renderAll();
}
async function send(body, hold) {   // 서버에 한 번 보내고 받은 상태로 갈아 끼운다(hold: 받은 뒤 화면에 올리기 전에 기다릴 것)
  const my = ++seq;
  try {
    const d = await api('/api/turn', { state: S, ...body });
    if (hold) await hold(d.view);
    if (my !== seq) return null;
    S = d.state; V = d.view;
    if (V.confirmed && !ui.status) { ui.status = 'filed'; recPost({ op: 'save', state: S, status: 'filed' }).then(() => { renderTop(); renderSide(); }); }      // 위치를 확인받으면 접수됨 → 상담 기록에 쌓인다
    if ((V.confirmed || (V.question && V.question.id === 'handoff')) && ui.t0 && !ui.t1) ui.t1 = Date.now();      // 통화가 끝난 때(사람 시험의 걸린 시간)
    if (!V.confirmed) ui.status = null;
    return V;
  } catch { if (my === seq) ui.notice = SIT()['서버 오류']; return null; }
}
async function turnReq(body) {   // 줄 하나 · 단추 하나. 시민의 말이면 ① 코드가 읽은 것으로 바로 그리고 ② Solar가 다시 읽은 것으로 갈아 끼운다
  const t0 = performance.now(), said = !!(body.line && body.line.who === '시민');
  ui.pending = true; ui.reading = said; ui.model = '';
  renderTalk(); renderAsk();
  const asks = !(body.line && body.line.who === '상담사');     // 「지금 물을 말」은 시민의 말 · 단추로만 바뀐다. 상담사가 말한 줄로는 바꾸지 않는다(인사 뒤에 다음 질문이 먼저 뜨던 일, 11-15 동규)
  let v = await send(body);
  ui.reading = false; ui.typing = null;
  if (!v) { ui.pending = false; renderAll(); return false; }
  if (asks) showAsk(v.question);
  if (said) {
    ui.ms = performance.now() - t0;                             // 말이 끝난 때부터 질문이 뜨기까지(코드만)
    if (MODE !== 'code') {
      const before = v.question && v.question.id, R = K('이렇게 물어보세요'), tc = performance.now();
      ui.model = R['다시 읽는 중']; renderAll();
      // 저장된 답 방식(영상 · 발표): Solar가 다시 읽는 데 실제로 걸린 시간(많아야 2.5초)만큼 기다렸다 갈아 끼운다. 실제 호출이면 그만큼 걸린다
      const m = await send({ phase: 'model' }, MODE === 'saved' ? (mv) => new Promise((r) => setTimeout(r, Math.max(0, tc + Math.min(mv.read_sec || 0, 2.5) * 1000 - performance.now()))) : null);
      if (m) {
        v = m;
        ui.model = m.read_how === 'live' ? fill(R['다시 읽음'], { 읽기: m.read_sec }) : m.read_how === 'saved' ? fill(R['다시 읽음 저장'], { 읽기: m.read_sec }) : '';
        if ((m.question && m.question.id) !== before && m.read_how !== 'nosaved') ui.model += ' · ' + R['고쳐 읽음'];
        ui.notice = m.read_how === 'failed' ? SIT()['모델을 부르지 못함'] : m.read_how === 'nosaved' && ui.input !== 'script' ? SIT()['저장된 답 없음'] : '';
        showAsk(m.question);
      }
    }
  }
  if (v.outside) ui.notice = SIT()['구역 밖'];
  ui.pending = false;
  renderAll(); schedulePoll();
  return true;
}
function showAsk(q) {   // 화면 맨 위 「지금 물을 말」에 올릴 질문(녹화 때는 올린 시각을 남긴다: 차례별 시각 표용)
  ui.askQ = q || null;
  if (REC) (window.__events = window.__events || []).push(['ask', performance.now(), q ? q.id : null, q ? q.say : null]);
}
function schedulePoll() { clearTimeout(pollT); if (V && V.engine && V.engine.status === 'running') pollT = setTimeout(poll, 700); }
async function poll() {   // 엔진 답을 기다린다(그 사이 줄이 더해졌으면 이 응답은 버린다)
  const my = seq;
  try { const d = await api('/api/view', { state: S }); if (my === seq) { V = { ...d.view, read_how: V.read_how, read_sec: V.read_sec }; renderSide(); } } catch { /* 다음 번에 다시 */ }
  if (my === seq) schedulePoll();
}
async function citizen(text, via) {   // 글로 넣은 시민의 말(실제로는 다산콜의 받아 적기 도구가 넘겨준 글). 화면이 띄운 질문은 상담사가 읽었다고 보고 통화 글에 먼저 적는다
  if (!S) resetCall();
  if (!ui.t0) ui.t0 = Date.now();
  const last = S.lines[S.lines.length - 1];
  if (!S.lines.length) S.lines.push({ who: '상담사', text: K('통화 글')['인사'], via: 'auto' });
  else if (ui.askQ && (!last || last.who !== '상담사')) S.lines.push({ who: '상담사', text: ui.askQ.say, via: 'auto' });
  return turnReq({ line: { who: '시민', text, via } });
}
let chain = Promise.resolve();
const queue = (fn) => (chain = chain.then(fn, fn));

// ---- 대본 재생: 화면이 띄운 질문을 상담사가 읽고, 그 질문에 맞는 대본 줄로 시민이 답한다
async function typeLine(who, text, alive, totalMs, ct) {      // ct가 있으면 글자마다 「소리 나는 그 시각」에 올린다. 없으면 totalMs에 고르게 나눠 올린다
  ui.typing = { who, text: '' }; renderTalk();
  if (ct) {
    const t0 = performance.now();
    for (let n = 0; n < ct.length && alive();) {
      const el = (performance.now() - t0) / 1000;
      while (n < ct.length && ct[n] <= el) n++;
      if (ui.typing.text.length !== n) { ui.typing.text = text.slice(0, n); renderTyping(); }
      if (n < ct.length) await new Promise((r) => setTimeout(r, 30));
    }
    if (alive()) { ui.typing.text = text; renderTyping(); }
    return;
  }
  const step = totalMs ? Math.max(16, totalMs / Math.ceil(text.length / 2)) : 52 / SPEED;
  for (let i = 1; i <= text.length && alive(); i += 2) { ui.typing.text = text.slice(0, i + 1); renderTyping(); await new Promise((r) => setTimeout(r, step)); }
  if (alive()) { ui.typing.text = text; renderTyping(); }
}
// 목소리(영상용): 미리 만들어 둔 음성 파일을 튼다: web/voice/<장면>-<줄 번호 두 자리>.mp3 (레포에 없음. 줄 번호와 글은 `server.py --lines`).
// 파일이 없으면 소리 없이 글 길이만큼 기다린다. 화면이 모델을 부르지 않는다(파일만 튼다)
let voiceN = 0, VOICE_IDX = null;
const REC = P.get('rec') === '1';      // 녹화용: 페이지는 소리를 내지 않고 줄마다 시작 시각만 남긴다(소리는 녹화 뒤에 얹는다)
async function voiceInfo(text) {      // 이번 줄의 음성 파일과 길이. 파일이 없으면 말하는 빠르기로 어림한 길이만 준다
  if (!ui.voice) return null;
  if (VOICE_IDX === null) { try { VOICE_IDX = await (await fetch('voice/index.json')).json(); } catch { VOICE_IDX = {}; } }      // {파일 이름: 길이(초)}
  const file = `${ui.scene}-${String(++voiceN).padStart(2, '0')}.mp3`, v = VOICE_IDX[file], dur = v && (v.dur || v);      // {dur, ct: 글자마다 소리 나는 시각}
  return { file, dur, ct: v && v.ct && v.ct.length === text.length ? v.ct : null, ms: dur ? dur * 1000 : Math.min(9000, 600 + text.length * 95) / SPEED };
}
function speak(info) {
  if (!info) return Promise.resolve();
  if (REC) { (window.__marks = window.__marks || []).push(['voice/' + info.file, performance.now(), !!info.dur]); return new Promise((r) => setTimeout(r, info.ms + 250)); }
  if (!info.dur) return new Promise((r) => setTimeout(r, info.ms));
  return new Promise((done) => { const a = new Audio('voice/' + info.file); a.onended = a.onerror = () => done(); a.play().catch(() => done()); });
}
// 발표자만 쓰는 숨은 조작: ` 조작 단추 보이기 · 1 2 장면 고르기 · 0 직접 통화 · Enter 전화 받기(대본 재생) · V 목소리 · T 밝기
const CTL = () => document.body.classList.contains('ctl');
if (P.get('ctl') === '1') document.body.classList.add('ctl');
document.addEventListener('keydown', (ev) => {
  if (ev.target.closest('input, select, textarea, button') || ev.metaKey || ev.ctrlKey || !DOC) return;
  const sc = scenes(), k = ev.key.toLowerCase();
  if (ev.key === '`') { document.body.classList.toggle('ctl'); renderAll(); }
  else if (ui.view === 'records' || (ui.input === 'type' && S && S.lines.length)) return;      // 상담 기록 화면 · 글로 넣는 통화 중에는 통화를 지우는 글쇠를 받지 않는다(64번 P04 · P08)
  else if ('12'.includes(k) && sc[Number(k) - 1]) { ui.scene = sc[Number(k) - 1].id; ui.input = SCRIPTS[ui.scene] ? 'script' : 'type'; resetCall(); }
  else if (k === '0') { ui.scene = 'free'; ui.input = 'type'; resetCall(); document.body.classList.add('ctl'); renderAll(); }
  else if (ev.key === 'Enter' && !ui.playing && SCRIPTS[ui.scene]) play();
  else if (k === 'v') { ui.voice = !ui.voice; renderTop(); }
  else if (k === 't') setTone(ui.tone === 'dark' ? 'light' : 'dark');
});
const closing = () => { const T = K('통화 글'), to = V && V.summary && V.summary.to; return to ? fill(T['맺음말'], { '넘길 곳': to.replace(/ · /g, ', ') }) : T['맺음말 넘길 곳 모름']; };      // 끝인사: 대본의 상담사 줄 = 「지금 물을 말」 칸의 말(57번 3)
async function play() {
  resetCall();
  const my = runId, sc = SCRIPTS[ui.scene], T = K('통화 글'), alive = () => my === runId;
  if (!sc) return;
  ui.t0 = Date.now(); ui.t1 = 0; ui.playing = true; renderTalk();
  const hold = async () => { while (ui.paused && alive()) await new Promise((r) => setTimeout(r, 120)); return alive(); };
  const line = async (who, text) => { if (!(await hold())) return false; const vi = await voiceInfo(text); await Promise.all([typeLine(who, text, alive, vi && vi.ms * 0.92, vi && vi.ct), speak(vi)]); if (who === '시민') await wait(500); return alive() && (await turnReq({ line: { who, text, via: 'script' } })) && alive(); };      // 그 사이 새 통화가 시작됐으면 이 재생은 멈춘다(64번 P11)      // 시민의 말이 끝나고 받아 적기가 마무리되는 짧은 틈 뒤에 읽는다
  const stop = () => { if (alive()) { ui.playing = false; renderTalk(); renderAsk(); } };
  await wait(500);
  if (!(await line('상담사', T['인사']))) return stop();
  let said = sc['처음'];
  for (let i = 0; i < 12; i++) {
    await wait(700);
    if (!(await line('시민', said))) return stop();
    if (V.matter && V.matter.ask && V.engine && !ui.answered) {
      ui.answered = true;
      ui.holdAns = true; renderSide();
      while (alive() && V.engine && V.engine.status === 'running') { await wait(400); await poll(); }
      await wait(300);
      ui.holdAns = false; renderSide();                   // 답이 칸에 뜨는 때 = 상담사가 읽기 시작하는 때
      if (REC) (window.__events = window.__events || []).push(['ans', performance.now(), null, null]);      // 녹화 때 남김: 조례 답이 칸에 뜬 때(차례별 시각 표용)
      if (ui.scene === 'vendor') await wait(800);        // 공원 노점 장면만: 답이 그려진 뒤 읽는다(창 없는 녹화에서 답 칸이 0.4초 늦게 그려졌다). 다른 두 장면은 그대로
      if (!(await line('상담사', (V.engine && (V.engine.say || V.engine.answer)) || K('일의 종류와 갈림')['엔진 확인 불가 말']))) return stop();
      if (ui.scene === 'vendor' && REC) window.__events.push(['same', performance.now(), null, null]);      // 공원 노점 장면: 「같은 일이 다른 자리였다면」은 이제 카드 맨 아래 참고 자료 칸에 늘 보인다(카드를 내리지 않음, 11-18 확정)
    }
    if (V.confirmed) break;
    const q = ui.askQ;
    if (STOP && q.id === STOP) return stop();
    await wait(800);                                    // 상담사가 화면의 질문을 보고 읽기 시작하는 틈(질문은 다시 읽기까지 끝난 뒤에 떠 있다)
    if (!(await line('상담사', q.say))) return stop();
    said = sc[q.id];
    if (!said) { ui.notice = T['대본에 없는 질문']; return stop(); }
  }
  if (alive() && V && V.confirmed) {
    await wait(900);
    await line('상담사', closing());
    ui.ended = true;
    await wait(900);
    if (alive()) { ui.status = 'sent'; renderSide(); renderTop(); recPost({ op: 'save', state: S, status: 'sent' }).then(() => { renderTop(); renderSide(); }); }      // 대본에서는 상담사가 「담당 부서로 넘김」을 고른 것으로 보인다
  }
  stop();
}

// ---- 그리기
function renderTop() {
  const T = K('맨 위 띠'), step = V ? (ui.status === 'sent' ? 5 : V.step) : 1;
  $('t-title').textContent = T['화면 이름']; $('t-who').textContent = T['쓰는 사람'];
  const B = K('상담 기록');
  $('t-view').setAttribute('aria-label', B['화면 고르기']);
  $('t-view').innerHTML = [['call', '통화'], ['records', '기록']].map(([id, k]) => `<button type="button" data-view="${id}" aria-pressed="${ui.view === id}">${esc(B[k])}${id === 'records' && RECS.length ? `<b>${RECS.length}</b>` : ''}</button>`).join('');
  document.body.classList.toggle('view-records', ui.view === 'records');
  $('t-steps').innerHTML = [1, 2, 3, 4].map((n) => `<li class="${n < step ? 'past' : n === step ? 'now' : ''}"><b>${n}</b>${esc(T['단계 ' + n])}</li>`).join('');
  if (CTL()) { $('t-mode').textContent = T[{ saved: '저장된 답', code: '코드만', live: '실제 호출' }[MODE]]; $('t-mode').className = 'live ' + MODE; } else callStatus();
  $('t-scene').setAttribute('aria-label', T['장면 고르기']);
  $('t-scene').innerHTML = scenes().map((s) => `<button type="button" data-scene="${esc(s.id)}" aria-pressed="${s.id === ui.scene}" title="${esc(s.desc)}">${esc(s.name)}</button>`).join('');
  $('t-tone').setAttribute('aria-label', T['화면 밝기']);
  $('t-tone').innerHTML = ['dark', 'light'].map((t) => `<button type="button" data-tone="${t}" aria-pressed="${t === ui.tone}">${esc(T[t === 'light' ? '밝은 화면' : '어두운 화면'])}</button>`).join('')
    + `<button type="button" data-voice="1" aria-pressed="${ui.voice}" title="${esc(T['목소리 설명'])}">${esc(T[ui.voice ? '목소리 켬' : '목소리 끔'])}</button>`;
}
const cluesOf = (t) => ((t && (t.model || t.code)) || {}).clues || [];
function bubble(l, cls = '', chips = []) {
  const T = K('통화 글'), me = l.who === '상담사';
  return `<li class="ln ${me ? 'me' : 'you'}${l.via === 'chip' ? ' chip' : ''} ${cls}"><span class="w">${esc(T[me ? '상담사' : '시민'])}${l.via === 'chip' ? ` <span class="tag">· ${esc(T['단추로 넣음'])}</span>` : ''}</span><span class="b">${esc(l.text)}</span>`
    + (chips.length ? `<span class="cl">${chips.map((c) => `<i>${esc(c)}</i>`).join('')}</span>` : '') + '</li>';
}
function renderTyping() { const el = document.querySelector('.ln.typing .b'); if (el && ui.typing) el.textContent = ui.typing.text; else renderTalk(); }
// 통화 상태(깔끔한 화면): 전화 수신 → 통화 중 00:12 · 받아 적기 연결됨 → 통화 종료
function callStatus() {
  const T = K('맨 위 띠'), el = $('t-mode'), sec = ui.t0 ? Math.floor(((ui.t1 || Date.now()) - ui.t0) / 1000) : 0, mmss = `${String(Math.floor(sec / 60)).padStart(2, '0')}:${String(sec % 60).padStart(2, '0')}`;
  el.className = 'live call ' + (ui.ended ? 'over' : ui.t0 ? 'on' : 'ring');
  el.textContent = ui.ended ? `${T['통화 끝']} ${mmss}` : ui.t0 ? `${T['통화 중']} ${mmss} · ${T['받아 적기 상태']}` : T['전화 옴'];
}
setInterval(() => {
  if (!DOC) return;
  if (!CTL()) { if (ui.ended && !ui.t1) ui.t1 = Date.now(); callStatus(); }
  if (ui.engT0) renderLaw();      // 조례 답을 기다리는 동안 지난 시간을 센다
}, 500);
function renderTalk() {
  const T = K('통화 글');
  $('k-title').textContent = T['제목']; $('k-lead').textContent = T['안내'];
  $('k-flow').textContent = T['가상 흐름'];      // 질문 흐름은 공개 자료 · 조례 원문으로 만든 가상의 것(120 표준상담DB와 연결 안 됨)이라고 늘 밝힌다(동규 11-18)
  let h = '', n = 0;
  if (!CTL() && !(S && S.lines.length) && !ui.typing) {
    const sc = scenes().find((s) => s.id === ui.scene);
    h += `<li class="ring"><span>${esc(T['전화 옴'])}${callerNo() ? `<small class="no">${esc(callerNo())} ${esc(K('접수 카드')['가상 번호 표시'])}</small>` : ''}</span><button type="button" class="primary" data-act="play">${esc(T['받기'])}</button></li>`
      + `<li class="ring-note">${SCRIPTS[ui.scene] ? `${esc(T['받기 안내'])}${sc ? ` ${esc(sc.name)}` : ''}` : esc(sc ? sc.desc : '')}</li>`;      // 누르면 무슨 일이 생기는지(57번 1). 대본 없는 장면은 그 설명(「대본 없이 글로 넣기」)
  }
  for (const l of (S ? S.lines : [])) {   // 시민의 말 아래에 그 말에서 뽑힌 단서를 칩으로 붙인다
    const t = l.who === '시민' ? S.turns[n++] : null;
    h += bubble(l, '', cluesOf(t).map((c) => c.label || '').filter(Boolean));
  }
  if (ui.typing) h += bubble(ui.typing, 'typing');
  if (ui.reading && !ui.typing) h += `<li class="ln reading">${esc(T['읽는 중'])}</li>`;
  if (ui.ended) h += `<li class="ln reading end">${esc(T['대본 끝'])}</li>`
    + `<li class="next"><button type="button" class="primary" data-act="next">${esc(T['다음 전화'])}</button><button type="button" class="outline" data-act="open-rec">${esc(T['기록 보기'])}</button></li>`;      // 통화가 끝난 뒤 갈 곳(57번 2)
  const box = $('lines'); box.innerHTML = h; box.scrollTop = box.scrollHeight;
  $('notice').hidden = !ui.notice; $('notice').textContent = ui.notice;
  const hasScript = !!SCRIPTS[ui.scene];
  $('k-input').setAttribute('aria-label', T['넣는 방법']);
  $('k-input').innerHTML = [['script', '대본 재생'], ['type', '직접 입력']].map(([id, name]) =>
    `<button type="button" data-input="${id}" aria-pressed="${id === ui.input}"${id === 'script' && !hasScript ? ' disabled' : ''}>${esc(T[name])}</button>`).join('');
  let c = '';
  if (ui.input === 'script') {
    c = !ui.playing ? `<button type="button" class="primary" data-act="play">${esc(T[S && S.lines.length ? '처음부터' : '시작'])}</button>`
      : `<button type="button" class="outline" data-act="pause">${esc(T[ui.paused ? '이어서' : '멈춤'])}</button><button type="button" class="outline" data-act="play">${esc(T['처음부터'])}</button>`;
  } else {
    c = `<input id="k-text" type="text" maxlength="300" placeholder="${esc(T['입력 칸'])}" aria-label="${esc(T['입력 칸'])}"><button type="button" class="primary" data-act="send"${ui.pending ? ' disabled' : ''}>${esc(T['넣기'])}</button>`
      + `<button type="button" class="outline" data-act="reset">${esc(T['처음부터'])}</button>`;
  }
  const had = document.activeElement && document.activeElement.id === 'k-text', val = had ? document.activeElement.value : '';
  $('k-ctl').innerHTML = c;
  if (had && $('k-text')) { $('k-text').value = val; $('k-text').focus(); }
}
function renderAsk() {
  const A = K('이렇게 물어보세요'), q = ui.askQ, el = $('ask');
  el.className = 'ask glass' + (ui.reading ? ' busy' : '') + (q && q.id === 'confirm' ? ' confirm' : '');
  const end = !q && V && V.confirmed;      // 확인받은 뒤: 민원인에게 할 마지막 말을 크게, 「위치 확인 완료」는 작은 상태 글로(57번 3)
  let h = `<div class="hd"><h2 id="a-title">${esc(A['제목'])}</h2>${q && q.bits ? `<span class="by">${esc(A['고른 방식'])}</span>` : ''}${end ? `<span class="badge done">${esc(A['끝'])}</span>` : ''}</div>`;
  if (end) h += `<p class="q">${esc(closing())}</p><p class="note">${esc(A['끝 안내'])}</p>`;
  else if (!q) h += `<p class="q idle">${esc(A['통화 전'])}</p>${S && S.lines.length ? '' : `<p class="note">${esc(A['화면 설명'])}</p>`}`;      // 첫 화면: 무슨 화면인지 한 문장(57번 1)
  else {
    h += `<p class="q">${esc(q.say)}</p><p class="why"><b>${esc(A['까닭'])}</b>${esc(q.why)}</p>`;
    const meta = [q.bits_text, ui.ms != null && V.read_how ? fill(A['걸린 시간'], { 초: (ui.ms / 1000).toFixed(2) }) : '', ui.model].filter(Boolean);
    if (meta.length) h += `<p class="exp">${meta.map(esc).join('<span class="sep"> · </span>')}</p>`;
    if (q.options.length) h += `<div class="opts"><span class="k">${esc(A['답 단추'])}</span>${q.options.map((o, i) => `<button type="button" data-opt="${i}"${ui.pending || ui.playing ? ' disabled' : ''}>${esc(o.label)}</button>`).join('')}</div>`;
  }
  el.innerHTML = h;
}
function renderRange() {
  const R = K('위치 범위'), G = K('지도'), all = (V && V.history) || [], hist = CTL() ? all : all.slice(-3);
  const st = !V || !V.size ? '' : V.confirmed ? `<span class="badge done">${esc(R['확인받음'])}</span>` : V.done ? `<span class="badge done">${esc(R['다 좁혀짐'])}</span>` : `<span class="badge going">${esc(R['좁히는 중'])}</span>`;
  const first = hist.length ? hist[0].m : 1;
  let h = `<div class="hd"><h2 id="r-title">${esc(R['제목'])}</h2><span class="big now">${esc(V && V.pin && V.pin.exact && V.confirmed ? '' : V ? V.size_text : R['통화 전'])}</span>${st}`
    + (S && S.turns.length && !(V && V.confirmed) ? `<button type="button" class="outline undo" data-act="undo"${ui.pending || ui.playing ? ' disabled' : ''}>${esc(R['되돌리기'])}</button>` : '')
    + (V && V.elsewhere >= 0.05 && V.size ? `<span class="else">${esc(fill(R['다른 곳일 몫'], { 몫: Math.round(V.elsewhere * 100) }))}</span>` : '') + '</div>';
  if (hist.length) h += `<ol class="steps">${hist.map((x, i) => `<li class="${i === hist.length - 1 ? 'last' : ''}"><div class="n">${i + 1}</div><div class="l">${esc(x.label)}</div><div class="m">${esc(x.text)}</div><div class="bar"><i style="width:${Math.max(4, Math.min(100, Math.round(100 * Math.log(x.m / 15) / Math.log(first / 15 + 1e-9))))}%"></i></div></li>`).join('')}</ol>`;
  if (V && V.doubt.length) h += `<p class="drop">${esc(fill(R['어긋난 말'], { 단서: V.doubt.join(', ') }))}</p>`;
  if (V && (V.heard || []).length) h += `<p class="drop heard">${esc(fill(R['알아들음'], { 들은: V.heard.map((x) => `${x.said} → ${x.as}`).join(', ') }))}</p>`;      // 비슷한 이름으로 이은 것(11-15)
  if (V && (V.unfound || []).length) h += `<p class="drop">${esc(fill(R['못 찾음'], { 이름: V.unfound.join(', ') }))}</p>`;      // 끝내 못 찾은 이름(조용히 넘어가지 않게)
  h += `<p class="foot"><button type="button" class="outline pinbtn" data-act="pin" aria-pressed="${!!ui.pin}"${S && S.lines.length > 1 ? '' : ' disabled'}>${esc(G[ui.pin ? '찍기 켜짐' : '찍기'])}</button><span class="lg"><i></i>${esc(G['후보 범위'])}</span><span class="lg"><i class="pin"></i>${esc(G['정해진 자리'])}</span><span class="lg"><i class="mk"></i>${esc(G['표지'])}</span>`
    + `<span class="note">${esc(fill(G['시연 구역'], { 장소: (META.places || 0).toLocaleString() }))}</span><span class="note">${esc(G['출처'])}</span><span>${esc(G['지도 저작권'])}</span>${P.get('heights') === 'off' ? '' : `<span>${esc(G['건물 높이 출처'])}</span>`}${R['시연 표시 켬'] === '켬' ? `<span class="demo">${esc(R['시연 표시'])}</span>` : ''}</p>`;
  $('range').innerHTML = h;
}
function engineLine(e) {
  const M = K('일의 종류와 갈림');
  return e.how === 'saved' ? fill(M['미리 받은 답'], { 초: e.sec }) : fill(M['지금 만든 답'], { 초: e.sec });
}
function fateTable(r, open) {      // 「살았나 · 죽었나 × 자리」: 조례 6종 안팎과 넘길 곳은 표(routes.json)의 줄 그대로, 지금 통화의 줄을 칠한다
  // 자리 · 크기: 옛 「같은 일이 다른 자리였다면」 표 자리 그대로. 그 표가 펼쳐져 보이던 일(동물 사체)만 펼치고, 표가 없던 일(유기 동물)은 한 줄로 접어 둔다(누르면 펼침). 다른 칸은 옮기지 않는다(11-18 동규)
  const M = K('일의 종류와 갈림'), F = K('일의 종류와 갈림', '살았나 죽었나'), cur = F[r.class] || r.class;
  const row = (f, i, all) => `<tr class="${f.here ? 'here' : ''}">${i ? '' : `<th rowspan="${all.length}">${esc(F[f.alive ? '살아 있음' : '죽음'])}</th>`}`
    + `<td>${esc(f.class ? F[f.class] : F['어디서든'])}${f.here ? ` <span class="badge in">${esc(f.class ? M['지금 자리'] : fill(F['지금 자리 글'], { 자리: cur }))}</span>` : ''}</td>`
    + `<td>${esc(f.scope === 'in' ? fill(F['6종 안 줄'], { 조례: (f.law || '').replace(/^서울특별시\s*/, '') }) : F['6종 밖 줄'])}</td>`
    + `<td>${esc(f.to)} <span class="badge ${f.basis === '확인' ? 'sure' : 'guess'}">${esc(F[f.basis === '확인' ? '확인' : '추측'])}</span></td></tr>`;
  const part = (alive) => r.fate.filter((f) => f.alive === alive).map(row).join('');
  return `<details class="same fate"${(open || (ui.fateOpen ?? r.others.length > 1)) ? ' open' : ''}><summary title="${esc(F['꼬리'])}">${esc(F['제목'])}</summary><table><colgroup><col class="c1"><col class="c2"><col class="c3"><col></colgroup>`
    + `${part(true)}${part(false)}</table></details>`;      // 머리줄 · 설명 줄 없이(설명은 제목에 마우스를 올리면): 옛 표 크기 안에
}
function nearBox() {      // 접수 카드 안 「이 자리 둘레 지난 기록」: 고정 칸에 한 줄씩(상태 · 언제 · 일 · 그때 넘긴 범위 · 여기서 거리). 누르면 상담 기록 화면에서 연다. 위치 전에는 자리만
  const B = K('상담 기록'), U = K('접수 카드'), near = nearRecs(), ex = near.some((x) => x.r.sample);
  let h = `<div class="slot s-near"><div class="t">${esc(U['둘레 기록 제목'])}${ex ? `<em class="ex">${esc(B['예시 표시'])}</em>` : ''}</div>`;
  if (!V || !(V.done || V.confirmed)) h += `<p class="wait">${esc(U['위치 대기'])}</p>`;
  else if (!near.length) h += `<p class="wait">${esc(fill(U['둘레 기록 없음'], { 거리: Number(B['둘레 거리']) || 400 }))}</p>`;
  else h += near.map(({ r, d }) => `<button type="button" class="nr" data-rec="${esc(r.id)}" title="${esc(U['둘레 기록 열기'])} · ${esc(U['그때 넘긴 위치'])} ${esc(r.go)} · ${esc(r.to)}">${stb(r.status)}`
    + `<span class="g">${esc(ago(r))} · ${esc(String(r.matter).split(' · ')[0])} · ${esc(r.range || '')}</span><span class="d">${esc(fill(U['여기서 거리'], { 거리: Math.round(d / 10) * 10 }))}</span></button>`).join('');
  return h + '</div>';
}
// ---- 11-18 확정 화면(동규 「안 가, (a), B」): 칸 자리 · 높이는 통화 단계와 상관없이 같다. 조례 근거 답 = 가운데 위 「지금 물을 말」 옆 칸(말할 것 띠),
//      접수 카드 = 넘길 것(요약 → 처리할 담당 부서 → 이 자리 둘레 지난 기록 → 처리 진행 상태 → 보일 것이 있을 때만 맨 아래 「참고 자료」)
const shortLaw = (l) => String(l || '').replace(/^서울특별시\s*/, '');
const engNow = () => V && V.engine && (ui.holdAns ? { status: 'running', citations: [] } : V.engine);
const hasAns = (e) => !!(e && e.status === 'ready' && e.answer && e.citations && e.citations.length);
const citeText = (e, s) => [...new Set(e.citations.map((c) => c.law))].map((l) => `${s ? shortLaw(l) : l} ${e.citations.filter((c) => c.law === l).map((c) => c.article).join(' · ')}`).join(' / ');
function scopeBadge() {
  const M = K('일의 종류와 갈림'), sc = V && V.matter && V.matter.scope, lab = { in: '6종 안', out: '6종 밖', wait: '6종 확인 중', nocite: '6종 근거 없음' }[sc];
  return sc ? `<span class="badge ${sc === 'in' ? 'in' : sc === 'out' ? 'out' : 'going'}">${esc(M[lab])}</span>` : '';
}
function renderLaw() {      // 조례 근거 답: 대기 → 6종 판정 → 찾는 중 → 답. 조항(또는 「답 전문」)을 누르면 이 칸 안에서 조문으로 바뀌고 「← 답으로」로 돌아온다(새 창 없음)
  const el = $('law'); if (!el) return;
  const M = K('일의 종류와 갈림'), e = engNow(), r = V && V.route, sc = V && V.matter && V.matter.scope, say = ((V && V.answer_box) || {})['안내'] || { name: K('접수 카드', '쓰임')['안내'] };
  const waiting = sc && sc !== 'out' && (!e || e.status === 'running');
  let revealing = '';      // 글자를 흘리는 중이면 지금 보일 앞부분
  ui.engT0 = waiting ? ui.engT0 || Date.now() : 0;      // 기다리기 시작한 때(지난 시간을 세는 기준). 엔진은 답을 한 번에 돌려주므로 남은 초는 모른다
  let h = `<div class="hd"><h2 id="w-title">${esc(M['답 칸 제목'])}</h2>${hasAns(e) ? `<span class="by">${esc(engineLine(e))}</span>` : ''}${scopeBadge()}`
    + (hasAns(e) && sc === 'in' ? `<span class="copied" role="status">${esc(ui.lawCopied)}</span><button type="button" class="outline copy" data-act="law-copy">${esc(M['답 복사'])}</button>` : '') + '</div>';      // 답과 근거 조항을 한 번에(문서로 넘길 때, 접수 카드 복사와 같은 꼴)
  if (!sc) h += `<p class="idle">${esc(M['답 대기'])}</p>`;
  else if (sc === 'out') {
    const t = e && e.status === 'running' ? M['엔진 찾는 중'] : e && e.status === 'ready' && e.citations.length && V.matter.law ? fill(M['엔진 참고'], { 조항: e.citations.map((c) => c.label).join(' · ') }) : M['엔진 확인 불가'];
    h += `<p class="idle">${esc((r && r.scope_why) || M['6종 밖'])}</p>` + (M['6종 밖 엔진 표시'] === '켬' || CTL() ? `<p class="idle">${esc(t)}</p>` : '');
  } else {
    const q = e && (e.question || V.matter.ask);
    if (q && ui.cite == null) h += `<p class="cq"><b>${esc(M['시민 물음'])}</b>${esc(q)}</p>`;
    if (waiting) h += `<p class="idle">${esc(M['답 기다림'])}</p><p class="wait2">${esc(fill(M['답 지난 시간'], { 초: ((Date.now() - ui.engT0) / 1000).toFixed(1) }))}${MODE === 'live' ? ` · ${esc(M['답 보통 시간'])}` : ''}</p><div class="skel" aria-busy="true"><i></i><i></i><i></i></div>`;
    else if (!e.answer) h += `<p class="idle">${esc(e.error === 'nosaved' ? M['저장된 답 없음'] : e.error ? M['엔진 못 부름'] : M['엔진 못 찾음'])}</p>`;
    else {
      const chips = (on) => [...new Set(e.citations.map((c) => c.law))].map((l) => `${esc(shortLaw(l))} ` + e.citations.map((c, i) => [c, i]).filter(([c]) => c.law === l).map(([c, i]) => `<button type="button" data-act="cite" data-i="${i}" class="${on === i ? 'on' : ''}" title="${esc(c.label)}">${esc(c.article)}</button>`).join('')).join(' ');      // 조례 이름은 한 번, 단추는 조항 번호만
      const c = typeof ui.cite === 'number' ? e.citations[ui.cite] : null;
      if (c) h += `<div class="qv"><div class="qtop"><button type="button" data-act="cite-back">${esc(M['답으로'])}</button><span class="chips2">${chips(ui.cite)}</span></div>`
        + `<div class="lb">${esc(c.label)}<span>${esc(fill(M['시행'], { 날짜: c.effective }))}</span></div>${c.quotes.map((x) => `<blockquote>「${esc(x)}」</blockquote>`).join('')}`
        + (c.url ? `<a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(M['원문 열기'])} ↗</a>` : '') + '</div>';
      else {      // 답: 줄인 말(say) 세 줄 → 「펼치기」면 같은 자리에 엔진 답 전문(칸 안에서 펼치고 접기, 새 창 없음)
        const open = ui.lawOpen, text = open ? e.answer : e.say || e.answer, n = revealN(text, e.answer);
        if (n < text.length) revealing = text.slice(0, n) || ' ';
        h += `<p class="lab">${esc(say.name)} · <span class="draft">${esc(M['초안 표시'])}</span></p><p class="say${open ? ' open' : ''}">${esc(text)}</p>`      // 칸 맞추기는 다 보인 글로 재고, 흘리는 중이면 아래에서 앞부분만 남긴다
          + `<button type="button" class="more" data-act="law-open" aria-expanded="${!!open}"${open || (e.say && e.say !== e.answer) ? '' : ' hidden'}>${esc(M[open ? '답 접기' : '답 펼치기'])}</button>`      // 줄인 답이거나 칸에서 잘리면 보인다(아래 fitLaw)
          + `<p class="from"><b>${esc(M['찾은 곳'])}</b><span class="chips2">${chips(null)}</span></p><p class="hint2">${esc(M['조항 누르기'])}${M['표준 답변 확인 켬'] === '켬' ? ` · ${esc(M['표준 답변 확인'])}` : ''}</p>`
          + (CTL() && e.ask ? `<p class="askq"><b>${esc(M['엔진 물음'])}</b>${esc(e.ask)}</p>` : '');
      }
    }
  }
  el.innerHTML = h;
  fitLaw(el);
  if (revealing) el.querySelector('.say').textContent = revealing.trim();      // 글자를 차례로(칸은 이미 다 보인 글에 맞춰 둠)
}
function fitLaw(el) {      // 칸 높이(222) 안에: 답이 잘리면 「펼치기」를 보이고, 그래도 넘치면 답을 두 줄로, 그래도 넘치면 조항 누르기 안내 줄을 뺀다(61번, 공원 고양이처럼 근거 단추가 두 줄일 때)
  const sy = el.querySelector('.say:not(.open)'), more = el.querySelector('.more'), fit = () => el.scrollHeight <= el.clientHeight + 1;
  if (!sy || !more) return;
  const cut = () => sy.scrollHeight > sy.clientHeight + 1;
  if (cut()) more.hidden = false;
  if (!fit()) { sy.classList.add('tight'); if (cut()) more.hidden = false; }
  if (!fit()) { const h2 = el.querySelector('.hint2'); if (h2) h2.remove(); }
}
// 답이 도착하면 글자를 차례로 보인다(도착한 글만. 오지 않은 글을 지어내지 않는다). 펼친 답 · 움직임 줄이기 설정이면 바로 다 보인다
const CPS = 40, still = matchMedia('(prefers-reduced-motion: reduce)').matches;
function revealN(text, key) {      // key = 엔진 답(같은 답이면 펼치고 접어도 다시 흘리지 않는다)
  if (!ui.reveal || ui.reveal.key !== key) ui.reveal = { key, t0: ui.lawOpen || still ? -1e9 : performance.now() };
  const n = Math.floor((performance.now() - ui.reveal.t0) / 1000 * CPS * SPEED);
  clearTimeout(ui.revealT);
  if (n < text.length) ui.revealT = setTimeout(() => { const el = document.querySelector('#law .say'); if (!el || !ui.reveal || ui.reveal.key !== key) return; const k = revealN(text, key); if (k >= text.length) renderLaw(); else el.textContent = text.slice(0, k); }, 40);      // 다 흘리면 한 번 다시 그려 칸에 맞춘다
  return n;
}
function lawCopyText(e) {      // 답 · 근거 조항 복사 글: 칸 이름(초안) → 민원인이 물은 것 → 엔진 답 전문 → 근거 조항(조항 · 시행일 · 인용 · 원문 주소)
  const M = K('일의 종류와 갈림'), q = e.question || (V.matter && V.matter.ask);
  return [`${M['답 칸 제목']} — ${M['초안 표시']}`, q ? `${M['시민 물음']}: ${q}` : '', `${M['답 전문']}: ${e.answer}`, `${M['근거 조항']}:`,
    ...e.citations.map((c) => `- ${c.label} (${fill(M['시행'], { 날짜: c.effective })})${c.quotes.length ? ` 「${c.quotes.join(' … ')}」` : ''}${c.url ? ` ${c.url}` : ''}`)].filter(Boolean).join('\n');
}
function refBlock() {      // 참고 자료(범용): 일의 종류마다 다르다. 조례 원문의 값(web/refs.json) → 자리 · 상태에 따라 표(서버의 넘길 곳 표) → 처리 기관 한 줄. 보일 것이 없으면 칸이 없다
  // 사람이 쓴 글(표 머리 · 단위 · 없음 줄 · 갈래 줄)은 문구 파일 「참고 자료」 표에서. refs.json에는 그 항목 이름만 있다(PR #114 리뷰)
  if (!V || !V.matter || !V.matter.type) return '';
  const M = K('일의 종류와 갈림'), F = K('일의 종류와 갈림', '살았나 죽었나'), U = K('접수 카드'), R = K('참고 자료'), r = V.route, type = V.matter.type;
  const T = (REFS.types || {})[type] || { routes: [] }, refs = (REFS.refs || {})[type] || [];
  let h = '', place = '', gal = '';
  const laws = new Set();
  for (const x of refs) {
    if (x.law) laws.add(`${x.law}|${x.effective}`);
    if (x.kind === 'table') { const hd = R[x.head].split(' · ');
      h += `<p class="rh">${esc(shortLaw(x.law))} ${esc(x.where)}</p><table class="rt"><colgroup><col class="c0">${hd.slice(1).map(() => '<col>').join('')}</colgroup><tr>${hd.map((c) => `<th>${esc(c)}</th>`).join('')}</tr>`
      + `${x.rows.map((row) => `<tr>${row.map((c, i) => `<td class="${i ? 'num' : ''}">${esc(c)}</td>`).join('')}</tr>`).join('')}</table><p class="ab">${esc(fill(U['단위'], { 단위: R[x.unit] }) + (x.more ? ' · ' + R[x.more] : ''))}</p>`; }
    else if (x.kind === 'quote') h += `<p class="ab">「${esc(x.text.replace(/^(.*?다\.)\s.+$/, '$1 …'))}」 — ${esc(refs.some((y) => y.kind === 'table' && y.law === x.law) ? '' : shortLaw(x.law) + ' ')}${esc(x.where)}</p>`;      // 같은 조례의 표가 위에 있으면 조례 이름은 빼고, 두 문장 넘는 조문은 첫 문장만
    else if (x.kind === 'text') h += `<p class="rh">${esc(shortLaw(x.law))} ${esc(x.where)}</p><blockquote>${esc(x.text)}</blockquote>`;
    else if (x.kind === 'absent') h += `<p class="ab">${esc(R[x.key])}</p>`;
    else if (x.kind === 'gal') gal = `<p class="ab gal">${esc(fill(U['갈래 줄'], { 갈래: R['갈래 ' + x.code], 기관: R['처리 기관 ' + x.code] }))}</p>`;
  }
  if (r && r.fate && r.fate.length) place = fateTable(r, true);
  else if (r && r.others.length > 1) {      // 같은 일이 다른 자리였다면 + 그 자리의 조례 6종 안팎(넘길 곳 표의 scope · law). 지금 자리와 같은 줄 · 서로 같은 줄은 묶는다
    const cls = Object.fromEntries(['자동차전용도로', '한강공원', '시 공원', '공원', '길'].map((c) => [M['다른 자리 · ' + c], c]));
    const sc6 = (p) => { const c = cls[p.split(' · ')[0]], rt = T.routes.find((x) => !x.class || x.class === c) || {}, s = rt.scope || T.scope, l = rt.law || T.law;
      return s === 'out' ? F['6종 밖 줄'] : l ? fill(F['6종 안 줄'], { 조례: shortLaw(l) }) : M['6종 후보']; };
    const here = r.others.find((o) => o.here), same = (o) => here && o.to === here.to && sc6(o.place) === sc6(here.place);
    const rest = r.others.filter((o) => !o.here && same(o)), rows = [];
    for (const o of r.others.filter((x) => x.here || !same(x))) { const g = !o.here && rows.find((x) => !x.here && x.to === o.to && sc6(x.place) === sc6(o.place)); if (g) g.place += ' · ' + o.place; else rows.push({ ...o }); }
    const one6 = new Set(r.others.map((o) => sc6(o.place))).size === 1;
    place = `<details class="same" open><summary>${esc(M['다른 자리 제목'])}</summary><table class="rt"><colgroup><col class="c1">${one6 ? '' : '<col class="c2">'}<col></colgroup><tr><th>${esc(F['자리'])}</th>${one6 ? '' : `<th>${esc(F['조례'])}</th>`}<th>${esc(F['넘길 곳'])}</th></tr>`
      + rows.map((o) => `<tr class="${o.here ? 'here' : ''}"><td>${esc(o.place)}${o.here ? ` <span class="badge in">${esc(M['지금 자리'])}</span>` : ''}</td>${one6 ? '' : `<td>${esc(sc6(o.place))}</td>`}<td>${esc(o.to)} <span class="badge ${o.basis === '확인' ? 'sure' : 'guess'}">${esc(F[o.basis === '확인' ? '확인' : '추측'])}</span></td></tr>`).join('') + '</table>'
      + `<p class="ab">${esc([one6 ? fill(U['6종 같음'], { 값: sc6(r.others[0].place) }) : '', rest.length ? fill(U['같은 줄 묶음'], { 자리: rest.map((o) => o.place).join(' · ') }) : ''].filter(Boolean).join(' · '))}</p></details>`;
  }
  if (!h && !place) return '';
  const src = [place ? U['출처 표'] : '', gal ? U['출처 갈래'] : '', ...[...laws].map((k) => { const [l, d] = k.split('|'); return fill(U['출처 조례'], { 조례: shortLaw(l), 날짜: d }); })].filter(Boolean).join(' · ');
  return `<div class="slot s-ref"><div class="t">${esc(U['참고 제목'])}<span>${esc(V.matter.line || '')}</span></div><div class="rbody" data-more="${esc(U['더 있음'])}">${h}${place}${gal}</div><p class="src">${esc(U['출처'])}: ${esc(src)}</p></div>`;
}
function fixBox() {      // 「일」 고치기(57번 6): 화면이 읽은 일의 종류를 넘길 곳 표의 종류에서 바로 고른다(새 창 없음). 고르면 넘길 곳 · 조례 6종 안팎이 다시 정해진다
  const U = K('접수 카드'), types = META.types || {}, cur = V && V.matter && V.matter.type;
  if (!cur || !Object.keys(types).length) return '';
  return (S.fix ? ` <span class="badge guess">${esc(U['일 고침 표시'])}</span>` : '')
    + ` <select class="fix" aria-label="${esc(U['일 고치기 설명'])}" title="${esc(U['일 고치기 설명'])}"${ui.pending || ui.playing ? ' disabled' : ''}><option value="" selected hidden>${esc(U['일 고치기'])}</option>`
    + Object.entries(types).map(([k, name]) => `<option value="${esc(k)}"${k === cur ? ' disabled' : ''}>${esc(name)}</option>`).join('') + '</select>';
}
function renderSide() {   // 접수 카드 = 넘길 것. 덩어리 차례 · 높이 고정: 요약 → 처리할 담당 부서 → 둘레 기록 → 진행 상태 → (보일 것이 있을 때만) 참고 자료
  renderLaw();
  if (ui.view === 'records') return renderRecCard();
  const M = K('일의 종류와 갈림'), U = K('접수 카드'), r = V && V.route, e = engNow(), s = (V && V.summary) || {}, sc = V && V.matter && V.matter.scope;
  const none = `<dd class="none">${esc(U['미정'])}</dd>`, dd = (v, x = '') => (v ? `<dd>${esc(v)}${x}</dd>` : none);
  const lawLine = r && sc === 'in' && hasAns(e) ? fill(M['적용 조례'], { 장소: [r.class_name, r.class].filter(Boolean).join(' · '), 조례: [...new Set(e.citations.map((c) => c.label.replace(/\s*제\d+조.*$/, '')))].join(' · ') })
    : r && r.scope === 'out' ? M['6종 밖'] : '';      // 조례 이름은 엔진이 근거 조항을 붙였을 때만 단정한다(server.py build()의 6종 안 판정과 같음). 찾는 중 · 근거 없음 · 위치 전에는 「아직 정해지지 않음」(PR #114 리뷰)
  const cites = sc === 'in' && hasAns(e) ? citeText(e, true) : sc === 'out' ? U['6종 밖 근거'] : '';      // 부서에 넘길 근거 조항(조항 이름). 인용문 · 시행일 · 원문은 조례 칸에서 누르면 본다
  let h = `<div class="chd"><h2>${esc(U['제목'])}</h2><span class="badge guess">${esc(U['가상 표시'])}</span><span class="copied" role="status">${esc(ui.copied)}</span><button type="button" class="outline copy" data-act="copy"${s.where ? '' : ' disabled'}>${esc(U['복사'])}</button></div>`
    + '<dl class="sum">'
    + `<dt>${esc(U['접수 담당자'])}</dt><dd>${esc(U['접수 담당자 값'])} <span class="sub">${esc(U['접수 담당자 설명'])}</span></dd>`
    + `<dt>${esc(U['일'])}</dt>${dd(s.matter, fixBox())}`      // 61번: 두 줄(민원인이 한 말 · 연락처)을 더해 요약 높이 262 안에 들게, 「민원을 받은 곳」(늘 같은 값)과 이 줄의 6종 표시(「조례」 줄 · 조례 칸 머리와 같음)는 화면에서 뺐다. 복사 글에는 그대로
    + `<dt>${esc(U['조례 줄'])}</dt>${dd(lawLine)}<dt>${esc(U['근거'])}</dt>${dd(cites)}`
    + (s.go ? `<dt class="go">${esc(U['찾아가는 말'])}</dt><dd class="go">${esc(s.go)}</dd>` : `<dt>${esc(U['위치'])}</dt>${dd(s.where)}`)
    + `<dt class="go">${esc(U['번지수'])}</dt>${s.bunji ? `<dd class="go">${esc(s.bunji.text)}${s.bunji.road ? `<span class="rd">${esc(s.bunji.road)}</span>` : ''}</dd>` : none}`
    + `<dt>${esc(U['민원인 말'])}</dt>${s.said ? `<dd class="said" title="${esc(s.said)}">「${esc(s.said)}」</dd>` : none}`      // 민원인이 위치를 처음 말한 문장 그대로(57번 5가): 현장이 못 찾으면 이 말로 다시 묻는다
    + (V && V.pin && V.pin.exact ? '' : `<dt>${esc(U['범위'])}</dt>${dd(s.size)}`)      // 지도 좌표는 복사 글에만(화면에는 지도의 핀). 두 줄을 더해 요약 높이 262 안에 들게(61번)
    + (s.said_place ? `<dt>${esc(U['말 그대로'])}</dt>${dd(s.said_place)}` : '')
    + `<dt>${esc(U['연락처'])}</dt>${callerNo() ? `<dd>${esc(callerNo())} <span class="sub2">${esc(U['가상 번호 표시'])}</span></dd>` : `<dd class="none">${esc(U['번호 없음'])}</dd>`}</dl>`;      // 전화가 온 번호(가상 · 가운데를 가림, 동규 11-19)
  // 처리할 담당 부서: 위치 전에는 같은 칸 안에 「가능성이 큰 곳」 두 줄(정해지면 이 칸이 담당 부서로 바뀐다)
  h += `<div class="slot s-to${r ? ' set' : ''}"><div class="t">${esc(U['담당 부서'])}${r ? '' : `<span>${esc(U['담당 부서 대기'])}</span>`}</div>`;
  if (r) h += `<p class="v">${esc(r.hit.to)}</p><p class="n"><span class="badge ${r.hit.basis === '확인' ? 'sure' : 'guess'}">${esc(M[r.hit.basis === '확인' ? '확인' : '추측'])}</span>${CTL() ? esc(r.hit.note || '') : ''}</p>`;      // 넘길 곳의 출처 글은 조작 화면에서만(main 깔끔한 화면과 같음)
  else h += ((V && V.cands) || []).slice(0, 2).map((x) => `<div class="cd"><span class="nm">${esc(x.name)}</span><span class="pb"><i style="width:${Math.round(x.p * 100)}%"></i></span><span class="pv">${Math.round(x.p * 100)}%</span></div>`).join('');
  h += '</div>';
  h += nearBox();
  // 처리 진행 상태: 다섯 칸을 모두 보이고, 막힌 까닭은 한 줄로(확인받기 전 / 담당 부서가 알려 오면)
  const can = !!(V && V.confirmed);
  h += `<fieldset class="radio"><legend>${esc(U['진행 상태'])}</legend>`
    + radio5('status', ui.status, (id) => can && (id === ui.status || (['filed', 'sent'].includes(id) && (NEXTS[ui.status] || []).includes(id))), () => '')
    + `<p class="exnote">${esc(can ? U['상태 막힘 부서'] : U['상태 막힘 통화'])}</p>${can ? `<p class="hint">${esc(U['상태 안내'])}</p>` : ''}</fieldset>`;
  h += refBlock();
  if (CTL() && V && V.confirmed && V.pin) h += `<div class="sumbtn"><button type="button" class="outline" data-act="alias">${esc(U['별명 저장'])}</button>${TRIAL && S && S.lines.length ? `<button type="button" class="outline" data-act="trial">${esc(U['시험 기록'])} ${esc(TRIAL)}</button>` : ''}</div>`;      // 숨은 조작 화면에서만
  const el = $('side'); el.innerHTML = h;
  const rb = el.querySelector('.s-ref .rbody'); if (rb) rb.classList.toggle('cut', rb.scrollHeight > rb.clientHeight + 2);      // 참고 자료가 칸보다 길면 칸 안에서만 잘리고 「아래에 더 있음」
}
// ---- 상담 기록 화면: 왼쪽 목록(상태 칩 · 넘긴 곳 고르기) · 지도 번호 점 · 오른쪽 고른 기록(그때의 접수 카드 + 처리 상태 + 처리 기록)
function renderRecList() {
  const B = K('상담 기록'), list = recShown(), n = (s) => RECS.filter((r) => s === 'all' || r.status === s).length;
  let h = `<header><h2 id="l-title"><span class="big">${RECS.length}</span>${esc(B['제목'])}</h2><p class="lead">${esc(B['안내'])}</p>`
    + `<div class="chips" role="group">${['all', 'filed', 'sent', 'doing', 'recall', 'closed'].map((s) => `<button type="button" data-rst="${s}" class="${s === 'all' ? 'all' : 'st-' + s}" aria-pressed="${ui.recSt === s}">${esc(s === 'all' ? B['모두'] : stName(s))} <b>${n(s)}</b></button>`).join('')}</div>`
    + `<select id="rec-to" aria-label="${esc(B['넘긴 곳 모두'])}"><option value="">${esc(B['넘긴 곳 모두'])}</option>${[...new Set(RECS.map((r) => r.to))].sort().map((t) => `<option${t === ui.recTo ? ' selected' : ''}>${esc(t)}</option>`).join('')}</select></header>`;
  h += `<ol class="recs">${list.length ? list.map((r) => `<li><button type="button" data-rec="${esc(r.id)}" class="${r.id === ui.rec ? 'on' : ''}"><span class="no">${recNo(r)}</span><span class="m">${esc(r.matter)}</span>${stb(r.status)}`
    + `<span class="g">${r.sample ? '' : `<span class="new">${esc(B['새 기록'])}</span> · `}${esc(ago(r))} · ${esc(r.go)}</span></button></li>`).join('') : `<li class="none">${esc(B['없음'])}</li>`}</ol>`;
  h += `<footer><div class="lgd">${['filed', 'sent', 'doing', 'recall', 'closed'].map((s) => `<span class="st-${s}"><i></i>${esc(stName(s))}</span>`).join('')}</div>`
    + `<p class="exnote"><em class="ex">${esc(B['예시 표시'])}</em> ${esc(B['예시 꼬리'])}</p>`
    + `<div class="row"><span class="exnote">${esc(ui.recErr || B['지도 범례'])}</span><button type="button" class="outline" data-act="rec-reset" title="${esc(B['되돌리기 설명'])}">${esc(B['되돌리기'])}</button></div></footer>`;
  $('reclist').innerHTML = h;
}
function renderRecCard() {
  const B = K('상담 기록'), U = K('접수 카드'), M = K('일의 종류와 갈림'), r = RECS.find((x) => x.id === ui.rec);
  if (!r) { $('side').innerHTML = `<div class="chd"><h2>${esc(B['제목'])}</h2></div><p class="empty">${esc(B['고르기 안내'])}</p>`; return; }
  const sc = { in: '6종 안', out: '6종 밖', wait: '6종 확인 중', nocite: '6종 근거 없음', cand: '6종 후보' }[r.scope];
  const law = r.law ? fill(M['적용 조례'], { 장소: r.place, 조례: r.law }) + (r.sample ? ` ${B['표 기준']}` : '') : r.scope_why;
  let h = `<div class="chd"><h2>${esc(fill(B['카드 제목'], { 번호: recNo(r) }))}</h2>${r.sample ? `<em class="ex">${esc(B['예시 표시'])}</em>` : `<span class="stb st-sent">${esc(B['새 기록'])}</span>`}</div><dl class="sum">`
    + `<dt>${esc(B['받은 때'])}</dt><dd>${esc(ago(r))} · ${esc(U['받은 곳 값'])}</dd>`
    + `<dt>${esc(U['일'])}</dt><dd>${esc(r.matter)}${sc ? ` <span class="badge ${r.scope === 'in' ? 'in' : r.scope === 'out' ? 'out' : 'going'}">${esc(M[sc])}</span>` : ''}</dd>`
    + (law ? `<dt>${esc(U['조례 줄'])}</dt><dd>${esc(law)}</dd>` : '')
    + `<dt class="go">${esc(U['찾아가는 말'])}</dt><dd class="go">${esc(r.go)}</dd>`
    + (r.bunji ? `<dt class="go">${esc(U['번지수'])}</dt><dd class="go">${esc(r.bunji.text)}${r.bunji.road ? `<span class="rd">${esc(r.bunji.road)}</span>` : ''}</dd>` : '')
    + `<dt>${esc(U['범위'])}</dt><dd>${esc(r.range || '')}</dd><dt>${esc(B['장소'])}</dt><dd>${esc(r.place)}</dd></dl>`;
  h += `<div class="box to set"><div class="t">${esc(U['담당 부서'])}</div><p class="v">${esc(r.to)}</p><p class="n"><span class="badge ${r.basis === '확인' ? 'sure' : 'guess'}">${esc(M[r.basis === '확인' ? '확인' : '추측'])}</span></p></div>`;
  if (r.status === 'recall') h += `<div class="box recall"><div class="t">${esc(B['다시 전화 제목'])}</div><p>${esc(fill(B['다시 전화 글'], { 범위: r.range || '' }))}</p></div>`;
  const next = NEXTS[r.status] || [];
  h += `<fieldset class="radio"><legend>${esc(U['진행 상태'])}</legend>${radio5('rstatus', r.status, (id) => id === r.status || next.includes(id), (id) => whyOff(id, r.status))}<p class="exnote">${esc(B['상태 안내'])}</p></fieldset>`;
  h += `<div class="box"><div class="t">${esc(B['처리 기록'])}</div><ol class="rlog">${r.log.map((x) => `<li>${stb(x.status)}${x.at ? `<small>${esc(ago({ at: x.at }))}</small>` : ''}</li>`).join('')}</ol></div>`
    + (ui.recErr ? `<p class="exnote">${esc(ui.recErr)}</p>` : '');
  $('side').innerHTML = h;
}
function renderAll() { renderTop(); renderTalk(); renderAsk(); renderRange(); renderSide(); renderRecList(); renderMap(); }

// ---- 지도 (MapLibre + OpenFreeMap positron 바탕에 화면 밝기별로 다시 칠함. 색은 call.css의 --map-*)
const STYLE = 'https://tiles.openfreemap.org/styles/positron', CAM = { pitch: 46, bearing: -10 }, FILL = 0.78;
const MAPC = ['bg', 'water', 'waterway', 'park', 'wood', 'resid', 'b-foot', 'road', 'road-minor', 'road-case', 'rail', 'label', 'halo', 'water-label', 'park-label', 'park-line',
  'b-low', 'b-mid', 'b-high', 'roof', 'b-line', 'mask', 'mask-op', 'data', 'hot', 'cloud-a', 'light', 'light-i'];
function pal() {   // 지금 화면 밝기의 지도 색 = call.css의 --map-* 변수(색은 그 파일에만 적는다). b-low → C.bLow
  const cs = getComputedStyle(document.body), C = {};
  for (const k of MAPC) C[k.replace(/-(\w)/g, (_, c) => c.toUpperCase())] = cs.getPropertyValue('--map-' + k).trim();
  return C;
}
let map = null, mapOk = false, lastFit = '';
const markers = [];
const shown = (el) => (el && getComputedStyle(el).display !== 'none' ? el.getBoundingClientRect() : null);
function freeRect() {   // 칸에 가리지 않은 지도 자리
  const L = shown($('talk')) || shown($('reclist')), R = shown($('side')), A = shown($('ask')), B = shown($('range'));
  const l = (L ? L.right : 0) + 26, r = (R ? R.left : innerWidth) - 26, t = (A ? A.bottom : 56) + 34, b = (B ? B.top : innerHeight) - 30;
  return { l, r, t, b, w: Math.max(r - l, 120), h: Math.max(b - t, 120), cx: (l + r) / 2, cy: (t + b) / 2 };
}
function fitPoints(pts, F, maxZ) {   // 기울인 시점에서 점들을 화면에 비춰 보며 사각형 F 안에 맞춘다(fitBounds는 기울기를 셈하지 않는다)
  const saved = { center: map.getCenter(), zoom: map.getZoom(), pitch: map.getPitch(), bearing: map.getBearing() };
  map.jumpTo({ center: [pts.reduce((s, c) => s + c[0], 0) / pts.length, pts.reduce((s, c) => s + c[1], 0) / pts.length], zoom: 13, ...CAM });
  const box = () => { const p = pts.map((c) => map.project(c)), xs = p.map((q) => q.x), ys = p.map((q) => q.y); return [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)]; };
  const center = () => { const [x0, x1, y0, y1] = box(); map.jumpTo({ center: map.unproject([innerWidth / 2 + (x0 + x1) / 2 - F.cx, innerHeight / 2 + (y0 + y1) / 2 - F.cy]) }); };
  for (let n = 0; n < 10; n++) {   // 확대와 가운데 맞추기를 따로 번갈아(한 번에 하면 오가며 안 맞는다)
    center();
    const [x0, x1, y0, y1] = box();
    map.jumpTo({ zoom: Math.min(maxZ, map.getZoom() + Math.log2(Math.min(F.w * FILL / Math.max(x1 - x0, 1), F.h * FILL / Math.max(y1 - y0, 1)))) });
  }
  center();
  const out = { center: map.getCenter(), zoom: map.getZoom(), ...CAM };
  map.jumpTo(saved);
  return out;
}
function paint(id, prop, v) { if (map.getLayer(id)) { try { map.setPaintProperty(id, prop, v); } catch { /* 그 층에 없는 속성 */ } } }
const H = ['coalesce', ['get', 'render_height'], 10], H0 = ['coalesce', ['get', 'render_min_height'], 0];
const rgba = (hex, a) => `rgba(${parseInt(hex.slice(1, 3), 16)}, ${parseInt(hex.slice(3, 5), 16)}, ${parseInt(hex.slice(5, 7), 16)}, ${a})`;
const cloudColor = (C) => ['interpolate', ['linear'], ['heatmap-density'], 0, rgba(C.data, 0), 0.08, rgba(C.data, +C.cloudA), 0.45, rgba(C.data, 0.8), 1, rgba(C.hot, 0.95)];   // 가능성이 클수록 짙게(한 색의 단계), 가장 큰 곳은 가장 짙은 색
function applyTone() {
  const C = pal();
  for (const l of map.getStyle().layers) {
    if (l.source !== 'openmaptiles' || l.id.startsWith('own-')) continue;
    if (l.type === 'line' && l['source-layer'] === 'transportation') paint(l.id, 'line-color', /casing/.test(l.id) ? C.roadCase : /rail/.test(l.id) ? C.rail : /minor|path|service|pier/.test(l.id) ? C.roadMinor : C.road);
    if (/shield/.test(l.id)) { map.setLayoutProperty(l.id, 'visibility', 'none'); continue; }
    if (l.type === 'symbol') { paint(l.id, 'text-color', /water/.test(l.id) ? C.waterLabel : C.label); paint(l.id, 'text-halo-color', C.halo); paint(l.id, 'text-halo-width', 1.4); }
  }
  paint('background', 'background-color', C.bg); paint('water', 'fill-color', C.water); paint('waterway', 'line-color', C.waterway);
  paint('park', 'fill-color', C.park); paint('landcover_wood', 'fill-color', C.wood); paint('landuse_residential', 'fill-color', C.resid);
  paint('building', 'fill-color', C.bFoot); paint('building', 'fill-outline-color', C.bLine);
  paint('own-park-line', 'line-color', C.parkLine); paint('own-park-label', 'text-color', C.parkLabel); paint('own-park-label', 'text-halo-color', C.halo);
  paint('own-b3d', 'fill-extrusion-color', ['interpolate', ['linear'], H, 0, C.bLow, 40, C.bMid, 150, C.bHigh]); paint('own-roof', 'fill-extrusion-color', C.roof);
  paint('own-mask', 'fill-color', C.mask); paint('own-mask', 'fill-opacity', +C.maskOp); paint('own-area', 'line-color', C.data);
  paint('own-cloud', 'heatmap-color', cloudColor(C)); paint('own-ring', 'line-color', C.hot);
  map.setLight({ anchor: 'viewport', position: [1.15, 210, 30], color: C.light, intensity: +C.lightI });
}
function addOwnLayers() {
  const firstSym = (map.getStyle().layers.find((l) => l.type === 'symbol') || {}).id, C = pal(), ring = META.seoul;
  const add = (spec, before) => { if (!map.getLayer(spec.id)) map.addLayer(spec, before); };
  const empty = { type: 'FeatureCollection', features: [] };
  for (const l of map.getStyle().layers) { const f = l.type === 'symbol' && map.getLayoutProperty(l.id, 'text-field'); if (f && /name/.test(JSON.stringify(f))) map.setLayoutProperty(l.id, 'text-field', ['coalesce', ['get', 'name:ko'], ['get', 'name']]); }
  add({ id: 'own-park-line', type: 'line', source: 'openmaptiles', 'source-layer': 'park', minzoom: 11, paint: { 'line-color': C.parkLine, 'line-width': ['interpolate', ['linear'], ['zoom'], 11, 0.6, 15, 1.8] } }, firstSym);
  // 가능성 구름: 격자점마다 가능성을 무게로 준 열 지도. 가능성이 클수록 짙다. 번지는 반지름은 점 하나가 나타내는 폭(m)에 맞춰 확대와 함께 커진다
  map.addSource('own-cloud', { type: 'geojson', data: empty });
  add({ id: 'own-cloud', type: 'heatmap', source: 'own-cloud', paint: { 'heatmap-color': cloudColor(C), 'heatmap-weight': ['interpolate', ['linear'], ['get', 'w'], 0, 0.15, 1, 1],
        'heatmap-intensity': 0.55, 'heatmap-radius': 8, 'heatmap-opacity': 0.9 } }, firstSym);
  map.addSource('own-ring', { type: 'geojson', data: empty });
  add({ id: 'own-ring', type: 'line', source: 'own-ring', paint: { 'line-color': C.hot, 'line-width': 2.2, 'line-dasharray': [2, 1.5] } }, firstSym);
  add({ id: 'own-b3d', type: 'fill-extrusion', source: 'openmaptiles', 'source-layer': 'building', minzoom: 13,
        paint: { 'fill-extrusion-color': ['interpolate', ['linear'], H, 0, C.bLow, 40, C.bMid, 150, C.bHigh], 'fill-extrusion-height': ['max', ['-', H, 0.8], 0], 'fill-extrusion-base': H0,
                 'fill-extrusion-opacity': ['interpolate', ['linear'], ['zoom'], 13, 0, 14, 0.9], 'fill-extrusion-vertical-gradient': true } }, firstSym);
  add({ id: 'own-roof', type: 'fill-extrusion', source: 'openmaptiles', 'source-layer': 'building', minzoom: 13,
        paint: { 'fill-extrusion-color': C.roof, 'fill-extrusion-height': H, 'fill-extrusion-base': ['max', ['-', H, 0.8], 0], 'fill-extrusion-opacity': ['interpolate', ['linear'], ['zoom'], 13, 0, 14, 0.9] } }, firstSym);
  map.moveLayer('own-cloud', firstSym); map.moveLayer('own-ring', firstSym);     // 가능성 구름과 범위 선은 건물 위에 그린다(색은 뜻이 있는 것에만)
  add({ id: 'own-park-label', type: 'symbol', source: 'openmaptiles', 'source-layer': 'park', minzoom: 12.5, filter: ['has', 'name'],
        layout: { 'text-field': ['coalesce', ['get', 'name:ko'], ['get', 'name']], 'text-font': ['Noto Sans Bold'], 'text-size': 12.5 }, paint: { 'text-color': C.parkLabel, 'text-halo-color': C.halo, 'text-halo-width': 1.6 } });
  // 서울 밖은 흐리게 가리고 경계에 선
  map.addSource('own-mask', { type: 'geojson', data: { type: 'Feature', geometry: { type: 'Polygon', coordinates: [[[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]], ring] } } });
  add({ id: 'own-mask', type: 'fill', source: 'own-mask', paint: { 'fill-color': C.mask, 'fill-opacity': +C.maskOp } });
  map.addSource('own-area', { type: 'geojson', data: { type: 'Feature', geometry: { type: 'LineString', coordinates: ring } } });
  add({ id: 'own-area', type: 'line', source: 'own-area', paint: { 'line-color': C.data, 'line-width': 1.6, 'line-opacity': 0.75 } });
}
function initMap() {
  if (!window.maplibregl) return mapFailed();
  try {
    map = new maplibregl.Map({ container: 'map', style: STYLE, center: [126.99, 37.56], zoom: 10.4, ...CAM, maxPitch: 60, attributionControl: false });
    const floor = () => { map.setMinZoom(null); map.setMinZoom(Math.max(fitPoints(META.seoul, freeRect(), 17).zoom - 0.3, 9.0)); };   // 가장 멀리 축소해도 서울 전체가 지도 칸에 맞는 정도까지만(칸 크기가 바뀌면 다시 구함). 9.0 = 좁은 창에서도 서울 가로 약 300px 아래로 줄지 않게 하는 바닥(기울기 46도에서 잰 값)
    map.on('style.load', () => { addOwnLayers(); applyTone(); mapOk = true; floor(); lastFit = ''; renderMap(true); });
    map.on('resize', () => { floor(); lastFit = ''; renderMap(true); });
    map.on('click', (e) => {                                    // 상담사가 아는 곳이면 지도에서 바로 찍는다: 그 자리 둘레가 단서 하나가 된다
      if (!ui.pin || ui.pending) return;
      ui.pin = false; document.body.classList.remove('pinning');
      queue(() => turnReq({ pin: [e.lngLat.lng, e.lngLat.lat] }));
    });
    map.on('error', (e) => { if (!mapOk && /style|Failed to fetch/i.test(String(e.error && e.error.message))) mapFailed(); });
  } catch { mapFailed(); }
}
function mapFailed() { $('map-failed').hidden = false; $('map-failed').textContent = K('지도')['지도 실패']; }
const circle = ([lon, lat], m) => Array.from({ length: 49 }, (_, i) => { const a = (i / 48) * 2 * Math.PI; return [lon + (m / 88200) * Math.cos(a), lat + (m / 111000) * Math.sin(a)]; });
function renderRecMap(jump) {      // 기록 화면: 고른 조건의 기록마다 번호 점(상태색 + 목록과 같은 번호), 고른 기록은 그때 넘긴 범위를 점선 원으로
  const list = recShown(), sel = RECS.find((r) => r.id === ui.rec), ringM = sel && sel.range_m ? (sel.range_kind === 'length' ? sel.range_m / 2 : sel.range_m) : 0;
  map.getSource('own-cloud').setData({ type: 'FeatureCollection', features: [] });
  map.getSource('own-ring').setData(sel && ringM > 60 ? { type: 'Feature', geometry: { type: 'LineString', coordinates: circle(sel.point, ringM) } } : { type: 'FeatureCollection', features: [] });
  while (markers.length) markers.pop().remove();
  for (const r of list) {
    const el = document.createElement('div');
    el.className = `rdot st-${r.status}${r === sel ? ' on' : ''}`; el.textContent = recNo(r); el.dataset.rec = r.id; el.title = `${ago(r)} · ${r.matter} · ${stName(r.status)}`;
    markers.push(new maplibregl.Marker({ element: el }).setLngLat(r.point).addTo(map));
  }
  if (sel) { const lab = document.createElement('div'); lab.className = 'rlab'; lab.textContent = sel.go; markers.push(new maplibregl.Marker({ element: lab, anchor: 'bottom', offset: [0, -20] }).setLngLat(sel.point).addTo(map)); }
  const key = JSON.stringify(['rec', ui.rec, ui.recSt, ui.recTo, list.length, innerWidth, innerHeight]);
  if (key === lastFit) return;
  lastFit = key;
  const pts = sel ? circle(sel.point, Math.max(150, Math.min(ringM, 800))) : list.length >= 2 ? list.map((r) => r.point) : list.length ? circle(list[0].point, 300) : META.seoul;
  const cam = fitPoints(pts, freeRect(), sel ? 16 : 15);
  if (jump) map.jumpTo(cam); else map.flyTo({ ...cam, duration: 1200 / Math.min(SPEED, 3), essential: true });
}
function renderMap(jump) {
  if (!mapOk) return;
  if (ui.view === 'records') return renderRecMap(jump);
  const heat = (V && V.heat) || { pts: [], cell: 20 }, pts = heat.pts;
  map.getSource('own-cloud').setData({ type: 'FeatureCollection', features: pts.map(([x, y, w]) => ({ type: 'Feature', properties: { w }, geometry: { type: 'Point', coordinates: [x, y] } })) });
  const px = (z) => Math.max(3, (heat.cell * 2.2) * (2 ** z) / 124100);      // 점 하나의 폭(m)을 그 확대에서의 화면 픽셀로(서울 위도). 이웃 점과 겹쳐 이어지게 넉넉히
  map.setPaintProperty('own-cloud', 'heatmap-radius', ['interpolate', ['exponential', 2], ['zoom'], 9, px(9), 20, px(20)]);
  map.getSource('own-ring').setData(V && V.done && V.center && !(V.pin && V.pin.exact) ? { type: 'Feature', geometry: { type: 'LineString', coordinates: circle(V.center, Math.max(V.radius, 25)) } } : { type: 'FeatureCollection', features: [] });
  while (markers.length) markers.pop().remove();
  const put = (el, c, opt = {}) => markers.push(new maplibregl.Marker({ element: el, ...opt }).setLngLat(c).addTo(map));
  const opts = (ui.askQ && ui.askQ.options) || [], marks = [];
  for (const o of opts) for (const c of (o.set.clues || [])) { if (c.p && typeof c.p[0] === 'number') marks.push([ll(c.p), c.label || o.label]); else if (c.p) c.p.forEach((q, i) => marks.push([ll(q), (c.label || '').replace(' 사이', '').split(' ~ ')[i] || ''])); }
  const seen = new Set();
  marks.filter(([c, name]) => name && !seen.has(name) && seen.add(name)).forEach(([c, name], k, all) => {   // 지금 질문이 물어보는 표지. 많으면 이름 없이 점만
    const el = document.createElement('div'), dot = all.length > 7;
    el.className = 'mk' + (dot ? ' dot' : ''); el.title = name; if (!dot) el.textContent = name;
    put(el, c, dot ? {} : k % 2 ? { anchor: 'top', offset: [0, 5] } : { anchor: 'bottom', offset: [0, -5] });
  });
  if (V && V.done && V.center) {
    const at = (V.pin && V.pin.at) || V.center;
    const pin = document.createElement('div'); pin.className = 'mpin'; put(pin, at);
    const lab = document.createElement('div'); lab.className = 'pinlab'; lab.textContent = (V.pin && V.pin.label) || K('지도')['정해진 자리']; put(lab, at, { anchor: 'top', offset: [0, 18] });
  }
  for (const { r } of nearRecs()) {      // 둘레의 지난 기록: 속 빈 점(번호 = 상담 기록의 번호). 누르면 기록 화면에서 연다
    const el = document.createElement('div'); el.className = 'rk'; el.textContent = recNo(r); el.dataset.rec = r.id; el.title = `${ago(r)} · ${r.matter} · ${stName(r.status)}`; put(el, r.point);
  }
  const strong = pts.filter((p) => p[2] >= 0.12), fitPts = (strong.length >= 2 ? strong : pts).map((p) => [p[0], p[1]]);
  const use = fitPts.length >= 2 ? fitPts : fitPts.length ? circle(fitPts[0], 60) : META.seoul;
  const key = JSON.stringify([use.length, use[0], use[use.length - 1], innerWidth, innerHeight, !!(V && V.done)]);
  if (key === lastFit) return;
  lastFit = key;
  const step = Math.max(1, Math.floor(use.length / 400)), cam = fitPoints(use.filter((_, i) => i % step === 0), freeRect(), V && V.done ? 16.3 : 17);
  if (jump) map.jumpTo(cam); else map.flyTo({ ...cam, duration: 1500 / Math.min(SPEED, 3), essential: true });
}
function setTone(t) { ui.tone = t; document.body.dataset.tone = t; renderTop(); if (mapOk) applyTone(); }

// ---- 누르는 것
document.addEventListener('click', async (ev) => {
  if (ev.target.closest('#side .s-ref summary')) { ev.preventDefault(); return; }      // 참고 자료 표는 늘 펼친다(눌러 접히면 다시 그릴 때 저절로 펼쳐지던 것, 64번 P12)
  const rk = ev.target.closest('[data-rec]');      // 기록 하나(목록 · 지도 점 · 통화 카드의 둘레 기록) → 상담 기록 화면에서 연다
  if (rk) { openRec(rk.dataset.rec); return; }
  const b = ev.target.closest('button'); if (!b || b.disabled) return;
  const d = b.dataset;
  if (d.view) { if (ui.view !== d.view) { ui.view = d.view; lastFit = ''; if (d.view === 'records') await loadRecords(); renderAll(); } }
  else if (d.rst) { ui.recSt = d.rst; renderRecList(); renderMap(); }
  else if (d.act === 'rec-reset') { if (await recPost({ op: 'reset' })) ui.rec = null; lastFit = ''; renderAll(); }
  else if (d.scene) { ui.scene = d.scene; ui.input = SCRIPTS[d.scene] ? 'script' : 'type'; resetCall(); }
  else if (d.tone) setTone(d.tone);
  else if (d.voice) { ui.voice = !ui.voice; renderTop(); }
  else if (d.input) { if (ui.input !== d.input) { ui.input = d.input; if (ui.playing) resetCall(); renderTalk(); renderAsk(); } }
  else if (d.opt !== undefined && ui.askQ) { const o = ui.askQ.options[Number(d.opt)]; if (o) queue(() => turnReq({ set: o.set, label: o.label })); }
  else if (d.act === 'pin') { ui.pin = !ui.pin; document.body.classList.toggle('pinning', ui.pin); renderRange(); }
  else if (d.act === 'undo') queue(() => turnReq({ undo: true }));
  else if (d.act === 'play') { if (SCRIPTS[ui.scene]) play(); else { ui.input = 'type'; resetCall(); document.body.classList.add('ctl'); renderAll(); const t = $('k-text'); if (t) t.focus(); } }      // 대본 없는 장면은 글로 넣는 통화(64번 P03)
  else if (d.act === 'pause') { ui.paused = !ui.paused; renderTalk(); renderAsk(); }
  else if (d.act === 'reset') resetCall();
  else if (d.act === 'send') { const t = $('k-text'), v = t.value.trim(); if (v) { t.value = ''; queue(() => citizen(v, 'type')); } }
  else if (d.act === 'alias' && V && V.pin) {   // 확인받은 자리에 시민이 부른 이름을 붙여 둔다(다음 통화부터 그 이름을 알아듣는다)
    const U = K('접수 카드'), name = window.prompt(U['별명 묻기'], (V.summary && V.summary.said_place) || '');
    if (name && name.trim()) {
      try { await api('/api/alias', { name: name.trim(), at: V.pin.at }); ui.copied = fill(U['별명 저장됨'], { 이름: name.trim() }); } catch { ui.copied = U['별명 저장 실패']; }
      renderSide();
    }
  }
  else if (d.act === 'trial' && S && TRIAL) {      // 시험 기록: 서버가 통화 글 · 확정한 자리를 로컬 파일에 한 줄로 남긴다(tools/human_test.py score가 읽음)
    const U = K('접수 카드');
    try { await api('/api/trial', { trial: TRIAL, state: S, sec: ui.t0 ? Math.round(((ui.t1 || Date.now()) - ui.t0) / 1000) : null }); ui.copied = fill(U['시험 기록 남김'], { 번호: TRIAL }); } catch { ui.copied = U['시험 기록 실패']; }
    renderSide();
  }
  else if (d.act === 'cite') { ui.cite = Number(d.i); renderLaw(); }      // 조례 칸 안에서 조문(인용문 · 시행일 · 원문 열기)으로
  else if (d.act === 'cite-back') { ui.cite = null; renderLaw(); }
  else if (d.act === 'copy' && V) {
    const U = K('접수 카드'), st = { filed: '접수됨', sent: '넘김' }[ui.status];
    const at = ui.t0 ? new Date(ui.t0) : null, p2 = (x) => String(x).padStart(2, '0');      // 받은 때(통화를 받은 시각)는 맨 아래 진행 상태 위에
    const when = at ? `\n${K('상담 기록')['받은 때']}: ${at.getFullYear()}-${p2(at.getMonth() + 1)}-${p2(at.getDate())} ${p2(at.getHours())}:${p2(at.getMinutes())}` : '';
    const tel = `\n${U['연락처']}: ${callerNo() ? `${callerNo()} ${U['가상 번호 표시']}` : U['번호 없음']}`;      // 넘겨받는 부서가 민원인에게 다시 연락할 때 쓰는 줄
    try { await navigator.clipboard.writeText(V.summary.copy + tel + when + (st ? `\n${U['진행 상태']}: ${U[st]}` : '')); ui.copied = U['복사됨']; } catch { ui.copied = U['복사 실패']; }
    renderSide();
  }
  else if (d.act === 'law-copy') {      // 조례 답 · 근거 조항을 한 번에(문서로 넘길 때)
    const e = engNow(), U = K('접수 카드');
    if (hasAns(e)) { try { await navigator.clipboard.writeText(lawCopyText(e)); ui.lawCopied = U['복사됨']; } catch { ui.lawCopied = U['복사 실패']; } renderLaw(); }
  }
  else if (d.act === 'law-open') { ui.lawOpen = !ui.lawOpen; if (ui.reveal) ui.reveal.t0 = -1e9; renderLaw(); }      // 칸 안에서 엔진 답 전문을 펼치고 접는다
  else if (d.act === 'next') play();      // 다음 전화 받기: 화면을 비우고 다음 통화(시연에서는 같은 장면을 다시)
  else if (d.act === 'open-rec') { await loadRecords(); openRec(S.id); }      // 방금 통화의 상담 기록
});
document.addEventListener('keydown', (ev) => { if (ev.key === 'Enter' && ev.target.id === 'k-text' && !ev.isComposing) { ev.preventDefault(); document.querySelector('[data-act="send"]').click(); } });
document.addEventListener('toggle', (ev) => { if (ev.target.classList && ev.target.classList.contains('fate')) ui.fateOpen = ev.target.open; }, true);      // 살았나 표를 펼치거나 접은 것은 카드를 다시 그려도 그대로
document.addEventListener('change', async (ev) => {
  if (ev.target.name === 'status') { ui.status = ev.target.value; renderSide(); renderTop(); await recPost({ op: 'save', state: S, status: ui.status }); renderTop(); renderSide(); }
  else if (ev.target.name === 'rstatus' && ui.rec) { await recPost({ op: 'status', id: ui.rec, status: ev.target.value }); renderTop(); renderRecList(); renderRecCard(); renderMap(); }
  else if (ev.target.id === 'rec-to') { ui.recTo = ev.target.value; renderRecList(); renderMap(); }
  else if (ev.target.classList.contains('fix') && ev.target.value) { const k = ev.target.value; queue(() => turnReq({ fix: k })); }
});

(async function main() {
  try {
    const t = await api('/api/text');
    DOC = t.text; SCRIPTS = t.scripts; MODE = t.mode; META = t;
  } catch { document.body.insertAdjacentHTML('beforeend', '<p class="map-failed">서버에 닿지 못했습니다.</p>'); return; }
  document.title = `${K('맨 위 띠')['화면 이름']} (시연)`;
  document.body.dataset.tone = ui.tone;
  if (TRIAL) { ui.scene = 'free'; document.body.classList.add('ctl'); }      // 사람 시험(?trial=번호): 열자마자 직접 통화(글로 넣기) · 시험 기록 단추
  if (!ui.scene) ui.scene = (scenes()[0] || {}).id || 'free';      // 첫 장면(장면 표의 맨 위). 표에 없는 장면도 ?auto=로 연다
  if (!SCRIPTS[ui.scene]) ui.input = 'type';
  try { REFS = await (await fetch('refs.json')).json(); } catch { /* 참고 자료 없이도 통화는 된다 */ }
  await loadRecords();
  resetCall(); initMap();
  window.CALL = { ui, get S() { return S; }, get V() { return V; }, get map() { return map; }, get RECS() { return RECS; }, play, resetCall, freeRect, openRec };   // 점검용
  if (P.get('auto') && SCRIPTS[ui.scene]) setTimeout(play, CTL() ? 0 : 1800);      // 깔끔한 화면에서는 전화가 걸려 온 것처럼 잠깐 울린 뒤 받는다
})();
