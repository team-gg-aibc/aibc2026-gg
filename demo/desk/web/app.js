// 문의 답변 창구 시연 화면. 글자는 /api/text(docs/content/)에서만, 문의 · 카드 값은 /api/state에서만 가져온다.
'use strict';
const STYLE_URL = 'https://tiles.openfreemap.org/styles/liberty';
const HOME = { center: [127.01, 37.585], zoom: 10.6, pitch: 50, bearing: -12 };
const KINDS = { '만드는 중': 'making', '초안': 'draft', '승인': 'approved', '6종 밖': 'out', '못 찾음': 'notfound', '실패': 'failed' };
const SOURCES = { '시민': 'citizen', '가상': 'virtual', '공개': 'real' };
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const store = { get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
                set: (k, v) => { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch { /* 저장 못 해도 화면은 돈다 */ } } };

let T = null, textVersion = null, S = null, view = 0, chip = 0, openId = null, map = null, mapOk = false;
const markers = {};
const ui = { dirty: {}, citizen: store.get('desk.citizen'), lastKind: {} };
const drawn = { list: '', card: '' };   // 마지막으로 그린 값. 값이 같으면 다시 그리지 않는다(누름 · 고른 글 · 글쇠 초점이 1.2초마다 사라지지 않게)
const WIDE = () => innerWidth >= 1200;   // style.css의 좁은 화면 기준(1199px 이하)과 같아야 한다
const setDlg = (text, yes) => { $('dlg-text').textContent = text; $('dlg-yes').textContent = yes; };   // 확인 창은 하나를 같이 쓰므로 열 때마다 글을 놓는다

// ---- 글자 꺼내기 (읽는 규칙: docs/content/A-01_답변화면.md 맨 위)
const doc = (k) => T[{ A: 'A-01_답변화면', C: 'C-01_답변초안카드', U: 'U-02_시민문의' }[k]];
const sec = (k, name) => doc(k).sections[name];
const its = (k, name, kind) => sec(k, name).items.filter((i) => i.kind === kind);
const tbl = (k, name, i = 0) => sec(k, name).tables[i].rows;
const kv = (k, name, i = 0) => Object.fromEntries(tbl(k, name, i).map((r) => [r[0], r[1]]));
const sit = (k) => kv(k, '상황별 안내');
const split2 = (t) => { const i = t.indexOf(' · '); return i < 0 ? [t, ''] : [t.slice(0, i), t.slice(i + 3)]; };
const kindLabel = (kind) => { const r = tbl('A', '들어온 문의', 1).find((x) => KINDS[x[0]] === kind); return split2(r ? r[1] : kind); };
const srcLabel = (src) => { const r = tbl('A', '들어온 문의', 2).find((x) => SOURCES[x[0]] === src); return r ? r[1] : src; };
const kindOf = (q) => (q.approved ? 'approved' : q.kind);
const fmt = (iso) => { if (!iso) return '—'; const d = new Date(iso); const p = (n) => String(n).padStart(2, '0');
  return `${String(d.getFullYear()).slice(2)}.${p(d.getMonth() + 1)}.${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`; };
const deptRows = () => tbl('C', '소관 부서와 처리 기관');
const deptsOf = (q) => [...new Set(((q.card || {}).citations || []).map((c) => deptRows().find((r) => c.law.includes(r[0]))).filter(Boolean).map((r) => r[1]))];

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(d.error || r.status), { data: d });
  return d;
}

