const money = new Intl.NumberFormat('en-GB', {style: 'currency', currency: 'GBP'});
const form = document.querySelector('#checkout-form');
const member = form.querySelector('[name=vip_season_holder]');
const legacy = document.querySelector('#legacy-class');
function updateBooking() {
  const lines = [...document.querySelectorAll('.booking-line')];
  let pence = 0;
  let vipCount = 0;
  for (const line of lines) {
    const count = Number(line.dataset.quantity);
    const vip = line.dataset.vip === 'true';
    if (vip) vipCount += count;
    const unit = vip && member?.checked ? 5000 : Math.round(Number(line.dataset.price) * 100);
    pence += unit * count;
    line.querySelector('.booking-line-price').textContent = money.format(unit * count / 100);
  }
  if (legacy) {
    const selected = legacy.selectedOptions[0];
    const count = Number(legacy.dataset.quantity);
    vipCount = selected?.dataset.vip === 'true' ? count : 0;
    pence = (vipCount && member?.checked ? 5000 : Math.round(Number(selected?.dataset.price || 0) * 100)) * count;
  }
  const discount = document.querySelector('#vip-discount');
  if (discount) discount.hidden = !vipCount;
  if (member) member.disabled = !vipCount;
  const number = document.querySelector('#season-ticket-number');
  number.required = !!(vipCount && member?.checked);
  const attendeeSection = document.querySelector('#vip-attendees');
  attendeeSection.hidden = !vipCount;
  const dates = document.querySelector('#vip-birth-dates');
  while (dates.children.length > vipCount) dates.lastElementChild.remove();
  while (dates.children.length < vipCount) {
    const label = document.createElement('label');
    label.textContent = `VIP attendee ${dates.children.length + 1} date of birth`;
    const input = document.createElement('input');
    input.type = 'date'; input.name = 'vip_birth_dates'; input.required = true;
    label.append(input); dates.append(label);
  }
  document.querySelector('#booking-total').textContent = money.format(pence / 100);
}
form.addEventListener('change', updateBooking);
updateBooking();
const timer = document.querySelector('.reservation-timer');
const initialRemaining = Number(timer.dataset.expires) - Number(timer.dataset.serverNow);
const started = performance.now();
function tick() {
  const remaining = Math.max(0, Math.ceil((initialRemaining - (performance.now() - started)) / 1000));
  document.querySelector('#reservation-countdown').textContent = `${String(Math.floor(remaining / 60)).padStart(2, '0')}:${String(remaining % 60).padStart(2, '0')}`;
  if (!remaining) {
    document.querySelector('#complete-payment').disabled = true;
    document.querySelector('#reservation-expired').hidden = false;
    return false;
  }
  return true;
}
if (tick()) {
  const interval = setInterval(() => { if (!tick()) clearInterval(interval); }, 250);
}
window.addEventListener('pageshow', tick);
