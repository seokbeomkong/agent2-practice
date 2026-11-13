/* 공통 스크립트: 키 세션, 상단바, 실습 목록(썸네일 포함), 유틸 */
(function () {
  // ── API 키는 "이 브라우저 탭"의 sessionStorage에만 둔다. 탭을 닫으면 사라진다. (서버 저장 없음)
  const store = {
    get(k) { try { return sessionStorage.getItem(k) || ''; } catch { return ''; } },
    set(k, v) { try { sessionStorage.setItem(k, v); } catch {} },
    clear() { try { sessionStorage.removeItem('apiKey'); sessionStorage.removeItem('demo'); } catch {} }
  };
  // 연결 테스트를 통과한 키가 있어야만 실습 화면에 들어갈 수 있다.
  const hasAccess = () => !!store.get('apiKey');
  const maskKey = () => {
    const k = store.get('apiKey');
    if (!k) return '';
    return k.length > 12 ? k.slice(0, 7) + '…' + k.slice(-4) : '연결됨';
  };

  // ── 썸네일: 실제 앱 화면을 축소해 그린 SVG (viewBox 320x200)
  const thumbs = {
    dashboard: `<svg viewBox="0 0 320 200" aria-hidden="true"><rect width="320" height="200" fill="#2B4CFF"/>
      <rect x="24" y="24" width="272" height="152" rx="6" fill="#fff"/>
      <g fill="#2B4CFF"><rect x="44" y="100" width="14" height="50"/><rect x="66" y="64" width="14" height="86"/><rect x="88" y="116" width="14" height="34"/><rect x="110" y="84" width="14" height="66"/><rect x="132" y="126" width="14" height="24"/></g>
      <rect x="66" y="64" width="14" height="86" fill="#FFBE1F"/>
      <rect x="40" y="150" width="112" height="2" fill="#101A3A"/>
      <g transform="rotate(-90 232 76)" fill="none" stroke-width="14"><circle cx="232" cy="76" r="32" stroke="#D7DDF5"/><circle cx="232" cy="76" r="32" stroke="#2B4CFF" stroke-dasharray="110 201"/><circle cx="232" cy="76" r="32" stroke="#FFBE1F" stroke-dasharray="50 201" stroke-dashoffset="-110"/><circle cx="232" cy="76" r="32" stroke="#E8452F" stroke-dasharray="30 201" stroke-dashoffset="-160"/></g>
      <rect x="186" y="128" width="96" height="34" rx="9" fill="#101A3A"/><rect x="198" y="138" width="60" height="4" rx="2" fill="#fff"/><rect x="198" y="148" width="40" height="4" rx="2" fill="#8E9BD6"/></svg>`,
    persona: `<svg viewBox="0 0 320 200" aria-hidden="true"><rect width="320" height="200" fill="#FFBE1F"/>
      <circle cx="40" cy="52" r="14" fill="#101A3A"/><rect x="62" y="30" width="170" height="44" rx="14" fill="#fff"/><rect x="76" y="44" width="110" height="5" rx="2.5" fill="#101A3A"/><rect x="76" y="56" width="70" height="5" rx="2.5" fill="#9AA3C4"/>
      <circle cx="282" cy="112" r="14" fill="#fff"/><rect x="88" y="90" width="170" height="44" rx="14" fill="#101A3A"/><rect x="102" y="104" width="120" height="5" rx="2.5" fill="#fff"/><rect x="102" y="116" width="60" height="5" rx="2.5" fill="#8E9BD6"/>
      <circle cx="40" cy="162" r="14" fill="#101A3A"/><rect x="62" y="144" width="120" height="34" rx="14" fill="#fff"/><circle cx="84" cy="161" r="4" fill="#101A3A"/><circle cx="98" cy="161" r="4" fill="#101A3A"/><circle cx="112" cy="161" r="4" fill="#101A3A"/></svg>`,
    orchestra: `<svg viewBox="0 0 320 200" aria-hidden="true"><rect width="320" height="200" fill="#0F8E6D"/>
      <g stroke="#fff" stroke-width="3" fill="none"><path d="M44 100H100"/><path d="M100 100L160 52"/><path d="M100 100H160" stroke-dasharray="6 5"/><path d="M100 100L160 148"/><path d="M160 148L262 148"/></g>
      <g fill="#fff" stroke="#101A3A" stroke-width="3"><circle cx="40" cy="100" r="14"/><circle cx="100" cy="100" r="18" fill="#FFBE1F"/><circle cx="160" cy="52" r="14"/><circle cx="160" cy="100" r="14"/><circle cx="160" cy="148" r="14"/><circle cx="262" cy="148" r="14"/></g>
      <circle cx="210" cy="148" r="7" fill="#FFBE1F" stroke="#101A3A" stroke-width="2.5"/>
      <rect x="132" y="168" width="60" height="18" rx="9" fill="#101A3A"/><rect x="144" y="175" width="36" height="4" rx="2" fill="#fff"/></svg>`,
    audit: `<svg viewBox="0 0 320 200" aria-hidden="true"><rect width="320" height="200" fill="#101A3A"/>
      <g stroke="#5A6BA8" stroke-width="2.5"><path d="M70 50L250 50"/><path d="M70 50L70 150"/><path d="M250 50L250 150"/><path d="M70 150L250 150"/><path d="M70 50L250 150"/><path d="M250 50L70 150"/></g>
      <path d="M70 50L250 150" stroke="#FFBE1F" stroke-width="3.5" stroke-dasharray="8 7"/>
      <g stroke="#fff" stroke-width="3"><circle cx="70" cy="50" r="17" fill="#FFBE1F"/><circle cx="250" cy="50" r="17" fill="#fff"/><circle cx="70" cy="150" r="17" fill="#fff"/><circle cx="250" cy="150" r="17" fill="#12A37F"/></g>
      <circle cx="160" cy="100" r="7" fill="#FFBE1F"/></svg>`
  };

  const LABS = [
    { id: 'dashboard', file: 'lab-dashboard.html', ch: 'CH3', bg: '#2B4CFF', short: '불량 분석',
      title: '불량 리포트 분석 Dashboard', desc: '스마트폰 불량 리포트 5건을 AI가 읽고 요약해 Dashboard로 보여 주고, 결과에 대해 챗봇과 대화합니다.',
      concepts: ['AI Application', 'Claude API'] },
    { id: 'persona', file: 'lab-persona.html', ch: 'CH4', bg: '#FFBE1F', short: '페르소나 챗봇',
      title: '페르소나 챗봇', desc: '캐릭터를 고르거나 직접 만들어 대화합니다. 현재 시각 Tool, HTML 카드 Tool, 대화 기억이 동작하는 모습을 볼 수 있어요.',
      concepts: ['Deep Agents', 'Tool', 'Skill', 'Memory'] },
    { id: 'orchestra', file: 'lab-orchestra.html', ch: 'CH4', bg: '#0F8E6D', short: 'Agent 협업 그래프',
      title: 'Agent Orchestration 학습 앱', desc: '문장 하나가 Latte, Cat, Emoji, Feedback Agent를 거치며 바뀌는 과정을 그래프와 로그로 따라갑니다.',
      concepts: ['Tool 호출', 'MCP', 'A2A'] },
    { id: 'audit', file: 'lab-audit.html', ch: 'CH5', bg: '#101A3A', short: '보험심사팀',
      title: '보험금 지급 판단 Agent App', desc: '법률, 고객, 경영 전문가 Agent가 서로 피드백을 주고받으며 의견을 조율해 결론을 냅니다.',
      concepts: ['Supervisor', 'Full-Mesh', 'High Stakes'] }
  ];

  const sleep = ms => new Promise(r => setTimeout(r, matchMedia('(prefers-reduced-motion:reduce)').matches ? Math.min(ms, 30) : ms));
  const $ = (s, r = document) => r.querySelector(s);
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const nowTime = () => new Date().toLocaleTimeString('ko-KR', { hour12: false });

  // 글자가 한 글자씩 나오는 효과 (샘플 응답 연출용)
  async function typeInto(el, text, speed = 16) {
    el.textContent = '';
    for (const ch of text) { el.textContent += ch; if (speed) await sleep(speed); }
  }

  // 상단바: 실습 목록으로 돌아가기 + 현재 연결 상태 + 연결 해제
  function mountBar(title, ch) {
    if (!hasAccess()) { location.replace('index.html'); return; }
    const bar = document.createElement('header');
    bar.className = 'bar';
    bar.innerHTML = `
      <a class="back" href="gallery.html" aria-label="실습 목록으로">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M15 5l-7 7 7 7"/></svg>실습 목록</a>
      ${title ? `<div class="bar-title">${esc(title)} <span class="tag">${esc(ch)}</span></div>` : ''}
      <div class="sp"></div>
      <div class="conn" title="연결된 키"><i class="dot"></i><span>${esc(maskKey())}</span></div>
      <button class="btn ghost sm" id="disconnect">연결 해제</button>`;
    document.body.prepend(bar);
    $('#disconnect').onclick = () => { store.clear(); location.href = 'index.html'; };
  }

  // 실습 머리말(제목/설명/개념/동작 안내)
  function mountHead(lab, howto, live = false) {
    const el = document.createElement('div');
    el.innerHTML = `
      <div class="lab-head"><div><h1>${esc(lab.title)}</h1><p>${esc(lab.desc)}</p></div>
        <div class="concepts">${lab.concepts.map(c => `<span>${esc(c)}</span>`).join('')}</div></div>
      <details class="explain"><summary>어떻게 동작하나요?</summary><div>${howto}</div></details>
      ${live
        ? `<p class="demo-note"><b>실제 Claude가 동작합니다.</b> 입력한 API 키로 claude-sonnet-5-5를 호출하므로 사용한 만큼 비용이 발생해요.</p>`
        : `<p class="demo-note"><b>샘플 화면입니다.</b> 지금은 미리 정해 둔 응답으로 동작을 보여 주고, 백엔드를 연결하면 입력한 API 키로 실제 Claude를 호출합니다.</p>`}`;
    const bar = $('.bar');
    bar.after(...el.children);
  }

  // 백엔드 API 호출: 키를 헤더로 붙이고, 실패하면 {error, detail}을 담은 Error를 던진다.
  class ApiError extends Error { constructor(msg, detail) { super(msg); this.detail = detail || ''; } }
  // 방문자 번호: 이 브라우저를 구분하는 랜덤 번호. 캐릭터, 채팅, 사건, 문서가 이 번호별로 따로 저장된다.
  const visitorId = (() => {
    try {
      let v = localStorage.getItem('visitorId');
      if (!v || !/^[A-Za-z0-9_-]{16,64}$/.test(v)) {
        v = (crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2)).replace(/[^A-Za-z0-9_-]/g, '');
        localStorage.setItem('visitorId', v);
      }
      return v;
    } catch { return 'anon' + Date.now().toString(36) + Math.random().toString(36).slice(2, 12); }
  })();
  const MAX_UPLOAD = 4 * 1024 * 1024;   // 서버 요청 본문 한도(약 4.5MB)에 맞춘 파일 크기 한도
  async function api(path, { json, form, method } = {}) {
    const headers = { 'X-Claude-Key': store.get('apiKey'), 'X-Visitor-Id': visitorId };
    let body;
    if (json) { headers['content-type'] = 'application/json'; body = JSON.stringify(json); }
    if (form) body = form;
    let r;
    try { r = await fetch(path, { method: method || (body ? 'POST' : 'GET'), headers, body }); }
    catch (e) { throw new ApiError('서버에 연결하지 못했습니다. 서버가 켜져 있는지 확인해 주세요.', e.message); }
    if (r.ok) return r;
    const j = await r.json().catch(() => ({}));
    const msg = j.error || (typeof j.detail === 'string' ? j.detail : '요청을 처리하지 못했습니다.');
    throw new ApiError(msg, j.error ? j.detail : `HTTP ${r.status}`);
  }
  // SSE 스트림 읽기: 서버가 보내는 data: {...} 줄마다 onEvent를 부른다.
  async function readSSE(res, onEvent) {
    const reader = res.body.getReader(), dec = new TextDecoder(); let buf = '';
    for (;;) {
      const { value, done } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true });
      let i; while ((i = buf.indexOf('\n\n')) >= 0) {
        const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
        const line = chunk.split('\n').find(l => l.startsWith('data:'));
        if (line) onEvent(JSON.parse(line.slice(5)));
      }
    }
  }

  window.App = { visitorId, MAX_UPLOAD, api, readSSE, ApiError, store, hasAccess, maskKey, thumbs, LABS, sleep, $, esc, nowTime, typeInto, mountBar, mountHead };
})();