// ---- 글자를 화면 자리에 놓기 (content를 고치면 다음 갱신에 다시 놓인다)
function placeText() {
  const A = doc('A'), U = doc('U');
  document.title = A.title;
  $('a-title').textContent = A.title; $('a-lead').textContent = A.lead;
  $('tab-staff').textContent = A.title; $('tab-citizen').textContent = U.title;
  $('a-basis').innerHTML = sec('A', '기준').items.map((i) => { const [b, s] = split2(i.text); return `<li><b>${esc(b)}</b> ${esc(s)}</li>`; }).join('');
  const L = sec('A', '들어온 문의');
  $('list-h').textContent = L.name; $('list-lead').textContent = L.lead; $('list-note').textContent = L.smalls[0] || '';
  const vs = its('A', '들어온 문의', '보기')[0].parts, cs = its('A', '들어온 문의', '칩')[0].parts, bs = its('A', '들어온 문의', '버튼');
  $('views').setAttribute('aria-label', L.name);
  $('views').innerHTML = vs.map((v, i) => `<button type="button" data-v="${i}" aria-pressed="${i === view}">${esc(v)}</button>`).join('');
  $('chips').setAttribute('aria-label', cs[0]);
  $('chips').dataset.labels = JSON.stringify(cs);
  $('btn-replay').textContent = bs[0].text; $('btn-reset').textContent = bs[1].text;
  $('map-notes').innerHTML = sec('A', '지도').items.slice(0, 2).map((i) => { const [b, s] = split2(i.text); return `<li><b>${esc(b)}</b> ${esc(s)}</li>`; }).join('');
  // 시민 화면
  $('u-title').textContent = U.title; $('u-lead').textContent = U.lead;
  const W = sec('U', '문의 쓰기'), inp = its('U', '문의 쓰기', '입력')[0].parts, pick = its('U', '문의 쓰기', '고르기')[0].parts;
  $('u-write-h').textContent = W.name; $('u-text-l').textContent = inp[0]; $('u-text').placeholder = inp[1] || '';
  $('u-place-l').textContent = pick[0];
  const keep = $('u-place').value;
  $('u-place').innerHTML = pick.slice(1).map((n, i) => `<option value="${i ? esc(placeIdOf(n)) : ''}">${esc(n)}</option>`).join('');
  $('u-place').value = keep;
  const ub = its('U', '문의 쓰기', '버튼');
  $('u-send').textContent = ub[0].text; $('u-example').textContent = ub[1] ? ub[1].text : '';
  $('u-privacy').textContent = W.smalls[0] || ''; $('u-demo').textContent = U.smalls[0] || '';
  $('u-sent-h').textContent = sec('U', '보낸 문의').name; $('u-sent-lead').textContent = sec('U', '보낸 문의').lead;
  $('u-answer-h').textContent = sec('U', '받은 답').name; $('u-answer-lead').textContent = sec('U', '받은 답').lead;
  $('u-answer-note').textContent = sec('U', '받은 답').smalls[0] || ''; $('u-new').textContent = its('U', '받은 답', '버튼')[0].text;
  $('dlg-no').textContent = sit('C')['승인 확인 · 그만두기'];
}
const placeIdOf = (name) => (S && Object.values(S.places).find((p) => p.name === name) || {}).id || '';

// ---- 목록 · 거르기
function filtered() {
  const cs = JSON.parse($('chips').dataset.labels || '[]');
  return S.inquiries.filter((q) => {
    const k = kindOf(q);
    if (view === 1 && k !== 'draft') return false;
    if (view === 2 && k !== 'approved') return false;
    if (chip === 0) return true;
    if (chip === cs.length - 1) return !['draft', 'approved', 'making'].includes(k);
    return deptsOf(q).includes(cs[chip]);
  });
}

