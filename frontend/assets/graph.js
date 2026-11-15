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

  function create(svg, data, opt = {}) {
    const W = opt.width || 780, H = opt.height || 420;
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    svg.classList.add('agraph'); svg.innerHTML = '';
    const pos = (opt.layout || layeredLayout)(data.nodes, data.links, W, H);
    const N = {}; data.nodes.forEach((n, i) => { N[n.id] = { ...n, ...pos[n.id], r: n.kind === 'hub' ? 50 : n.kind === 'human' ? 34 : 42, color: n.color || PALETTE[i % PALETTE.length] }; });
    const el = (tag, attrs, parent = svg) => { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); parent.append(e); return e; };

    data.links.forEach(l => { const a = N[l.from], b = N[l.to]; el('line', { class: `edge ${l.kind}`, id: `e-${l.from}-${l.to}`, x1: a.x, y1: a.y, x2: b.x, y2: b.y }); });
    // 연결 방식 라벨(Tool, A2A, MCP 등)은 각 연결선 가운데에 작게 붙인다. 선 색·모양과 아래 범례로도 구분한다
    data.links.forEach(l => {
      const a = N[l.from], b = N[l.to];
      const w = [...l.label].reduce((s, c) => s + (c.charCodeAt(0) > 255 ? 11 : 6.8), 0) + 14;
      // 라벨이 노드에 가려지지 않게: 선의 가운데부터 시작해, 어떤 노드와도 겹치지 않는 지점을 선을 따라 찾는다
      const clear = (x, y) => Object.values(N).every(n => Math.hypot(Math.max(Math.abs(x - n.x) - w / 2, 0), Math.max(Math.abs(y - n.y) - 10, 0)) > n.r + 3);
      const t = [.5, .42, .58, .35, .65, .3, .7, .25, .75].find(t => clear(a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t)) ?? .5;
      const g = el('g', { class: `pill ${l.kind}`, transform: `translate(${a.x + (b.x - a.x) * t} ${a.y + (b.y - a.y) * t})` });
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
        const s = N[from], d = N[to], line = edge(from, to);
        if (!s || !d || !line) return Promise.resolve();
        line.classList.add('on'); [pk, ...trail].forEach(c => c.setAttribute('visibility', 'visible'));
        return new Promise(res => {
          const t0 = performance.now();
          const f = t => {
            const k = reduce() ? 1 : Math.min(1, (t - t0) / ms), e = k < .5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2;
            [pk, ...trail].forEach((c, i) => { const q = Math.max(0, e - i * .06); c.setAttribute('cx', s.x + (d.x - s.x) * q); c.setAttribute('cy', s.y + (d.y - s.y) * q); });
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

  window.AgentGraph = { create, player, layeredLayout };
})();
