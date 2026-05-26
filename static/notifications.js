document.addEventListener('DOMContentLoaded', function () {
  const badgeSelector = '#notif-badge';
  const notifLink = document.querySelector('a[href="/notifications"]');

  async function updateCount() {
    try {
      const resp = await fetch('/notifications/count');
      if (!resp.ok) return;
      const data = await resp.json();
      let badge = document.querySelector(badgeSelector);
      if (!badge && notifLink) {
        badge = document.createElement('span');
        badge.id = 'notif-badge';
        badge.className = 'badge-count';
        badge.style.display = 'none';
        notifLink.appendChild(badge);
      }
      if (!badge) return;
      const count = data.count || 0;
      if (count > 0) {
        badge.textContent = count;
        badge.style.display = 'inline-block';
      } else {
        badge.style.display = 'none';
      }
    } catch (e) {
      // ignore
    }
  }

  updateCount();
  setInterval(updateCount, 10000);
});
