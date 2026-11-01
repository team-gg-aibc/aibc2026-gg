// 한강 3D 지도 — MapLibre GL JS 5.6.0 + OpenFreeMap liberty (키 없음)
const STYLE_URL = 'https://tiles.openfreemap.org/styles/liberty';
const DEMO = { center: [126.93, 37.529], zoom: 14.6, pitch: 60, bearing: 200 };
const FLY = { zoom: 14.2, pitch: 60, seconds: 110, lookAhead: 1200 };
// 예시(불꽃축제 날 밤) 카메라: 1600×900 기준. 큰 화면은 상황판 글자 크기(rem)에 맞춰 줌을 올린다.
const SCENE = { center: [126.93351, 37.53048], zoom: 14.9, pitch: 58, bearing: 320 };
const PLAY_SECONDS = 45;   // 19:00~19:30(1800초)을 몇 초에 재생할지
const WINDOW = 1800;
// 불꽃 바지선: 마포대교 이름표 점 → 원효대교 이름표 점을 잇는 선의 35%·50%·65%(강 가운데)
const BARGES = [0.35, 0.5, 0.65].map((k) => [126.93638 + (126.94587 - 126.93638) * k, 37.53352 + (37.52718 - 37.53352) * k]);
const ATTR = '© <a href="https://openfreemap.org" target="_blank" rel="noopener">OpenFreeMap</a> · '
  + '© <a href="https://www.openmaptiles.org/" target="_blank" rel="noopener">OpenMapTiles</a> · '
  + '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors';
const C = {
  land: '#e4e5e1', water: '#a8bece', green: '#cbdac1', park: '#bdd5b0', parkLine: '#8fb57f',
  building: '#eef0ee', road: '#ffffff', casing: '#d3d6d3', rail: '#c4c8cb',
  deck: '#f6f6f4', pier: '#cfd3d6', text: '#3a4350', pin: '#3DDC84',
};
// 밤 색(예시 장면). 낮 값은 바꾸기 직전에 지도에서 읽어 두었다가 그대로 되돌린다.
const N = {
  land: '#0a1322', water: '#0e3166', green: '#0f2629', landuse: '#0e1828', building: '#17233a', building3d: '#1e2d4a',
  park: '#14483a', parkLine: '#2e8f62', road: '#ffc56b', road2: '#d39a52', roadMinor: '#2a3854', casing: '#b0661a',
  casingMinor: '#111a2b', rail: '#3a4766', deck: '#43557a', pier: '#25314a', text: '#c9d4e6', halo: '#0a1322',
};
const LIGHT = {
  day: { anchor: 'viewport', color: '#ffffff', intensity: 0.4, position: [1.2, 210, 35] },
  night: { anchor: 'viewport', color: '#c9d3ff', intensity: 0.35, position: [1.2, 210, 35] },
};
// 부서 색(유형 6개와 담당 부서 6곳은 하나씩 맞물린다): 밝은 낮 지도·어두운 밤 지도 모두에서 서로 구별되게. 늘 부서 이름 · 번호와 함께 쓴다.
const TYPE_COLOR = { 금연: '#ff7a59', 자전거: '#3fa9ff', 동물보호: '#ffc53d', 주차장: '#b18cff', 도시공원: '#2fd4b8', 청년: '#ff6fb5' };
// 화면 문구: vault content/A-01_상황판.md · U-01_현장휴대폰.md · U-02_시민신고.md의 상황별 안내·고정 입력 그대로
const SAY = {
  loading: '들어온 일을 상황판에 올리고 있어요.',
  empty: '아직 들어온 일이 없어요.',
  deptEmpty: '이 부서에 온 일이 아직 없어요. 전체 보기로 돌아갈게요.',
  failed: '들어온 일을 불러오지 못했어요. 잠시 후 다시 시도해 주세요.',
  approved: '현장에 안내를 보냈어요.',
  sending: '보내고 있어요.',
  doneEmpty: '아직 해결한 일이 없어요.',
  openEmpty: '남은 일이 없어요. 모두 해결했어요.',
};
const U02 = { what: '여의나루역 출구 앞에서 담배 피우는 사람이 많아요', where: '여의나루역 출구 앞', phone: '010-0000-0000' };
const APPROVED_1 = '출구 10m 금연구역 안내';   // A-01 「승인한 안내」 표의 1번 안내
const KO = ['coalesce', ['get', 'name:ko'], ['get', 'name']];
const IS_RAIL = ['match', ['get', 'class'], ['rail', 'transit'], true, false];
const FILES = ['bridges', 'bridge_mask', 'piers', 'bridge_labels', 'parks', 'park_labels', 'ring10'];

// 로컬 http.server는 여러 파일을 한꺼번에 받을 때 가끔 연결을 끊는다(직접 재현): 0.4초 뒤 한 번 더 받는다
const getJSON = (url, init, retry = 1) => fetch(url, init).then((r) => {
  if (!r.ok) throw new Error(`${url} → ${r.status}`);
  return r.json();
}).catch((err) => {
  if (!retry) throw err;
  return new Promise((ok) => setTimeout(ok, 400)).then(() => getJSON(url, init, retry - 1));
});
const meters = (a, b) => Math.hypot((b[0] - a[0]) * Math.cos(a[1] * Math.PI / 180) * 111320, (b[1] - a[1]) * 110574);
const bearingOf = (a, b) => Math.atan2((b[0] - a[0]) * Math.cos(a[1] * Math.PI / 180), b[1] - a[1]) * 180 / Math.PI;
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
// 마지막 글자 받침(0=없음, 8=ㄹ): 「건강관리과로」 · 「청년정책담당관으로」, 「건강관리과가」 · 「청년정책담당관이」
const jong = (w) => { const c = w.charCodeAt(w.length - 1) - 0xac00; return c >= 0 && c < 11172 ? c % 28 : 0; };
const ro = (w) => (jong(w) && jong(w) !== 8 ? '으로' : '로');
const iga = (w) => (jong(w) ? '이' : '가');
const hhmm = (sec) => `19:${String(Math.floor(sec / 60)).padStart(2, '0')}`;
const verdictOf = (v) => { const i = v.indexOf(' · '); return i < 0 ? [v, ''] : [v.slice(0, i), v.slice(i + 3)]; };
const badgeCls = (b) => (b === '예' ? 'yes' : b === '확인 필요' ? 'check' : 'other');

