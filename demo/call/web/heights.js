// 시연 자리 둘레 건물의 실제 높이와 대본 건물의 지붕 둘레 띠. 끄기: 주소에 ?heights=off
// 지도 타일의 건물 층은 같은 높이의 건물을 타일마다 한 덩어리로 묶어 두어 건물마다 높이를 바꿀 수 없다. 그래서 타일 건물은 그대로 두고(자리 밖은 지금과 같음),
// 서울시 실제 높이(「건물 태양에너지 등급도(2018)」)가 더 높은 건물만 바닥 모양을 0.4m 넓혀 실제 높이로 덧그린다(web/heights/*.geojson, tools/make_heights.py).
// 칠은 타일 건물 층(own-b3d · own-roof)을 그대로 따라 한다. call.js의 map · markers · V를 읽기만 한다
'use strict';
(function () {
  if (new URLSearchParams(location.search).get('heights') === 'off') return;
  const COL = '#ff9f1c', PROPS = ['fill-extrusion-color', 'fill-extrusion-height', 'fill-extrusion-base', 'fill-extrusion-opacity', 'fill-extrusion-vertical-gradient'];
  const PAIRS = [['own-b3d', 'own-hb3d'], ['own-roof', 'own-hroof']];
  const near = (a, b) => Math.hypot((a[0] - b[0]) * 88200, (a[1] - b[1]) * 111000);
  function copyPaint() {      // 화면 밝기를 바꾸면(applyTone) 타일 건물 층의 칠을 그대로 따른다
    for (const [from, to] of PAIRS) for (const k of PROPS) {
      const v = map.getPaintProperty(from, k);
      if (v !== undefined && JSON.stringify(v) !== JSON.stringify(map.getPaintProperty(to, k))) map.setPaintProperty(to, k, v);
    }
  }
  async function add() {
    const hi = await fetch('heights/hi.geojson').then((r) => r.json()).catch(() => ({ type: 'FeatureCollection', features: [] }));
    map.addSource('own-heights', { type: 'geojson', data: 'heights/buildings.geojson' });
    map.addSource('own-hi', { type: 'geojson', data: hi });
    for (const [, to] of PAIRS) map.addLayer({ id: to, type: 'fill-extrusion', source: 'own-heights', minzoom: 13 }, 'own-cloud');
    copyPaint();
    map.on('styledata', copyPaint);
    // 대본 건물 강조: 지붕 둘레 띠(지붕 색은 덮지 않음). 표지와 같은 때에만 보인다 — 지금 질문이 물어보는 표지가 든 건물, 자리가 정해지면 그 자리 건물
    map.addLayer({ id: 'own-hring', type: 'fill-extrusion', source: 'own-hi', minzoom: 13, filter: ['in', ['get', 'name'], ['literal', []]],
      paint: { 'fill-extrusion-color': COL, 'fill-extrusion-height': ['+', ['get', 'h'], 0.6], 'fill-extrusion-base': ['max', ['-', ['get', 'h'], 2.4], 0] } }, 'own-cloud');
    let last = '';
    setInterval(() => {
      const names = new Set(markers.map((m) => m.getElement().title).filter(Boolean));
      if (V && V.confirmed && V.pin) for (const f of hi.features) if (near(f.properties.at, V.pin.at) <= 25) names.add(f.properties.name);
      const key = [...names].sort().join('|');
      if (key !== last) { last = key; map.setFilter('own-hring', ['in', ['get', 'name'], ['literal', [...names]]]); }
    }, 300);
  }
  const wait = setInterval(() => { if (map && map.getLayer('own-roof') && map.getLayer('own-cloud')) { clearInterval(wait); add(); } }, 200);
})();
