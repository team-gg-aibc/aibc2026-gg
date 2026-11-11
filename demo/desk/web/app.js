// 문의 답변 창구 시연 화면. 글자는 /api/text(docs/content/)에서만, 문의 · 카드 값은 /api/state에서만 가져온다.
'use strict';
const STYLE_URL = 'https://tiles.openfreemap.org/styles/liberty';
const HOME = { center: [126.978, 37.566], zoom: 10.4, pitch: 40, bearing: -12 };
const KINDS = { '만드는 중': 'making', '초안': 'draft', '승인': 'approved', '6종 밖': 'out', '못 찾음': 'notfound', '실패': 'failed' };
const SOURCES = { '시민': 'citizen', '가상': 'virtual', '공개': 'real', '팀': 'team' };
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const store = { get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
                set: (k, v) => { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch { /* 저장 못 해도 화면은 돈다 */ } } };

let T = null, textVersion = null, S = null, view = 0, chip = 0, openId = null, map = null, mapOk = false, fitSeoul = () => {};
const markers = {};
const ui = { dirty: {}, citizen: store.get('desk.citizen'), lastKind: {}, phone: true, work: true, show: 'list' };   // B안: 작업 칸 하나에 목록(list) 또는 초안(card)
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
const titleOf = (q) => (q.form && q.form.title) || '';   // 시민 화면에서 쓴 제목(시연 문의 · 앞 판 서버에는 없음)
const fmt = (iso) => { if (!iso) return '—'; const d = new Date(iso); const p = (n) => String(n).padStart(2, '0');
  return `${String(d.getFullYear()).slice(2)}.${p(d.getMonth() + 1)}.${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`; };
// ---- 소관 부서 · 처리 기관: data/agencies.json 한 곳에서 읽는다(조례 6종 × 갈래 37, 소관-처리-기관 조사)
let AG = null;
const lawOf = (name) => (AG && AG['조례'][name]) || null;
const deptsOf = (q) => [...new Set(((q.card || {}).citations || []).map((c) => lawOf(c.law)).filter(Boolean).map((L) => L['소관 부서']))];
// 갈래는 엔진이 인용한 조 · 항으로만 찾는다. 「제12조의2 제7항」처럼 항이 적힌 줄이 있으면 그 줄이 이긴다. 문의 글의 낱말은 보지 않는다
function galOf(c) {
  const L = lawOf(c.law);
  if (!L) return null;
  const a = c.article.replace(/\s+/g, ' ').trim(), m = /^(제\d+조(?:의\d+)?)(?: (제\d+항))?/.exec(a), b = /^별표 ?(\d+)/.exec(a);
  const keys = m ? [m[2] ? `${m[1]} ${m[2]}` : '', m[1]] : b ? [`별표 ${b[1]}`, '별표'] : [a];
  const id = keys.filter(Boolean).map((k) => L['조항→갈래'][k]).find(Boolean);
  return { L, g: id ? L['갈래'].find((x) => x.id === id) : null };
}

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
  const cr = sec('A', '화면 아래 출처'); $('credit').textContent = cr ? cr.smalls.join(' ') : '';   // 오른쪽 아래 작은 회색 글씨(동규 11-11)
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
  const who = sec('U', '신청인 정보'), nt = sec('U', '처리결과 수신'), B = sec('U', '민원내용'), pub = sec('U', '민원공개여부'), ag = sec('U', '개인정보 수집 · 이용 동의');
  $('u-who-h').textContent = who.name;
  $('u-who').innerHTML = who.items.map((i) => { const [k, v] = split2(i.text); return `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`; }).join('');
  { const [okb, oks] = split2(who.smalls[0] || ''); $('u-who-note').innerHTML = `<span class="badge k-approved">${esc(okb)}</span> ${esc(oks)}`; }
  $('u-notify-h').textContent = nt.name;
  const keepN = [...document.querySelectorAll('#u-notify input')].map((x) => x.checked);
  $('u-notify').innerHTML = nt.items.map((i, n) => `<label class="check"><input type="checkbox" value="${esc(i.text)}" ${(keepN.length ? keepN[n] : n === 0) ? 'checked' : ''}> ${esc(i.text)}</label>`).join('');
  $('u-body-h').textContent = B.name;
  const pick = its('U', '민원내용', '고르기')[0].parts, inp = its('U', '민원내용', '입력').map((i) => i.parts);
  $('u-place-l').textContent = pick[0];
  const keep = $('u-place').value;
  $('u-place').innerHTML = pick.slice(1).map((n, i) => `<option value="${i ? esc(placeIdOf(n)) : ''}">${esc(n)}</option>`).join('');
  $('u-place').value = keep;
  $('u-title-l').textContent = inp[0][0]; $('u-title-in').placeholder = inp[0][1] || '';
  $('u-text-l').textContent = inp[1][0]; $('u-text').placeholder = inp[1][1] || '';
  $('u-limit').textContent = B.smalls[0] || ''; $('u-privacy').textContent = B.smalls[1] || '';
  $('u-public-h').textContent = pub.name; $('u-public-q').textContent = pub.lead;
  const keepP = (document.querySelector('#u-public input:checked') || {}).value;
  $('u-public').innerHTML = its('U', '민원공개여부', '보기')[0].parts.map((o, n) => `<label class="check"><input type="radio" name="u-public" value="${n}" ${String(n) === (keepP ?? '0') ? 'checked' : ''}> ${esc(o)}</label>`).join('');
  $('u-agree-h').textContent = ag.name; $('u-agree-l').textContent = ag.items.find((i) => !i.kind).text; $('u-agree-note').textContent = ag.smalls[0] || '';
  const ub = its('U', '개인정보 수집 · 이용 동의', '버튼');
  $('u-send').textContent = ub[0].text; $('u-example').textContent = ub[1] ? ub[1].text : '';
  $('u-demo').textContent = U.smalls[0] || '';
  countUp(); agreeGate(); applyPanels();
  $('u-sent-h').textContent = sec('U', '보낸 문의').name; $('u-sent-lead').textContent = sec('U', '보낸 문의').lead;
  const again = its('U', '보낸 문의', '버튼')[0];
  $('u-again').textContent = again ? again.text : ''; $('u-again').hidden = !again;
  $('u-answer-h').textContent = sec('U', '받은 답').name; $('u-answer-lead').textContent = sec('U', '받은 답').lead;
  $('u-answer-note').textContent = sec('U', '받은 답').smalls[0] || ''; $('u-new').textContent = its('U', '받은 답', '버튼')[0].text;
  $('dlg-no').textContent = sit('C')['승인 확인 · 그만두기'];
}
const placeIdOf = (name) => (S && Object.values(S.places).find((p) => p.name === name) || {}).id || '';

