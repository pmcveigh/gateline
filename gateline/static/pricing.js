const rows = document.querySelector('.pricing-rows');
const blank = rows.lastElementChild.cloneNode(true);
for (const input of blank.querySelectorAll('input')) input.value = '';
document.querySelector('#add-price-row').addEventListener('click', () => {
  const row = blank.cloneNode(true);
  rows.append(row);
  row.querySelector('input').focus();
});
rows.addEventListener('click', event => {
  if (event.target.closest('.remove-price-row')) event.target.closest('.pricing-row').remove();
});