function renderList() {
  const cs = JSON.parse($('chips').dataset.labels || '[]');
  $('chips').innerHTML = cs.map((c, i) => {
    const n = i === 0 ? S.inquiries.length : i === cs.length - 1 ? S.inquiries.filter((q) => !['draft', 'approved', 'making'].includes(kindOf(q))).length
      : S.inquiries.filter((q) => deptsOf(q).includes(c)).length;
    return `<button type="button" data-c="${i}" aria-pressed="${i === chip}">${esc(c)} <span class="n">${n}</span></button>`;
  }).join('');
  [...$('views').children].forEach((b, i) => b.setAttribute('aria-pressed', i === view));
  const A = sit('A'), list = filtered().slice().reverse();
  let msg = '';
  if (!S.inquiries.length) msg = A['들어온 문의 없음'];
  else if (!list.length) msg = view === 1 ? A['「승인 전」으로 거른 결과 없음'] : view === 2 ? A['「승인 완료」로 거른 결과 없음'] : A['고른 소관 부서의 문의 없음'];
  else if (S.replaying) msg = A['시연 문의를 들여오는 중'];
  else if (S.replay_left === 0) msg = A['시연 문의를 다 들여옴'];   // 막힌 「시연 문의 들여오기」 버튼의 까닭
  $('list-msg').textContent = msg;
  $('btn-replay').disabled = S.replaying || S.replay_left === 0;
  $('rows').innerHTML = list.map((q) => {
    const k = kindOf(q), [b, s] = kindLabel(k), d = deptsOf(q);
    return `<li><button type="button" class="row k-${k}${q.id === openId ? ' open' : ''}" data-id="${q.id}" aria-current="${q.id === openId}">
      <span class="no">${q.no}</span>
      <span class="body"><span class="q">${esc(q.text)}</span>
        <span class="tags"><span class="badge k-${k}">${esc(b)}</span>${s ? `<span class="side">${esc(s)}</span>` : ''}</span>
        <span class="meta"><span class="src s-${q.source}">${esc(srcLabel(q.source))}</span>${d.length ? `<span class="dept">${esc(d.join(' · '))}</span>` : ''}</span></span>
    </button></li>`;
  }).join('');
  const eng = { live: '엔진에 연결됨', notrace: '엔진 기록 없이 연결됨', down: '엔진에 연결되지 않음', saved: '미리 받은 답으로 보임' }[S.engine];
  const [eb, es] = split2(A[eng] || '');
  $('a-engine').className = `engine e-${S.engine}`;
  $('a-engine').innerHTML = `<b>${esc(eb)}</b> ${esc(es)}`;
}

// ---- 지도
function initMap() {
  if (!window.maplibregl) return mapFailed();
  try {
    map = new maplibregl.Map({ container: 'map', style: STYLE_URL, ...HOME, maxPitch: 60, attributionControl: false });
    map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right');
    map.jumpTo({ padding: mapPad() });   // 처음 모습도 칸에 가리지 않는 곳을 가운데로(안 그러면 지도 점이 시민 화면 · 목록 밑에 숨는다)
    map.on('load', () => {
      for (const l of map.getStyle().layers) {   // 지도 이름표는 한글 이름 먼저(없으면 원래 이름)
        if (l.type === 'symbol' && map.getLayoutProperty(l.id, 'text-field')) map.setLayoutProperty(l.id, 'text-field', ['coalesce', ['get', 'name:ko'], ['get', 'name']]);
      }
      mapOk = true; renderMarkers();
    });
    map.on('error', (e) => { if (!mapOk && /style|Failed to fetch/i.test(String(e.error && e.error.message))) mapFailed(); });
  } catch { mapFailed(); }
}
function mapFailed() { $('map-failed').hidden = false; if (T) $('map-failed').textContent = sit('A')['지도를 불러오지 못함']; }
function renderMarkers() {
  if (!mapOk) return;
  const seen = new Set();
  for (const q of S.inquiries) {
    const p = q.place && S.places[q.place];
    if (!p) continue;
    seen.add(q.id);
    let m = markers[q.id];
    if (!m) {
      const el = document.createElement('button');
      el.type = 'button'; el.className = 'pin'; el.dataset.id = q.id;
      el.addEventListener('click', () => openCard(q.id));
      m = markers[q.id] = new maplibregl.Marker({ element: el }).setLngLat([p.lon, p.lat]).addTo(map);
    }
    const k = kindOf(q), el = m.getElement();
    el.className = `pin k-${k}${q.id === openId ? ' open' : ''}`;
    el.innerHTML = `<b>${q.no}</b><span>${esc(p.name)}</span>`;
    el.setAttribute('aria-label', `${q.no} ${p.name} ${kindLabel(k)[0]}`);
  }
  for (const id of Object.keys(markers)) if (!seen.has(id)) { markers[id].remove(); delete markers[id]; }
}
// 지도에서 칸(시민 화면 · 목록 · 열린 카드)에 가리지 않는 곳. 화면 너비의 비율이 아니라 칸의 실제 끝을 잰다
function mapPad() {
  if (!WIDE()) return { top: 20, bottom: 20, left: 20, right: 20 };
  const c = $('card');
  return { left: $('inbox').getBoundingClientRect().right + 8, right: c.hidden ? 16 : innerWidth - c.getBoundingClientRect().left + 8, top: 40, bottom: 40 };
}
function flyTo(q) {
  const p = q && q.place && S.places[q.place];
  if (!mapOk || !p) return;
  map.flyTo({ center: [p.lon, p.lat], zoom: 15.6, pitch: 58, bearing: -20, duration: 2200, padding: mapPad() });
}