// ---- 바탕 스타일을 낮 「클레이」 색으로 바꾸고 우리 레이어를 끼워 넣는다
function buildStyle(style, tj, D) {
  style.sources.openmaptiles = { type: 'vector', tiles: tj.tiles, minzoom: tj.minzoom ?? 0, maxzoom: tj.maxzoom ?? 14, attribution: ATTR };
  style.transition = { duration: 1600, delay: 0 };   // 낮 ↔ 밤 색 바꿈을 부드럽게
  // POI·잡다한 이름·터널, 원래 다리 도로선(bridge_*)은 숨긴다
  const hide = /^(poi_|highway-|road_shield|road_one_way|airport|label_country|label_state|tunnel_|bridge_|landuse_residential|natural_earth)/;
  style.layers = style.layers.filter((l) => !hide.test(l.id));
  for (const l of style.layers) {
    const p = (l.paint ??= {});
    const id = l.id;
    if (l.type === 'symbol') {
      if (l.layout?.['text-field']) l.layout['text-field'] = KO;
      Object.assign(p, { 'text-color': C.text, 'text-halo-color': '#ffffff', 'text-halo-width': 1.5 });
    } else if (id === 'background') p['background-color'] = C.land;
    else if (id === 'water') p['fill-color'] = C.water;
    else if (id.startsWith('waterway')) p['line-color'] = C.water;
    else if (['park', 'landcover_wood', 'landcover_grass', 'landcover_wetland', 'landuse_cemetery'].includes(id)) {
      Object.assign(p, { 'fill-color': C.green, 'fill-opacity': id === 'landcover_wood' ? 0.85 : 1 });
    } else if (id === 'park_outline') p['line-color'] = '#bccdb1';
    else if (id === 'landuse_pitch' || id === 'landuse_track') p['fill-color'] = '#d3dfca';
    else if (id.startsWith('landuse_') || id === 'landcover_ice' || id === 'landcover_sand') p['fill-color'] = '#dfe0db';
    else if (id === 'aeroway_fill') p['fill-color'] = '#dcdedb';
    else if (id.startsWith('aeroway_')) p['line-color'] = '#f2f2f0';
    else if (id === 'building') p['fill-color'] = '#dcdedb';
    else if (id === 'building-3d') {
      // OpenFreeMap z13 타일의 건물은 높이 없는 덩어리뿐이라 13에서는 세울 수 없다.
      // 대신 z14에서 납작하게(0m, 2D 건물과 이어짐) 시작해 14.2까지 제 높이로 자라게 한다.
      const grow = (key) => ['interpolate', ['linear'], ['zoom'], 14, 0, 14.2, ['coalesce', ['get', key], 0]];
      Object.assign(p, {
        'fill-extrusion-color': C.building,
        'fill-extrusion-height': grow('render_height'),
        'fill-extrusion-base': grow('render_min_height'),
        'fill-extrusion-opacity': 1,
        'fill-extrusion-vertical-gradient': true,
      });
    } else if (l.type === 'line' && id.startsWith('road_')) {
      p['line-color'] = id.includes('rail') ? C.rail : id.includes('casing') ? C.casing : C.road;
    }
  }
  style.light = LIGHT.day;

  for (const f of ['bridges', 'piers', 'bridge_labels', 'parks', 'park_labels', 'ring10', 'complaints']) {
    style.sources[f] = { type: 'geojson', data: D[f] };
  }
  const at = (id) => style.layers.findIndex((l) => l.id === id);
  const put = (i, ...ls) => style.layers.splice(i, 0, ...ls);
  const isPoly = ['==', ['geometry-type'], 'Polygon'];

  put(style.layers.findIndex((l) => l.id.startsWith('road_')),
    { id: 'hg-parks', type: 'fill', source: 'parks', paint: { 'fill-color': C.park, 'fill-opacity': 0.55 } },
    { id: 'hg-parks-line', type: 'line', source: 'parks', paint: { 'line-color': C.parkLine, 'line-width': 1.2 } });

  // 우리 다리 판 밑이 아닌 다리 도로선(고가·하천 다리 등)은 다시 그린다
  const cls = ['get', 'class'];
  const w = ['match', cls, ['motorway', 'trunk'], 1.2, 'primary', 1, ['secondary', 'tertiary'], 0.8, ['rail', 'transit'], 0.35, 0.55];
  const width = (pad) => ['interpolate', ['exponential', 1.5], ['zoom'], 12, ['+', ['*', w, 1.6], pad], 18, ['+', ['*', w, 24], pad * 3]];
  const otherBridge = ['all', ['in', ['geometry-type'], ['literal', ['LineString', 'MultiLineString']]],
    ['==', ['get', 'brunnel'], 'bridge'], ['!', ['within', D.bridge_mask]]];
  const line = { type: 'line', source: 'openmaptiles', 'source-layer': 'transportation', minzoom: 12, layout: { 'line-join': 'round' } };
  put(at('building'),
    { ...line, id: 'hg-bridge-road-casing', filter: ['all', otherBridge, ['!', IS_RAIL]], paint: { 'line-color': C.casing, 'line-width': width(1.5) } },
    { ...line, id: 'hg-bridge-road', filter: otherBridge, paint: { 'line-color': ['case', IS_RAIL, C.rail, C.road], 'line-width': width(0) } },
    { id: 'hg-ring10-fill', type: 'fill', source: 'ring10', filter: isPoly, paint: { 'fill-color': C.pin, 'fill-opacity': 0.3 } },
    { id: 'hg-ring10-line', type: 'line', source: 'ring10', filter: isPoly, paint: { 'line-color': C.pin, 'line-width': 1.5 } });

  const ext = (id, source, color) => ({
    id, source, type: 'fill-extrusion',
    paint: { 'fill-extrusion-color': color, 'fill-extrusion-base': ['get', 'base'], 'fill-extrusion-height': ['get', 'top'] },
  });
  put(at('building-3d') + 1, ext('hg-piers', 'piers', C.pier), ext('hg-bridges', 'bridges', C.deck));

  // 들어온 일 점: 3D 건물 위에 그려 가리지 않는다. 동그라미 색 = 담당 부서, 가까이서는 안에 번호(들어온 순서)
  put(at('hg-bridges') + 1,
    { id: 'hg-cp-sel', type: 'circle', source: 'complaints', filter: ['==', ['get', 'id'], -1],
      paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 10, 9, 12.9, 10, 13, 12.5, 15, 14.5, 17, 16.5], 'circle-color': 'rgba(0,0,0,0)', 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 3 } },
    { id: 'hg-cp-dot', type: 'circle', source: 'complaints',
      paint: {
        'circle-color': ['get', 'color'], 'circle-radius': ['interpolate', ['linear'], ['zoom'], 10, 4, 12.9, 5.5, 13, 8, 15, 10, 17, 12],
        'circle-stroke-color': '#0C1421', 'circle-stroke-width': ['interpolate', ['linear'], ['zoom'], 10, 1, 14, 1.6],
      } });

  const halo = { 'text-halo-color': '#ffffff', 'text-halo-width': 1.6 };
  style.layers.push(
    { id: 'hg-park-labels', type: 'symbol', source: 'park_labels', minzoom: 11.5,
      layout: { 'text-field': ['get', 'name'], 'text-font': ['Noto Sans Bold'], 'text-size': ['interpolate', ['linear'], ['zoom'], 12, 11, 16, 14] },
      paint: { 'text-color': '#3f7d3a', ...halo } },
    { id: 'hg-bridge-labels', type: 'symbol', source: 'bridge_labels', minzoom: 12,
      layout: {
        'text-field': ['get', 'name'], 'text-font': ['Noto Sans Bold'], 'text-size': 12,
        'icon-image': 'chip', 'icon-text-fit': 'both', 'icon-text-fit-padding': [3, 7, 3, 7],
        'text-variable-anchor': ['center', 'top', 'bottom'], 'text-radial-offset': 0.9,
      },
      paint: { 'text-color': C.text } },
    { id: 'hg-ring10-label', type: 'symbol', source: 'ring10', minzoom: 16, filter: ['==', ['geometry-type'], 'Point'],
      layout: { 'text-field': ['get', 'label'], 'text-font': ['Noto Sans Bold'], 'text-size': 12, 'text-anchor': 'top-left', 'text-offset': [1.1, 0.9], 'text-allow-overlap': true },   // 번호 동그라미를 가리지 않게
      paint: { 'text-color': '#16804a', ...halo } },
    { id: 'hg-cp-num', type: 'symbol', source: 'complaints', minzoom: 13,
      layout: {
        'text-field': ['to-string', ['get', 'no']], 'text-font': ['Noto Sans Bold'],
        'text-size': ['interpolate', ['linear'], ['zoom'], 13, 9.5, 15, 11.5, 17, 13],
        'text-allow-overlap': true, 'text-ignore-placement': true, 'symbol-sort-key': ['get', 'no'],
      },
      paint: { 'text-color': '#0C1421' } },
    // 고른 일의 장소 이름표(번호 동그라미 위)
    { id: 'hg-cp-label', type: 'symbol', source: 'complaints', filter: ['==', ['get', 'id'], -1],
      layout: {
        'text-field': ['get', 'place'], 'text-font': ['Noto Sans Bold'], 'text-size': 12.5,
        'text-anchor': 'bottom', 'text-offset': [0, -1.5], 'text-allow-overlap': true, 'text-ignore-placement': true,
        'icon-image': 'chip', 'icon-text-fit': 'both', 'icon-text-fit-padding': [3, 7, 3, 7],
      },
      paint: { 'text-color': C.text } });
  return style;
}

