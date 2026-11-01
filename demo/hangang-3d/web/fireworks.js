// 불꽃놀이 — 지도 위 2D canvas(pointer-events: none, 상황판 패널보다 아래)
// 바지선 자리를 매 프레임 map.project로 구하고, 화면 가로로 100m 떨어진 땅 점을 함께 투영해 px/m를 얻는다.
// 높이는 px/m × sin(기울기)로 세워서, 지도를 움직여도 원근에 맞게 커지고 작아진다.
(() => {
  const COLORS = ['#ff4d6d', '#ffd23f', '#5ce1ff', '#c77dff', '#ff8c42', '#ffffff', '#ff6ad5', '#7dffb2'];
  const GOLD = '#ffc864';
  const MAX = 2000;   // 입자 수 상한
  const rand = (a, b) => a + Math.random() * (b - a);
  const pick = (a) => a[Math.floor(Math.random() * a.length)];

  // 빛 번짐 점(가운데 흰색 → 색 → 투명)
  const sprite = (color) => {
    const c = document.createElement('canvas');
    c.width = c.height = 64;
    const g = c.getContext('2d');
    const r = g.createRadialGradient(32, 32, 0, 32, 32, 32);
    r.addColorStop(0, '#ffffff');
    r.addColorStop(0.12, color);
    r.addColorStop(0.4, color + '55');
    r.addColorStop(1, color + '00');
    g.fillStyle = r;
    g.fillRect(0, 0, 64, 64);
    return c;
  };
  // 경위도 점에서 방위 az(도)로 m미터 떨어진 점
  const offset = ([lng, lat], m, az) => {
    const a = az * Math.PI / 180;
    return [lng + m * Math.sin(a) / (111320 * Math.cos(lat * Math.PI / 180)), lat + m * Math.cos(a) / 110574];
  };

  window.createFireworks = (map, canvas, barges) => {
    const ctx = canvas.getContext('2d');
    const sprites = Object.fromEntries([...COLORS, GOLD].map((c) => [c, sprite(c)]));
    const glow = barges.map(() => ({ v: 0, color: GOLD }));
    let rockets = [], parts = [], flashes = [], raf = 0, last = 0, wait = 0, opening = 0;

    const launch = (b, delay = 0) => {
      const h = rand(170, 300);
      const kind = Math.random() < 0.2 ? 'willow' : Math.random() < 0.35 ? 'two' : Math.random() < 0.15 ? 'ring' : 'peony';
      rockets.push({ b, x: rand(-170, 170), h, t: -delay, T: rand(0.9, 1.3), color: pick(COLORS), kind });   // 강 폭 안에서 좌우로 흩어 쏜다
    };

    const burst = (r) => {
      const willow = r.kind === 'willow';
      const n = willow ? 130 : Math.round(rand(120, 170));
      if (parts.length + n > MAX) return;
      const R = Math.min(r.h * 0.8, rand(150, 220));   // 터지는 반지름(m): 큰 축제 불꽃, 물 아래로는 안 내려가게
      const drag = willow ? 1.15 : 1.7;
      const c2 = pick(COLORS);
      const tilt = rand(-0.6, 0.6);
      for (let i = 0; i < n; i++) {
        let vx, vy;
        if (r.kind === 'ring') {   // 고리: 기울어진 원
          const a = (i / n) * Math.PI * 2;
          vx = Math.cos(a); vy = Math.sin(a) * 0.45 + Math.cos(a) * tilt * 0.3;
        } else {                   // 국화: 구에 고르게 퍼진 방향을 화면에 투영
          const z = rand(-1, 1), a = rand(0, Math.PI * 2), s = Math.sqrt(1 - z * z);
          vx = s * Math.cos(a); vy = z;
        }
        const sp = R * drag * rand(0.82, 1.05);
        parts.push({
          b: r.b, x: r.x, y: r.h, vx: vx * sp, vy: vy * sp, life: 0,
          max: willow ? rand(2.8, 3.6) : rand(1.8, 2.5), drag, g: willow ? 30 : 16,
          color: willow ? GOLD : r.kind === 'two' && i % 2 ? c2 : r.color,
        });
      }
      flashes.push({ b: r.b, x: r.x, y: r.h, life: 0, R, color: willow ? GOLD : r.color });
      glow[r.b].v = Math.min(1.6, glow[r.b].v + 1);
      glow[r.b].color = willow ? GOLD : r.color;
    };

    const frame = (ts) => {
      raf = requestAnimationFrame(frame);
      const dt = Math.min(0.05, Math.max(0, (ts - last) / 1000));
      last = ts;
      const dpr = window.devicePixelRatio || 1;
      const w = canvas.clientWidth, h = canvas.clientHeight;
      if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
        canvas.width = Math.round(w * dpr);
        canvas.height = Math.round(h * dpr);
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.globalCompositeOperation = 'source-over';
      ctx.globalAlpha = 1;
      ctx.clearRect(0, 0, w, h);

      // 바지선마다 화면 위치와 px/m
      const pitch = map.getPitch() * Math.PI / 180, sinP = Math.sin(pitch), cosP = Math.cos(pitch);
      const az = map.getBearing() + 90;
      const P = barges.map((b) => {
        const p = map.project(b), q = map.project(offset(b, 100, az));
        return { x: p.x, y: p.y, s: Math.hypot(q.x - p.x, q.y - p.y) / 100 };
      });
      const sx = (o) => P[o.b].x + o.x * P[o.b].s;
      const sy = (o) => P[o.b].y - o.y * P[o.b].s * sinP;

      // 발사: 처음 몇 초는 세 바지선에서 몰아서, 그 뒤로는 0.2~0.6초마다(자주 여러 발 한꺼번에)
      if ((wait -= dt) <= 0) {
        if (opening < 4 || Math.random() < 0.3) barges.forEach((_, i) => launch(i, Math.random() * 0.25));
        else launch(Math.floor(Math.random() * barges.length));
        opening++;
        wait = opening < 4 ? 0.35 : rand(0.2, 0.6);
      }

      ctx.globalCompositeOperation = 'lighter';

      // 강물 위 반사광(바지선 둘레 납작한 빛)
      glow.forEach((g, i) => {
        g.v *= Math.exp(-1.8 * dt);
        if (g.v < 0.02) return;
        const p = P[i], rx = 380 * p.s;
        ctx.save();
        ctx.translate(p.x, p.y);
        ctx.scale(1, Math.max(0.12, cosP));
        ctx.globalAlpha = Math.min(0.7, 0.45 * g.v);
        ctx.drawImage(sprites[g.color] || sprites[GOLD], -rx, -rx, rx * 2, rx * 2);
        ctx.restore();
      });

      // 로켓: 꼬리를 끌며 올라가다 정점에서 터진다
      ctx.lineCap = 'round';
      rockets = rockets.filter((r) => {
        r.t += dt;
        if (r.t < 0) return true;
        const k = Math.min(1, r.t / r.T), k0 = Math.max(0, k - 0.12);
        const y = r.h * (1 - (1 - k) ** 2), y0 = r.h * (1 - (1 - k0) ** 2);
        const x = sx(r), a = sy({ b: r.b, y }), b = sy({ b: r.b, y: y0 });
        ctx.globalAlpha = 0.9;
        ctx.strokeStyle = GOLD;
        ctx.lineWidth = 1.6;
        ctx.beginPath(); ctx.moveTo(x, b); ctx.lineTo(x, a); ctx.stroke();
        const s = Math.max(6, 16 * P[r.b].s);
        ctx.drawImage(sprites[GOLD], x - s / 2, a - s / 2, s, s);
        if (k >= 1) { burst(r); return false; }
        return true;
      });

      // 터질 때 번쩍
      flashes = flashes.filter((f) => {
        f.life += dt;
        if (f.life > 0.2) return false;
        const s = f.R * 0.9 * P[f.b].s;
        ctx.globalAlpha = 0.3 * (1 - f.life / 0.2);
        ctx.drawImage(sprites[f.color], sx(f) - s / 2, sy(f) - s / 2, s, s);
        return true;
      });

      // 별(입자): 속도에 비례한 꼬리 + 빛 번짐 머리, 끝무렵엔 반짝이며 사라짐
      const streaks = new Map();
      const next = [];
      for (const q of parts) {
        q.life += dt;
        if (q.life >= q.max) continue;
        const f = Math.exp(-q.drag * dt);
        q.vx *= f;
        q.vy = q.vy * f - q.g * dt;
        q.x += q.vx * dt;
        q.y += q.vy * dt;
        next.push(q);
        const u = q.life / q.max;
        let a = u < 0.6 ? 1 : (1 - u) / 0.4;
        if (u > 0.55 && Math.random() < 0.35) a *= 0.25;   // 반짝
        const x = sx(q), y = sy(q), sc = P[q.b].s;
        const key = q.color + '|' + Math.ceil(a * 4);
        let path = streaks.get(key);
        if (!path) streaks.set(key, (path = []));
        path.push(x, y, x - q.vx * 0.16 * sc, y + q.vy * 0.16 * sc * sinP);
        const s = Math.max(6, 18 * sc) * (u < 0.1 ? 1.2 : 1);
        ctx.globalAlpha = a * 0.9;
        ctx.drawImage(sprites[q.color], x - s / 2, y - s / 2, s, s);
      }
      parts = next;
      ctx.lineWidth = 2;
      for (const [key, pts] of streaks) {
        const [color, k] = key.split('|');
        ctx.strokeStyle = color;
        ctx.globalAlpha = (k / 4) * 0.75;
        ctx.beginPath();
        for (let i = 0; i < pts.length; i += 4) { ctx.moveTo(pts[i], pts[i + 1]); ctx.lineTo(pts[i + 2], pts[i + 3]); }
        ctx.stroke();
      }
    };

    return {
      start() {
        if (raf) return;
        canvas.hidden = false;
        opening = 0; wait = 0;
        last = performance.now();
        raf = requestAnimationFrame(frame);
      },
      stop() {
        cancelAnimationFrame(raf);
        raf = 0;
        rockets = []; parts = []; flashes = [];
        glow.forEach((g) => { g.v = 0; });
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        canvas.hidden = true;
      },
      count: () => parts.length,
    };
  };
})();