// ---- 답변 초안 카드
function openCard(id) {
  openId = id;
  const q = S.inquiries.find((x) => x.id === id);
  renderCard(true); renderList(); renderMarkers(); flyTo(q);
  if (!WIDE()) $('card').scrollIntoView({ behavior: 'smooth', block: 'start' });   // 안 그러면 줄을 눌러도 바뀐 것이 안 보인다
}
function closeCard() { openId = null; $('card').hidden = true; drawn.card = 'null'; renderList(); renderMarkers(); if (mapOk) map.easeTo({ padding: mapPad(), duration: 600 }); }

function placeLine(q) {
  const pairs = sec('A', '지도').items.map((i) => split2(i.text)), notes = Object.fromEntries(pairs);
  const p = q.place && S.places[q.place];
  if (!p) { const [nb, ns] = pairs[pairs.length - 1]; return `<span class="badge k-check">${esc(nb)}</span> ${esc(ns)}`; }   // 지도 구역 맨 끝 줄 = 장소 없음
  const attr = p.kind === '공원' ? '공원 구분' : p.kind === '공영주차장' ? '급지' : '';
  return `${esc(p.name)}${attr ? ` <span class="badge k-check">${esc(attr)} ${esc(notes[attr])}</span>` : ''}`;
}

function renderCard(fresh) {
  const q = S.inquiries.find((x) => x.id === openId);
  const box = $('card');
  if (!q) { box.hidden = true; drawn.card = 'null'; return; }
  const ta = $('c-draft');
  if (!fresh && ta && document.activeElement === ta && ui.lastKind[q.id] === kindOf(q)) return;   // 고쳐 쓰는 중에는 다시 그리지 않는다
  ui.lastKind[q.id] = kindOf(q); drawn.card = JSON.stringify(q);
  const C = doc('C'), st = sit('C'), k = kindOf(q), [kb, ks] = kindLabel(k), rowsQ = kv('C', '문의');
  const qLabels = tbl('C', '문의').map((r) => r[0]);
  let h = `<header class="c-head"><p class="c-no">${q.no}</p><div><h2>${esc(C.title)}</h2>
      <p class="tags"><span class="badge k-${k}">${esc(kb)}</span>${ks ? `<span class="side">${esc(ks)}</span>` : ''}</p></div>
      <button type="button" class="ghost close" id="c-close">${esc(its('C', '처리 상태', '버튼')[0].text)}</button></header>
    <section><h3>${esc(sec('C', '문의').name)}</h3><dl class="kv">
      <dt>${esc(qLabels[0])}</dt><dd class="qtext">${esc(q.text)}</dd>
      <dt>${esc(qLabels[1])}</dt><dd>${esc(srcLabel(q.source))}</dd>
      <dt>${esc(qLabels[2])}</dt><dd>${esc(fmt(q.received))}</dd>
      <dt>${esc(qLabels[3])}</dt><dd>${placeLine(q)}</dd></dl></section>`;
  void rowsQ;
  if (k === 'making') {
    h += `<section class="making" aria-busy="true"><p class="lead">${esc(st['초안을 만드는 중'])}</p><div class="sk"></div><div class="sk"></div><div class="sk short"></div></section>`;
  } else if (k === 'out' || k === 'notfound' || k === 'failed') {
    const name = { out: '6종 밖', notfound: '조항을 찾지 못함', failed: '불러오지 못함' }[k], b = sec('C', name);
    const noSaved = k === 'failed' && q.engine && q.engine.how === 'saved';   // 엔진을 부르지 않는 방식인데 받아 둔 답이 없는 문의: 「연결이 끊겼다」고 말하지 않는다
    h += `<section class="gap k-${k}"><p class="lead">${esc(noSaved ? st['미리 받은 답이 없음'] : b.lead)}</p>${(noSaved ? [] : b.smalls).map((s) => `<p class="note">${esc(s)}</p>`).join('')}
      ${k === 'failed' && S.engine !== 'saved' ? `<button type="button" class="outline" id="c-retry">${esc(its('C', name, '버튼')[0].text)}</button>` : ''}</section>`;
  } else {
    h += draftSections(q);
  }
  h += sourceLine(q);
  box.innerHTML = h; box.hidden = false;
  if (fresh) box.scrollTop = 0;
  bindCard(q);
}