// 밤에 바꿀 paint 값(레이어 종류·이름으로 고른다). 없는 레이어는 그대로 둔다.
function nightPaint({ id, type }) {
  if (type === 'symbol') {
    if (id === 'hg-cp-label' || id === 'hg-cp-num') return null;
    if (id === 'hg-park-labels') return { 'text-color': '#7fe0a8', 'text-halo-color': N.halo };
    if (id === 'hg-bridge-labels') return { 'text-color': '#eef3fb', 'text-halo-color': N.halo, 'text-halo-width': 1.4, 'icon-opacity': 0.14 };
    if (id === 'hg-ring10-label') return { 'text-color': '#7ef0b0', 'text-halo-color': N.halo };
    if (id.startsWith('water')) return { 'text-color': '#79a3dd', 'text-halo-color': N.halo };
    return { 'text-color': N.text, 'text-halo-color': N.halo };
  }
  if (id === 'background') return { 'background-color': N.land };
  if (id === 'water') return { 'fill-color': N.water };
  if (id.startsWith('waterway')) return { 'line-color': N.water };
  if (['park', 'landcover_wood', 'landcover_grass', 'landuse_cemetery'].includes(id)) return { 'fill-color': N.green };
  if (id === 'landcover_wetland' || id === 'road_area_pattern') return { 'fill-opacity': 0.12 };
  if (id === 'park_outline') return { 'line-color': '#1c3a33' };
  if (type === 'fill' && (id.startsWith('landuse_') || id.startsWith('landcover_') || id === 'aeroway_fill')) return { 'fill-color': N.landuse };
  if (id.startsWith('aeroway_')) return { 'line-color': '#1a2436' };
  if (id === 'building') return { 'fill-color': N.building };
  if (id === 'building-3d') return { 'fill-extrusion-color': N.building3d };
  if (id === 'hg-parks') return { 'fill-color': N.park };
  if (id === 'hg-parks-line') return { 'line-color': N.parkLine };
  if (id === 'hg-piers') return { 'fill-extrusion-color': N.pier };
  if (id === 'hg-bridges') return { 'fill-extrusion-color': N.deck };
  if (id === 'hg-bridge-road-casing') return { 'line-color': N.casing, 'line-blur': 2 };
  if (id === 'hg-bridge-road') return { 'line-color': ['case', IS_RAIL, N.rail, N.road] };
  if (type === 'line' && id.startsWith('road_')) {
    if (id.includes('rail')) return { 'line-color': N.rail };
    const big = /motorway|trunk|link/.test(id), mid = id.includes('secondary');
    if (id.includes('casing')) return big || mid ? { 'line-color': N.casing, 'line-blur': 3 } : { 'line-color': N.casingMinor };
    return { 'line-color': big ? N.road : mid ? N.road2 : N.roadMinor };   // 큰길은 가로등 빛
  }
  if (id.startsWith('boundary')) return { 'line-color': '#334059' };
  return null;
}

// 다리 이름표 칩(흰 둥근 사각형, 글자 길이에 맞춰 늘어남)
function chipImage() {
  const r = 2, w = 32, h = 24;
  const c = document.createElement('canvas');
  c.width = w * r; c.height = h * r;
  const g = c.getContext('2d');
  g.scale(r, r);
  g.fillStyle = '#ffffff'; g.strokeStyle = '#c3c9cf'; g.lineWidth = 1;
  g.beginPath(); g.roundRect(0.5, 0.5, w - 1, h - 1, 6); g.fill(); g.stroke();
  return [g.getImageData(0, 0, w * r, h * r),
    { pixelRatio: r, stretchX: [[8 * r, 24 * r]], stretchY: [[8 * r, 16 * r]], content: [6 * r, 4 * r, 26 * r, 20 * r] }];
}

