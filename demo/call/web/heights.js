// 서울 전체 건물의 실제 높이와 대본 건물의 지붕 둘레 띠. 끄기: 주소에 ?heights=off
// 지도 타일의 건물 층은 같은 높이의 건물을 타일마다 한 덩어리로 묶어 두어 건물마다 높이를 바꿀 수 없다. 그래서 타일 건물은 그대로 두고,
// 서울시 자료(「건물 태양에너지 등급도(2018)」)의 높이(= 층수 × 3.5m)가 더 높은 건물만 바닥 모양을 0.4m 넓혀 그 높이로 덧그린다.
// 자료는 칸(확대 14 타일, 약 1.9km 네모)마다 파일 하나(web/heights/cells/<x>-<y>.json, tools/make_heights.py)이고, 지금 보이는 칸만 불러온다.
// 칠은 타일 건물 층(own-b3d · own-roof)을 그대로 따라 한다. call.js의 map · markers · V를 읽기만 한다
'use strict';
(function () {
  if (new URLSearchParams(location.search).get('heights') === 'off') return;
  const COL = '#ff9f1c', PROPS = ['fill-extrusion-color', 'fill-extrusion-height', 'fill-extrusion-base', 'fill-extrusion-opacity', 'fill-extrusion-vertical-gradient'];
  const PAIRS = [['own-b3d', 'own-hb3d'], ['own-roof', 'own-hroof']];
  const N = 2 ** 14, FROM = 13.5, MAX = 30;      // 칸 번호를 세는 확대(14), 이 확대부터 불러옴(건물이 또렷해지는 때), 지도에 올려 두는 칸 수
  const near = (a, b) => Math.hypot((a[0] - b[0]) * 88200, (a[1] - b[1]) * 111000);
  const cell = ({ lng, lat }) => [(lng + 180) / 360 * N, (1 - Math.asinh(Math.tan(lat * Math.PI / 180)) / Math.PI) / 2 * N];      // 경도 · 위도 → 칸 번호(소수)
  const far = (k, [cx, cy]) => Math.hypot(+k.split('-')[0] + 0.5 - cx, +k.split('-')[1] + 0.5 - cy);
  const ring = (a, o) => { const r = []; for (let i = 0, x = 0, y = 0; i < a.length; i += 2) r.push([o[0] + (x += a[i]) / 1e6, o[1] + (y += a[i + 1]) / 1e6]); r.push(r[0]); return r; };
  function copyPaint() {      // 화면 밝기를 바꾸면(applyTone) 타일 건물 층의 칠을 그대로 따른다
    for (const [from, to] of PAIRS) for (const k of PROPS) {
      const v = map.getPaintProperty(from, k);
      if (v !== undefined && JSON.stringify(v) !== JSON.stringify(map.getPaintProperty(to, k))) map.setPaintProperty(to, k, v);
    }
  }
  async function add() {
    const [hi, idx] = await Promise.all(['hi.geojson', 'index.json'].map((f) => fetch('heights/' + f).then((r) => r.json()).catch(() => null)));
    map.addSource('own-heights', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
    map.addSource('own-hi', { type: 'geojson', data: hi || { type: 'FeatureCollection', features: [] } });
    for (const [, to] of PAIRS) map.addLayer({ id: to, type: 'fill-extrusion', source: 'own-heights', minzoom: 13 }, 'own-cloud');
    copyPaint();
    map.on('styledata', copyPaint);
    // 대본 건물 강조: 지붕 둘레 띠(지붕 색은 덮지 않음). 표지와 같은 때에만 보인다 — 지금 질문이 물어보는 표지가 든 건물, 자리가 정해지면 그 자리 건물
    map.addLayer({ id: 'own-hring', type: 'fill-extrusion', source: 'own-hi', minzoom: 13, filter: ['in', ['get', 'name'], ['literal', []]],
      paint: { 'fill-extrusion-color': COL, 'fill-extrusion-height': ['+', ['get', 'h'], 0.6], 'fill-extrusion-base': ['max', ['-', ['get', 'h'], 2.4], 0] } }, 'own-cloud');
    let last = '';
    setInterval(() => {
      const names = new Set(markers.map((m) => m.getElement().title).filter(Boolean));
      if (hi && V && V.confirmed && V.pin) for (const f of hi.features) if (near(f.properties.at, V.pin.at) <= 25) names.add(f.properties.name);
      const key = [...names].sort().join('|');
      if (key !== last) { last = key; map.setFilter('own-hring', ['in', ['get', 'name'], ['literal', [...names]]]); }
    }, 300);
    if (!idx) return;
    // 실제 높이: 보이는 칸만 받아 지도에 올리고, MAX칸을 넘으면 화면 가운데에서 먼 칸부터 내린다
    const got = new Map(), on = new Map();      // 칸 → 받는 중이거나 받은 건물들, 칸 → 지도에 올린 건물들
    if (window.CALL) CALL.heights = on;      // 점검용
    let line = Promise.resolve();      // 칸 파일은 한 번에 하나씩 받는다. 여러 개를 한꺼번에 청하면 시연 서버(파이썬 기본 서버)가 바쁠 때 연결을 끊는다
    const get = (k) => (line = line.catch(() => {}).then(() => fetch(`heights/cells/${k}.json`)).then((r) => r.json()));
    const load = (k) => got.get(k) || got.set(k, get(k).catch(() => get(k)).then(({ o, b }) => b.map(([h, , h0, ...rings], i) => (
      { type: 'Feature', id: (+k.split('-')[0] * N + +k.split('-')[1]) * 1e5 + i, properties: { render_height: h, render_min_height: h0 }, geometry: { type: 'Polygon', coordinates: rings.map((a) => ring(a, o)) } }))).catch(() => { got.delete(k); })).get(k);      // 받다 끊기면 한 번 더, 그래도 안 되면 다음에 다시
    async function refresh() {
      if (map.getZoom() < FROM) return;
      // 부른 그 순간의 시점으로 칸을 정한다. call.js가 날아갈 시점을 재느라 지도를 잠깐 옮겨 볼 때도 불리므로, 도착할 자리의 칸을 날아가기 전에 받게 된다
      const b = map.getBounds(), c = cell(map.getCenter()), [x0, y0] = cell(b.getNorthWest()).map(Math.floor), [x1, y1] = cell(b.getSouthEast()).map(Math.floor), keys = [];
      for (let x = x0; x <= x1; x++) for (let y = y0; y <= y1; y++) if (idx.cells[`${x}-${y}`]) keys.push(`${x}-${y}`);
      keys.sort((p, q) => far(p, c) - far(q, c)).splice(MAX);
      const fresh = new Map((await Promise.all(keys.map(load))).map((f, i) => [keys[i], f])), now = cell(map.getCenter()), diff = { add: [], remove: [] };
      const keep = [...keys, ...[...on.keys()].filter((k) => !keys.includes(k)).sort((p, q) => far(p, now) - far(q, now))].slice(0, MAX);      // 이번에 걸친 칸은 모두, 남는 자리는 이미 올린 칸 가운데 지금 화면 가운데에서 가까운 순으로
      for (const k of [...on.keys()]) if (!keep.includes(k)) { diff.remove.push(...on.get(k).map((f) => f.id)); on.delete(k); }
      for (const k of keep) if (!on.has(k) && fresh.get(k)) { on.set(k, fresh.get(k)); diff.add.push(...fresh.get(k)); }
      for (const k of [...got.keys()]) if (!keep.includes(k)) got.delete(k);
      if (diff.add.length || diff.remove.length) map.getSource('own-heights').updateData(diff);
    }
    let t = 0;
    map.on('moveend', refresh);
    map.on('move', () => { if (!map.isZooming() && performance.now() - t > 300) { t = performance.now(); refresh(); } });      // 끌어서 옮기는 동안에도(확대가 바뀌는 날아가기 중에는 쉼)
    refresh();
  }
  const wait = setInterval(() => { if (map && map.getLayer('own-roof') && map.getLayer('own-cloud')) { clearInterval(wait); add(); } }, 200);
})();