function draftSections(q) {
  const st = sit('C'), c = q.card, inp = its('C', '답변 초안', '입력')[0].parts, B = kv('C', '근거'), BL = tbl('C', '근거').map((r) => r[0]);
  const verdictMap = kv('C', '근거', 1), noQuote = split2(sec('C', '근거').items[0].text), noVerdict = split2(sec('C', '근거').items[1].text);
  const value = ui.dirty[q.id] ?? q.draft ?? '', edited = (q.approved ? q.approved.text : value) !== c.answer;
  const verdict = c.conclusion ? (verdictMap[c.conclusion] || c.conclusion) : verdictMap['없음'];
  const done = !!q.approved, opts = its('C', '처리 상태', '보기')[0].parts;
  const D = sec('C', '소관 부서와 처리 기관'), dl = D.items.map((i) => split2(i.text)[0]);
  const rows = [...new Map(c.citations.map((x) => [x.law, deptRows().find((r) => x.law.includes(r[0]))])).values()].filter(Boolean);
  return `<section><h3><label for="c-draft">${esc(inp[0])}</label>${edited ? ` <span class="badge k-edit">${esc(st['고친 글이 있음'])}</span>` : ''}</h3>
      <p class="lead">${esc(doc('C').lead)}</p>
      <textarea id="c-draft" rows="7" placeholder="${esc(inp[1] || '')}" ${done ? 'readonly' : ''} aria-describedby="c-draft-help c-draft-err">${esc(done ? q.approved.text : value)}</textarea>
      <p class="note" id="c-draft-help">${esc(sec('C', '답변 초안').smalls[0])}</p>
      <p class="err" id="c-draft-err" role="alert" hidden></p>
      ${done ? '' : `<button type="button" class="ghost" id="c-revert" ${edited ? '' : 'disabled'}>${esc(its('C', '답변 초안', '버튼')[0].text)}</button>`}</section>
    <section><h3>${esc(sec('C', '근거').name)}</h3>
      <dl class="kv"><dt>${esc(BL[0])}</dt><dd><span class="badge verdict">${esc(verdict)}</span> <span class="side">${esc(c.conclusion ? split2(B[BL[0]])[1] : noVerdict[1])}</span></dd></dl>
      ${c.citations.map((x) => `<div class="cite">
        <dl class="kv"><dt>${esc(BL[1])}</dt><dd><b>${esc(x.law)}</b> ${esc(x.article)}</dd>
        <dt>${esc(BL[2])}</dt><dd>${x.quotes.length ? `${x.quotes.map((t) => `<blockquote>${esc(t)}</blockquote>`).join('')}<p class="note">${esc(B[BL[2]])}</p>`
          : `<p class="note">${esc(noQuote[0])} · ${esc(noQuote[1])}</p><blockquote class="full">${esc(x.text || '—')}</blockquote>`}</dd>
        <dt>${esc(BL[3])}</dt><dd>${esc(x.effective || '—')}</dd>
        <dt>${esc(BL[4])}</dt><dd>${x.url ? `<a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(B[BL[4]])}</a>` : '—'}</dd></dl></div>`).join('')}
    </section>
    <section><h3>${esc(D.name)}</h3><dl class="kv">
      <dt>${esc(dl[0])}</dt><dd>${esc(rows.map((r) => r[1]).join(' · ') || '—')}</dd>
      <dt>${esc(dl[1])}</dt><dd>${esc(rows.map((r) => r[2]).filter((v) => v && v !== '—').join(' · ') || '—')}</dd></dl>
      <p class="note">${esc(D.smalls[0])}</p></section>
    <section><h3 id="c-status-h">${esc(sec('C', '처리 상태').name)}</h3><p class="lead">${esc(sec('C', '처리 상태').lead)}</p>
      <div class="radios" role="radiogroup" aria-labelledby="c-status-h">
        ${opts.map((o, i) => `<label class="radio${(i === 1) === done ? ' on' : ''}"><input type="radio" name="c-status" value="${i}" ${(i === 1) === done ? 'checked' : ''} ${done && i === 0 ? 'disabled' : ''}> ${esc(o)}</label>`).join('')}
      </div>
      ${done ? `<p class="note why">${esc(st['승인한 뒤 「검토 중」'])}</p><p class="msg ok" role="status">${esc(st['승인 완료'])} · ${esc(fmt(q.approved.at))}</p>`
             : `<p class="note">${esc(sec('C', '처리 상태').smalls[0])}</p>`}
      <p class="err" id="c-approve-err" role="alert" hidden></p></section>`;
}

