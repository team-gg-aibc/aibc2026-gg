// 3판 담당자 화면. 글자는 /api/text(docs/content/A-01_답변창구-3판.md)에서만, 문의 · 카드 값은 /api/state에서만 가져온다.
// 지도: 서울 밖으로 못 나가고, 가장 멀리 본 상태 = 서울 전체가 칸에 가리지 않는 자리에 꽉 차는 정도(3판 시안 7절 규칙 그대로)
'use strict';
const STYLE = 'https://tiles.openfreemap.org/styles/positron';   // 밝은 · 어두운 화면 모두 이 바탕에 색만 바꿔 칠한다(층 이름이 같아 두 톤이 같은 것을 보인다)
const FILE = 'A-01_답변창구-3판';
const KIND_ROW = { making: '만드는 중', draft: '초안', approved: '승인', out: '6종 밖', notfound: '못 찾음', failed: '실패' };
const SRC_ROW = { citizen: '시민', real: '공개', faq: '기관', virtual: '가상', team: '팀' };
const CHIP_KINDS = [null, 'draft', 'approved', 'notfound', 'out'];
const OV = { pitch: 48, bearing: -12 }, FOCUS = { pitch: 58, bearing: -10 }, FILL = 0.96, MARGIN = 0.01;
// 톤마다 지도 색. 공원 · 물 · 건물 높이 · 고른 자리가 바탕과 확실히 갈리게(동규 11-11 밤: 어두우면 건물 · 올린 것이 잘 안 보임)
const PAL = {
  light: { bg: '#e9edf1', water: '#a8cbe9', waterway: '#8bbbe3', park: '#cde6c1', wood: '#c3dfb4', resid: '#e4e7eb', bFoot: '#d9dde3',
    road: '#ffffff', roadMinor: '#f6f7f9', roadCase: '#c9cfd8', rail: '#bcc3cd', boundary: '#b5bcc6', label: '#3a4454', halo: '#ffffff', waterLabel: '#1f4774',
    parkLabel: '#2f6b3a', parkLine: '#86b973', bLow: '#d3d9e2', bMid: '#b9c3d1', bHigh: '#94a3b8', roof: '#f5f7fa', bLine: '#a3adbb',
    mask: '#dfe4ea', maskOp: 0.88, seoul: '#0a7368', P: '#2f6fb5', accent: '#0a7368', light: { color: '#ffffff', intensity: 0.4 } },
  dark: { bg: '#0a111d', water: '#15406e', waterway: '#1f5a96', park: '#1a4a32', wood: '#1c4d35', resid: '#111a29', bFoot: '#1a2538',
    road: '#3a4b68', roadMinor: '#26334b', roadCase: '#141d2d', rail: '#2e3b55', boundary: '#3a4760', label: '#c9d6ea', halo: '#0a111d', waterLabel: '#93c5f7',
    parkLabel: '#8fd6a6', parkLine: '#3d9663', bLow: '#34496b', bMid: '#4c6794', bHigh: '#7193c9', roof: '#bcd0f0', bLine: '#58739c',
    mask: '#02050a', maskOp: 0.82, seoul: '#38d6c4', P: '#2f6fd6', accent: '#38d6c4', light: { color: '#cfe0ff', intensity: 0.6 } },
};

let T = null, X = null, AG = null, RING = null, S = null, textVersion = null, map = null, mapOk = false;
const ui = { open: null, pair: null, chip: 0, dept: 0, list: true, card: true, listBeforePair: true, editing: {}, dirty: {}, sent: {}, reply: {},
             fix: false, picking: false, seen: null, fresh: new Set(), tone: 'light' };
const drawn = { list: '', card: '', pins: '' };
const markers = {}, extra = [];
const W = (name) => X(name);
const SIT = () => W('상황별 안내').tab('상황');
const kindOf = (q) => (q.approved ? 'approved' : q.kind);
const kindLabel = (k) => W('들어온 문의').tab('상태')[KIND_ROW[k]];
const srcLabel = (s) => W('들어온 문의').tab('출처')[SRC_ROW[s]];
const byId = (id) => S && S.inquiries.find((x) => x.id === id);
const shortLaw = (law) => ((AG && AG['조례'][law]) || {})['짧은 이름'] || String(law || '').replace(/^서울특별시 /, '');
const sameText = (q) => S.inquiries.filter((x) => x.id !== q.id && x.text.trim() === q.text.trim());

// ---- 소관 부서 · 처리 기관: data/agencies.json(조례 6종 × 갈래 37). 갈래는 엔진이 인용한 첫 조 · 항으로만 찾는다(문의 글의 낱말은 보지 않는다)
const lawOf = (name) => (AG && AG['조례'][name]) || null;
function galOf(c) {
  const L = lawOf(c.law);
  if (!L) return null;
  const a = c.article.replace(/\s+/g, ' ').trim(), m = /^(제\d+조(?:의\d+)?)(?: (제\d+항))?/.exec(a), b = /^별표 ?(\d+)/.exec(a);
  const keys = m ? [m[2] ? `${m[1]} ${m[2]}` : '', m[1]] : b ? [`별표 ${b[1]}`, '별표'] : [a];
  const id = keys.filter(Boolean).map((k) => L['조항→갈래'][k]).find(Boolean);
  return { L, g: id ? L['갈래'].find((x) => x.id === id) : null };
}
// → {dept, agency, agencyNote, cap, gal, why, links, out, law, url} 또는 null. 공원 · 주차장은 접수 위치의 「처리 장소」로 처리 기관을 한 번 더 좁힌다
function agencyOf(q) {
  const C = W('답변 초안').kv, p = q.loc && q.loc.place && S.places[q.loc.place];
  if (q.kind === 'out') {
    const info = p && p['6종 밖'];
    return info ? { out: true, law: info['조례'], url: info['원문'], dept: info['소관 부서'], agency: info['처리 기관'], cap: info['믿을 만한 정도'], why: info['근거'], links: [] }
                : { out: true, dept: '—', agency: C['처리 기관 확인 전'], cap: '', links: [] };
  }
  if (q.kind !== 'draft' || !q.card) return null;
  const first = q.card.citations[0], hit = first && galOf(first);
  if (!hit) return null;
  const { L, g } = hit, gu = (t) => /^자치구/.test(t || '');
  const place = g && g['장소에 따라'] && p && p['처리 장소'] ? L['장소별 처리 기관'].find((e) => e['장소'] === p['처리 장소']) : null;
  let agency, agencyNote = '', cap = g ? g['믿을 만한 정도'] : '';
  if (!g || !g['처리 기관']) { agency = C['처리 기관 확인 전']; cap = ''; }
  else if (place) { agency = gu(place['처리 기관']) ? C['자치구가 처리'] : place['처리 기관']; cap = p['처리 장소 믿을 만한 정도'] || place['믿을 만한 정도']; }
  else if (g['자치구가 처리'] === '예') agency = C['자치구가 처리'];
  else if (g['같은가'] === '같다') { agency = g['처리 기관']; agencyNote = C['소관 부서와 같음']; }
  else agency = g['처리 기관'];
  if (!place && g && g['자치구가 처리'] === '일부') agencyNote = C['자치구가 처리하기도 함'];
  return { dept: L['소관 부서'], agency, agencyNote, cap, gal: g && g['갈래'], why: g && g['근거'],
           links: g ? [...new Map((g['출처'] || []).map((o) => [o['주소'], o])).values()] : [] };
}
const deptsOf = (q) => (q.kind === 'draft' && q.card ? [...new Set(q.card.citations.map((c) => (lawOf(c.law) || {})['소관 부서']).filter(Boolean))] : []);
// 견줄 세 줄(근거 조항 · 소관 부서 · 처리 기관). 위치 바로잡기 전후 · 두 시민 카드 사이의 「바뀜 · 다름」에 쓴다
function lines(q) {
  const a = agencyOf(q) || {};
  return { cite: q.kind === 'draft' ? q.card.citations.map((c) => c.label).join('|') : q.kind === 'out' ? `out:${a.law || ''}` : q.kind,
           dept: a.dept || '', agency: a.agency || '' };
}