// 밤 건물 창문 불빛(fill-extrusion-pattern). 밤 건물 색 바탕에 노랑·파랑 창을 흩뿌린다
function windowsImage() {
  const r = 2, n = 32;
  const c = document.createElement('canvas');
  c.width = c.height = n * r;
  const g = c.getContext('2d');
  g.scale(r, r);
  g.fillStyle = N.building3d;
  g.fillRect(0, 0, n, n);
  let seed = 7;
  const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;   // 늘 같은 무늬
  for (let y = 2; y < n; y += 5) for (let x = 2; x < n; x += 4) {
    const v = rnd();
    g.fillStyle = v < 0.28 ? '#ffd27a' : v < 0.4 ? '#9fb7ff' : '#26385a';
    g.fillRect(x, y, 2, 3);
  }
  return [g.getImageData(0, 0, n * r, n * r), { pixelRatio: r }];
}

// 강 중심선: 다리 이름표 점(경도순, 400m 안쪽 점은 건너뜀) → Catmull-Rom → 누적 거리
function riverPath(features) {
  const pts = [];
  for (const f of features) {
    const p = f.geometry.coordinates;
    if (!pts.length || meters(pts.at(-1), p) > 400) pts.push(p);
  }
  const dense = [];
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[Math.max(0, i - 1)], p1 = pts[i], p2 = pts[i + 1], p3 = pts[Math.min(pts.length - 1, i + 2)];
    for (let k = 0; k < 20; k++) {
      const t = k / 20, t2 = t * t, t3 = t2 * t;
      dense.push([0, 1].map((j) => 0.5 * (2 * p1[j] + (p2[j] - p0[j]) * t
        + (2 * p0[j] - 5 * p1[j] + 4 * p2[j] - p3[j]) * t2 + (3 * p1[j] - p0[j] - 3 * p2[j] + p3[j]) * t3)));
    }
  }
  dense.push(pts.at(-1));
  const dist = [0];
  for (let i = 1; i < dense.length; i++) dist.push(dist[i - 1] + meters(dense[i - 1], dense[i]));
  const pointAt = (d) => {
    let lo = 0, hi = dist.length - 1;
    while (hi - lo > 1) { const m = (lo + hi) >> 1; if (dist[m] <= d) lo = m; else hi = m; }
    const t = Math.min(1, Math.max(0, (d - dist[lo]) / (dist[hi] - dist[lo] || 1)));
    return [dense[lo][0] + (dense[hi][0] - dense[lo][0]) * t, dense[lo][1] + (dense[hi][1] - dense[lo][1]) * t];
  };
  return { total: dist.at(-1), pointAt };
}

// 강을 따라 z13·z14 타일을 미리 받아 브라우저 캐시를 데워 둔다
function prefetch(template, path) {
  const want = new Set();
  for (let d = 0; d <= path.total; d += 400) {
    const [lon, lat] = path.pointAt(d);
    for (const z of [13, 14]) {
      const n = 2 ** z, r = z === 14 ? 1 : 0;
      const x = Math.floor((lon + 180) / 360 * n);
      const y = Math.floor((1 - Math.asinh(Math.tan(lat * Math.PI / 180)) / Math.PI) / 2 * n);
      for (let i = -r; i <= r; i++) for (let j = -r; j <= r; j++) {
        want.add(template.replace('{z}', z).replace('{x}', x + i).replace('{y}', y + j));
      }
    }
  }
  const urls = [...want];
  const worker = async () => { for (let u; (u = urls.pop());) await fetch(u).then((r) => r.arrayBuffer()).catch(() => {}); };
  for (let k = 0; k < 3; k++) worker();
  return want.size;
}