function sourceLine(q) {
  if (!q.engine || kindOf(q) === 'failed') return '';   // 받은 답이 없으면 출처 줄도 없다
  const it = sec('C', '엔진 답의 출처').items.map((i) => split2(i.text)), [b, s] = it[q.engine.how === 'live' ? 0 : 1];
  const meta = [fmt(q.engine.at), q.engine.sec != null ? `${q.engine.sec}초` : ''].filter(Boolean).join(' · ');
  return `<footer class="c-src s-${q.engine.how}"><b>${esc(b)}</b> ${esc(s)} <span class="meta">${esc(meta)}</span></footer>`;
}

function bindCard(q) {
  $('c-close').onclick = closeCard;
  const retry = $('c-retry');
  if (retry) retry.onclick = async () => { retry.disabled = true; try { await api(`/api/inquiries/${q.id}/retry`, {}); } catch { retry.disabled = false; } refresh(); };
  const ta = $('c-draft');
  if (!ta) return;
  ta.oninput = () => { ui.dirty[q.id] = ta.value; const rv = $('c-revert'); if (rv) rv.disabled = ta.value === q.card.answer; };
  ta.onblur = () => { if (!q.approved && ui.dirty[q.id] != null) api(`/api/inquiries/${q.id}/draft`, { text: ta.value }).catch(() => {}); };
  const rv = $('c-revert');
  if (rv) rv.onclick = () => { ta.value = q.card.answer; ui.dirty[q.id] = q.card.answer; rv.disabled = true; api(`/api/inquiries/${q.id}/draft`, { text: q.card.answer }).catch(() => {}); renderCard(true); };
  document.querySelectorAll('input[name="c-status"]').forEach((r) => {
    r.onchange = () => { if (r.value === '1' && !q.approved) askApprove(q); };
  });
}

