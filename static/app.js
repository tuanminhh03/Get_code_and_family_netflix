// static/app.js (REPLACE your old file with this)
document.addEventListener('DOMContentLoaded', () => {
  const isAdminPage = window.location.pathname.startsWith('/admin');
  const emailInput = document.querySelector('input[name="email"]');
  const passInput  = document.querySelector('input[name="password"]');
  const btnLogin   = document.getElementById('btnLoginCode');
  const btnVerify  = document.getElementById('btnVerifyLink');
  const resEl      = document.getElementById('result');
  const form       = document.getElementById('fetchForm');
  const activityModal = document.getElementById('activityModal');
  const activitySubtitle = document.getElementById('activitySubtitle');
  const activityLogs = document.getElementById('activityLogs');

  if (!isAdminPage && !resEl) {
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

  function buildActivityHTML(log){
    const statusTag = log.success ? '<span class="tag-success">Thành công</span>' : '<span class="tag-fail">Thất bại</span>';
    const message = log.message ? log.message : '';
    const requester = log.requester_email ? `Requester: ${log.requester_email}` : '';
    const target = log.target_email ? `Target: ${log.target_email}` : '';
    const phone = log.phone ? `SĐT: ${log.phone}` : '';
    const metaParts = [statusTag, phone, requester, target].filter(Boolean);
    return `<div class="activity-item">
        <div class="activity-top">
          <div class="activity-kind">${log.kind}</div>
          <div class="activity-time">${log.created_at}</div>
        </div>
        <div class="activity-message">${message}</div>
        <div class="activity-meta">${metaParts.join(' • ')}</div>
      </div>`;
  }

  function renderActivityList(targetEl, logs, emptyHtml){
    if (!targetEl) return;
    if (!logs || logs.length === 0){
      targetEl.innerHTML = emptyHtml || '<div class="alert warn">Chưa có nhật ký hoạt động.</div>';
      return;
    }
    targetEl.innerHTML = logs.map(buildActivityHTML).join('');
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
      renderActivityList(activityLogs, data.logs);
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

    const activityFeed = document.getElementById('activityFeed');
    const activityRefreshBtn = document.getElementById('activityRefreshBtn');

    if (activityFeed){
      try {
        const initialData = JSON.parse(activityFeed.dataset.initialActivity || '[]');
        renderActivityList(activityFeed, initialData, '<div class="alert warn">Chưa có nhật ký hoạt động.</div>');
      } catch (_err){
        renderActivityList(activityFeed, [], '<div class="alert warn">Chưa có nhật ký hoạt động.</div>');
      }
    }

    async function refreshActivityFeed(){
      if (!activityFeed) return;
      activityFeed.innerHTML = '<div class="alert info">Đang tải nhật ký...</div>';
      try {
        const resp = await fetch('/admin/activity-feed');
        const data = await resp.json();
        if (!data?.success){
          activityFeed.innerHTML = `<div class="alert danger">${data?.message || 'Không thể tải nhật ký.'}</div>`;
          return;
        }
        renderActivityList(activityFeed, data.logs, '<div class="alert warn">Chưa có nhật ký hoạt động.</div>');
      } catch (_err){
        activityFeed.innerHTML = '<div class="alert danger">Lỗi khi tải nhật ký.</div>';
      }
    }

    activityRefreshBtn?.addEventListener('click', refreshActivityFeed);
    if (activityFeed){
      setInterval(refreshActivityFeed, 15000);
    }
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
});
