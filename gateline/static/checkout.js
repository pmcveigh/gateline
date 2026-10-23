const money = new Intl.NumberFormat('en-GB', {style: 'currency', currency: 'GBP'});
const form = document.querySelector('#checkout-form');
const member = form.querySelector('[name=vip_season_holder]');
const legacy = document.querySelector('#legacy-class');
const personal = form.dataset.personal === 'true';
const cards = document.querySelector('#attendee-fields');
let legacySelection = cards.children.length ? legacy?.value || '' : '';
function rebuildLegacy() {
  if (!legacy || legacy.value === legacySelection) return;
  legacySelection = legacy.value;
  cards.replaceChildren();
  const option = legacy.selectedOptions[0];
  if (!legacy.value) return;
  for (let i = 0; i < Number(legacy.dataset.quantity); i++) {
    const card = document.createElement('div');card.className = 'attendee';
    card.dataset.kind = option.dataset.kind;card.dataset.price = option.dataset.price;card.dataset.vip = option.dataset.vip;
    const title = document.createElement('b');title.textContent = `Ticket ${i + 1} · ${option.textContent}`;card.append(title);
    if (personal) {
      const label = document.createElement('label');label.className = 'checkbox-label';
      const radio = document.createElement('input');radio.type = 'radio';radio.name = 'personal_index';radio.value = i;radio.checked = i === 0;
      label.append(radio, 'This is my ticket');card.append(label);
    }
    const nameLabel = document.createElement('label');nameLabel.textContent = "Ticket holder's full name";
    const fullName = document.createElement('input');fullName.name = 'attendee_names';fullName.required = true;fullName.maxLength = 120;nameLabel.append(fullName);card.append(nameLabel);
    const label = document.createElement('label');label.textContent = 'Attendee date of birth';label.className = 'attendee-dob';
    const born = document.createElement('input');born.name = 'attendee_birth_dates';
    if (['vip','child','concession'].includes(card.dataset.kind)) { born.type = 'date';label.append(born);card.append(label); }
    else { born.type = 'hidden';card.append(born); }
    if (['concession', 'disability'].includes(card.dataset.kind)) {
      const access = document.createElement('label');access.className = 'checkbox-label guest-disability';
      const box = document.createElement('input');box.type = 'checkbox';box.name = 'disability_indices';box.value = i;
      access.append(box,'Disability concession / access eligibility for this guest');card.append(access);
    }
    const detail = document.createElement('small');
    detail.textContent = card.dataset.kind === 'concession' ? `Under ${option.dataset.under} or over ${option.dataset.over}, or disability concession.` : card.dataset.kind === 'child' ? 'Under 11, with a paying adult.' : card.dataset.kind === 'vip' ? 'Aged 18 and above.' : '';
    card.append(detail);cards.append(card);
  }
}
function updateBooking() {
  rebuildLegacy();
  const attendees = [...cards.querySelectorAll('.attendee')];
  const ownIndex = personal ? Number(form.querySelector('[name=personal_index]:checked')?.value ?? -1) : -1;
  attendees.forEach((card,index) => {
    const own = index === ownIndex;
    const wasOwn = card.dataset.own === 'true';
    const name = card.querySelector('[name=attendee_names]');
    if (own && !wasOwn) { name.dataset.guestValue = name.value;name.value = form.dataset.fullName; }
    if (!own && wasOwn) name.value = name.dataset.guestValue || '';
    name.readOnly = own;
    const date = card.querySelector('[name=attendee_birth_dates]');
    const access = card.querySelector('[name=disability_indices]');
    if (access) { access.disabled = own;access.closest('label').hidden = own; }
    const forced = own ? form.dataset.forceConcession === 'true' : !!access?.checked;
    const ageRequired = ['vip','child'].includes(card.dataset.kind) || (card.dataset.kind === 'concession' && !forced);
    if (date.type === 'date') {
      if (own && !wasOwn && form.dataset.birthDate) { date.dataset.guestValue = date.value;date.value = form.dataset.birthDate; }
      if (!own && wasOwn && form.dataset.birthDate) date.value = date.dataset.guestValue || '';
      date.readOnly = own && !!form.dataset.birthDate;
      date.required = ageRequired;
      date.closest('label').hidden = !ageRequired;
    }
    card.dataset.own = String(own);
  });
  const vipCount = attendees.filter(card => card.dataset.vip === 'true').length;
  const ownVip = ownIndex >= 0 && attendees[ownIndex]?.dataset.vip === 'true';
  const discountAllowed = personal ? ownVip : vipCount > 0;
  const discount = document.querySelector('#vip-discount');
  if (discount) discount.hidden = !vipCount;
  if (member) { member.disabled = !discountAllowed;if (!discountAllowed) member.checked = false; }
  document.querySelector('#season-ticket-number').required = !!(discountAllowed && member?.checked);
  let pence = 0;
  for (const [index,card] of attendees.entries()) {
    const discounted = card.dataset.vip === 'true' && member?.checked && (!personal || index === ownIndex);
    pence += discounted ? 5000 : Math.round(Number(card.dataset.price) * 100);
  }
  for (const line of document.querySelectorAll('.booking-line')) {
    const count = Number(line.dataset.quantity);
    const off = line.dataset.vip === 'true' && member?.checked ? (personal ? 1 : count) * (Math.round(Number(line.dataset.price) * 100) - 5000) : 0;
    line.querySelector('.booking-line-price').textContent = money.format((Math.round(Number(line.dataset.price)*100)*count-off)/100);
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