async function main() {
  const [style, ...data] = await Promise.all([getJSON(STYLE_URL), ...FILES.map((f) => getJSON(`data/${f}.geojson`))]);
  const D = Object.fromEntries(FILES.map((f, i) => [f, data[i]]));
  const tj = await getJSON(style.sources.openmaptiles.url);
  // 들어온 일(가상 예시). 못 불러와도 지도는 뜬다
  const CP = await getJSON('data/complaints.json', { cache: 'no-cache' }).catch((err) => { console.warn(err); return null; });
  const types = CP ? CP.types : [];
  const typeOf = Object.fromEntries(types.map((t) => [t.key, t]));
  const items = (CP ? CP.items : [])
    .map((it) => ({ ...it, T: CP.templates[it.tpl], type: typeOf[CP.templates[it.tpl].type] }))
    .sort((a, b) => a.sec - b.sec || a.id - b.id);
  const byId = new Map(items.map((it) => [it.id, it]));
  D.complaints = { type: 'FeatureCollection', features: items.map((it) => ({
    type: 'Feature', geometry: { type: 'Point', coordinates: [it.lng, it.lat] },
    properties: { id: it.id, no: it.no, place: it.place, color: TYPE_COLOR[it.type.key] || '#ffffff' },
  })) };

  const map = new maplibregl.Map({
    // maxPitch 60(기본값): 5.6.0은 60보다 기울인 채 줌 14 아래로 날면 _updateRetainedTiles 오류가 난다(직접 재현)
    container: 'map', style: buildStyle(style, tj, D), hash: true, ...DEMO, maxPitch: 60,
    localIdeographFontFamily: 'Pretendard, Apple SD Gothic Neo, sans-serif',
    attributionControl: false, maxTileCacheSize: 2000, maxTileCacheZoomLevels: 8, fadeDuration: 150,
    refreshExpiredTiles: false, cancelPendingTileRequestsWhileZooming: false,
    canvasContextAttributes: { antialias: true },
  });
  window.hangangMap = map;   // 콘솔 점검용
  map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right');
  map.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-right');
  map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: '핀은 시연용 가상 예시' }), 'bottom-right');
  map.on('styleimagemissing', (e) => {
    if (e.id === 'chip' && !map.hasImage('chip')) map.addImage('chip', ...chipImage());
    if (e.id === 'windows' && !map.hasImage('windows')) map.addImage('windows', ...windowsImage());
  });

  const labels = D.bridge_labels.features;   // 경도순(서→동)
  const path = riverPath(labels);
  const flyBtn = document.getElementById('btn-fly');
  let flight = null;

  const stopFlight = () => {
    if (!flight) return;
    cancelAnimationFrame(flight.raf);
    flight = null;
    flyBtn.textContent = '한강 따라 날기 ▶';
    flyBtn.classList.remove('on');
  };
  const startFlight = () => {
    flight = { raf: 0 };
    flyBtn.textContent = '한강 따라 날기 ■';
    flyBtn.classList.add('on');
    const speed = path.total / FLY.seconds;
    let brg = (bearingOf(path.pointAt(0), path.pointAt(FLY.lookAhead)) + 360) % 360;
    map.once('moveend', () => {
      if (!flight) return;
      let t0 = 0, last = 0;
      const step = (ts) => {
        if (!flight) return;
        if (!t0) t0 = last = ts;
        const d = (ts - t0) / 1000 * speed;
        if (d >= path.total) {
          stopFlight();
          map.flyTo({ ...DEMO, duration: 3500, essential: true });
          return;
        }
        const p = path.pointAt(d), ahead = path.pointAt(Math.min(path.total, d + FLY.lookAhead));
        if (meters(p, ahead) > 100) {
          const diff = ((bearingOf(p, ahead) - brg + 540) % 360) - 180;
          brg = (brg + diff * (1 - Math.exp(-(ts - last) / 900)) + 360) % 360;
        }
        last = ts;
        map.jumpTo({ center: p, bearing: brg, zoom: FLY.zoom, pitch: FLY.pitch });
        flight.raf = requestAnimationFrame(step);
      };
      flight.raf = requestAnimationFrame(step);
    });
    map.flyTo({ center: path.pointAt(0), zoom: FLY.zoom, pitch: FLY.pitch, bearing: brg, duration: 3000, essential: true });
  };
  // 날던 중 사용자가 지도를 만지면 멈춘다
  for (const ev of ['pointerdown', 'wheel']) map.getCanvasContainer().addEventListener(ev, stopFlight, { passive: true });

  flyBtn.onclick = () => (flight ? stopFlight() : startFlight());
  document.getElementById('btn-demo').onclick = () => { stopFlight(); map.flyTo({ ...DEMO, duration: 2600, essential: true }); };
  document.getElementById('btn-all').onclick = () => {
    stopFlight();
    const b = new maplibregl.LngLatBounds();
    for (const f of labels) b.extend(f.geometry.coordinates);
    map.fitBounds(b, { padding: { top: 60, bottom: 50, left: 370, right: 50 }, pitch: 45, bearing: 0, duration: 2600, essential: true });   // 왼쪽 목록에 안 가리게
  };

  const sel = document.getElementById('sel-bridge');
  labels.forEach((f, i) => sel.add(new Option(f.properties.name, i)));
  sel.onchange = () => {
    const f = labels[sel.value];
    if (!f) return;
    stopFlight();
    map.flyTo({ center: f.geometry.coordinates, zoom: 15.8, pitch: 60, bearing: map.getBearing(), duration: 2600, essential: true });
  };

  // ---- 들어온 일: 지도 핀 · 목록 · 판정 카드 (낮·밤 공용)
  const $ = (id) => document.getElementById(id);
  const card = $('card'), phone = $('phone');
  const filter = { type: '', status: '', group: false, timer: 0 };   // 부서 · 해결 여부 · 부서별로 모아 보기
  const board = { arrived: [], approved: new Map(), note: '' };   // 밤: 들어온 일, 해결한 일(id → 승인 시각)
  const play = { t: 0, idx: 0, aidx: 0, on: false, started: false, raf: 0, last: 0 };
  const scene = { on: false, back: null, moved: false, timers: [] };
  let picked = null;
  const one = items.find((it) => it.n === 1);   // 19:02 시민 신고(1번)
  // 해결 = 맡은 부서가 안내를 승인해 현장에 보낸 일. 낮 지도는 19:30 끝 장면, 밤은 재생 시각까지
  const dayDone = new Map(items.filter((it) => it.done != null).map((it) => [it.id, hhmm(it.done)]));
  const autos = items.filter((it) => it.done != null).sort((a, b) => a.done - b.done);
  const doneMap = () => (scene.on ? board.approved : dayDone);
  const passes = (it) => (!filter.type || it.type.key === filter.type)
    && (!filter.status || (filter.status === 'done') === doneMap().has(it.id));

  for (const id of ['hg-cp-dot', 'hg-cp-num']) {
    map.on('click', id, (e) => pick(byId.get(e.features[0].properties.id)));
    map.on('mouseenter', id, () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', id, () => { map.getCanvas().style.cursor = ''; });
  }

  const stat = (pool) => {
    const done = pool.filter((it) => doneMap().has(it.id)).length;
    return { n: pool.length, done, open: pool.length - done };
  };
  const numHTML = (it) => `<b class="num" style="--c:${TYPE_COLOR[it.type.key]}">${it.no}</b>`;
  const rowHTML = (it, cls = '') => {
    const [b, d] = verdictOf(it.T.verdict), done = doneMap().get(it.id);
    return `<li class="${cls}"><button type="button" class="row${picked === it ? ' on' : ''}${done ? ' done' : ''}" data-id="${it.id}">${numHTML(it)}`
      + `<span class="when">${it.time} · ${esc(it.src)}</span><span class="text">「${esc(it.text)}」</span>`
      + `<span class="verdict"><b class="badge ${badgeCls(b)}">${esc(b)}</b>${esc(d)}</span>`
      + `<span class="dept">${esc(it.type.dept)}</span><span class="state">${done ? `해결 · ${done}` : '미해결'}</span>`
      + '<span class="open">근거 보기</span></button></li>';
  };
  const emptyHTML = (text) => `<li class="empty">${esc(text)}</li>`;
  // 칩: 낮은 「● 건강관리과 22」, 밤은 「건강관리과 / 금연 · 22건 · 미해결 16」
  const chipsHTML = (pool, night) => {
    const chip = (key, top, bottom, color) => `<button type="button" class="chip${filter.type === key ? ' on' : ''}" data-type="${key}" aria-pressed="${filter.type === key}">`
      + `${color ? `<i class="tdot" style="--c:${color}"></i>` : ''}<b>${top}</b><span>${bottom}</span></button>`;
    const all = stat(pool);
    return chip('', '전체', `${all.n}건${night ? ` · 미해결 ${all.open}` : ''}`) + types.map((t) => {
      const k = stat(pool.filter((it) => it.type.key === t.key));
      return chip(t.key, esc(t.dept), night ? `${esc(t.key)} · ${k.n}건 · 미해결 ${k.open}` : `${k.n}`, TYPE_COLOR[t.key]);
    }).join('');
  };
  const groupHTML = (t, pool) => {
    const k = stat(pool);
    return `<li class="group"><i class="tdot" style="--c:${TYPE_COLOR[t.key]}"></i><b>${esc(t.dept)}</b>`
      + `<span>${esc(t.key)} · ${k.n}건 · 미해결 ${k.open} · 해결 ${k.done}</span></li>`;
  };
  // 목록: 낮은 번호 순, 밤은 새로 들어온 일이 위. 「부서별로 모아 보기」면 부서마다 묶는다
  function listHTML(pool, newest, fresh) {
    const rows = (a) => (newest ? a.slice().reverse() : a).filter(passes).map((it) => rowHTML(it, fresh?.has(it) ? 'in' : '')).join('');
    if (!filter.group) return rows(pool);
    return types.filter((t) => !filter.type || t.key === filter.type).map((t) => {
      const p = pool.filter((it) => it.type.key === t.key);
      return p.length ? groupHTML(t, p) + rows(p) : '';
    }).join('');
  }
  const emptyText = () => board.note || { done: SAY.doneEmpty, open: SAY.openEmpty }[filter.status] || '';
  function renderRows(fresh) {
    $('day-rows').innerHTML = CP ? listHTML(items, false) || emptyHTML(emptyText() || SAY.empty) : emptyHTML(SAY.failed);
    $('b-rows').innerHTML = listHTML(board.arrived, true, fresh)
      || emptyHTML(emptyText() || (play.started ? SAY.empty : SAY.loading));
  }
  function renderSegs() {
    for (const b of document.querySelectorAll('.seg button')) {
      const on = b.dataset.v === (b.parentElement.dataset.k === 'group' ? (filter.group ? '1' : '') : filter.status);
      b.classList.toggle('on', on);
      b.setAttribute('aria-pressed', on);
    }
  }
  function renderAll(fresh) {
    $('day-n').textContent = items.length;
    $('day-chips').innerHTML = chipsHTML(items, false);
    $('b-chips').innerHTML = chipsHTML(board.arrived, true);
    renderSegs();
    renderRows(fresh);
    applyPins();
  }
  // 지도: 밤에는 이미 들어온 일만, 부서 · 해결 여부를 고르면 그 일만. 해결한 일은 흐리게
  function applyPins() {
    if (!map.getLayer('hg-cp-dot')) return;
    const shown = (scene.on ? board.arrived : items).filter(passes).map((it) => it.id);
    const f = ['in', ['get', 'id'], ['literal', shown]], done = ['in', ['get', 'id'], ['literal', [...doneMap().keys()]]];
    map.setFilter('hg-cp-dot', f);
    map.setFilter('hg-cp-num', f);
    map.setPaintProperty('hg-cp-dot', 'circle-opacity', ['case', done, 0.45, 1]);
    map.setPaintProperty('hg-cp-dot', 'circle-stroke-opacity', ['case', done, 0.45, 1]);
    map.setPaintProperty('hg-cp-num', 'text-opacity', ['case', done, 0.6, 1]);
    const ring = one && shown.includes(one.id) ? 'visible' : 'none';
    for (const id of ['hg-ring10-fill', 'hg-ring10-line', 'hg-ring10-label']) map.setLayoutProperty(id, 'visibility', ring);
  }
  function setType(key) {
    clearTimeout(filter.timer);
    board.note = '';
    filter.type = key && filter.type !== key ? key : '';   // 고른 칩을 다시 누르면 전체
    if (filter.type && !(scene.on ? board.arrived : items).some((it) => it.type.key === filter.type)) {
      board.note = SAY.deptEmpty;
      filter.timer = setTimeout(() => { filter.type = ''; board.note = ''; renderAll(); }, 1800);
    }
    renderAll();
    toTop();
  }
  // 거르기 · 보기를 바꾸면 목록을 맨 위부터 보이고, 고른 일은 보이게 둔다
  function toTop() {
    for (const id of ['day-rows', 'b-rows']) $(id).scrollTop = 0;
    if (picked) select(picked);
  }
  for (const id of ['day-chips', 'b-chips']) {
    $(id).onclick = (e) => { const b = e.target.closest('.chip'); if (b) setType(b.dataset.type); };
  }
  for (const id of ['day-rows', 'b-rows']) {
    $(id).onclick = (e) => { const b = e.target.closest('.row'); if (b) pick(byId.get(+b.dataset.id)); };
  }
  // 목록 보기(들어온 순서 · 부서별로 모아 보기)와 해결 여부(전체 · 미해결 · 해결)
  document.addEventListener('click', (e) => {
    const b = e.target.closest('.seg button');
    if (!b) return;
    if (b.parentElement.dataset.k === 'group') filter.group = !!b.dataset.v;
    else filter.status = b.dataset.v;
    renderAll();
    toTop();
  });

  function select(it) {
    picked = it;
    if (map.getLayer('hg-cp-sel')) for (const id of ['hg-cp-sel', 'hg-cp-label']) map.setFilter(id, ['==', ['get', 'id'], it ? it.id : -1]);
    for (const b of document.querySelectorAll('.row.on')) b.classList.remove('on');
    if (it) for (const b of document.querySelectorAll(`.row[data-id="${it.id}"]`)) { b.classList.add('on'); b.scrollIntoView({ block: 'nearest' }); }
  }
  // 판정 카드: content A-01 「판정 카드」 표 순서(안내 초안을 맨 위)
  function openCard(it) {
    select(it);
    const T = it.T, [b, d] = verdictOf(T.verdict), q = T.basis.indexOf('「');
    const done = doneMap().has(it.id);
    card.innerHTML = '<button class="x" type="button" aria-label="카드 닫기">×</button>'
      + `<p class="eyebrow">${numHTML(it)}${it.time} · ${esc(it.src)} · ${esc(it.place)}</p><h2>${esc(T.title)}</h2>`
      + `<div class="draft"><small>안내 초안</small><p>${esc(T.draft)}</p></div><dl>`
      + `<dt>판정</dt><dd><b class="badge ${badgeCls(b)}">${esc(b)}</b> ${esc(d)}</dd>`
      + `<dt>근거</dt><dd>${q < 0 ? esc(T.basis) : `${esc(T.basis.slice(0, q).trim())}<span class="quote">${esc(T.basis.slice(q))}</span>`}</dd>`
      + `<dt>시행일</dt><dd>${esc(T.effective)}</dd><dt>${esc(T.extra_label)}</dt><dd>${esc(T.extra)}</dd>`
      + `<dt>맡은 부서</dt><dd><span class="dept">${esc(it.type.dept)}</span> ${esc(it.type.phone)}</dd>`
      + (it.citizen ? `<dt>신고한 시민</dt><dd>${esc(it.citizen)}</dd>` : '')
      + `</dl><footer><button type="button" class="approve"${done ? ' disabled' : ''}>✓ 안내 승인</button>`
      + `<a class="law" href="${esc(T.law)}" target="_blank" rel="noopener">조례 원문 보기</a>`
      + `<button type="button" class="close">카드 닫기</button><output class="said">${done ? SAY.approved : ''}</output></footer>`;
    card.hidden = false;
    card.scrollTop = 0;
  }
  function closeCard() {
    card.hidden = true;
    select(null);
    if (scene.on && scene.moved) {   // 카드 때문에 멀리 갔으면 불꽃이 보이는 자리로 돌아온다
      scene.moved = false;
      map.flyTo({ ...sceneCamera(), duration: 2000, essential: true });
    }
  }
  card.onclick = (e) => {
    if (e.target.closest('.approve')) approve(picked);
    else if (e.target.closest('.close, .x')) closeCard();
  };
  // 핀·목록에서 일을 고르면: 낮에는 그 핀으로 날아가고, 밤에는 화면 밖일 때만 옮긴다
  function pick(it) {
    if (!it) return;
    if (!scene.on) {
      stopFlight();
      map.flyTo({ center: [it.lng, it.lat], zoom: Math.max(map.getZoom(), 16.4), pitch: 55, bearing: map.getBearing(), duration: 2200, essential: true });
    } else if (!inView(it)) {
      scene.moved = true;
      map.flyTo({ ...sceneCamera(), center: [it.lng, it.lat], duration: 2200, essential: true });
    }
    openCard(it);
  }

  // ---- 예시: 불꽃축제 날 밤 상황판
  // 불꽃 canvas는 지도 그림 바로 위·핀(HTML 마커) 아래에 끼운다
  map.getCanvasContainer().insertBefore($('fx'), map.getCanvas().nextSibling);
  const fx = createFireworks(map, $('fx'), BARGES);
  const later = (fn, ms) => scene.timers.push(setTimeout(fn, ms));
  let swap = null, phoneTimer = 0;

  // 낮 ↔ 밤 색. 바꿀 paint 값의 낮 값은 처음 한 번 읽어 두고 그대로 되돌린다(style.transition으로 1.6초)
  function setNight(on) {
    if (!swap?.length) {   // 스타일이 다 뜨기 전에 눌렀으면 다음에 다시 모은다
      swap = [];
      const ids = map.getLayersOrder ? map.getLayersOrder() : map.getStyle().layers.map((l) => l.id);
      for (const id of ids) {
        const night = nightPaint(map.getLayer(id));
        if (night) for (const [k, v] of Object.entries(night)) swap.push([id, k, map.getPaintProperty(id, k), v]);
      }
    }
    for (const [id, k, day, night] of swap) map.setPaintProperty(id, k, on ? night : day);
    map.setLight(on ? LIGHT.night : LIGHT.day);
    // 창문 불빛은 색이 다 어두워진 뒤 켠다(무늬는 부드럽게 바뀌지 않아서). 낮으로 갈 때는 바로 끈다
    if (on) later(() => map.setPaintProperty('building-3d', 'fill-extrusion-pattern', 'windows'), 1700);
    else map.setPaintProperty('building-3d', 'fill-extrusion-pattern', undefined);
  }
  // 패널 몫을 비운 가운데 빈 곳(패널은 transform 없는 layout 크기로 잰다). 위는 장소 이름표 아래부터
  function padding() {
    const place = document.querySelector('.b-place'), side = document.querySelector('.b-side');
    const list = document.querySelector('.b-list'), slot = $('card-slot');
    return {
      top: place.offsetTop + place.offsetHeight + 8, bottom: innerHeight - list.offsetTop,
      left: side.offsetLeft + side.offsetWidth, right: innerWidth - slot.offsetLeft,
    };
  }
  function sceneCamera() {
    const rem = parseFloat(getComputedStyle(document.documentElement).fontSize);
    return { ...SCENE, zoom: SCENE.zoom + Math.log2(rem / (1600 / 120)), padding: padding() };
  }
  function inView(it) {
    const p = map.project([it.lng, it.lat]), pad = padding();
    return p.x > pad.left && p.x < innerWidth - pad.right && p.y > pad.top && p.y < innerHeight - pad.bottom;
  }

  const bump = (id, text) => {
    const el = $(id);
    if (el.textContent === text) return;
    el.textContent = text;
    el.classList.remove('bump');
    void el.offsetWidth;
    el.classList.add('bump');
  };
  function renderKpi() {
    const s = stat(board.arrived);
    bump('k-n', `${s.n}건`);
    bump('k-open', `${s.open}건`);
    bump('k-done', `${s.done}건`);
  }
  function renderClock() {
    $('b-clock').textContent = hhmm(play.t);
    $('b-bar').style.width = `${(play.t / WINDOW) * 100}%`;
  }
  let toastTimer = 0;
  function toast(text) {
    const el = $('b-toast');
    el.textContent = text;
    el.classList.add('on');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove('on'), 2400);
  }
  // 일이 들어온 자리에 유형 색 고리가 퍼진다
  function pulse(it) {
    const el = document.createElement('div');
    el.className = 'pulse';
    el.style.setProperty('--c', TYPE_COLOR[it.type.key]);
    el.innerHTML = '<i></i><i></i>';
    const m = new maplibregl.Marker({ element: el }).setLngLat([it.lng, it.lat]).addTo(map);
    setTimeout(() => m.remove(), 1700);
  }

  function resetBoard() {
    play.t = 0; play.idx = 0; play.aidx = 0;
    board.arrived = []; board.approved.clear(); board.note = '';
    clearTimeout(phoneTimer);
    phone.className = 'phone';
    $('u-send').textContent = '보내기';
    $('b-approved').innerHTML = '';
    card.hidden = true;
    select(null);
    renderAll(); renderKpi(); renderClock();
  }
  // 재생 시각 t(19:00부터 초)까지 들어온 일과, 그사이 부서가 승인(해결)한 일을 상황판에 올린다
  function advance(t, animate) {
    play.t = Math.min(WINDOW, t);
    const fresh = [];
    while (play.idx < items.length && items[play.idx].sec <= play.t) fresh.push(items[play.idx++]);
    board.arrived.push(...fresh);
    let solved = 0;
    for (; play.aidx < autos.length && autos[play.aidx].done <= play.t; play.aidx++) {
      const it = autos[play.aidx];
      if (!board.approved.has(it.id)) { addApproved(it, hhmm(it.done)); solved++; }
    }
    if (fresh.length || solved) {
      if (animate) {
        for (const it of fresh) {
          pulse(it);
          if (it.n) toast(`${it.type.dept}${ro(it.type.dept)} 보냈어요.`);   // content 상황별 안내 「맡은 부서로 보냄」
        }
      }
      renderAll(animate ? new Set(fresh) : null);
      if (fresh.includes(one)) phoneSent(animate);
      renderKpi();
    }
    renderClock();
  }
  function seek(t) { resetBoard(); advance(t, false); }
  function setPlaying(on) {
    cancelAnimationFrame(play.raf);
    play.on = on;
    if (on) {
      if (play.t >= WINDOW) seek(0);
      play.last = performance.now();
      const tick = (ts) => {
        const dt = Math.min(0.1, Math.max(0, (ts - play.last) / 1000));
        play.last = ts;
        advance(play.t + dt * WINDOW / PLAY_SECONDS, true);
        if (play.t >= WINDOW) setPlaying(false);
        else play.raf = requestAnimationFrame(tick);
      };
      play.raf = requestAnimationFrame(tick);
    }
    $('b-play').textContent = on ? '❚❚ 일시정지' : '▶ 재생';
  }

  // 왼쪽 휴대폰: U-02 시민 신고(19:02에 1번을 보냄) → 안내 승인 뒤 U-01 받은 안내
  $('u-what').textContent = U02.what;
  $('u-where').textContent = U02.where;
  $('u-phone').textContent = U02.phone;
  function phoneSent(animate) {
    $('u-sent').innerHTML = `<dt>보낸 것</dt><dd>「${esc(U02.what)}」</dd><dt>보낸 시각</dt><dd>${one.time}</dd>`
      + `<dt>맡은 부서</dt><dd>${esc(one.type.dept)}</dd>`;
    clearTimeout(phoneTimer);
    if (!animate) { phone.classList.add('sent'); return; }
    phone.classList.add('sending');
    $('u-send').textContent = SAY.sending;
    phoneTimer = setTimeout(() => {
      phone.classList.replace('sending', 'sent');
      $('u-send').textContent = '보내기';
    }, 900);
  }
  $('u-send').onclick = () => { if (scene.on && one && play.t < one.sec) advance(one.sec, true); };
  function phoneReceived(it, time) {
    const T = it.T, q = T.basis.indexOf('「');
    $('u-recv').innerHTML = `<b class="box-head">${esc(it.type.dept)}${iga(it.type.dept)} 승인한 안내예요. 이대로 안내해 주세요.</b><dl>`
      + `<dt>안내</dt><dd class="big">${esc(T.draft)}</dd>`
      + `<dt>장소</dt><dd>${esc(it === one ? U02.where : it.place)}</dd>`
      + `<dt>근거</dt><dd>${esc((q < 0 ? T.basis : T.basis.slice(0, q)).trim())} · ${esc(T.effective)} 시행본</dd>`
      + `<dt>승인</dt><dd>${esc(it.type.dept)} 담당 · ${time} · ${esc(it.type.phone)}</dd>`
      + (it.citizen ? `<dt>신고한 시민</dt><dd>${esc(it.citizen)}</dd>` : '') + '</dl>';
    phone.classList.remove('received');
    void phone.offsetWidth;
    phone.classList.add('received');
  }
  function addApproved(it, time) {
    board.approved.set(it.id, time);
    const ul = $('b-approved');
    ul.insertAdjacentHTML('afterbegin', `<li class="glass"><b>승인한 안내</b><span>${time}</span><span>${esc(it.type.dept)} 담당</span>`
      + `<em>${esc(it === one ? APPROVED_1 : `${it.place} · ${verdictOf(it.T.verdict)[1]}`)}</em></li>`);
    while (ul.children.length > 3) ul.lastElementChild.remove();
  }
  function approve(it) {
    if (!it || doneMap().has(it.id)) return;
    const time = hhmm(Math.min(WINDOW, Math.max(scene.on ? play.t : 0, it.sec + 60)));
    if (scene.on) addApproved(it, time);
    else dayDone.set(it.id, time);
    renderKpi();
    renderAll();
    phoneReceived(it, time);
    openCard(it);   // 버튼과 「현장에 안내를 보냈어요.」를 다시 그린다
  }

  function enterScene(opt = {}) {
    if (scene.on || !CP) return;
    stopFlight();
    scene.on = true;
    scene.moved = false;
    scene.back = { center: map.getCenter(), zoom: map.getZoom(), pitch: map.getPitch(), bearing: map.getBearing() };
    Object.assign(filter, { type: '', status: '', group: false });
    play.started = false;
    $('card-slot').append(card);
    document.body.classList.add('night');
    resetBoard();
    setNight(true);
    fx.start();   // 들어온 순간부터 불꽃
    const cam = sceneCamera();
    if (opt.jump) map.jumpTo(cam);
    else map.flyTo({ ...cam, duration: 3000, essential: true });
    later(() => document.body.classList.add('board-in'), opt.jump ? 0 : 1500);
    later(() => {
      play.started = true;   // 이제부터 빈 목록은 「아직 들어온 일이 없어요.」
      seek(opt.t || 0);
      setPlaying(play.t < WINDOW);   // 끝 시각으로 건너뛰었으면 멈춘 채로 둔다
      const c = opt.card && items.find((it) => it.no === opt.card);
      if (c) {
        if (c.sec > play.t) advance(c.sec, false);
        openCard(c);
      }
    }, opt.jump ? 0 : 2600);
  }
  function exitScene() {
    if (!scene.on) return;
    scene.on = false;
    scene.timers.forEach(clearTimeout);
    scene.timers = [];
    setPlaying(false);
    fx.stop();
    card.hidden = true;
    select(null);
    document.body.append(card);
    document.body.classList.remove('night', 'board-in');
    setNight(false);
    Object.assign(filter, { type: '', status: '', group: false });
    board.note = '';
    renderAll();
    map.flyTo({ ...scene.back, padding: { top: 0, bottom: 0, left: 0, right: 0 }, duration: 2400, essential: true });
  }
  $('btn-scene').onclick = () => enterScene();
  $('b-exit').onclick = exitScene;
  $('b-play').onclick = () => setPlaying(!play.on);

  renderAll();
  map.once('load', () => {
    // 바로 가기: ?scene=fireworks[&t=재생 초][&card=번호]
    const q = new URLSearchParams(location.search);
    if (q.get('scene') === 'fireworks') {
      enterScene({ jump: true, t: (Number(q.get('t')) || 0) * WINDOW / PLAY_SECONDS, card: Number(q.get('card')) || 0 });
    }
  });
  map.once('idle', () => { window.prefetchCount = prefetch(tj.tiles[0], path); });
}

main().catch((err) => {
  console.error(err);
  document.querySelector('.head p').textContent = '지도를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.';
});
