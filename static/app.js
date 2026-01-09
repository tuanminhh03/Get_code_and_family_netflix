// static/app.js (REPLACE your old file with this)
document.addEventListener('DOMContentLoaded', () => {
  const isAdminPage = window.location.pathname.startsWith('/admin');
  const isTvPage = window.location.pathname.startsWith('/tv');
  const emailInput = document.querySelector('input[name="email"]');
  const passInput  = document.querySelector('input[name="password"]');
  const btnLogin   = document.getElementById('btnLoginCode');
  const btnVerify  = document.getElementById('btnVerifyLink');
  const resEl      = document.getElementById('result');
  const form       = document.getElementById('fetchForm');
  const loginTvForm = document.getElementById('loginTvForm');
  const loginTvStatus = document.getElementById('loginTvStatus');
  const btnLoginTv = document.getElementById('btnLoginTv');
  const tvLoginPageForm = document.getElementById('tvLoginPageForm');
  const tvStatusBox = document.getElementById('tvStatusBox');
  const tvLoginPageBtn = document.getElementById('tvLoginPageBtn');
  const activityModal = document.getElementById('activityModal');
  const activitySubtitle = document.getElementById('activitySubtitle');
  const activityLogs = document.getElementById('activityLogs');

  if (!isAdminPage && !isTvPage && !resEl) {
    console.warn('result element not found (#result)');
    return;
  }

  // Prevent default form submit
  if (form) form.addEventListener('submit', (e) => e.preventDefault());

  function closeModal(){
    if (!activityModal) return;
    activityModal.classList.add('hidden');
  }

  function openModal(){
    if (!activityModal) return;
    activityModal.classList.remove('hidden');
  }

  if (activityModal){
    activityModal.querySelectorAll('[data-close-modal]').forEach((btn)=>{
      btn.addEventListener('click', closeModal);
    });
  }

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
    if (!resEl) return;
    resEl.innerHTML = `<div class="alert info">${msg}</div>`;
  }

  function showError(msg) {
    if (!resEl) return;
    resEl.innerHTML = `<div class="alert danger">❌ ${msg}</div>`;
  }

  function showWarn(msg) {
    if (!resEl) return;
    resEl.innerHTML = `<div class="alert warn">⚠️ ${msg}</div>`;
  }

  const buildStatusSteps = (steps = []) => {
    const items = steps.filter(Boolean);
    if (!items.length) return '';
    return `<div class="status-steps-list">${items
      .map((step) => `<div class="status-step"><span class="status-dot"></span>${step}</div>`)
      .join('')}</div>`;
  };

  const tvAccountIssueMessage = 'Tài khoản đăng nhập TV có vấn đề, đang đổi qua tài khoản mới.';

  function showSuccessBlock({ code, link, time, content, kind }) {
    const showCode = kind !== 'verify_link' && code;
    const showLink = kind !== 'login_code' && link;
    const showContent = content && (!showCode || !showLink);
    const allowDetails = !isAdminPage;
    const linkVisible = allowDetails && showLink;
    const contentVisible = allowDetails && showContent;
    const timeHtml = time ? `<div class="small muted">🕒 Thời gian nhận: ${time}</div>` : '';
    const codeLabel = kind === 'login_code' ? 'Mã đăng nhập' : 'Mã';
    const linkLabel = kind === 'verify_link' ? 'Link xác minh hộ gia đình' : 'Link';
    const codeHtml = showCode ? `<div class="result-line"><strong>${codeLabel}:</strong> <span class="mono">${code}</span></div>` : '';
    const linkHtml = linkVisible ? `<div class="result-line"><strong>${linkLabel}:</strong> <a href="${link}" target="_blank" rel="noopener noreferrer" class="result-link">${link}</a></div>` : '';
    const safeContent = content ? escapeHtml(content) : '';
    const contentHtml = contentVisible ? `<div class="result-line"><strong>Nội dung:</strong> <pre class="result-content">${safeContent}</pre></div>` : '';
    if (!resEl) return;

    resEl.innerHTML = `<div class="alert success">
        <div class="success-title">✅ Thành công</div>
        ${codeHtml}
        ${linkHtml}
        ${contentHtml}
        ${timeHtml}
        <div class="actions-row">
          ${showCode ? `<button id="copyCodeBtn" class="btn small">Sao chép mã</button>` : ''}
          ${linkVisible ? `<button id="openLinkBtn" class="btn small">Mở link</button>` : ''}
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
    if (openBtn && linkVisible) {
      openBtn.addEventListener('click', () => {
        window.open(link, '_blank', 'noopener');
      });
    }
    // auto-copy best candidate (link if exists, otherwise code)
    const toCopy = (linkVisible ? link : '') || (showCode ? code : '') || '';
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
        if (!displayCode && rawContent) {
          return showSuccessBlock({ code: '', link: '', time, content: rawContent, kind });
        }
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
        if (rawContent) {
          return showSuccessBlock({ code: '', link: '', time, content: rawContent, kind });
        }
        return showWarn(fallbackMsg);
      }

      showSuccessBlock({ code: displayCode, link: displayLink, time, content: rawContent, kind });
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

  // === Admin helpers ===
  const bulkDeleteForm = document.getElementById('bulkDeleteForm');
  const selectAllEmails = document.getElementById('selectAllEmails');
  const bulkDeleteBtn = document.getElementById('bulkDeleteBtn');
  const emailCheckboxes = bulkDeleteForm ? Array.from(bulkDeleteForm.querySelectorAll('.email-select')) : [];

  function refreshBulkDeleteState() {
    if (!bulkDeleteBtn) return;
    const checkedCount = emailCheckboxes.filter((cb) => cb.checked).length;
    bulkDeleteBtn.disabled = checkedCount === 0;
    if (selectAllEmails) {
      const allChecked = emailCheckboxes.length > 0 && checkedCount === emailCheckboxes.length;
      selectAllEmails.checked = allChecked;
      const someChecked = checkedCount > 0 && checkedCount < emailCheckboxes.length;
      selectAllEmails.indeterminate = someChecked;
    }
  }

  async function loadActivityLogs(customerId, phoneLabel){
    if (!activityLogs || !activitySubtitle) return;
    activityLogs.innerHTML = '<div class="alert info">Đang tải nhật ký...</div>';
    activitySubtitle.textContent = `Số điện thoại: ${phoneLabel}`;
    openModal();
    try {
      const resp = await fetch(`/admin/activity/${customerId}`);
      const data = await resp.json();
      if (!data?.success){
        activityLogs.innerHTML = `<div class="alert danger">${data?.message || 'Không thể tải nhật ký.'}</div>`;
        return;
      }
      if (!data.logs || data.logs.length === 0){
        activityLogs.innerHTML = '<div class="alert warn">Chưa có nhật ký hoạt động.</div>';
        return;
      }
      activityLogs.innerHTML = data.logs.map(log => {
        const statusTag = log.success ? '<span class="tag-success">Thành công</span>' : '<span class="tag-fail">Thất bại</span>';
        const message = log.message ? log.message : '';
        const requester = log.requester_email ? `Requester: ${log.requester_email}` : '';
        const target = log.target_email ? `Target: ${log.target_email}` : '';
        return `<div class="activity-item">
            <div class="activity-top">
              <div class="activity-kind">${log.kind}</div>
              <div class="activity-time">${log.created_at}</div>
            </div>
            <div class="activity-message">${message}</div>
            <div class="activity-meta">${statusTag}${requester ? ` • ${requester}` : ''}${target ? ` • ${target}` : ''}</div>
          </div>`;
      }).join('');
    } catch (err){
      activityLogs.innerHTML = '<div class="alert danger">Lỗi khi tải nhật ký.</div>';
    }
  }

  if (isAdminPage){
    document.querySelectorAll('.phone-log-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const customerId = btn.getAttribute('data-customer-id');
        const phone = btn.getAttribute('data-phone') || '';
        if (customerId){
          loadActivityLogs(customerId, phone);
        }
      });
    });
  }

  if (bulkDeleteForm) {
    selectAllEmails?.addEventListener('change', () => {
      emailCheckboxes.forEach((cb) => {
        cb.checked = !!selectAllEmails.checked;
      });
      refreshBulkDeleteState();
    });

    emailCheckboxes.forEach((cb) => cb.addEventListener('change', refreshBulkDeleteState));

    bulkDeleteForm.addEventListener('submit', (e) => {
      const hasSelection = emailCheckboxes.some((cb) => cb.checked);
      if (!hasSelection) {
        e.preventDefault();
        return;
      }
      if (!confirm('Xóa các email đã chọn?')) {
        e.preventDefault();
      }
    });

    refreshBulkDeleteState();
  }

  const emailCopySpans = document.querySelectorAll('.email-copy[data-copy-email]');
  function copyEmailValue(el) {
    const value = el?.dataset?.copyEmail || el?.textContent?.trim();
    if (!value) return;
    if (navigator.clipboard) {
      navigator.clipboard.writeText(value).catch(() => {});
    }
    el.classList.add('copied');
    setTimeout(() => el.classList.remove('copied'), 1200);
  }

  emailCopySpans.forEach((span) => {
    span.addEventListener('click', () => copyEmailValue(span));
    span.addEventListener('keypress', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        copyEmailValue(span);
      }
    });
    span.setAttribute('tabindex', '0');
    span.setAttribute('role', 'button');
    span.setAttribute('aria-label', 'Nhấp để sao chép email');
  });

  // === Login TV page (public) ===
  if (isTvPage && tvLoginPageForm && tvStatusBox) {
    const setTvStatus = (message, state = 'info') => {
      const cls = {
        info: 'alert info',
        success: 'alert success',
        warn: 'alert warn',
        danger: 'alert danger',
      }[state] || 'alert info';
      const title = state === 'success' ? 'Trạng thái đăng nhập' : 'Thông báo';
      tvStatusBox.innerHTML = `<div class="${cls}"><div class="status-title">${title}</div>${message}</div>`;
    };

    const validateCode = (value) => /^\d{8}$/.test((value || '').trim());

    tvLoginPageForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const password = tvLoginPageForm.querySelector('input[name="tv_password"]').value.trim();
      const code = tvLoginPageForm.querySelector('input[name="tv_code"]').value.trim();

      if (!password) {
        setTvStatus('Vui lòng nhập mật khẩu.', 'warn');
        return;
      }
      if (!validateCode(code)) {
        setTvStatus('Mã TV phải đủ 8 số.', 'warn');
        return;
      }

      setTvStatus(
        `<div class="status-summary">Hệ thống đang xử lý đăng nhập TV.</div>${buildStatusSteps([
          'Đang đăng nhập tài khoản...',
          'Đang nhập TV...',
        ])}`,
        'info'
      );
      tvLoginPageBtn?.setAttribute('disabled', 'disabled');

      try {
        const resp = await fetch('/api/tv-login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ password, code })
        });
        const data = await resp.json();
        const ok = resp.ok && data?.success;
        const msg = data?.message || (ok ? 'Đăng nhập thành công.' : tvAccountIssueMessage);

        // merged: show message + append chosen email if backend returns it
        const chosenEmail = data?.email;
        const detail = chosenEmail ? `${msg} (Email: ${chosenEmail})` : msg;

        setTvStatus(`<div class="status-summary">${detail}</div>`, ok ? 'success' : 'warn');

      } catch (err) {
        setTvStatus('<div class="status-summary">Lỗi khi gọi API đăng nhập TV.</div>', 'danger');
      } finally {
        tvLoginPageBtn?.removeAttribute('disabled');
      }
    });
  }

  // === Login TV (admin) ===
  if (loginTvForm && loginTvStatus) {
    const setStep = (message, state = 'info') => {
      const cls = {
        info: 'alert info',
        success: 'alert success',
        warn: 'alert warn',
        danger: 'alert danger',
      }[state] || 'alert info';
      loginTvStatus.innerHTML = `<div class="${cls}">${message}</div>`;
    };

    const renderTvAttempts = (payload) => {
      const attempts = Array.isArray(payload?.attempts) ? payload.attempts : [];
      const ok = !!payload?.success;
      const cls = ok ? 'alert success' : 'alert warn';
      const summary = payload?.message || (ok ? 'Đăng nhập thành công.' : tvAccountIssueMessage);
      const pool = Array.isArray(payload?.pool) ? payload.pool : [];
      const poolList = pool.map((p) => p.email).filter(Boolean).join(', ');
      const attemptsHtml = attempts
        .map((item, idx) => {
          const status = item.success ? '✅' : '⚠️';
          const note = item.message || (item.success ? 'Thành công' : tvAccountIssueMessage);
          const email = item.email || payload?.email || '—';
          return `<div class="result-line"><strong>Lần ${idx + 1}:</strong> <span class="mono">${email}</span> — ${status} ${note}</div>`;
        })
        .join('');
      const poolHtml = poolList ? `<div class="small muted">Danh sách xoay vòng: ${poolList}</div>` : '';
      loginTvStatus.innerHTML = `<div class="${cls}">${summary}${attemptsHtml ? `<div class="attempts">${attemptsHtml}</div>` : ''}${poolHtml}</div>`;
    };

    const validateCode = (value) => /^\d{8}$/.test((value || '').trim());

    loginTvForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const password = loginTvForm.querySelector('input[name="tv_password"]').value.trim();
      const code = loginTvForm.querySelector('input[name="tv_code"]').value.trim();

      if (!password) {
        setStep('Vui lòng nhập mật khẩu.', 'warn');
        return;
      }
      if (!validateCode(code)) {
        setStep('Mã TV phải đủ 8 số.', 'warn');
        return;
      }

      setStep(
        buildStatusSteps(['Đang đăng nhập tài khoản...', 'Đang nhập TV...']),
        'info'
      );
      btnLoginTv?.setAttribute('disabled', 'disabled');

      try {
        const resp = await fetch('/api/login-tv', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ password, code })
        });
        const data = await resp.json();

        if (!resp.ok) {
          setStep(data?.message || tvAccountIssueMessage, 'danger');
          return;
        }

        renderTvAttempts(data);
      } catch (err) {
        setStep('Lỗi khi gọi API đăng nhập TV.', 'danger');
      } finally {
        btnLoginTv?.removeAttribute('disabled');
      }
    });
  }
});
