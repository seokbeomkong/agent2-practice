/* Agent 그래프 공통 모듈: 서버가 보낸 nodes/links로 그래프를 그리고, 메시지 이동·상태·말풍선을 보여 준다.
   사용: const g = AgentGraph.create(svg, {nodes, links}, {width, height, layout});
         await g.travel(from, to); g.setOn(id, true); g.say(id, text); */
(function () {
  const NS = 'http://www.w3.org/2000/svg';
  const PALETTE = ['#2B9BFF', '#E0218A', '#00A86B', '#FF5A2E', '#7A6FA8', '#FFD400'];
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  // 기본 배치: 사람(들어오는 연결이 없는 노드)부터 너비 우선으로 단계를 나눠 왼쪽 → 오른쪽으로 놓는다.
  // 3단계 이후 노드는 부모와 같은 높이에 둔다. 같은 단계 안에서는 위아래로 고르게 편다.
  function layeredLayout(nodes, links, W, H) {
    const ids = nodes.map(n => n.id), level = {}, parent = {};
    const nbr = id => links.filter(l => l.from === id || l.to === id).map(l => l.from === id ? l.to : l.from);
    const root = nodes.find(n => n.kind === 'human') || nodes.find(n => !links.some(l => l.to === n.id)) || nodes[0];
    level[root.id] = 0; const q = [root.id];
    while (q.length) { const c = q.shift(); nbr(c).forEach(n => { if (level[n] == null) { level[n] = level[c] + 1; parent[n] = c; q.push(n); } }); }
    ids.forEach(id => { if (level[id] == null) level[id] = 1; });
    const maxL = Math.max(...Object.values(level));
    const byL = {}; ids.forEach(id => (byL[level[id]] = byL[level[id]] || []).push(id));
    const pos = {}, padX = 70, stepX = (W - padX * 2) / Math.max(maxL, 1);
    Object.keys(byL).sort((a, b) => a - b).forEach(L => {
      const row = byL[L];
      row.forEach((id, i) => {
        let y = H / 2 + (i - (row.length - 1) / 2) * Math.min(130, (H - 120) / Math.max(row.length - 1, 1));
        if (L >= 3 && pos[parent[id]] && row.length === 1) y = pos[parent[id]].y;
        pos[id] = { x: padX + L * stepX, y };
      });
    });
    return pos;
  }

  // 연결선 경로: 기본은 직선. 다른 노드와 가깝게(반지름+12px 안) 지나가면 노드 바깥쪽으로 휘어진 곡선(2차 베지어)으로 바꾼다.
  // 돌려주는 값: 휘어야 하면 제어점 {x, y}, 직선이면 null
  function route(N, l, W, H) {
    const a = N[l.from], b = N[l.to], others = Object.values(N).filter(n => n.id !== a.id && n.id !== b.id);
    const pt = (c, t) => { const u = 1 - t; return c ? { x: u * u * a.x + 2 * u * t * c.x + t * t * b.x, y: u * u * a.y + 2 * u * t * c.y + t * t * b.y } : { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t }; };
    const clearance = c => { let m = 1e9; for (let i = 1; i < 24; i++) { const p = pt(c, i / 24); for (const n of others) m = Math.min(m, Math.hypot(p.x - n.x, p.y - n.y) - n.r); } return m; };
    let best = null, bestScore = clearance(null);
    if (!others.length || bestScore >= 12) return null;
    const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1, nx = -dy / len, ny = dx / len, mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
    for (const d of [30, 45, 60, 80, 100, 125, 150, 180, 220]) for (const sgn of [1, -1]) {
      const c = { x: mx + nx * d * 2 * sgn, y: my + ny * d * 2 * sgn }, m = pt(c, .5);   // 제어점을 2배 지점에 두면 곡선은 d만큼 휜다
      if (m.x < 6 || m.x > W - 6 || m.y < 6 || m.y > H - 6) continue;
      const score = clearance(c); if (score >= 12) return c; if (score > bestScore) { best = c; bestScore = score; }
    }
    return best;
  }

  function create(svg, data, opt = {}) {
    const W = opt.width || 780, H = opt.height || 420;
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    svg.classList.add('agraph'); svg.innerHTML = '';
    const pos = (opt.layout || layeredLayout)(data.nodes, data.links, W, H);
    const N = {}; data.nodes.forEach((n, i) => { N[n.id] = { ...n, ...pos[n.id], r: n.kind === 'hub' ? 50 : n.kind === 'human' ? 34 : 42, color: n.color || PALETTE[i % PALETTE.length] }; });
    const el = (tag, attrs, parent = svg) => { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); parent.append(e); return e; };

    // 연결선(직선, 또는 노드를 피해 휘어진 곡선)과 그 위의 한 점을 구하는 함수
    const paths = {};
    const at = (key, t) => { const { a, b, c } = paths[key], u = 1 - t;   // t: 0이면 from, 1이면 to
      return c ? { x: u * u * a.x + 2 * u * t * c.x + t * t * b.x, y: u * u * a.y + 2 * u * t * c.y + t * t * b.y } : { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t }; };
    data.links.forEach(l => {
      const a = N[l.from], b = N[l.to], c = route(N, l, W, H); paths[`${l.from}>${l.to}`] = { a, b, c };
      if (c) el('path', { class: `edge ${l.kind}`, id: `e-${l.from}-${l.to}`, d: `M${a.x} ${a.y} Q${c.x} ${c.y} ${b.x} ${b.y}` });
      else el('line', { class: `edge ${l.kind}`, id: `e-${l.from}-${l.to}`, x1: a.x, y1: a.y, x2: b.x, y2: b.y });
    });
    // 연결 방식 라벨(Tool, A2A, MCP 등)은 각 연결선 가운데에 작게 붙인다. 선 색·모양과 아래 범례로도 구분한다
    const placed = [];   // 이미 놓은 라벨의 자리(서로 겹치지 않게)
    data.links.forEach(l => {
      const a = N[l.from], b = N[l.to];
      const w = [...l.label].reduce((s, c) => s + (c.charCodeAt(0) > 255 ? 11 : 6.8), 0) + 14;
      // 라벨이 노드에 가려지지 않게: 선의 가운데부터 시작해, 어떤 노드와도 겹치지 않는 지점을 선을 따라 찾는다
      const clear = (x, y) => Object.values(N).every(n => Math.hypot(Math.max(Math.abs(x - n.x) - w / 2, 0), Math.max(Math.abs(y - n.y) - 10, 0)) > n.r + 3);
      // 가운데에서 가까운 순서로 훑어 겹치지 않는 자리를 찾고, 어디에도 없으면(연결이 빽빽할 때) 라벨을 숨긴다.
      // 선 모양·색과 아래 범례로 연결 종류를 알 수 있다. (라벨 순서는 연결 순서와 같아야 하므로 요소는 항상 만든다)
      const key = `${l.from}>${l.to}`, ts = Array.from({ length: 19 }, (_, i) => .5 + (i % 2 ? 1 : -1) * Math.ceil(i / 2) * .04).filter(t => t > .1 && t < .9);
      const free = (x, y) => clear(x, y) && placed.every(q => Math.abs(x - q.x) > (w + q.w) / 2 + 3 || Math.abs(y - q.y) > 24);
      const crowded = data.links.filter(x => x.kind === l.kind).length > 6;   // 같은 종류 연결이 많으면 라벨은 생략(선 모양·색과 범례로 구분)
      const t = crowded ? null : ts.find(t => { const p = at(key, t); return free(p.x, p.y); }), p = at(key, t ?? .5); if (t != null) placed.push({ x: p.x, y: p.y, w });
      const g = el('g', { class: `pill ${l.kind}`, transform: `translate(${p.x} ${p.y})` }); if (t == null) g.style.display = 'none';
      el('rect', { x: -w / 2, y: -10, width: w, height: 20, rx: 10 }, g); el('text', {}, g).textContent = l.label;
    });
    svg.parentElement.querySelector(':scope > .glegend')?.remove();
    const kinds = [...new Map(data.links.map(l => [l.kind, l.label])).entries()];
    const legend = document.createElement('div'); legend.className = 'glegend';
    legend.innerHTML = kinds.map(([k, label]) => `<span><svg width="34" height="10" aria-hidden="true"><line class="edge ${k}" x1="2" y1="5" x2="32" y2="5"/></svg>${esc(label)}</span>`).join('')
      + (opt.onNodeClick ? '<span class="tip">노드를 누르면 자세히 볼 수 있어요</span>' : '');
    svg.after(legend);
    Object.values(N).forEach(n => {
      const g = el('g', { class: `node ${n.kind || ''}${opt.onNodeClick ? ' clickable' : ''}`, id: `n-${n.id}` });
      if (opt.onNodeClick) {
        // 노드를 누르면(키보드 Enter/Space 포함) 상세 팝업을 열고 닫는다
        g.setAttribute('tabindex', '0'); g.setAttribute('role', 'button');
        g.setAttribute('aria-label', `${n.name} 상세 보기`);
        g.addEventListener('click', () => opt.onNodeClick(n.id));
        g.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); opt.onNodeClick(n.id); } });
      }
      el('circle', { class: 'ring', cx: n.x, cy: n.y, r: n.r }, g);
      el('circle', { class: 'shadow', cx: n.x + 5, cy: n.y + 5, r: n.r }, g);
      el('circle', { class: 'body', cx: n.x, cy: n.y, r: n.r }, g);
      el('circle', { class: 'band', cx: n.x, cy: n.y, r: n.r - 7, stroke: n.color }, g);
      const long = n.name.length > 6;
      el('text', { class: 'name' + (long ? ' long' : ''), x: n.x, y: n.y }, g).textContent = n.name;
      if (n.role) el('title', {}, g).textContent = `${n.name}: ${n.role}`;  // 역할은 마우스를 올렸을 때만 보인다
      const bx = n.x + n.r * 0.72, by = n.y - n.r * 0.72, badge = el('g', { class: 'nbadge', transform: `translate(${bx} ${by})` }, g);
      el('circle', { r: 12 }, badge); el('text', {}, badge);
    });
    const trail = [0, 1, 2].map(i => el('circle', { class: 'trail', r: 6 - i * 1.5, cx: -50, cy: -50, visibility: 'hidden' }));
    const pk = el('circle', { class: 'packet', r: 9, cx: -50, cy: -50, visibility: 'hidden' });
    const bubbles = el('g', {});
    const edge = (a, b) => svg.querySelector(`#e-${a}-${b}`) || svg.querySelector(`#e-${b}-${a}`);
    const reduce = () => matchMedia('(prefers-reduced-motion:reduce)').matches;

    return {
      nodes: N,
      setOn(id, on) { svg.querySelector('#n-' + id)?.classList.toggle('on', !!on); },
      clear() { svg.querySelectorAll('.node.on').forEach(n => n.classList.remove('on')); bubbles.innerHTML = ''; },
      // 꺼진 Agent: 노드와 연결선을 흐리게
      setOff(id, off) {
        svg.querySelector('#n-' + id)?.classList.toggle('off', !!off);
        data.links.forEach((l, i) => { if (l.from === id || l.to === id) {
          const offAny = [l.from, l.to].some(x => svg.querySelector('#n-' + x)?.classList.contains('off'));
          edge(l.from, l.to)?.classList.toggle('off', offAny); svg.querySelectorAll('.pill')[i]?.classList.toggle('off', offAny);
        } });
      },
      // 연결 종류별로 흐리게 (예: Full-Mesh를 끄면 a2a 연결)
      setKindOff(kind, off) {
        data.links.forEach((l, i) => { if (l.kind === kind) { edge(l.from, l.to)?.classList.toggle('off', !!off); svg.querySelectorAll('.pill')[i]?.classList.toggle('off', !!off); } });
      },
      setSelected(id) { svg.querySelectorAll('.node.sel').forEach(n => n.classList.remove('sel')); if (id) svg.querySelector('#n-' + id)?.classList.add('sel'); },
      setBadge(id, count) {
        const b = svg.querySelector(`#n-${id} .nbadge`); if (!b) return;
        b.classList.toggle('show', count > 0); b.querySelector('text').textContent = count > 9 ? '9+' : count;
      },
      // 노드 중심의 화면 좌표 (팝업 위치 계산용)
      screenPos(id) {
        const n = N[id], m = svg.getScreenCTM(); if (!n || !m) return null;
        return { x: n.x * m.a + m.e, y: n.y * m.d + m.f, r: n.r * m.a };
      },
      // 노란 점이 연결선을 따라 이동 (꼬리 3개가 뒤따른다). 연결이 없으면 바로 끝낸다.
      travel(from, to, ms = 650) {
        const s = N[from], d = N[to], line = edge(from, to), key = paths[`${from}>${to}`] ? `${from}>${to}` : `${to}>${from}`, fwd = key === `${from}>${to}`;
        if (!s || !d || !line || !paths[key]) return Promise.resolve();
        line.classList.add('on'); [pk, ...trail].forEach(c => c.setAttribute('visibility', 'visible'));
        return new Promise(res => {
          const t0 = performance.now();
          const f = t => {
            const k = reduce() ? 1 : Math.min(1, (t - t0) / ms), e = k < .5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2;
            [pk, ...trail].forEach((c, i) => { const q = Math.max(0, e - i * .06), p = at(key, fwd ? q : 1 - q); c.setAttribute('cx', p.x); c.setAttribute('cy', p.y); });
            if (k < 1) requestAnimationFrame(f); else { [pk, ...trail].forEach(c => { c.setAttribute('cx', -50); c.setAttribute('visibility', 'hidden'); }); line.classList.remove('on'); res(); }
          };
          requestAnimationFrame(f);
        });
      },
      // 말풍선: 노드 위(위쪽에 있는 노드는 아래)에 잠깐 띄운다
      say(id, text, ms = 3200) {
        const n = N[id]; if (!n || !text) return;
        const w = 220, h = 76, above = n.y > H * 0.36;
        const x = Math.max(4, Math.min(W - w - 4, n.x - w / 2)), y = above ? n.y - n.r - h - 6 : n.y + n.r + 34;
        const fo = el('foreignObject', { x, y, width: w, height: h }, bubbles);
        fo.innerHTML = `<div xmlns="http://www.w3.org/1999/xhtml" class="say">${esc(text)}</div>`;
        setTimeout(() => fo.remove(), ms);
      }
    };
  }

  // 이벤트를 순서대로 재생하는 큐: 애니메이션이 끝난 뒤 다음 이벤트를 처리한다
  function player(handle) {
    const q = []; let busy = false;
    return {
      push(ev) { q.push(ev); if (!busy) this.run(); },
      async run() { busy = true; while (q.length) { try { await handle(q.shift()); } catch (e) { console.error(e); } } busy = false; },
      get idle() { return !busy && !q.length; }
    };
  }

  window.AgentGraph = { create, player, layeredLayout, route };
})();