// ---- 문장 ↔ 구절 짝(짐작): 두 글자씩 묶어 문장 쪽 묶음이 구절에 얼마나 들어 있나. 엔진 기록엔 짝이 없어서 화면이 짐작한다고 늘 밝힌다
const grams = (s) => { const t = String(s).replace(/[\s.,·「」()『』"'~?!:;\-]/g, ''), g = new Set(); for (let i = 0; i < t.length - 1; i++) g.add(t.slice(i, i + 2)); return g; };
function pairUp(text, card) {
  const quotes = card.citations.flatMap((c, ci) => c.quotes.map((t, qi) => ({ ci, qi, g: grams(t) })));
  return String(text).split(/(?<=[.?!])\s+/).filter(Boolean).map((s) => {
    const g = grams(s); let best = null, bs = 0;
    for (const q of quotes) { let n = 0; for (const x of g) if (q.g.has(x)) n++; const sc = g.size ? n / g.size : 0; if (sc > bs) { bs = sc; best = q; } }
    return { s, q: bs >= 0.2 ? best : null };   // ponytail: 두 글자 겹침 비율 0.2 고정. 틀린 짝이 많으면 엔진이 짝을 내게 하는 것(E1)이 길
  });
}

// ---- 글자를 자리에 놓기
function placeText() {
  const D = T[FILE], top = W('맨 위 띠'), L = W('들어온 문의'), M = W('지도').kv;
  document.title = D.title;
  $('t-title').textContent = D.title; $('t-basis').textContent = top.kv['기준'];
  $('t-citizen').textContent = top.kv['시민 화면']; $('t-citizen').title = top.kv['시민 화면 설명'];
  $('t-tone').setAttribute('aria-label', top.kv['화면 밝기']);
  $('t-tone').innerHTML = top.pick('보기').map((t, i) => `<button type="button" data-tone="${i ? 'dark' : 'light'}">${esc(t)}</button>`).join('');
  $('l-name').textContent = L.name; $('l-lead').textContent = L.lead; $('l-small').textContent = L.smalls[0] || '';
  const dp = L.pick('고르기');
  $('l-dept-l').textContent = dp[0];
  $('l-dept').innerHTML = dp.slice(1).map((d, i) => `<option value="${i}">${esc(d)}</option>`).join(''); $('l-dept').value = ui.dept;
  $('btn-reset').textContent = L.btn()[0];
  $('credit').innerHTML = W('화면 아래 출처').smalls.map((s) => `<p>${esc(s)}</p>`).join('');
  $('legend').setAttribute('aria-label', M['범례']);
  drawLegend();
  $('dlg-no').textContent = SIT()['승인 확인 · 그만두기'];
  applyPanels(false);
}
function drawLegend() {
  const M = W('지도').kv, P = PAL[ui.tone];
  // 둘째 줄: 문의 점 색의 뜻을 글로(색만으로 가르지 않는다, 점검 11-11 밤)
  $('legend').innerHTML = `<div class="lr"><b>${esc(M['범례'])}</b><span><i style="background:${P.park};box-shadow:inset 0 0 0 1px ${P.parkLine}"></i>${esc(M['공원'])}</span>
    <span><i style="background:${P.water}"></i>${esc(M['한강'])}</span><span><i class="P" style="background:${P.P}">P</i>${esc(M['주차장'])}</span>
    <span><i class="ring"></i>${esc(M['고른 자리'])}</span></div>
    <div class="lr"><b>${esc(M['문의'])}</b>${['draft', 'approved', 'notfound', 'out'].map((k) => `<span class="k-${k}"><i class="dot kb"></i>${esc(kindLabel(k))}</span>`).join('')}</div>`;
}

// ---- 칸 접고 펴기 · 톤
function applyPanels(move = true) {
  const b = document.body, top = W('맨 위 띠'), open = !!(ui.open || ui.pair);
  b.classList.toggle('nolist', !ui.list);
  b.classList.toggle('nocard', !ui.card || !open);
  b.classList.toggle('cardon', ui.card && open);
  b.classList.toggle('pairing', !!ui.pair);
  const [lOn, lOff] = top.btn(0), [cOn, cOff] = top.btn(1);
  $('tg-list').textContent = ui.list ? lOn : lOff; $('tg-list').setAttribute('aria-expanded', ui.list);
  $('tg-card').textContent = ui.card && open ? cOn : cOff; $('tg-card').setAttribute('aria-expanded', ui.card && open); $('tg-card').disabled = !open;
  $('card').hidden = !open;
  document.querySelectorAll('#t-tone button').forEach((x) => x.setAttribute('aria-pressed', x.dataset.tone === ui.tone));
  if (move && mapOk) requestAnimationFrame(() => relayout(false));
}
function setTone(t) {
  ui.tone = t === 'dark' ? 'dark' : 'light'; store.set('desk3.tone', ui.tone);
  document.body.dataset.tone = ui.tone;
  if (T) { drawLegend(); applyPanels(false); }
  if (mapOk) applyTone();
}

// ---- 목록
function filtered() {
  const want = CHIP_KINDS[ui.chip], dept = ui.dept ? W('들어온 문의').pick('고르기')[ui.dept + 1] : null;
  return S.inquiries.filter((q) => (!want || kindOf(q) === want) && (!dept || deptsOf(q).includes(dept)));
}
function renderList() {
  const L = W('들어온 문의'), names = L.pick('칩'), Lk = L.kv;
  const cnt = (k) => (k ? S.inquiries.filter((q) => kindOf(q) === k).length : S.inquiries.length);
  $('l-count').textContent = S.inquiries.length;
  $('chips').setAttribute('aria-label', L.name);
  $('chips').innerHTML = names.map((n, i) => `<button type="button" data-chip="${i}" aria-pressed="${i === ui.chip}" class="${CHIP_KINDS[i] ? 'k-' + CHIP_KINDS[i] : ''}">${CHIP_KINDS[i] ? '<i class="kb"></i>' : ''}${esc(n)} <b>${cnt(CHIP_KINDS[i])}</b></button>`).join('');
  const list = filtered().slice().reverse();
  $('l-msg').textContent = !S.inquiries.length ? SIT()['들어온 문의 없음'] : !list.length ? SIT()['거른 결과 없음'] : '';
  const sel = new Set(ui.pair || (ui.open ? [ui.open] : []));
  $('rows').innerHTML = list.map((q) => {
    const k = kindOf(q), same = sameText(q).length;
    return `<li><button type="button" class="row${sel.has(q.id) ? ' sel' : ''}${ui.fresh.has(q.id) ? ' new' : ''}" data-id="${q.id}" aria-current="${sel.has(q.id)}">
      <span class="no">${q.no}</span><span class="tm">${hhmm(q.received)}</span><span class="tx">${esc(q.text)}</span>
      <span class="st kc k-${k}"><i class="kb"></i>${esc(kindLabel(k))}</span>
      <span class="sub2">${same ? `<span class="tag pair" data-pairwith="${q.id}">${esc(fill(Lk['같은 글'], { n: same }))}</span>` : ''}<span>${esc(srcLabel(q.source))}</span>${q.loc && q.loc.name ? `<span>· ${esc(q.loc.name)}</span>` : ''}</span>
    </button></li>`;
  }).join('');
  const st = { live: '연결됨', notrace: '기록 없이 연결됨', down: '연결되지 않음', saved: '미리 받은 답' }[S.engine];
  const [eb, es] = split2(SIT()[st]);
  $('t-engine').className = `live e-${S.engine}`;
  $('t-engine').innerHTML = `<b>${esc(eb)}</b> <span class="s">${esc(es)}</span>`;
}

// ---- 지도
let fitting = false, fitF = null, fitZ = 0, SB = null;
const shown = (el) => (el && !el.hidden && getComputedStyle(el).display !== 'none' ? el.getBoundingClientRect() : null);
function freeRect() {   // 지도에서 칸에 가리지 않은 자리
  const L = shown($('list')), C = shown($('card')), l = L ? L.right + 8 : 8, r = C ? C.left - 8 : innerWidth - 8, t = 54, b = innerHeight - 44;
  return { l, r, t, b, w: r - l, h: b - t, cx: (l + r) / 2, cy: (t + b) / 2 };
}
function fitPoints(pts, F, cam, fill_, maxZ = 22) {   // 기울인 시점에서 점들을 화면에 비춰 보며 사각형 F 안에 맞춤(fitBounds는 기울기를 안 셈)
  fitting = true;
  const saved = { center: map.getCenter(), zoom: map.getZoom(), pitch: map.getPitch(), bearing: map.getBearing() }, mz = map.getMinZoom();
  map.setMinZoom(0);
  map.jumpTo({ center: [pts.reduce((s, c) => s + c[0], 0) / pts.length, pts.reduce((s, c) => s + c[1], 0) / pts.length], zoom: 10.5, ...cam });
  const box = () => { const p = pts.map((c) => map.project(c)), xs = p.map((q) => q.x), ys = p.map((q) => q.y); return [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)]; };
  const center = () => { const [x0, x1, y0, y1] = box(); map.jumpTo({ center: map.unproject([innerWidth / 2 + (x0 + x1) / 2 - F.cx, innerHeight / 2 + (y0 + y1) / 2 - F.cy]) }); };
  // 확대와 가운데 맞추기를 따로 번갈아 한다(한 번에 하면 많이 기울인 시점에서 가까운 쪽이 커져 확대가 오가며 안 맞음)
  for (let n = 0; n < 10; n++) {
    center();
    const [x0, x1, y0, y1] = box();
    map.jumpTo({ zoom: Math.min(maxZ, map.getZoom() + Math.log2(Math.min(F.w * fill_ / Math.max(x1 - x0, 1), F.h * fill_ / Math.max(y1 - y0, 1)))) });
  }
  center();
  const out = { center: map.getCenter(), zoom: map.getZoom(), ...cam }, fc = map.unproject([F.cx, F.cy]);
  map.jumpTo(saved); map.setMinZoom(mz); fitting = false;
  return [out, fc];
}
function computeFit() {   // 서울 전체를 남는 자리에 맞춘 카메라 = 가장 멀리 볼 수 있는 상태
  const [fit, fc] = fitPoints(RING, freeRect(), OV, FILL);
  fitF = fc; fitZ = fit.zoom; map.setMinZoom(fitZ);
  return fit;
}
function focusCam(pts) {   // 고른 문의(들)가 칸 · 위치 바로잡기 창에 가리지 않는 자리에 들어오게
  const L = shown($('list')), C = shown($('card')), H = shown($('fixpop'));
  let l = (L ? L.right : 0) + 60, r = (C ? C.left : innerWidth) - 60;
  if (r - l < 160) { l = (L ? L.right : 0) + 10; r = (C ? C.left : innerWidth) - 10; }
  const t = (H ? H.bottom : 56) + 40, b = innerHeight - 70;
  return fitPoints(pts, { l, r, t, b, w: r - l, h: b - t, cx: (l + r) / 2, cy: (t + b) / 2 }, FOCUS, 0.85, pts.length > 1 ? 15.2 : 15.6)[0];
}
const focusPts = () => {
  const ids = ui.pair || (ui.open ? [ui.open] : []), pts = [];
  for (const id of ids) { const q = byId(id); if (q && q.loc) { pts.push([q.loc.lon, q.loc.lat]); if (q.loc_from && ui.fix) pts.push([q.loc_from.lon, q.loc_from.lat]); } }
  return pts;
};
function relayout(fly = false) {
  if (!mapOk) return;
  const fit = computeFit(), pts = focusPts();
  if (!pts.length) return fly ? map.flyTo({ ...fit, duration: 1500 }) : map.easeTo({ ...fit, duration: 500 });
  if (fly) return map.flyTo({ ...focusCam(pts), duration: 1600 });
  map.jumpTo({});   // 칸이 바뀌어도 고른 자리는 그대로, 범위만 다시 묶는다
}
const circle = ([lon, lat], m = 170) => ({ type: 'Feature', geometry: { type: 'Polygon', coordinates: [Array.from({ length: 49 }, (_, i) => { const a = (i / 48) * 2 * Math.PI; return [lon + (m / 88200) * Math.cos(a), lat + (m / 111000) * Math.sin(a)]; })] } });
function paint(id, prop, v) { if (map.getLayer(id)) { try { map.setPaintProperty(id, prop, v); } catch { /* 그 층에 없는 속성 */ } } }
const H = ['coalesce', ['get', 'render_height'], 10], H0 = ['coalesce', ['get', 'render_min_height'], 0];
function applyTone() {
  const P = PAL[ui.tone];
  for (const l of map.getStyle().layers) {
    if (l.source !== 'openmaptiles' || l.id.startsWith('own-')) continue;
    if (l.type === 'line' && l['source-layer'] === 'transportation') paint(l.id, 'line-color', /casing/.test(l.id) ? P.roadCase : /rail/.test(l.id) ? P.rail : /minor|path|service|pier/.test(l.id) ? P.roadMinor : P.road);
    if (l.type === 'line' && l['source-layer'] === 'boundary') paint(l.id, 'line-color', P.boundary);
    if (/shield/.test(l.id)) { map.setLayoutProperty(l.id, 'visibility', 'none'); continue; }   // 도로 번호판은 문의 표시를 가려서 끈다
    if (l.type === 'symbol') { paint(l.id, 'text-color', /water/.test(l.id) ? P.waterLabel : P.label); paint(l.id, 'text-halo-color', P.halo); paint(l.id, 'text-halo-width', 1.4); }
  }
  paint('background', 'background-color', P.bg); paint('water', 'fill-color', P.water); paint('waterway', 'line-color', P.waterway);
  paint('park', 'fill-color', P.park); paint('landcover_wood', 'fill-color', P.wood); paint('landuse_residential', 'fill-color', P.resid);
  paint('building', 'fill-color', P.bFoot); paint('building', 'fill-outline-color', P.bLine);
  paint('own-park-line', 'line-color', P.parkLine); paint('own-park-label', 'text-color', P.parkLabel); paint('own-park-label', 'text-halo-color', P.halo);
  paint('own-b3d', 'fill-extrusion-color', ['interpolate', ['linear'], H, 0, P.bLow, 40, P.bMid, 150, P.bHigh]);
  paint('own-roof', 'fill-extrusion-color', P.roof); paint('own-bline', 'line-color', P.bLine);
  paint('own-pk', 'circle-color', P.P); paint('own-pk', 'circle-stroke-color', P.halo);
  paint('own-mask', 'fill-color', P.mask); paint('own-mask', 'fill-opacity', P.maskOp); paint('own-seoul', 'line-color', P.seoul);
  paint('own-sel-fill', 'fill-color', P.accent); paint('own-sel-line', 'line-color', P.accent); paint('own-fixline', 'line-color', P.accent);
  map.setLight({ anchor: 'viewport', position: [1.15, 210, 30], ...P.light });
}
function addOwnLayers(seoul) {
  const firstSym = (map.getStyle().layers.find((l) => l.type === 'symbol') || {}).id, P = PAL[ui.tone];
  const add = (spec, before) => { if (!map.getLayer(spec.id)) map.addLayer(spec, before); };
  add({ id: 'own-park-line', type: 'line', source: 'openmaptiles', 'source-layer': 'park', minzoom: 11, paint: { 'line-color': P.parkLine, 'line-width': ['interpolate', ['linear'], ['zoom'], 11, 0.6, 15, 1.8] } }, firstSym);
  map.addSource('own-sel', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
  add({ id: 'own-sel-fill', type: 'fill', source: 'own-sel', paint: { 'fill-color': P.accent, 'fill-opacity': 0.2 } }, firstSym);
  add({ id: 'own-sel-line', type: 'line', source: 'own-sel', paint: { 'line-color': P.accent, 'line-width': 2.5 } }, firstSym);
  add({ id: 'own-bline', type: 'line', source: 'openmaptiles', 'source-layer': 'building', minzoom: 14.5, paint: { 'line-color': P.bLine, 'line-width': 0.7 } }, firstSym);
  // 3D 건물: 벽 + 지붕 판(조금 밝게)을 따로 칠해 윤곽과 높이가 읽히게. 같은 높이에 두 면이 겹치지 않게 지붕 판 아래까지만 벽을 올린다
  add({ id: 'own-b3d', type: 'fill-extrusion', source: 'openmaptiles', 'source-layer': 'building', minzoom: 13,
        paint: { 'fill-extrusion-color': ['interpolate', ['linear'], H, 0, P.bLow, 40, P.bMid, 150, P.bHigh], 'fill-extrusion-height': ['max', ['-', H, 0.8], 0],
                 'fill-extrusion-base': H0, 'fill-extrusion-opacity': ['interpolate', ['linear'], ['zoom'], 13, 0, 14, 0.95], 'fill-extrusion-vertical-gradient': true } }, firstSym);
  add({ id: 'own-roof', type: 'fill-extrusion', source: 'openmaptiles', 'source-layer': 'building', minzoom: 13,
        paint: { 'fill-extrusion-color': P.roof, 'fill-extrusion-height': H, 'fill-extrusion-base': ['max', ['-', H, 0.8], 0],
                 'fill-extrusion-opacity': ['interpolate', ['linear'], ['zoom'], 13, 0, 14, 0.95] } }, firstSym);
  map.addSource('own-fix', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
  add({ id: 'own-fixline', type: 'line', source: 'own-fix', paint: { 'line-color': P.accent, 'line-width': 2.5, 'line-dasharray': [2, 1.6] } }, firstSym);
  add({ id: 'own-park-label', type: 'symbol', source: 'openmaptiles', 'source-layer': 'park', minzoom: 12.5, filter: ['has', 'name'],
        layout: { 'text-field': ['coalesce', ['get', 'name:ko'], ['get', 'name']], 'text-font': ['Noto Sans Bold'], 'text-size': 12.5, 'symbol-placement': 'point' },
        paint: { 'text-color': P.parkLabel, 'text-halo-color': P.halo, 'text-halo-width': 1.6 } });
  // 주차장: 지도 자료에 면이 없어 점(P)으로
  add({ id: 'own-pk', type: 'circle', source: 'openmaptiles', 'source-layer': 'poi', minzoom: 14.5, filter: ['==', ['get', 'class'], 'parking'],
        paint: { 'circle-radius': 6.5, 'circle-color': P.P, 'circle-stroke-width': 1.5, 'circle-stroke-color': P.halo } });
  add({ id: 'own-pk-t', type: 'symbol', source: 'openmaptiles', 'source-layer': 'poi', minzoom: 14.5, filter: ['==', ['get', 'class'], 'parking'],
        layout: { 'text-field': 'P', 'text-font': ['Noto Sans Bold'], 'text-size': 10.5, 'text-allow-overlap': true }, paint: { 'text-color': '#ffffff' } });
  if (seoul) {
    map.addSource('own-mask', { type: 'geojson', data: { type: 'Feature', geometry: { type: 'Polygon', coordinates: [[[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]], RING] } } });
    add({ id: 'own-mask', type: 'fill', source: 'own-mask', paint: { 'fill-color': P.mask, 'fill-opacity': P.maskOp } });
    map.addSource('own-seoul', { type: 'geojson', data: seoul });
    add({ id: 'own-seoul', type: 'line', source: 'own-seoul', paint: { 'line-color': P.seoul, 'line-width': 1.8, 'line-opacity': 0.8 } });
  }
}
async function initMap() {
  if (!window.maplibregl) return mapFailed();
  let seoul = null;
  try { seoul = await (await fetch('data/seoul.geojson')).json(); } catch { /* 경계 없이도 지도는 뜬다 */ }
  RING = seoul ? seoul.features[0].geometry.coordinates[0] : [[126.76, 37.42], [127.19, 37.42], [127.19, 37.71], [126.76, 37.71], [126.76, 37.42]];
  SB = RING.reduce((b, [x, y]) => [Math.min(b[0], x), Math.min(b[1], y), Math.max(b[2], x), Math.max(b[3], y)], [180, 90, -180, -90]);
  try {
    map = new maplibregl.Map({ container: 'map', style: STYLE, center: [126.99, 37.56], zoom: 10.4, ...OV, maxPitch: 65, attributionControl: false });
    map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right');
    // 범위 묶기(동규 11-11): 남는 자리 가운데가 서울 경계 상자 + 여유(약 1km) 밖으로 못 간다. 가장 멀리 본 상태(fitZ)면 서울을 맞춘 자리에 고정, 확대할수록 끝까지
    // ponytail: 경계 「상자」로 묶음(서울 모양 다각형이 아님) — 상자 모서리의 서울 밖 땅은 가린 채 보일 수 있다
    map.transformCameraUpdate = (s) => {
      if (fitting || !fitF) return {};
      const F = freeRect(), k = 2 ** (map.getZoom() - s.zoom), c0 = map.getCenter(), fc = map.unproject([F.cx, F.cy]);
      const ox = (fc.lng - c0.lng) * k, oy = (fc.lat - c0.lat) * k, fx = s.center.lng + ox, fy = s.center.lat + oy;
      const g = Math.max(0, 1 - 2 ** (fitZ - s.zoom)), lim = (v, f, lo, hi) => Math.min(Math.max(v, f - (f - lo + MARGIN) * g), f + (hi - f + MARGIN) * g);
      const nx = lim(fx, fitF.lng, SB[0], SB[2]), ny = lim(fy, fitF.lat, SB[1], SB[3]);
      return nx === fx && ny === fy ? {} : { center: new maplibregl.LngLat(nx - ox, ny - oy) };
    };
    map.on('style.load', () => {
      koLabels(map);
      addOwnLayers(seoul); applyTone();
      mapOk = true;
      map.jumpTo(computeFit());
      drawn.pins = ''; renderPins();
      if (ui.open || ui.pair) relayout(true);
    });
    map.on('resize', () => relayout(false));
    map.on('click', (e) => { if (ui.picking && ui.open) relocate(ui.open, { lon: e.lngLat.lng, lat: e.lngLat.lat }); });
    map.on('error', (e) => { if (!mapOk && /style|Failed to fetch/i.test(String(e.error && e.error.message))) mapFailed(); });
  } catch { mapFailed(); }
}
function mapFailed() { $('map-failed').hidden = false; if (T) $('map-failed').textContent = SIT()['지도를 불러오지 못함']; }
const POS = { left: ['right', [-24, 0]], right: ['left', [24, 0]], top: ['bottom', [0, -24]], bottom: ['top', [0, 24]] };
function renderPins() {
  if (!mapOk) return;
  const focus = new Set(ui.pair || (ui.open ? [ui.open] : []));
  const key = JSON.stringify([S.inquiries.map((q) => [q.id, kindOf(q), q.loc && q.loc.lon, q.loc && q.loc.lat]), [...focus], ui.fix, [...ui.fresh]]);
  if (key === drawn.pins) return;
  drawn.pins = key;
  const seen = new Set();
  for (const q of S.inquiries) {
    if (!q.loc) continue;
    seen.add(q.id);
    let m = markers[q.id];
    if (!m) {
      const el = document.createElement('button');
      el.type = 'button'; el.addEventListener('click', (e) => { e.stopPropagation(); openCard(el.dataset.id); });
      m = markers[q.id] = new maplibregl.Marker({ element: el }).setLngLat([q.loc.lon, q.loc.lat]).addTo(map);
    }
    m.setLngLat([q.loc.lon, q.loc.lat]);
    const k = kindOf(q), el = m.getElement();
    el.dataset.id = q.id;
    el.className = [...el.classList].filter((c) => c.startsWith('maplibregl-')).concat(`pin k-${k}${focus.has(q.id) ? ' sel' : focus.size ? ' dim' : ''}${ui.fresh.has(q.id) ? ' new' : ''}`).join(' ');   // 지도 라이브러리의 자리 잡기 클래스는 남긴다
    el.textContent = q.no;
    el.setAttribute('aria-label', `${q.no} ${q.loc.name || ''} ${kindLabel(k)}`);
  }
  for (const id of Object.keys(markers)) if (!seen.has(id)) { markers[id].remove(); delete markers[id]; }
  // 고른 자리: 바닥 둥근 띠 + 이름표. 위치를 바로잡은 문의는 시민이 지정한 자리(점선)와 잇는 선
  while (extra.length) extra.pop().remove();
  const label = (c, text, pos, cls = '') => { const e = document.createElement('div'); e.className = 'plabel ' + cls; e.textContent = text; extra.push(new maplibregl.Marker({ element: e, anchor: POS[pos][0], offset: POS[pos][1] }).setLngLat(c).addTo(map)); };
  const sel = [], fixl = [];
  const ids = [...focus];
  ids.forEach((id, i) => {
    const q = byId(id); if (!q || !q.loc) return;
    const c = [q.loc.lon, q.loc.lat];
    sel.push(circle(c));
    label(c, `${q.no} · ${q.loc.name || W('답변 초안').kv['이름 없는 자리']}`, ids.length > 1 ? (i ? 'bottom' : 'top') : 'top');
    if (q.loc_from && q.loc_from.lon !== q.loc.lon) {
      const f = [q.loc_from.lon, q.loc_from.lat], e = document.createElement('div');
      e.className = 'pin was'; e.textContent = q.no; extra.push(new maplibregl.Marker({ element: e }).setLngLat(f).addTo(map));
      label(f, `${W('위치 바로잡기').kv['시민이 지정한 위치']} · ${q.loc_from.name || ''}`, 'left', 'was');
      fixl.push({ type: 'Feature', geometry: { type: 'LineString', coordinates: [f, c] } });
    }
  });
  map.getSource('own-sel').setData({ type: 'FeatureCollection', features: sel });
  map.getSource('own-fix').setData({ type: 'FeatureCollection', features: fixl });
}

// ---- 답변 초안 카드
function openCard(id) {
  ui.open = id; ui.pair = null; ui.card = true; ui.fix = false; ui.picking = false; ui.list = ui.listBeforePair;
  applyPanels(false); renderAll(true);
  requestAnimationFrame(() => relayout(true));
}
function closeCard() { ui.open = null; ui.pair = null; ui.fix = false; ui.picking = false; ui.list = ui.listBeforePair; applyPanels(false); renderAll(true); requestAnimationFrame(() => relayout(true)); }
function openPair(id) {
  const q = byId(id), o = q && sameText(q)[0];
  if (!o) return;
  if (!ui.pair) ui.listBeforePair = ui.list;
  ui.pair = [q, o].sort((a, b) => a.no - b.no).map((x) => x.id); ui.open = null; ui.card = true; ui.fix = false; ui.list = false;
  applyPanels(false); renderAll(true);
  requestAnimationFrame(() => relayout(true));
}
const mark = (on, word) => (on ? `<span class="chg">${esc(word)}</span>` : '');
// 「이 위치 기준」은 위치를 실제로 엔진에 넘겨 받은 답에만(시민 접수 · 담당자 바로잡기 + 이름 있는 장소). 처음 47건은 글만 넘겼다
const here = (q, label) => (q.loc && ['here', 'map', 'staff'].includes(q.loc.how) && q.loc.name ? `${label} · ${W('답변 초안').kv['이 위치 기준']}` : label);
function locRow(q, compact) {
  const C = W('답변 초안').kv, L = q.loc || {}, name = L.name || C['이름 없는 자리'];
  const how = L.how === 'here' ? C['현재 위치'] + (L.demo ? ` · ${C['시연용 자리']}` : '') : L.how === 'map' ? C['지도에서 지정']
    : L.how === 'staff' ? fill(C['바로잡음'], { 장소: (q.loc_from && q.loc_from.name) || C['이름 없는 자리'] }) : L.virtual ? C['시연 문의 가상 자리'] : C['시연 문의 자리'];
  const canFix = !compact && !q.approved && q.kind !== 'making';
  return `<div class="loc"><span class="k">${esc(C['접수 위치'])}</span><b>${esc(name)}</b>
    ${canFix ? `<button type="button" class="fixbtn" data-act="fix" aria-expanded="${ui.fix}">${esc(C['위치 바로잡기'])}</button>` : ''}
    <span class="how">${esc(how)}</span></div>`;
}
function head(q, compact) {
  const C = W('답변 초안').kv, k = kindOf(q), t = (q.form || {}).title;
  return `<div class="hd"><div class="meta"><span class="n">${q.no}</span><span>${hhmm(q.received)} · ${esc(srcLabel(q.source))}</span>
      <span class="stt kc k-${k}"><i class="kb"></i>${esc(kindLabel(k))}</span></div>
    ${t ? `<p class="ttl">${esc(C['문의 제목'])} · ${esc(t)}</p>` : ''}<p class="qq">${esc(q.text)}</p>${locRow(q, compact)}</div>`;
}
// 세 줄(근거 조항 · 소관 부서 · 처리 기관)에 붙일 표시: cmp = 견줄 문의(또는 바로잡기 전), word = 「바뀜」 · 「다름」
function diffs(q, cmp) {
  if (!cmp) return {};
  const a = lines(q), b = lines(cmp);
  return { cite: a.cite !== b.cite, dept: a.dept !== b.dept, agency: a.agency !== b.agency };
}
function prevOf(q) { return q.prev && q.loc && q.loc.how === 'staff' && q.kind !== 'making' ? { ...q, kind: q.prev.kind, card: q.prev.card, loc: q.prev.loc, approved: null } : null; }
function agBox(q, d, word) {
  const a = agencyOf(q), O = W('6종 밖').kv;
  if (!a || !a.law) return '';
  return `<div class="agbox"><div class="k">${esc(here(q, O['처리 기관 머리']))}${mark(d.agency, word)}</div><div class="v">${esc(a.agency)}</div>
    <div class="r">${esc(fill(O['다른 조례'], { 조례: a.law, 부서: a.dept }))}</div>${a.url ? `<a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(O['다른 조례 원문'])}</a>` : ''}</div>`;
}
function citesBlock(q, d, word, compact, on) {
  const C = W('답변 초안').kv, c = q.card, V = W('답변 초안').tab('초안의 결론');
  const verdict = c.conclusion && V[c.conclusion] && !V[c.conclusion].startsWith('[') ? `<p class="note">${esc(fill(C['판정'], { 판정: V[c.conclusion] }))}</p>` : '';
  const annex = (x) => /^별표/.test(x.article);   // 별표 구절은 표를 한 줄로 편 꼴이라 「글자까지 맞춰 봄」이 아니다(점검 11-11 밤, 39번)
  return `<h3><span>${esc(here(q, C['근거 조항']))}${mark(d.cite, word)}</span><span class="r">${esc(C[c.citations.some(annex) ? '근거 조항 작은 글 · 별표' : '근거 조항 작은 글'])}</span></h3>${compact ? '' : verdict}
    ${c.citations.map((x, ci) => `<div class="cite${on && on.ci === ci ? ' on' : ''}"><div class="lb">${esc(shortLaw(x.law))} ${esc(x.article)}<span>${esc(fill(C['시행일'], { 날짜: x.effective || '—' }))}</span></div>
      ${x.quotes.length ? x.quotes.slice(0, compact ? 1 : 9).map((t, qi) => `<blockquote class="${on && on.ci === ci && on.qi === qi ? 'on' : ''}">${esc(t)}</blockquote>`).join('')
        : `<p class="note">${esc(C['원문 구절 없음'])}</p><blockquote class="full">${esc(x.text || '—')}</blockquote>`}
      ${annex(x) && x.quotes.length && !compact ? `<p class="note">${esc(C['별표 구절'])}</p>` : ''}
      ${compact || !x.url ? '' : `<a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(C['원문 보기'])}</a>`}</div>`).join('')}`;
}
function agencyBlock(q, d, word, compact) {
  const C = W('답변 초안').kv, a = agencyOf(q);
  if (!a) return '';
  const capNote = a.cap && C[a.cap] && !C[a.cap].startsWith('[') ? C[a.cap] : '';
  return `<h3><span>${esc(here(q, C['소관 처리']))}</span></h3><dl class="kv">
      <dt>${esc(C['소관 부서'])}</dt><dd>${esc(a.dept)}${mark(d.dept, word)}</dd>
      <dt>${esc(C['처리 기관'])}</dt><dd>${esc(a.agency)}${mark(d.agency, word)}${a.agencyNote ? `<span class="note">${esc(a.agencyNote)}</span>` : ''}${capNote && !compact ? `<span class="note">${esc(capNote)}</span>` : ''}</dd>
      ${a.gal && !compact ? `<dt>${esc(C['일의 갈래'])}</dt><dd>${esc(a.gal)}</dd>` : ''}</dl>
    ${!compact && a.why ? `<details class="why"><summary>${esc(C['처리 기관 근거 보기'])}</summary><p>${esc(a.why)}</p>${a.links.map((o) => `<div><a href="${esc(o['주소'])}" target="_blank" rel="noopener">${esc(o['주소'].replace(/^https?:\/\//, '').slice(0, 64))}</a></div>`).join('')}</details>` : ''}
    ${compact ? '' : `<p class="note">${esc(C['처리 기관 뜻'])}</p>`}`;
}
function pastFor(q) {
  const labels = new Set(q.card.citations.map((c) => c.label));
  return S.inquiries.filter((x) => x.id !== q.id && x.approved && x.approved.reply === 'draft' && ((x.card || {}).citations || []).some((c) => labels.has(c.label)))
    .sort((a, b) => b.approved.at.localeCompare(a.approved.at))[0];
}
function draftBlock(q, compact) {
  const C = W('답변 초안').kv, P = W('문장과 구절'), done = !!q.approved;
  const value = done ? q.approved.text : (ui.dirty[q.id] ?? q.draft ?? '');
  const edited = !done ? value !== q.card.answer : q.approved.edited;
  let h = `<h3><span>${esc(C['초안'])}${edited ? ` <span class="verdict">${esc(C['고친 글'])}</span>` : ''}</span><span class="r">${esc(C['초안 작은 글'])}</span></h3>`;
  if (ui.editing[q.id] && !done && !compact) {
    return { html: h + `<textarea class="draft" id="c-text" aria-label="${esc(C['초안'])}">${esc(value)}</textarea>
      <div class="rowbtn"><button type="button" class="outline" data-act="edit-done">${esc(P.btn()[1])}</button></div>`, on: null };
  }
  const pairs = pairUp(value, q.card);
  let si = ui.sent[q.id];
  if (si == null || !pairs[si]) si = pairs.findIndex((p) => p.q);
  const on = !compact && si >= 0 && pairs[si] && pairs[si].q ? pairs[si].q : null;
  h += `<div class="draft">${pairs.map((p, i) => `<span class="s${p.q ? '' : ' none'}${!compact && i === si && p.q ? ' on' : ''}" ${compact ? '' : `data-act="sent" data-i="${i}"`} title="${p.q ? '' : esc(P.kv['짝 없음'])}">${esc(p.s)}</span>`).join(' ')}</div>`;
  if (!compact) {
    h += `<p class="pairnote">${esc(P.kv['안내'])} · ${esc(P.kv['짐작'])}</p>`;
    if (!done) h += `<div class="rowbtn"><button type="button" class="outline" data-act="edit">${esc(P.btn()[0])}</button>${edited ? `<button type="button" class="ghost" data-act="revert">${esc(C['처음 초안으로'])}</button>` : ''}</div>`;
  }
  return { html: h, on };
}
function replyBlock(q) {   // 초안이 없는 문의(6종 밖 · 조항 못 찾음)에 담당자가 직접 쓰거나 처리 기관 안내로 답하기
  const C = W('답변 초안').kv, done = !!q.approved, value = done ? q.approved.text : (ui.dirty[q.id] ?? '');
  if (!done && !ui.reply[q.id]) {
    const O = W(q.kind === 'out' ? '6종 밖' : '조항을 찾지 못함'), bs = O.btn();
    const canGuide = q.kind === 'out' && (agencyOf(q) || {}).law;
    return `<div class="rowbtn"><button type="button" class="outline" data-act="reply" data-r="direct">${esc(bs[0])}</button>${canGuide ? `<button type="button" class="primary" data-act="reply" data-r="guide">${esc(bs[1])}</button>` : ''}</div>`;
  }
  return `<h3><span>${esc(C['초안'])}</span></h3>${done ? `<div class="draft">${esc(value)}</div>` : `<textarea class="draft" id="c-text" aria-label="${esc(C['초안'])}">${esc(value)}</textarea>`}`;
}
function statusBlock(q) {
  const ST = W('처리 상태'), opts = ST.pick('보기'), done = !!q.approved, s = SIT();
  return `<div class="status"><h3 id="c-status-h"><span>${esc(ST.name)}</span></h3><p class="lead2">${esc(ST.lead)}</p>
    <div class="radios" role="radiogroup" aria-labelledby="c-status-h">${opts.map((o, i) => `<label class="radio${(i === 1) === done ? ' on' : ''}"><input type="radio" name="c-status" value="${i}" ${(i === 1) === done ? 'checked' : ''} ${done && i === 0 ? 'disabled' : ''}> ${esc(o)}</label>`).join('')}</div>
    ${done ? `<p class="note">${esc(s['승인한 뒤 「검토 중」'])}</p><p class="okmsg" role="status">${esc(s['승인 완료'])} · ${esc(hhmm(q.approved.at))}</p>` : `<p class="note">${esc(ST.smalls[0] || '')}</p>`}
    <p class="err" id="c-err" role="alert" hidden></p></div>`;
}
function sourceLine(q) {
  if (!q.engine || q.kind === 'failed' || q.kind === 'making') return '';
  const none = q.kind !== 'draft';   // 6종 밖 · 조항 못 찾음: 초안이 없으니 「결과」라고 쓴다
  const O = W('초안의 출처'), it = O.plain(), [b, s0] = it[(q.engine.how === 'live' ? 0 : 1) + (none ? 2 : 0)] || ['', ''], made = O.tab('만든 판');
  const key = `${q.engine.made_by}${none ? ' · 초안 없음' : ''}`, s = q.engine.made_by && Object.prototype.hasOwnProperty.call(made, key) ? made[key] : s0;
  const meta = [hhmm(q.engine.at), q.engine.sec != null ? `${q.engine.sec}초` : ''].filter(Boolean).join(' · ');
  return `<footer class="c-src"><b>${esc(b)}</b> ${esc(s)} · ${esc(meta)}</footer>`;
}
function bodyOf(q, o = {}) {   // o.compact(나란히 보기의 한 칸) · o.cmp(견줄 문의) · o.word(「다름」 · 「바뀜」)
  const s = SIT(), k = q.kind;
  const prev = !o.cmp && prevOf(q), cmp = o.cmp || prev, word = o.word || W('위치 바로잡기').kv['바뀜'], d = diffs(q, cmp);
  let h = '';
  if (k === 'making') {
    h += `<div class="gap" aria-busy="true"><p class="lead2">${esc(q.loc && q.loc.how === 'staff' ? W('위치 바로잡기').kv['다시 찾는 중'] : s['초안을 만드는 중'])}</p><div class="sk"></div><div class="sk"></div><div class="sk short"></div></div>`;
  } else if (k === 'failed') {
    const B = W('불러오지 못함'), noSaved = q.engine && q.engine.how === 'saved';
    h += `<div class="gap"><p class="lead2">${esc(noSaved ? s['미리 받은 답이 없음'] : B.lead)}</p>${noSaved ? '' : B.smalls.map((x) => `<p class="note">${esc(x)}</p>`).join('')}
      ${!noSaved && !o.compact ? `<button type="button" class="outline" data-act="retry">${esc(B.btn()[0])}</button>` : ''}</div>`;
  } else if (k === 'out' || k === 'notfound') {
    const B = W(k === 'out' ? '6종 밖' : '조항을 찾지 못함');
    const law = k === 'out' && (agencyOf(q) || {}).law, O = W('6종 밖').kv;
    h += agBox(q, d, word);
    h += `<div class="gap"><p class="lead2">${esc(B.lead)}</p>${B.smalls.map((x) => `<p class="note">${esc(x)}</p>`).join('')}</div>`;
    if (law) h += `<h3><span>${esc(here(q, W('답변 초안').kv['근거 조항']))}${mark(d.cite, word)}</span></h3><div class="cite"><div class="lb">${esc(fill(O['근거 줄'], { 조례: shortLaw(law) }))}</div><p class="note">${esc(O['근거 설명'])}</p></div>`;
    if (k === 'out') h += agencyBlock(q, d, word, o.compact);
    if (!o.compact) h += replyBlock(q);
  } else {
    const dr = draftBlock(q, o.compact);
    h += dr.html + citesBlock(q, d, word, o.compact, dr.on) + agencyBlock(q, d, word, o.compact);
    if (!o.compact) {
      const past = !q.approved && pastFor(q), PA = W('지난번에 승인한 답');
      if (past) h += `<div class="past"><div class="t">${esc(fill(PA.kv['머리'], { 번호: past.no, 조항: `${shortLaw(past.card.citations[0].law)} ${past.card.citations[0].article}` }))}</div>
        <div class="a">${esc(past.approved.text)}</div><button type="button" class="outline" data-act="past" data-id="${past.id}">${esc(PA.btn()[0])}</button><p class="note">${esc(PA.smalls[0] || '')}</p></div>`;
    }
  }
  if (prev && !o.compact && (d.cite || d.dept || d.agency)) h = `<p class="note">${esc(W('위치 바로잡기').kv['바뀜 설명'])}</p>` + h;
  return h;
}
function navBar(q) {
  const nb = W('답변 초안').btn(), list = filtered().slice().reverse(), i = list.findIndex((x) => x.id === q.id), same = sameText(q);
  const prev = i > 0 ? list[i - 1].id : '', next = i >= 0 && i < list.length - 1 ? list[i + 1].id : '';
  return `<nav class="c-nav" aria-label="${esc(W('답변 초안').name)}"><button type="button" class="outline" data-act="back">← ${esc(nb[0])}</button>
    ${same.length ? `<button type="button" class="primary" data-act="pair-on" data-id="${q.id}">${esc(W('두 시민').kv['나란히 보기'])}</button>` : ''}
    <span><button type="button" class="ghost" data-act="go" data-id="${prev}" ${prev ? '' : 'disabled'}>${esc(nb[1])}</button>
    <span class="pos">${i >= 0 ? `${i + 1} / ${list.length}` : ''}</span>
    <button type="button" class="ghost" data-act="go" data-id="${next}" ${next ? '' : 'disabled'}>${esc(nb[2])}</button></span></nav>`;
}
function renderCard(force) {
  const box = $('card');
  if (ui.pair) {
    const [a, b] = ui.pair.map(byId);
    if (!a || !b) { ui.pair = null; return renderCard(true); }
    const key = JSON.stringify(['pair', a, b, ui.tone, textVersion]);
    if (!force && key === drawn.card) return;
    drawn.card = key;
    const P = W('두 시민');
    $('fixpop').hidden = true;
    box.innerHTML = `<div class="pairhd">${esc(P.kv['머리'])}<span>${esc(P.kv['다름 설명'])}</span><button type="button" class="outline" data-act="pair-off">${esc(P.btn()[0])}</button></div>
      <div class="cols">${[a, b].map((q, i) => `<section>${head(q, true)}<div class="bd">${bodyOf(q, { compact: true, cmp: i ? a : null, word: P.kv['다름'] })}
        <div class="rowbtn"><button type="button" class="outline" data-act="go" data-id="${q.id}">${esc(String(q.no))} · ${esc(W('답변 초안').name)}</button></div></div>${sourceLine(q)}</section>`).join('')}</div>`;   // 출처 줄도 칸마다(미리 받은 답 · 반영 전 기능을 영상 한 장면 안에서 밝힘)
    return;
  }
  const q = byId(ui.open);
  if (!q) { if (ui.open) { ui.open = null; applyPanels(); } drawn.card = ''; return; }
  const ta = $('c-text');
  if (!force && ta && document.activeElement === ta && ui.lastKind === q.kind) return;   // 고쳐 쓰는 중에는 다시 그리지 않는다
  const key = JSON.stringify([q, ui.editing[q.id], ui.sent[q.id], ui.reply[q.id], ui.fix, ui.picking, S.engine, textVersion, S.inquiries.filter((x) => x.approved).length, sameText(q).length]);
  if (!force && key === drawn.card) return;
  drawn.card = key; ui.lastKind = q.kind;
  const scroll = box.querySelector('.c-scroll'), top = scroll ? scroll.scrollTop : 0;
  // 처리 상태(승인)는 카드 아래 붙박이: 카드를 내리지 않아도 늘 보인다(시연 흐름 손질 2)
  const st = q.kind === 'draft' || (['out', 'notfound'].includes(q.kind) && (ui.reply[q.id] || q.approved)) ? `<div class="c-status">${statusBlock(q)}</div>` : '';
  box.innerHTML = navBar(q) + `<div class="c-scroll">${head(q)}<div class="bd">${bodyOf(q)}</div></div>` + st + sourceLine(q);
  if (!force) box.querySelector('.c-scroll').scrollTop = top;
  renderFix(q);
}
function renderFix(q) {
  const pop = $('fixpop'), F = W('위치 바로잡기'), K = F.kv;
  pop.hidden = !ui.fix || !q || !!q.approved;
  $('map').classList.toggle('picking', ui.picking && !pop.hidden);
  if (pop.hidden) return;
  const cur = q.loc, orig = q.loc_from || (['here', 'map'].includes(cur.how) ? cur : null), opts = [];
  const same = (a, b) => a && b && (a.place ? a.place === b.place : Math.abs(a.lon - b.lon) < 1e-5 && Math.abs(a.lat - b.lat) < 1e-5);
  if (orig) opts.push({ loc: orig, tag: K['시민이 지정한 위치'] });
  if (!orig || !same(orig, cur)) opts.push({ loc: cur, tag: K['지금 위치'] });
  const near = Object.values(S.places).map((p) => [km([cur.lon, cur.lat], [p.lon, p.lat]), p]).filter(([d, p]) => d < 4.5 && !opts.some((o) => o.loc.place === p.id)).sort((a, b) => a[0] - b[0]).slice(0, 4);
  for (const [, p] of near) opts.push({ loc: { name: p.name, place: p.id, lon: p.lon, lat: p.lat }, tag: K['가까운 장소'] });
  pop.innerHTML = `<h4>${esc(F.name)}<span>${q.no}</span></h4><p class="lead2">${esc(F.lead)}</p>
    ${opts.map((o, i) => `<button type="button" class="opt${same(o.loc, cur) && !ui.picking ? ' on' : ''}" data-act="reloc" data-i="${i}"><i></i>${esc(o.loc.name || W('답변 초안').kv['이름 없는 자리'])}<span>${esc(o.tag)}</span></button>`).join('')}
    <button type="button" class="opt${ui.picking ? ' on' : ''}" data-act="pick"><i></i>${esc(K['지도에서 다시 찍기'])}</button>
    ${ui.picking ? `<p class="note">${esc(K['찍는 중'])}</p>` : ''}
    <div class="foot"><p>${esc(F.smalls[0] || '')}</p><button type="button" class="outline" data-act="fix-close">${esc(F.btn()[0])}</button></div><p class="err" id="fix-err" role="alert" hidden></p>`;
  pop._opts = opts;
  const R = freeRect();
  pop.style.left = `${Math.max(R.l + 6, Math.min(R.cx - 170, R.r - 346))}px`;
}
async function relocate(id, body) {
  ui.picking = false;
  try { await api(`/api/inquiries/${id}/relocate`, body); ui.editing[id] = false; delete ui.dirty[id]; ui.reply[id] = null; ui.sent[id] = null; }
  catch { const e = $('fix-err'); if (e) { e.textContent = SIT()['바로잡지 못함']; e.hidden = false; } }
  await refresh(); renderCard(true);
  requestAnimationFrame(() => relayout(true));
}
function askApprove(q) {
  const ta = $('c-text'), err = $('c-err');
  const text = (ta ? ta.value : (ui.dirty[q.id] ?? q.draft ?? '')).trim();
  const back = () => { const r0 = document.querySelector('input[name="c-status"][value="0"]'); if (r0) r0.checked = true; };
  if (!text) { err.textContent = SIT()['답이 비어 있음']; err.hidden = false; back(); if (ta) ta.focus(); return; }
  err.hidden = true;
  const dlg = $('dlg'), s = SIT();
  $('dlg-text').textContent = s['승인 확인']; $('dlg-yes').textContent = s['승인 확인 · 보내기'];
  $('dlg-no').onclick = () => { dlg.close(); back(); };
  dlg.oncancel = () => back();
  $('dlg-yes').onclick = async () => {
    $('dlg-yes').disabled = $('dlg-no').disabled = true;
    try {
      await api(`/api/inquiries/${q.id}/approve`, { text, reply: q.kind === 'draft' ? 'draft' : ui.reply[q.id] });
      delete ui.dirty[q.id]; ui.editing[q.id] = false;
    } catch { back(); const e = $('c-err'); if (e) { e.textContent = s['승인하지 못함']; e.hidden = false; } }
    finally { $('dlg-yes').disabled = $('dlg-no').disabled = false; dlg.close(); }
    await refresh(); renderCard(true);
  };
  dlg.showModal();
}
function cardClick(e) {
  const b = e.target.closest('[data-act]');
  if (!b || b.disabled) return;
  const q = byId(ui.open), act = b.dataset.act;
  if (act === 'back') return closeCard();
  if (act === 'go') return b.dataset.id && openCard(b.dataset.id);
  if (act === 'pair-on') return openPair(b.dataset.id);
  if (act === 'pair-off') { const id = ui.pair[0]; ui.pair = null; return openCard(id); }
  if (act === 'fix-close') { ui.fix = false; ui.picking = false; renderCard(true); return requestAnimationFrame(() => relayout(true)); }
  if (act === 'pick') { ui.picking = !ui.picking; return renderFix(q); }
  if (act === 'reloc') { const o = $('fixpop')._opts[+b.dataset.i]; return o && relocate(q.id, o.loc.place ? { place: o.loc.place } : { lon: o.loc.lon, lat: o.loc.lat }); }
  if (!q) return;
  if (act === 'fix') { ui.fix = !ui.fix; ui.picking = false; renderCard(true); return requestAnimationFrame(() => relayout(true)); }
  if (act === 'sent') { ui.sent[q.id] = +b.dataset.i; return renderCard(true); }
  if (act === 'edit') { ui.editing[q.id] = true; renderCard(true); return $('c-text') && $('c-text').focus(); }
  if (act === 'edit-done') { saveDraft(q); ui.editing[q.id] = false; return renderCard(true); }
  if (act === 'revert') { ui.dirty[q.id] = q.card.answer; api(`/api/inquiries/${q.id}/draft`, { text: q.card.answer }).catch(() => {}); return renderCard(true); }
  if (act === 'past') { const p = byId(b.dataset.id); ui.dirty[q.id] = p.approved.text; ui.editing[q.id] = true; saveDraft(q); return renderCard(true); }
  if (act === 'reply') {
    ui.reply[q.id] = b.dataset.r;
    if (b.dataset.r === 'guide') { const a = agencyOf(q); ui.dirty[q.id] = fill(W('6종 밖').kv['안내 답'], { 조례: a.law, 기관: a.agency }); }
    return renderCard(true);
  }
  if (act === 'retry') { b.disabled = true; return api(`/api/inquiries/${q.id}/retry`, {}).catch(() => {}).then(refresh); }
}
function saveDraft(q) { const ta = $('c-text'); if (ta) ui.dirty[q.id] = ta.value; if (ui.dirty[q.id] != null && !q.approved) api(`/api/inquiries/${q.id}/draft`, { text: ui.dirty[q.id] }).catch(() => {}); }

// ---- 새 문의 알림 · 갱신
function noticeNew(list) {
  const q = list[list.length - 1], t = $('toast');
  t.textContent = fill(SIT()['새 문의'], { 번호: q.no, 장소: (q.loc && q.loc.name) || '' });
  t.dataset.id = q.id; t.hidden = false;
  const R = freeRect(); t.style.left = `${Math.max(R.l + t.offsetWidth / 2 + 6, R.cx)}px`;   // 칸에 가리지 않는 자리의 가운데 위
  clearTimeout(noticeNew.t); noticeNew.t = setTimeout(() => { t.hidden = true; }, 7000);
  for (const x of list) ui.fresh.add(x.id);
  setTimeout(() => { for (const x of list) ui.fresh.delete(x.id); drawn.list = ''; drawn.pins = ''; }, 5000);
}
function renderAll(force) {
  if (!S || !T) return;
  const lk = JSON.stringify([S.inquiries.map((q) => [q.id, kindOf(q), q.loc && q.loc.name]), S.engine, ui.chip, ui.dept, ui.open, ui.pair, [...ui.fresh], textVersion]);
  if (force || lk !== drawn.list) { drawn.list = lk; renderList(); }
  renderCard(force); renderPins();
}
async function refresh() {
  try {
    S = await api('/api/state');
    if (S.text_version !== textVersion) {
      const t = await api('/api/text');
      textVersion = t.version;
      let err = t.error;
      if (t.text) {          // 새 글자로 그려 보고, 깨졌으면(고치는 중인 파일) 마지막으로 정상이던 글자로 돌아간다
        const prev = [T, X];
        T = t.text; X = texts(T, FILE);
        try { placeText(); renderAll(true); } catch (e) { [T, X] = prev; err = err || String(e.message || e); if (T) placeText(); }
      }
      $('text-err').hidden = !err || !T; if (err && T) { $('text-err').textContent = SIT()['화면 문구 파일을 읽지 못함']; console.warn('content:', err); }
    }
    if (ui.seen) { const nw = S.inquiries.filter((q) => !ui.seen.has(q.id)); if (nw.length) noticeNew(nw); }
    ui.seen = new Set(S.inquiries.map((q) => q.id));
    if (ui.open && !byId(ui.open)) { ui.open = null; applyPanels(); }
    renderAll(false);
  } catch {
    if (T) { $('l-msg').textContent = SIT()['불러오지 못함']; drawn.list = ''; }
  }
}
function bind() {
  $('chips').addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) { ui.chip = +b.dataset.chip; renderAll(false); } });
  $('l-dept').onchange = () => { ui.dept = +$('l-dept').value; renderAll(false); };
  $('rows').addEventListener('click', (e) => {
    const p = e.target.closest('[data-pairwith]'); if (p) { e.stopPropagation(); return openPair(p.dataset.pairwith); }
    const b = e.target.closest('button.row'); if (b) openCard(b.dataset.id);
  });
  $('tg-list').onclick = () => { ui.list = !ui.list; ui.listBeforePair = ui.list; applyPanels(); };
  $('tg-card').onclick = () => { if (ui.open || ui.pair) { ui.card = !ui.card; applyPanels(); } };
  $('t-tone').addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) setTone(b.dataset.tone); });
  $('card').addEventListener('click', cardClick);
  $('fixpop').addEventListener('click', cardClick);
  $('card').addEventListener('change', (e) => { if (e.target.name === 'c-status' && e.target.value === '1') { const q = byId(ui.open); if (q && !q.approved) askApprove(q); } });
  $('card').addEventListener('input', (e) => { if (e.target.id === 'c-text' && ui.open) ui.dirty[ui.open] = e.target.value; });
  $('card').addEventListener('focusout', (e) => { if (e.target.id === 'c-text' && ui.open) { const q = byId(ui.open); if (q) saveDraft(q); } });
  $('toast').onclick = () => { $('toast').hidden = true; if ($('toast').dataset.id) openCard($('toast').dataset.id); };
  $('btn-reset').onclick = () => {
    const dlg = $('dlg'), s = SIT();
    $('dlg-text').textContent = s['처음 상태로 되돌리기 확인']; $('dlg-yes').textContent = s['처음 상태로 되돌리기 확인 · 되돌리기'];
    $('dlg-no').onclick = () => dlg.close(); dlg.oncancel = null;
    $('dlg-yes').onclick = async () => { await api('/api/reset', {}).catch(() => {}); dlg.close(); Object.assign(ui, { open: null, pair: null, editing: {}, dirty: {}, sent: {}, reply: {}, fix: false, seen: null });
      applyPanels(false); await refresh(); relayout(true); };
    dlg.showModal();
  };
  addEventListener('keydown', (e) => { if (e.key === 'Escape' && ui.picking) { ui.picking = false; renderFix(byId(ui.open)); } });
}

(async function main() {
  const q = new URLSearchParams(location.search).get('tone');
  setTone(q || store.get('desk3.tone') || 'light');
  bind();
  try { AG = await (await fetch('data/agencies.json')).json(); } catch { AG = null; }   // 없으면 카드에 소관 부서 칸이 빠질 뿐 나머지는 돈다
  await refresh();
  if (!T) $('l-msg').textContent = '문의 목록을 불러오지 못했습니다.';   // ponytail: content를 한 번도 못 받은 때만 쓰는 마지막 문장
  await initMap();
  setInterval(refresh, 1200);
  window.DESK = { ui, get S() { return S; }, get map() { return map; }, get ready() { return mapOk; }, freeRect, get fitZ() { return fitZ; }, get SB() { return SB; }, get ring() { return RING; }, MARGIN, openCard, openPair, closeCard, setTone, PAL, focusCam, focusPts };   // 점검용
})();
