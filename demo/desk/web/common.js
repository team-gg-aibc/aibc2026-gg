// 3판 화면 둘(담당자 desk.html · 시민 citizen.html)이 같이 쓰는 작은 도구. 화면 글자는 /api/text(docs/content/의 3판 파일 둘)에서만 온다
'use strict';
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fill = (s, o) => String(s ?? '').replace(/\{([^}]+)\}/g, (m, k) => (o[k] ?? m));   // 「{장소} 부근」 → 「서울숲 부근」
const store = { get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
                set: (k, v) => { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch { /* 저장 못 해도 화면은 돈다 */ } } };
async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(d.error || r.status), { data: d });
  return d;
}
// 글 꺼내기: W(파일, 구역) = 그 구역의 글 묶음. tab(머리) = 표 머리 첫 칸이 머리인 표 → {왼쪽: 오른쪽}. 없는 이름은 이름 그대로 보여 빠진 글을 바로 알아보게
function texts(T, file) {
  const D = T[file];
  return (name) => {
    const s = D.sections[name] || { items: [], smalls: [], tables: [], lead: '' };
    const tab = (head = '항목') => { const t = s.tables.find((x) => x.head[0] === head); return new Proxy(t ? Object.fromEntries(t.rows.map((r) => [r[0], r[1]])) : {}, { get: (o, k) => (k in o ? o[k] : `[${String(k)}]`) }); };
    return { name: s.name, lead: s.lead || '', smalls: s.smalls, items: s.items, tab, kv: tab(),
             btn: (i = 0) => (s.items.filter((x) => x.kind === '버튼')[i] || { parts: [] }).parts,
             pick: (kind, i = 0) => (s.items.filter((x) => x.kind === kind)[i] || { parts: [] }).parts,
             plain: () => s.items.filter((x) => !x.kind).map((x) => x.parts) };
  };
}
const split2 = (t) => { const i = String(t).indexOf(' · '); return i < 0 ? [t, ''] : [t.slice(0, i), t.slice(i + 3)]; };
function inRing([x, y], ring) {   // 점이 서울 경계 안인가(반직선 세기)
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
const km = (a, b) => Math.hypot((a[0] - b[0]) * 88.2, (a[1] - b[1]) * 111);   // 서울 위도에서 대략 거리(서버 near_place와 같은 셈)
const nearPlace = (places, c, within = 0.9) => {
  const n = Object.values(places).map((p) => [km(c, [p.lon, p.lat]), p]).sort((a, b) => a[0] - b[0])[0];
  return n && n[0] <= within ? n[1] : null;
};
const hhmm = (iso) => { if (!iso) return '—'; const d = new Date(iso), p = (n) => String(n).padStart(2, '0'); return `${p(d.getHours())}:${p(d.getMinutes())}`; };
const ymd = (iso) => { if (!iso) return '—'; const d = new Date(iso), p = (n) => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`; };
const koLabels = (m) => { for (const l of m.getStyle().layers) { const f = l.type === 'symbol' && m.getLayoutProperty(l.id, 'text-field'); if (f && /name/.test(JSON.stringify(f))) m.setLayoutProperty(l.id, 'text-field', ['coalesce', ['get', 'name:ko'], ['get', 'name']]); } };   // 지도 글자는 한글 이름 먼저(도로 번호판처럼 번호를 쓰는 층은 그대로)