// ---- 칸 접고 펴기 (맨 위 띠의 글자 버튼 셋, 늘 같은 자리)
function applyPanels(ease = true) {   // ease: 지도 여백을 새 칸 끝에 맞춰 옮긴다(곧바로 날아갈 때는 끈다: 날아가는 중간에 끊기지 않게)
  const b = document.body, card = !!openId && ui.show === 'card';
  b.classList.toggle('phone-off', !ui.phone);
  b.classList.toggle('work-off', !ui.work);
  b.classList.toggle('show-card', card);
  if (T) {
    const [tp, tl, tc] = its('A', '화면 칸', '버튼').map((i) => i.parts);
    const set = (el, on, words) => { el.textContent = on ? words[0] : words[1]; el.setAttribute('aria-expanded', on); };
    set($('tg-phone'), ui.phone, tp);
    set($('tg-list'), ui.work && !card, tl);
    set($('tg-card'), ui.work && card, tc);
    $('tg-card').disabled = !openId;
  }
  if (mapOk && ease) setTimeout(() => map.easeTo({ padding: mapPad(), duration: 500 }), 30);
}
function togglePanel(which) {
  if (which === 'phone') ui.phone = !ui.phone;
  else {
    const want = which === 'card' ? 'card' : 'list', shown = ui.work && (openId && ui.show === 'card' ? 'card' : 'list');
    if (shown === want) ui.work = false; else { ui.work = true; ui.show = want; }
  }
  applyPanels();
}

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
      <span class="body">${titleOf(q) ? `<span class="t">${esc(titleOf(q))}</span>` : ''}<span class="q">${esc(q.text)}</span>
        <span class="tags"><span class="badge k-${k}">${esc(b)}</span>${s ? `<span class="side">${esc(s)}</span>` : ''}</span>
        <span class="meta"><span class="src s-${q.source}">${esc(srcLabel(q.source))}</span>${d.length ? `<span class="dept">${esc(d.join(' · '))}</span>` : ''}</span></span>
    </button></li>`;
  }).join('');
  const eng = { live: '엔진에 연결됨', notrace: '엔진 기록 없이 연결됨', down: '엔진에 연결되지 않음', saved: '미리 받은 답으로 보임' }[S.engine];
  const [eb, es] = split2(A[eng] || '');
  $('a-engine').className = `engine e-${S.engine}`;
  $('a-engine').innerHTML = `<b>${esc(eb)}</b> ${esc(es)}`;
}

// ---- 지도 (서울시만: 처음 모습 · 움직일 수 있는 범위를 서울로 묶고, 서울 밖은 흐리게 가린다. 경계는 data/seoul.geojson = OSM)
async function initMap() {
  if (!window.maplibregl) return mapFailed();
  let seoul = null;
  try { seoul = await (await fetch('data/seoul.geojson')).json(); } catch { /* 경계 없이도 지도는 뜬다 */ }
  const b = (seoul && seoul.bbox) || [126.76, 37.42, 127.19, 37.71];
  try {
    map = new maplibregl.Map({ container: 'map', style: STYLE_URL, ...HOME, maxPitch: 60, minZoom: 9, attributionControl: false,
                               maxBounds: [[b[0] - 0.7, b[1] - 0.35], [b[2] + 0.7, b[3] + 0.35]] });   // 서울 둘레까지만 움직인다(칸이 왼쪽을 가려도 서울을 보이는 곳 가운데로 옮길 수 있게 조금 넓게)
    map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right');
    fitSeoul = (duration) => map.fitBounds([[b[0], b[1]], [b[2], b[3]]], { padding: mapPad(), pitch: HOME.pitch, bearing: HOME.bearing, duration });   // 서울 전체를 칸에 가리지 않는 곳에
    fitSeoul(0);
    let rt; addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(() => { if (!openId || ui.show !== 'card') fitSeoul(400); }, 250); });
    map.on('load', () => {
      for (const l of map.getStyle().layers) {   // 지도 이름표는 한글 이름 먼저(없으면 원래 이름)
        if (l.type === 'symbol' && map.getLayoutProperty(l.id, 'text-field')) map.setLayoutProperty(l.id, 'text-field', ['coalesce', ['get', 'name:ko'], ['get', 'name']]);
      }
      if (seoul) {
        const ring = seoul.features[0].geometry.coordinates[0];
        map.addSource('seoul-mask', { type: 'geojson', data: { type: 'Feature', properties: {}, geometry: { type: 'Polygon',
          coordinates: [[[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]], ring] } } });
        map.addSource('seoul', { type: 'geojson', data: seoul });
        map.addLayer({ id: 'seoul-mask', type: 'fill', source: 'seoul-mask', paint: { 'fill-color': '#e9ecf0', 'fill-opacity': 0.93 } });
        map.addLayer({ id: 'seoul-line', type: 'line', source: 'seoul', paint: { 'line-color': '#1f3a8a', 'line-width': 2.5, 'line-opacity': 0.8 } });
      }
      mapOk = true; renderMarkers(); fitSeoul(0);
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
  const right = Math.max(16, ...['phone', 'inbox', 'card'].map((id) => { const r = $(id).getBoundingClientRect(); return r.width ? r.right : 0; }));
  return { left: right + 8, right: 24, top: document.querySelector('.topbar').getBoundingClientRect().bottom + 16, bottom: 48 };
}
function flyTo(q) {
  const p = q && q.place && S.places[q.place];
  if (!mapOk || !p) return;
  map.flyTo({ center: [p.lon, p.lat], zoom: 15.6, pitch: 58, bearing: -20, duration: 2200, padding: mapPad() });
}

// ---- 답변 초안 카드
function openCard(id) {
  openId = id; ui.show = 'card'; ui.work = true; applyPanels(false);
  const q = S.inquiries.find((x) => x.id === id);
  renderCard(true); renderList(); renderMarkers();
  if (q && q.place) requestAnimationFrame(() => flyTo(q)); else if (mapOk) setTimeout(() => map.easeTo({ padding: mapPad(), duration: 500 }), 30);   // 칸이 바뀐 뒤의 여백으로 날아간다
  if (!WIDE()) $('card').scrollIntoView({ behavior: 'smooth', block: 'start' });   // 안 그러면 줄을 눌러도 바뀐 것이 안 보인다
}
function closeCard() { ui.show = 'list'; applyPanels(); renderList(); }   // 「문의 목록으로」: 같은 작업 칸에 목록을 다시 보인다(고른 문의는 「답변 초안 보기」로 돌아갈 수 있게 남긴다)
function resetCard() { openId = null; ui.show = 'list'; $('card').hidden = true; drawn.card = 'null'; applyPanels(); }

function cardNav(q) {   // 「문의 목록으로 · 이전 문의 · 몇 번째 / 모두 · 다음 문의」(B안: 고치는 동안 목록이 안 보이는 것을 메움)
  const nb = its('C', '카드 머리', '버튼').map((i) => i.text), list = filtered().slice().reverse(), i = list.findIndex((x) => x.id === q.id);
  const prev = i > 0 ? list[i - 1].id : '', next = i >= 0 && i < list.length - 1 ? list[i + 1].id : '';
  return `<nav class="c-nav" aria-label="${esc(sec('C', '카드 머리').name)}"><button type="button" class="outline" id="c-close">${esc(nb[0])}</button>
    <span class="c-step"><button type="button" class="ghost" data-go="${prev}" ${prev ? '' : 'disabled'}>${esc(nb[1])}</button>
    <span class="pos">${i >= 0 ? `${i + 1} / ${list.length}` : ''}</span>
    <button type="button" class="ghost" data-go="${next}" ${next ? '' : 'disabled'}>${esc(nb[2])}</button></span></nav>`;
}
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
      </header>
    ${cardNav(q)}
    <section><h3>${esc(sec('C', '문의').name)}</h3><dl class="kv">
      ${titleOf(q) ? `<dt>${esc(qLabels[0])}</dt><dd class="qtext">${esc(titleOf(q))}</dd>` : ''}
      <dt>${esc(qLabels[1])}</dt><dd class="qtext">${esc(q.text)}</dd>
      <dt>${esc(qLabels[2])}</dt><dd>${esc(srcLabel(q.source))}</dd>
      <dt>${esc(qLabels[3])}</dt><dd>${esc(fmt(q.received))}</dd>
      <dt>${esc(qLabels[4])}</dt><dd>${placeLine(q)}</dd></dl></section>`;
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
  const D = sec('C', '소관 부서와 처리 기관');
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
    ${agencyBlock(q, D)}
    <section><h3 id="c-status-h">${esc(sec('C', '처리 상태').name)}</h3><p class="lead">${esc(sec('C', '처리 상태').lead)}</p>
      <div class="radios" role="radiogroup" aria-labelledby="c-status-h">
        ${opts.map((o, i) => `<label class="radio${(i === 1) === done ? ' on' : ''}"><input type="radio" name="c-status" value="${i}" ${(i === 1) === done ? 'checked' : ''} ${done && i === 0 ? 'disabled' : ''}> ${esc(o)}</label>`).join('')}
      </div>
      ${done ? `<p class="note why">${esc(st['승인한 뒤 「검토 중」'])}</p><p class="msg ok" role="status">${esc(st['승인 완료'])} · ${esc(fmt(q.approved.at))}</p>`
             : `<p class="note">${esc(sec('C', '처리 상태').smalls[0])}</p>`}
      <p class="err" id="c-approve-err" role="alert" hidden></p></section>`;
}

// 카드의 「소관 부서와 처리 기관」. 첫 인용 조항의 갈래 → 공원 · 주차장은 고른 장소로 한 번 더 좁힘 → 자치구는 「자치구가 처리」로만
function agencyBlock(q, D) {
  const W = Object.fromEntries(D.items.map((i) => split2(i.text))), basis = kv('C', '소관 부서와 처리 기관');
  const first = q.card.citations[0], hit = first && galOf(first);
  if (!hit) return '';
  const { L, g } = hit, p = q.place && S.places[q.place];
  const place = g && g['장소에 따라'] && p && p['처리 장소'] ? L['장소별 처리 기관'].find((e) => e['장소'] === p['처리 장소']) : null;
  const gu = (t) => /^자치구/.test(t || ''), GU = '자치구가 처리', PICK = '고른 장소 기준';   // content 「소관 부서와 처리 기관」 목록의 열쇠(· 앞) 이름
  let who, note = '', cap = g ? g['믿을 만한 정도'] : '확인 전';
  if (!g || !g['처리 기관']) { who = `<span class="badge k-check">${esc(split2(basis['확인 전'])[0])}</span> ${esc(split2(basis['확인 전'])[1])}`; cap = ''; }
  else if (place) {
    who = esc(gu(place['처리 기관']) ? GU : place['처리 기관']);
    note = `<p class="note">${esc(PICK)} · ${esc(place['장소'])}</p>`;
    cap = p['처리 장소 믿을 만한 정도'] || place['믿을 만한 정도'];
  } else if (g['자치구가 처리'] === '예') who = esc(GU);
  else if (g['같은가'] === '같다') who = `${esc(g['처리 기관'])} <span class="side">· ${esc(W['소관 부서와 같음'])}</span>`;
  else who = esc(g['처리 기관']);
  if (!place && g && g['자치구가 처리'] === '일부') note += `<p class="note">${esc(W['자치구가 처리하기도 함'])}</p>`;
  const links = g ? [...new Map((g['출처'] || []).map((o) => [o['주소'], o])).values()] : [];
  const lbl = D.items.map((i) => split2(i.text)[0]);
  return `<section><h3>${esc(D.name)}</h3><dl class="kv">
      <dt>${esc(lbl[0])}</dt><dd>${esc(L['소관 부서'])}</dd>
      <dt>${esc(lbl[1])}</dt><dd>${who}${note}${cap && basis[cap] ? `<p class="note">${esc(basis[cap])}</p>` : ''}</dd>
      ${g ? `<dt>${esc(lbl[2])}</dt><dd>${esc(g['갈래'])}</dd>` : ''}</dl>
      ${g && g['근거'] ? `<details class="why-src"><summary>${esc(lbl[lbl.length - 1])}</summary><p>${esc(g['근거'])}</p>
        <ul>${links.map((o) => `<li><a href="${esc(o['주소'])}" target="_blank" rel="noopener">${esc(o['주소'].replace(/^https?:\/\//, '').slice(0, 60))}</a></li>`).join('')}</ul></details>` : ''}
      <p class="note">${esc(D.smalls[0])}</p></section>`;
}

function sourceLine(q) {
  if (!q.engine || kindOf(q) === 'failed') return '';   // 받은 답이 없으면 출처 줄도 없다
  const it = sec('C', '엔진 답의 출처').items.map((i) => split2(i.text)), [b, s] = it[q.engine.how === 'live' ? 0 : 1];
  const meta = [fmt(q.engine.at), q.engine.sec != null ? `${q.engine.sec}초` : ''].filter(Boolean).join(' · ');
  return `<footer class="c-src s-${q.engine.how}"><b>${esc(b)}</b> ${esc(s)} <span class="meta">${esc(meta)}</span></footer>`;
}

function bindCard(q) {
  $('c-close').onclick = closeCard;
  document.querySelectorAll('.c-nav [data-go]').forEach((b) => { b.onclick = () => { if (b.dataset.go) openCard(b.dataset.go); }; });
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

// ---- 시민 화면 (응답소 민원신청 화면의 항목 · 순서 · 낱말)
const countUp = () => { $('u-title-n').textContent = `${$('u-title-in').value.length}/30`; $('u-text-n').textContent = `${$('u-text').value.length.toLocaleString()}/3,000`; };
function agreeGate() {   // 동의해야 「등록」이 눌린다. 막힌 동안은 까닭을 바로 아래에
  const ok = $('u-agree').checked;
  $('u-send').disabled = !ok;
  $('u-why').textContent = ok ? '' : sit('U')['동의하지 않음'];
}
async function renderCitizen() {
  const show = (w) => { $('u-write').hidden = w !== 'write'; $('u-sent').hidden = w === 'write'; $('u-answer').hidden = w !== 'answer'; };
  if (!ui.citizen) return show('write');
  let c;
  try { c = await api(`/api/citizen/${ui.citizen}`); } catch { ui.citizen = null; store.set('desk.citizen', null); return show('write'); }
  const L = tbl('U', '보낸 문의').map((r) => r[0]), wait = split2(sit('U')['답을 기다리는 중']);
  $('u-sent-kv').innerHTML = `<dt>${esc(L[0])}</dt><dd>${c.no}</dd>${c.title ? `<dt>${esc(L[1])}</dt><dd>${esc(c.title)}</dd>` : ''}<dt>${esc(L[2])}</dt><dd>${esc(c.text)}</dd>
    <dt>${esc(L[3])}</dt><dd><span class="badge ${c.answer ? 'k-approved' : 'k-wait'}">${esc(c.answer ? sit('U')['답 도착'] : wait[0])}</span>${c.answer ? '' : ` <span class="side">${esc(wait[1])}</span>`}</dd>`;
  if (!c.answer) { ui.arrived = null; return show('sent'); }
  const R = tbl('U', '받은 답');
  $('u-answer-kv').innerHTML = `<dt>${esc(R[0][0])}</dt><dd class="answer">${esc(c.answer)}</dd>
    <dt>${esc(R[1][0])}</dt><dd>${c.citations.map((x) => esc(x.label)).join('<br>')}</dd>
    <dt>${esc(R[2][0])}</dt><dd>${esc(c.citations[0] ? c.citations[0].effective : '—')}</dd>
    <dt>${esc(R[3][0])}</dt><dd>${esc(R[3][1])} · ${esc(fmt(c.approved_at))}</dd>`;
  show('answer');
  if (ui.arrived !== ui.citizen) { ui.arrived = ui.citizen; $('u-answer').scrollIntoView({ block: 'start', behavior: 'smooth' }); }   // 답이 처음 도착하면 휴대폰 화면을 받은 답으로 내린다
}

async function sendCitizen() {
  const text = $('u-text').value.trim(), title = $('u-title-in').value.trim(), err = $('u-err'), b = $('u-send'), U = sit('U');
  const miss = !title ? [U['제목을 쓰지 않음'], 'u-title-in'] : !text ? [U['아무것도 쓰지 않음'], 'u-text'] : !$('u-agree').checked ? [U['동의하지 않음'], 'u-agree'] : null;
  if (miss) { err.textContent = miss[0]; err.hidden = false; $(miss[1]).focus(); return; }
  err.hidden = true; b.disabled = true; b.textContent = U['보내는 중'];
  try {
    const r = await api('/api/inquiries', { text, title, place: $('u-place').value || null, agree: true,
      public: (document.querySelector('#u-public input:checked') || {}).value === '1',
      notify: [...document.querySelectorAll('#u-notify input:checked')].map((x) => x.value) });
    ui.citizen = r.id; store.set('desk.citizen', r.id);
    $('u-text').value = ''; $('u-title-in').value = ''; $('u-place').value = ''; $('u-agree').checked = false; countUp();
    await refresh(); openCard(r.id); renderCitizen();
  } catch { err.textContent = U['보내지 못함']; err.hidden = false; }
  b.textContent = its('U', '개인정보 수집 · 이용 동의', '버튼')[0].text; agreeGate();
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
    $('dlg-yes').onclick = async () => { await api('/api/reset', {}).catch(() => {}); dlg.close(); resetCard(); ui.citizen = null; store.set('desk.citizen', null); ui.dirty = {};
      refresh(); renderCitizen(); };
    dlg.showModal();
  };
  $('toggles').addEventListener('click', (e) => { const b = e.target.closest('button'); if (b && !b.disabled) togglePanel(b.dataset.panel); });
  $('u-send').onclick = sendCitizen;
  $('u-example').onclick = () => { $('u-text').value = S.core.text; $('u-title-in').value = S.core.title || ''; $('u-place').value = S.core.place || ''; $('u-err').hidden = true; countUp(); };
  $('u-title-in').oninput = $('u-text').oninput = countUp;
  $('u-agree').onchange = agreeGate;
  $('u-new').onclick = $('u-again').onclick = () => { ui.citizen = null; store.set('desk.citizen', null); renderCitizen(); };
  document.querySelector('.tabs').addEventListener('click', (e) => {
    const b = e.target.closest('button'); if (!b) return;
    document.body.dataset.tab = b.dataset.tab;
    document.querySelectorAll('.tabs button').forEach((x) => x.setAttribute('aria-pressed', x === b));
  });
}

(async function main() {
  document.body.dataset.tab = 'staff';
  bind();
  try { AG = await (await fetch('data/agencies.json')).json(); } catch { AG = null; }   // 없으면 카드에 소관 부서 칸이 빠질 뿐 나머지는 돈다
  await refresh();
  if (!T) { $('list-msg').textContent = '문의 목록을 불러오지 못했습니다.'; }   // ponytail: content를 한 번도 못 받은 때만 쓰는 마지막 문장(서버가 꺼져 content도 못 읽음)
  initMap(); renderCitizen();
  setInterval(refresh, 1200);
  setInterval(() => { if (ui.citizen) renderCitizen(); }, 1500);
})();
