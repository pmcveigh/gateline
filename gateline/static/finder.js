const panel = document.querySelector('.finder-panel');
const opener = document.querySelector('.filter-open');
const closer = document.querySelector('.filter-close');
const actions = document.querySelector('.filter-actions');
const initialChoices = [...panel.querySelectorAll('a')].map(link => ({link, className: link.className, current: link.getAttribute('aria-current')}));
function resetChoices() {
  for (const {link, className, current} of initialChoices) {
    link.className = className;
    if (current) link.setAttribute('aria-current', current);
    else link.removeAttribute('aria-current');
  }
}
const mobile = window.matchMedia('(max-width: 1000px)');
let pendingUrl = window.location.href;
const filterMenus = [...document.querySelectorAll('.filter-menu')];
function closeFilters() { for (const menu of filterMenus) menu.open = false; }
function closePanel() {
  resetChoices();
  panel.close();
  opener.setAttribute('aria-expanded', 'false');
  document.body.style.overflow = '';
  opener.focus();
}
function syncLayout() {
  resetChoices();
  panel.close();
  document.body.style.overflow = '';
  opener.hidden = !mobile.matches;
  closer.hidden = !mobile.matches;
  actions.hidden = !mobile.matches;
  opener.setAttribute('aria-expanded', 'false');
  if (!mobile.matches) panel.show();
}
if (panel) {
  syncLayout();
  mobile.addEventListener('change', syncLayout);
  opener.addEventListener('click', () => {
    pendingUrl = window.location.href;
    panel.showModal();
    opener.setAttribute('aria-expanded', 'true');
    document.body.style.overflow = 'hidden';
  });
  // Closing without applying leaves the current filters unchanged.
  closer.addEventListener('click', closePanel);
  document.querySelector('.filter-cancel').addEventListener('click', closePanel);
  panel.addEventListener('cancel', event => { event.preventDefault(); closePanel(); });
  document.querySelector('.filter-apply').addEventListener('click', () => {
    window.location.assign(pendingUrl);
  });
  panel.addEventListener('click', event => {
    const link = event.target.closest('a');
    if (!mobile.matches || !link) return;
    event.preventDefault();
    const next = new URL(link.href);
    const pending = new URL(pendingUrl);
    const keys = link.classList.contains('reset-filters') ? ['venue', 'competition'] :
      [link.classList.contains('club-card') ? 'club' :
        (link.closest('.filter-menu') === filterMenus[0] ? 'venue' : 'competition')];
    for (const key of keys) {
      if (next.searchParams.has(key)) pending.searchParams.set(key, next.searchParams.get(key));
      else pending.searchParams.delete(key);
    }
    pendingUrl = pending.href;
    const group = link.closest('.club-picker, .filter-options');
    group?.querySelectorAll('a[aria-current]').forEach(item => {
      item.removeAttribute('aria-current');
      item.classList.remove('active', 'selected');
    });
    link.setAttribute('aria-current', 'true');
    link.classList.add(link.classList.contains('club-card') ? 'active' : 'selected');
  });
}
document.addEventListener('click', event => {
  if (!event.target.closest('.filter-menu')) closeFilters();
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') closeFilters();
});
