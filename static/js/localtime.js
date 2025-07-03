// Convert UTC timestamps in elements with data-utc to local time
// Format: 01 Jan '25 10:00 am

document.addEventListener('DOMContentLoaded', () => {
  const elements = document.querySelectorAll('[data-utc]');
  elements.forEach(el => {
    let iso = el.getAttribute('data-utc');
    if (!iso) return;
    if (!iso.endsWith('Z') && !iso.includes('+')) {
      iso += 'Z';
    }
    const date = new Date(iso);
    if (isNaN(date)) return;
    const dayMonth = new Intl.DateTimeFormat('en-GB', { day: '2-digit', month: 'short' }).format(date);
    const year = new Intl.DateTimeFormat('en-US', { year: '2-digit' }).format(date);
    const time = new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit', hour12: true }).format(date).toLowerCase();
    el.textContent = `${dayMonth} '${year} ${time}`;
  });
});
