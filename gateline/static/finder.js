const panel = document.querySelector('.finder-panel');
const form = document.querySelector('#fixture-filters');
const opener = document.querySelector('.filter-open');
const closer = document.querySelector('.filter-close');
const actions = document.querySelector('.filter-actions');
const mobile = window.matchMedia('(max-width: 1000px)');
const choices = [...form.querySelectorAll('input[type=checkbox]')];
const applied = choices.map(input => input.checked);
function restoreChoices() { choices.forEach((input, index) => input.checked = applied[index]); }
function closePanel() {
  restoreChoices();
  panel.close();
  opener.setAttribute('aria-expanded', 'false');
  document.body.style.overflow = '';
  opener.focus();
}
function syncLayout() {
  restoreChoices();
  panel.close();
  document.body.style.overflow = '';
  opener.hidden = !mobile.matches;
  closer.hidden = !mobile.matches;
  actions.hidden = !mobile.matches;
  opener.setAttribute('aria-expanded', 'false');
  if (!mobile.matches) panel.show();
}
syncLayout();
mobile.addEventListener('change', syncLayout);
opener.addEventListener('click', () => {
  panel.showModal();
  opener.setAttribute('aria-expanded', 'true');
  document.body.style.overflow = 'hidden';
});
closer.addEventListener('click', closePanel);
document.querySelector('.filter-cancel').addEventListener('click', closePanel);
panel.addEventListener('cancel', event => { event.preventDefault(); closePanel(); });
document.querySelector('.reset-filters').addEventListener('click', () => {
  choices.forEach(input => input.checked = false);
  if (!mobile.matches) form.requestSubmit();
});
