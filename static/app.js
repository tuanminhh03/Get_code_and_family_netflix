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

  function extractNumericCode(text) {
    if (!text) return null;
    const asString = String(text);
    const direct = asString.match(/\b(\d{3,10})\b/);
    if (direct) return direct[1];
    const compact = asString.replace(/[^0-9]/g, '');
    if (compact.length >= 3 && compact.length <= 10) return compact;
    return null;
  }

  function escapeHtml(str) {
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function resolveDisplayTime(data) {
    const raw = data?.received_at_raw || data?.timestamp_raw || data?.timestamp || null;
    const iso = data?.received_at || data?.timestamp_iso || null;
    const serverRaw = data?.server_time_raw || null;

    if (raw) return raw;
    if (serverRaw) return serverRaw;
    if (iso) {
      try {
        const d = new Date(iso);
        if (!isNaN(d)) return d.toLocaleString();
      } catch (e) {}
      return iso;
    }

    return new Date().toLocaleString();
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

  function showSuccessBlock({ code, link, time, kind, status }) {
    const statusText = status || 'Thành công';
    const showCode = kind !== 'verify_link' && Boolean(code);
    const showLink = kind !== 'login_code' && Boolean(link);
    const timeHtml = time
      ? `<div class="result-row"><span class="result-label">Thời gian nhận</span><span class="result-value">${escapeHtml(time)}</span></div>`
      : '';

    const codeLabel = kind === 'login_code' ? 'Mã đăng nhập' : 'Mã';
    const linkLabel = kind === 'verify_link' ? 'Link xác minh hộ gia đình' : 'Link';
    const codeHtml = showCode
      ? `<div class="result-row"><span class="result-label">${codeLabel}</span><span class="result-value mono">${escapeHtml(code)}</span></div>`
      : '';
    const linkHtml = showLink
      ? `<div class="result-row"><span class="result-label">${linkLabel}</span><a href="${escapeHtml(link)}" target="_blank" rel="noopener noreferrer" class="result-value result-link">${escapeHtml(link)}</a></div>`
      : '';

    const copyButtonLabel = showCode ? 'Sao chép mã' : 'Sao chép link';
    const copyButtonId = showCode ? 'copyCodeBtn' : 'copyLinkBtn';
    const statusHtml = `<div class="result-row"><span class="result-label">Trạng thái</span><span class="result-value status-success">✅ ${escapeHtml(statusText)}</span></div>`;

    resEl.innerHTML = `<div class="alert success result-card">
        <div class="result-grid">
          ${statusHtml}
          ${codeHtml}
          ${linkHtml}
          ${timeHtml}
        </div>
        <div class="actions-row">
          ${(showCode || showLink) ? `<button id="${copyButtonId}" class="btn small">${copyButtonLabel}</button>` : ''}
          ${showLink ? `<button id="openLinkBtn" class="btn small">Mở link</button>` : ''}
        </div>
      </div>`;

    const toCopy = showLink ? link : (showCode ? code : '');

    const copyBtn = document.getElementById(copyButtonId);
    if (copyBtn && (showCode || showLink)) {
      copyBtn.addEventListener('click', () => {
        if (navigator.clipboard && toCopy) {
          navigator.clipboard.writeText(toCopy).catch(() => {});
        }
      });
    }

    const openBtn = document.getElementById('openLinkBtn');
    if (openBtn && showLink) {
      openBtn.addEventListener('click', () => {
        window.open(link, '_blank', 'noopener');
      });
    }

    if (navigator.clipboard && toCopy) {
      navigator.clipboard.writeText(toCopy).catch(() => {});
    }
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
      // possible keys: verify_link, code, content, received_at_raw, received_at, timestamp
      const rawContent = (data.content && String(data.content).trim()) || '';
      const codeRaw = (data.code && String(data.code).trim()) || '';
      const verifyLink = data.verify_link || data.link || extractFirstUrl(rawContent) || extractFirstUrl(codeRaw) || null;
      let code = codeRaw || null;
      if (!code) {
        code = extractNumericCode(rawContent);
      } else {
        const normalized = extractNumericCode(codeRaw);
        if (normalized) code = normalized;
      }
      const time = resolveDisplayTime(data);

      // If kind is verify_link but no explicit link found, try parse from message
      if (kind === 'verify_link' && !verifyLink) {
        const candidate = extractFirstUrl(JSON.stringify(data));
        if (candidate) {
          // could assign candidate if you want stricter fallback:
          // verifyLink = candidate;
        }
      }

      // Show cleaned result (only code or link + time as requested)
      let displayCode = code;
      let displayLink = verifyLink;

      if (kind === 'login_code') {
        displayLink = null;
        if (!displayCode) {
          return showWarn('Chưa có mã đăng nhập, vui lòng bấm lại.');
        }
      } else if (kind === 'verify_link') {
        displayCode = null;
        if (!displayLink) {
          return showWarn('Chưa có mã hộ gia đình, hãy bấm lại.');
        }
      }

      if (!displayCode && !displayLink) {
        const fallbackMsg = kind === 'login_code'
          ? 'Chưa có mã đăng nhập, vui lòng bấm lại.'
          : 'Chưa có mã hộ gia đình, hãy bấm lại.';
        return showWarn(fallbackMsg);
      }

      showSuccessBlock({ code: displayCode, link: displayLink, time, kind });
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
