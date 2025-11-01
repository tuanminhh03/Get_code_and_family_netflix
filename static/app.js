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

  function showSuccessBlock({ code, link, time, kind }) {
    const showCode = kind !== 'verify_link' && code;
    const showLink = kind !== 'login_code' && link;
    const timeHtml = time ? `<div class="small muted">🕒 Thời gian nhận: ${time}</div>` : '';
    const codeLabel = kind === 'login_code' ? 'Mã đăng nhập' : 'Mã';
    const linkLabel = kind === 'verify_link' ? 'Link xác minh hộ gia đình' : 'Link';
    const codeHtml = showCode ? `<div class="result-line"><strong>${codeLabel}:</strong> <span class="mono">${code}</span></div>` : '';
    const linkHtml = showLink ? `<div class="result-line"><strong>${linkLabel}:</strong> <a href="${link}" target="_blank" rel="noopener noreferrer" class="result-link">${link}</a></div>` : '';
    resEl.innerHTML = `<div class="alert success">
        <div class="success-title">✅ Thành công</div>
        ${codeHtml}
        ${linkHtml}
        ${timeHtml}
        <div class="actions-row">
          ${showCode ? `<button id="copyCodeBtn" class="btn small">Sao chép mã</button>` : ''}
          ${showLink ? `<button id="openLinkBtn" class="btn small">Mở link</button>` : ''}
        </div>
      </div>`;

    // wire buttons
    const copyBtn = document.getElementById('copyCodeBtn');
    if (copyBtn && showCode) {
      copyBtn.addEventListener('click', () => {
        if (navigator.clipboard) navigator.clipboard.writeText(code).catch(()=>{});
      });
    }
    const openBtn = document.getElementById('openLinkBtn');
    if (openBtn && showLink) {
      openBtn.addEventListener('click', () => {
        window.open(link, '_blank', 'noopener');
      });
    }
    // auto-copy best candidate (link if exists, otherwise code)
    const toCopy = (showLink ? link : '') || (showCode ? code : '') || '';
    if (navigator.clipboard && toCopy) {
      navigator.clipboard.writeText(toCopy).catch(()=>{});
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
      const verifyLink = data.verify_link || data.link || extractFirstUrl(data.content) || extractFirstUrl(data.code) || null;
      const code = (data.code && String(data.code).trim())
        || (data.content && (data.content.match(/\b(\d{3,6})\b/) || [])[1])
        || null;
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
