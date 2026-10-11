const sidebar = document.querySelector('.sidebar-panel');
if (sidebar && window.matchMedia('(max-width: 900px)').matches) sidebar.open = false;
const filterMenus = [...document.querySelectorAll('.filter-menu')];
function closeFilters() { for (const menu of filterMenus) menu.open = false; }
document.addEventListener('click', event => {
  if (!event.target.closest('.filter-menu')) closeFilters();
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') {
    const open = filterMenus.find(menu => menu.open);
    closeFilters();
    open?.querySelector('summary').focus();
  }
});