function askApprove(q) {
  const ta = $('c-draft'), err = $('c-draft-err');
  const back = () => { const r0 = document.querySelector('input[name="c-status"][value="0"]'); if (r0) r0.checked = true; };
  if (!ta.value.trim()) { err.textContent = sit('C')['답변 초안이 비어 있음']; err.hidden = false; back(); ta.focus(); return; }
  err.hidden = true;
  const dlg = $('dlg');
  setDlg(sit('C')['승인 확인'], sit('C')['승인 확인 · 보내기']);
  $('dlg-no').onclick = () => { dlg.close(); back(); };
  dlg.oncancel = () => back();
  $('dlg-yes').onclick = async () => {
    $('dlg-yes').disabled = $('dlg-no').disabled = true; dlg.setAttribute('aria-busy', 'true');
    try {
      await api(`/api/inquiries/${q.id}/approve`, { text: ta.value });
      delete ui.dirty[q.id];
      dlg.close();
    } catch {
      dlg.close(); back();
      const e = $('c-approve-err'); if (e) { e.textContent = sit('C')['승인하지 못함']; e.hidden = false; }
    } finally { $('dlg-yes').disabled = $('dlg-no').disabled = false; dlg.removeAttribute('aria-busy'); }
    await refresh(); renderCard(true);
  };
  dlg.showModal();
}

// ---- 시민 화면
async function renderCitizen() {
  const show = (w) => { $('u-write').hidden = w !== 'write'; $('u-sent').hidden = w === 'write'; $('u-answer').hidden = w !== 'answer'; };
  if (!ui.citizen) return show('write');
  let c;
  try { c = await api(`/api/citizen/${ui.citizen}`); } catch { ui.citizen = null; store.set('desk.citizen', null); return show('write'); }
  const L = tbl('U', '보낸 문의').map((r) => r[0]), wait = split2(sit('U')['답을 기다리는 중']);
  $('u-sent-kv').innerHTML = `<dt>${esc(L[0])}</dt><dd>${c.no}</dd><dt>${esc(L[1])}</dt><dd>${esc(c.text)}</dd>
    <dt>${esc(L[2])}</dt><dd><span class="badge ${c.answer ? 'k-approved' : 'k-wait'}">${esc(c.answer ? sit('U')['답 도착'] : wait[0])}</span>${c.answer ? '' : ` <span class="side">${esc(wait[1])}</span>`}</dd>`;
  if (!c.answer) return show('sent');
  const R = tbl('U', '받은 답');
  $('u-answer-kv').innerHTML = `<dt>${esc(R[0][0])}</dt><dd class="answer">${esc(c.answer)}</dd>
    <dt>${esc(R[1][0])}</dt><dd>${c.citations.map((x) => esc(x.label)).join('<br>')}</dd>
    <dt>${esc(R[2][0])}</dt><dd>${esc(c.citations[0] ? c.citations[0].effective : '—')}</dd>
    <dt>${esc(R[3][0])}</dt><dd>${esc(R[3][1])} · ${esc(fmt(c.approved_at))}</dd>`;
  show('answer');
}

async function sendCitizen() {
  const text = $('u-text').value.trim(), err = $('u-err'), b = $('u-send');
  if (!text) { err.textContent = sit('U')['아무것도 쓰지 않음']; err.hidden = false; $('u-text').focus(); return; }
  err.hidden = true; b.disabled = true; b.textContent = sit('U')['보내는 중'];
  try {
    const r = await api('/api/inquiries', { text, place: $('u-place').value || null });
    ui.citizen = r.id; store.set('desk.citizen', r.id);
    $('u-text').value = ''; $('u-place').value = '';
    await refresh(); openCard(r.id); renderCitizen();
  } catch { err.textContent = sit('U')['보내지 못함']; err.hidden = false; }
  b.disabled = false; b.textContent = its('U', '문의 쓰기', '버튼')[0].text;
}

