"""Audience access, section allocation and account-owned season claims."""
from datetime import datetime, timezone
from decimal import Decimal
import secrets
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from .models import Customer, Event, EventInventory, Order, Reservation, SeasonTicket, SupporterProfile, Ticket
from .supporters import london_date, restriction, validate_attendees
from .ticketing import club_key, offered_classes, ticket_prefix


def valid_membership(st,event,club):
    return bool(st and st.active and st.club_name==club_key(club) and st.valid_from<=london_date(event.starts_at)<=st.valid_until)


def verify_away_membership(db,event,supporter,number=None,membership_id=None):
    st=db.get(SeasonTicket,membership_id) if membership_id else db.scalar(select(SeasonTicket).where(SeasonTicket.club_name==club_key(event.away_team),SeasonTicket.number==str(number or '').strip()))
    if not supporter or supporter.role!='supporter' or not st or st.user_id!=supporter.id or not valid_membership(st,event,event.away_team):
        raise ValueError(f'Enter a valid {event.away_team} season-ticket number belonging to your account')
    return st


def allocated_class(tc,inventory):
    if tc.section_id is not None and tc.section_id!=inventory.section_id: return False
    if tc.audience==inventory.audience: return True
    # Away accessibility tickets deliberately share the home Lower Grandstand.
    return tc.audience=='away' and inventory.audience=='home' and tc.section_id==inventory.section_id and restriction(tc)=='disability'


def classes_for_inventory(event,inventory,classes,audience='home'):
    return [tc for tc in classes if tc.audience==audience and allocated_class(tc,inventory)]


def claim_memberships(db,event,supporter):
    if not supporter or not event.season_claim_required: return []
    return [st for st in db.scalars(select(SeasonTicket).where(SeasonTicket.user_id==supporter.id)) if valid_membership(st,event,event.home_team)]


def claim_target(event,st):
    section_key=lambda name: {'grandstand lower':'lower grandstand'}.get(name.strip().casefold(),name.strip().casefold())
    inventory=next((inv for inv in event.inventories if inv.audience=='home' and section_key(inv.section.name)==section_key(st.section)),None)
    tc=next((tc for tc in offered_classes(event) if tc.maximum>0 and tc.audience=='home' and tc.name.casefold()==st.ticket_type.casefold() and inventory and allocated_class(tc,inventory)),None)
    if not inventory or not tc: raise ValueError('Your season-ticket section or type is unavailable for this fixture. Contact the club.')
    return inventory,tc


def claim_season_ticket(db,event_id,supporter,membership_id,seat_id=None):
    from .services import reserve
    event=db.get(Event,event_id);st=db.get(SeasonTicket,membership_id)
    if not event or not supporter or supporter.role!='supporter' or not st or st.user_id!=supporter.id or st not in claim_memberships(db,event,supporter):
        raise ValueError('A valid home season ticket belonging to your account is required for this claim')
    prior=db.scalar(select(Ticket).where(Ticket.event_id==event_id,Ticket.season_ticket_id==st.id))
    if prior:
        if prior.status not in ('sold','scanned'): raise ValueError('This claim was cancelled. Contact the club to arrange a replacement.')
        return prior.order
    inventory,tc=claim_target(event,st)
    profile=db.get(SupporterProfile,supporter.id)
    if restriction(tc) in ('vip','child'): validate_attendees(event,[(tc,1)],profile,0,[''])
    # The verified season category authorises the free claim, independently of
    # the paid basket's discount/guardian rules. The allocation was checked above.
    row=reserve(db,event.id,inventory.section_id,1,[seat_id] if seat_id else [],supporter=supporter)
    customer=Customer(full_name=st.full_name,email=st.email,**{key:getattr(profile,key) if profile else '' for key in ('address1','address2','city','postcode','country')})
    db.add(customer);db.flush()
    order=Order(reference='GL-'+secrets.token_hex(4).upper(),customer_id=customer.id,event_id=event.id,supporter_id=supporter.id,subtotal=Decimal('0'),discount=Decimal('0'),total=Decimal('0'),payment_status='successful',status='complete')
    db.add(order);db.flush()
    now=datetime.now(timezone.utc)
    changed=db.execute(update(Reservation).where(Reservation.id==row.id,Reservation.completed==False,Reservation.expires_at>now).values(completed=True).execution_options(synchronize_session='fetch'))
    if changed.rowcount!=1:
        db.rollback();raise ValueError('The claim reservation expired. Try again.')
    ticket=Ticket(public_id=ticket_prefix(event.home_team)+'-'+secrets.token_hex(6).upper(),qr_token=secrets.token_urlsafe(32),order_id=order.id,event_id=event.id,section_id=inventory.section_id,seat_id=seat_id,ticket_class_id=tc.id,price=Decimal('0'),status='sold',complimentary=True,attendee_user_id=supporter.id,attendee_birth_date=profile.birth_date if profile else None,season_ticket_id=st.id)
    db.add(ticket)
    try: db.commit()
    except IntegrityError:
        db.rollback()
        held=db.get(Reservation,row.id)
        if held and not held.completed: held.expires_at=now;db.commit()
        prior=db.scalar(select(Ticket).where(Ticket.event_id==event_id,Ticket.season_ticket_id==st.id,Ticket.status.in_(['sold','scanned'])))
        if prior: return prior.order
        raise ValueError('This ticket could not be claimed. Try another available seat.')
    return order
