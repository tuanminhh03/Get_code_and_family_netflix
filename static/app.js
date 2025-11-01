// static/app.js (REPLACE your old file with this)
document.addEventListener('DOMContentLoaded', () => {
  const emailInput = document.querySelector('input[name="email"]');
  const passInput  = document.querySelector('input[name="password"]');
  const btnLogin   = document.getElementById('btnLoginCode');
  const btnVerify  = document.getElementById('btnVerifyLink');
  const resEl      = document.getElementById('result');
  const form       = document.getElementById('fetchForm');

  if (!resEl) {
    console.warn('result element not found (#result)');
    return;
  }

  // Prevent default form submit
  if (form) form.addEventListener('submit', (e) => e.preventDefault());

  // helper: extract first URL from text
  function extractFirstUrl(text) {
    if (!text) return null;
    const urlRegex = /(https?:\/\/[^\s"'<>]+)/i;
    const m = text.match(urlRegex);
    return m ? m[0] : null;
  }

  // helper: format timestamp (fallback to now)
  function formatTimestamp(ts) {
    if (!ts) return new Date().toLocaleString();
    try {
      const d = new Date(ts);
      if (!isNaN(d)) return d.toLocaleString();
      return ts;
    } catch (e) { return ts; }
  }

  function setLoading(msg = 'Đang lấy dữ liệu...') {
    resEl.innerHTML = `<div class="alert info">${msg}</div>`;
  }

  function showError(msg) {
    resEl.innerHTML = `<div class="alert danger">❌ ${msg}</div>`;
  }

  function showWarn(msg) {
    resEl.innerHTML = `<div class="alert warn">⚠️ ${msg}</div>`;
  }

  function showSuccessBlock({ code, link, time, raw }) {
    const timeHtml = time ? `<div class="small muted">Thời gian: ${time}</div>` : '';
    const codeHtml = code ? `<div class="result-line"><strong>Mã:</strong> <span class="mono">${code}</span></div>` : '';
    const linkHtml = link ? `<div class="result-line"><strong>Link:</strong> <a href="${link}" target="_blank" rel="noopener noreferrer" class="result-link">${link}</a></div>` : '';
    // "Xem đầy đủ" to show raw if needed
    const rawToggle = raw ? `<details class="raw-box"><summary>Xem nội dung đầy đủ</summary><pre>${escapeHtml(raw)}</pre></details>` : '';
    resEl.innerHTML = `<div class="alert success">
        <div class="success-title">✅ Thành công</div>
        ${codeHtml}
        ${linkHtml}
        ${timeHtml}
        ${rawToggle}
        <div class="actions-row">
          ${code ? `<button id="copyCodeBtn" class="btn small">Sao chép mã</button>` : ''}
          ${link ? `<button id="openLinkBtn" class="btn small">Mở link</button>` : ''}
        </div>
      </div>`;

    // wire buttons
    const copyBtn = document.getElementById('copyCodeBtn');
    if (copyBtn && code) {
      copyBtn.addEventListener('click', () => {
        if (navigator.clipboard) navigator.clipboard.writeText(code).catch(()=>{});
      });
    }
    const openBtn = document.getElementById('openLinkBtn');
    if (openBtn && link) {
      openBtn.addEventListener('click', () => {
        window.open(link, '_blank', 'noopener');
      });
    }
    // auto-copy best candidate (link if exists, otherwise code)
    const toCopy = link || code || '';
    if (navigator.clipboard && toCopy) {
      navigator.clipboard.writeText(toCopy).catch(()=>{});
    }
  }

  function escapeHtml(s) {
    return (s || '').toString()
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  async function callAPI(kind) {
    const email = (emailInput?.value || '').trim();
    const password = (passInput?.value || '').trim();

    if (!email) return showWarn('Vui lòng nhập email.');

    setLoading();

    try {
      const resp = await fetch('/api/fetch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password, kind })
      });

      let data;
      try { data = await resp.json(); } catch (e) {
        return showError('Phản hồi từ server không phải JSON.');
      }

      if (!data || data.success !== true) {
        const m = data && data.message ? data.message : 'Phản hồi không thành công từ server.';
        return showWarn(m);
      }

      // Prefer explicit fields from backend
      // possible keys: verify_link, code, content, received_at_raw, timestamp
      const verifyLink = data.verify_link || data.link || extractFirstUrl(data.content) || extractFirstUrl(data.code) || null;
      const code = (data.code && String(data.code).trim()) || (data.content && (data.content.match(/\b(\d{3,6})\b/) || [])[1]) || null;
      const timeRaw = data.received_at_raw || data.timestamp || data.time || null;
      const time = timeRaw ? formatTimestamp(timeRaw) : formatTimestamp(null);

      // If kind is verify_link but no explicit link found, try parse from message
      if (kind === 'verify_link' && !verifyLink) {
        // try to find a long netflix url pattern
        const candidate = extractFirstUrl(JSON.stringify(data));
        if (candidate) {
          // use candidate
        }
      }

      // Show cleaned result (only code or link + time)
      showSuccessBlock({ code, link: verifyLink, time, raw: data.content || JSON.stringify(data, null, 2) });
    } catch (err) {
      showError(`Lỗi khi gọi API: ${err}`);
    }
  }

  // ensure buttons not submit form
  [btnLogin, btnVerify].forEach(b => {
    if (b && !b.getAttribute('type')) b.setAttribute('type', 'button');
  });

  btnLogin?.addEventListener('click', () => callAPI('login_code'));
  btnVerify?.addEventListener('click', () => callAPI('verify_link'));
});