// ---- 갱신
async function refresh() {
  try {
    S = await api('/api/state');
    if (S.text_version !== textVersion) {
      const t = await api('/api/text');
      textVersion = t.version;
      let err = t.error;
      if (t.text) {          // 새 글자로 그려 보고, 깨졌으면(고치는 중인 파일) 마지막으로 정상이던 글자로 돌아간다
        const prev = T;
        T = t.text;
        try { placeText(); renderList(); } catch (e) { T = prev; err = err || String(e.message || e); if (T) placeText(); }
        drawn.list = drawn.card = '';   // 글자가 바뀌었으니 목록 · 카드를 다시 그린다
      }
      $('a-text-err').hidden = !err || !T; if (err && T) { $('a-text-err').textContent = sit('A')['화면 문구 파일을 읽지 못함']; console.warn('content:', err); }
    }
    $('rows').setAttribute('aria-busy', 'false');
    const listKey = JSON.stringify([S.inquiries, S.engine, S.replaying, S.replay_left]);
    if (listKey !== drawn.list) { drawn.list = listKey; renderList(); renderMarkers(); }
    if (JSON.stringify(S.inquiries.find((q) => q.id === openId) || null) !== drawn.card) renderCard(false);
    if (ui.citizen && !S.inquiries.some((q) => q.id === ui.citizen)) { ui.citizen = null; store.set('desk.citizen', null); }
  } catch {
    if (T) { $('list-msg').textContent = sit('A')['불러오지 못함']; drawn.list = ''; }   // 다시 이어지면 목록 안내를 새로 그린다
  }
}

function bind() {
  $('views').addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) { view = +b.dataset.v; renderList(); } });
  $('chips').addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) { chip = +b.dataset.c; renderList(); } });
  $('rows').addEventListener('click', (e) => { const b = e.target.closest('button.row'); if (b) openCard(b.dataset.id); });
  $('btn-replay').onclick = async () => { await api('/api/replay', {}).catch(() => {}); refresh(); };
  $('btn-reset').onclick = () => {
    const dlg = $('dlg');
    setDlg(sit('A')['처음 상태로 되돌리기 확인'], its('A', '들어온 문의', '버튼')[1].text);
    $('dlg-no').onclick = () => dlg.close(); dlg.oncancel = null;
    $('dlg-yes').onclick = async () => { await api('/api/reset', {}).catch(() => {}); dlg.close(); closeCard(); ui.citizen = null; store.set('desk.citizen', null); ui.dirty = {};
      refresh(); renderCitizen(); };
    dlg.showModal();
  };
  $('u-send').onclick = sendCitizen;
  $('u-example').onclick = () => { $('u-text').value = S.core.text; $('u-place').value = S.core.place || ''; $('u-err').hidden = true; };
  $('u-new').onclick = () => { ui.citizen = null; store.set('desk.citizen', null); renderCitizen(); };
  document.querySelector('.tabs').addEventListener('click', (e) => {
    const b = e.target.closest('button'); if (!b) return;
    document.body.dataset.tab = b.dataset.tab;
    document.querySelectorAll('.tabs button').forEach((x) => x.setAttribute('aria-pressed', x === b));
  });
}

(async function main() {
  document.body.dataset.tab = 'staff';
  bind();
  await refresh();
  if (!T) { $('list-msg').textContent = '문의 목록을 불러오지 못했습니다.'; }   // ponytail: content를 한 번도 못 받은 때만 쓰는 마지막 문장(서버가 꺼져 content도 못 읽음)
  initMap(); renderCitizen();
  setInterval(refresh, 1200);
  setInterval(() => { if (ui.citizen) renderCitizen(); }, 1500);
})();
