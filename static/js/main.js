/* =====================================================
   CareForNow - main.js
   Shared JS utilities loaded on every page
   ===================================================== */

// ---- TOAST NOTIFICATION ----
function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  if (!container) return;
  const icons = { success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️' };
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `<span>${icons[type] || 'ℹ️'}</span><span>${message}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(60px)';
    toast.style.transition = 'all 0.3s';
    setTimeout(() => toast.remove(), 300);
  }, 3700);
}

// ---- FORMAT CURRENCY ----
function formatINR(amount) {
  return '₹' + Number(amount).toLocaleString('en-IN');
}

// ---- CONFIRM DIALOG ----
function confirmAction(message, callback) {
  if (window.confirm(message)) callback();
}

// ---- ACTIVE NAV LINK HIGHLIGHT ----
document.addEventListener('DOMContentLoaded', () => {
  const path = window.location.pathname;
  document.querySelectorAll('.nav-links a').forEach(link => {
    if (link.getAttribute('href') === path) {
      link.classList.add('active');
    }
  });

  // Auto-dismiss any flash alerts after 4s
  document.querySelectorAll('.alert[data-auto-dismiss]').forEach(el => {
    setTimeout(() => el.remove(), 4000);
  });

  // Animate stat values counting up
  document.querySelectorAll('.stat-value[data-count]').forEach(el => {
    const target = parseInt(el.dataset.count);
    let count = 0;
    const step = Math.ceil(target / 30);
    const timer = setInterval(() => {
      count = Math.min(count + step, target);
      el.textContent = count.toLocaleString('en-IN');
      if (count >= target) clearInterval(timer);
    }, 30);
  });
});

// ---- FORM HELPER: disable submit on enter for multi-step forms ----
document.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && e.target.tagName === 'INPUT') {
    const form = e.target.closest('[data-multistep]');
    if (form) e.preventDefault();
  }
});
