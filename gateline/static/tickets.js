const currency = new Intl.NumberFormat('en-GB', {style: 'currency', currency: 'GBP'});
for (const form of document.querySelectorAll('.ticket-selection')) {
  const quantities = [...form.querySelectorAll('[name=ticket_quantities]')];
  function update() {
    const count = quantities.reduce((sum, input) => sum + (Number(input.value) || 0), 0);
    const pence = quantities.reduce((sum, input) => sum + (Number(input.value) || 0) * Math.round(Number(input.dataset.price) * 100), 0);
    const children = quantities.some(input => input.dataset.type === 'Under 11' && Number(input.value) > 0);
    const adult = quantities.some(input => input.dataset.adult === 'true' && Number(input.dataset.price) > 0 && Number(input.value) > 0);
    quantities[0]?.setCustomValidity(count < 1 ? 'Select at least one ticket.' : count > 10 ? 'Select a maximum of 10 tickets per booking.' : children && !adult ? 'Under 11 tickets require a paying adult in this booking.' : '');
    form.querySelector('.selection-total').textContent = `${count} ticket${count === 1 ? '' : 's'} · ${currency.format(pence / 100)}`;
  }
  form.addEventListener('input', update);
  form.addEventListener('submit', () => {
    const seats = form.querySelector('[name=seat_ids]');
    if (seats) seats.value = [...form.querySelectorAll('[name=seat_choice]:checked')].map(input => input.value).join(',');
  });
  update();
}
