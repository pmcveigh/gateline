from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import json, secrets
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from .models import *
from .ticketing import club_key, is_adult, selected_classes, ticket_prefix, validate_vip_ages
from .supporters import london_date, scan_season_ticket, validate_attendees
from .allocations import allocated_class, verify_away_membership

def utc(value: datetime) -> datetime:
    """Return a comparable UTC datetime (SQLite drops timezone metadata)."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

class PaymentResult:
    def __init__(self, successful: bool): self.successful=successful; self.reference="TEST-"+secrets.token_hex(5).upper()
class PaymentService:
    def charge(self, amount: Decimal, test_result: str) -> PaymentResult: raise NotImplementedError
class SimulatedPaymentService(PaymentService):
    def charge(self, amount: Decimal, test_result: str) -> PaymentResult: return PaymentResult(test_result == "success")

def reserve(db:Session,event_id:int,section_id:int,quantity:int,seat_ids:list[int],selection=None,*,supporter=None,away_season_number=None) -> Reservation:
    now=datetime.now(timezone.utc); event=db.get(Event,event_id); section=db.get(Section,section_id); inv=db.scalar(select(EventInventory).where(EventInventory.event_id==event_id,EventInventory.section_id==section_id))
    if not event or not section or not inv or quantity < 1 or quantity > 10: raise ValueError("Invalid ticket selection")
    if not event.published or event.cancelled or event.sales_suspended or now < utc(event.sales_open) or now > utc(event.sales_close): raise ValueError("Tickets are not currently on sale")
    stand=db.get(Stand,section.stand_id)
    if not stand or stand.venue_id != event.venue_id: raise ValueError("Section does not belong to this fixture venue")
    if section.mode!='assigned' and seat_ids: raise ValueError("This section does not use assigned seats")
    lines=selected_classes(event,selection,quantity) if selection is not None else []
    if any(not allocated_class(tc,inv) for tc,_ in lines): raise ValueError("Choose a ticket type available in this section")
    away=inv.audience=='away' or any(tc.audience=='away' for tc,_ in lines)
    membership=verify_away_membership(db,event,supporter,away_season_number) if away else None
    if inv.audience=='away' and selection is None: raise ValueError("Choose an away ticket type")
    active=select(Reservation).where(Reservation.event_id==event_id,Reservation.section_id==section_id,Reservation.completed==False,Reservation.expires_at>now)
    sold_qty=db.scalar(select(func.count(Ticket.id)).where(Ticket.event_id==event_id,Ticket.section_id==section_id,Ticket.status.in_(["sold","scanned"]))) or 0
    held_qty=db.scalar(select(func.coalesce(func.sum(Reservation.quantity),0)).where(Reservation.event_id==event_id,Reservation.section_id==section_id,Reservation.completed==False,Reservation.expires_at>now)) or 0
    if sold_qty+held_qty+quantity > inv.capacity-inv.held: raise ValueError("Your selected tickets are unavailable. Please change your selection.")
    if section.mode==Mode.ASSIGNED.value:
        if len(seat_ids)!=quantity or len(set(seat_ids))!=quantity: raise ValueError("Select distinct seats for every ticket")
        valid=set(db.scalars(select(Seat.id).join(SeatRow).where(SeatRow.section_id==section_id,Seat.id.in_(seat_ids),Seat.available==True)).all())
        if valid != set(seat_ids): raise ValueError("A selected seat is invalid or unavailable")
        sold=set(db.scalars(select(Ticket.seat_id).where(Ticket.event_id==event_id,Ticket.status.in_(["sold","scanned"]),Ticket.seat_id.in_(seat_ids))).all())
        held=set(db.scalars(active.where(Reservation.seat_id.in_(seat_ids)).with_only_columns(Reservation.seat_id)).all())
        if sold or held: raise ValueError("A selected seat is no longer available")
    token=secrets.token_urlsafe(20); expiry=min(now+timedelta(minutes=10),utc(event.sales_close))
    # One reservation row per assigned seat preserves the database uniqueness guard.
    rows=[]
    for seat in (seat_ids if seat_ids else [None]):
        row=Reservation(token=token if not rows else token+f"-{len(rows)}",event_id=event_id,section_id=section_id,seat_id=seat,quantity=1 if seat else quantity,expires_at=expiry,selection_json=json.dumps({"classes":selection or {},"root":token,"away_season_ticket_id":membership.id if membership else None,"supporter_id":supporter.id if membership else None})); db.add(row); rows.append(row)
    db.commit(); return rows[0]

def voucher_discount(db, code, event_id, subtotal):
    if not code:return Decimal("0")
    now=datetime.now(timezone.utc); v=db.scalar(select(Voucher).where(func.upper(Voucher.code)==code.upper()))
    if not v or not v.enabled or utc(v.starts_at)>now or utc(v.expires_at)<now or v.uses>=v.maximum_uses or (v.event_id and v.event_id!=event_id): raise ValueError("Voucher code is not valid")
    return min(subtotal, v.value if v.kind=="fixed" else subtotal*v.value/100)

def reservation_rows(db, token):
    # Compare the generated seat tokens literally; do not use LIKE wildcards.
    first=db.scalar(select(Reservation).where(Reservation.token==token))
    if not first: return []
    stored=json.loads(first.selection_json or "{}")
    if stored.get("root") and stored["root"]!=token: return []
    if first.seat_id is None: return [first]
    return db.scalars(select(Reservation).where(Reservation.token.in_([token]+[f"{token}-{i}" for i in range(1,10)])).order_by(Reservation.id)).all()


def checkout(db:Session, reservation_token:str, class_id:int|None, customer_data:dict, payment_result="success", priority_code=None, voucher_code=None, vip_season_holder=False, vip_birth_dates=(), *, supporter=None, personal_index=None, attendee_birth_dates=None, disability_indices=()):
    now=datetime.now(timezone.utc); reservations=reservation_rows(db,reservation_token)
    if not reservations or any(r.completed or utc(r.expires_at)<=now for r in reservations): raise ValueError("Reservation has expired or has already been completed")
    event=db.get(Event,reservations[0].event_id); qty=sum(r.quantity for r in reservations)
    if not event.published or event.cancelled or event.sales_suspended or now < utc(event.sales_open) or now > utc(event.sales_close): raise ValueError("Tickets are not currently on sale")
    stored=json.loads(reservations[0].selection_json or "{}")
    selection=stored.get("classes",stored) or {class_id:qty}
    lines=selected_classes(event,selection,qty)
    inventory=db.scalar(select(EventInventory).where(EventInventory.event_id==event.id,EventInventory.section_id==reservations[0].section_id))
    if not inventory or any(not allocated_class(tc,inventory) for tc,_ in lines): raise ValueError("Choose a ticket type available in this section")
    if inventory.audience=='away' or any(tc.audience=='away' for tc,_ in lines):
        if stored.get('supporter_id')!=(supporter.id if supporter else None): raise ValueError("Sign in to the account that reserved these away tickets")
        verify_away_membership(db,event,supporter,membership_id=stored.get('away_season_ticket_id'))
    profile=db.get(SupporterProfile,supporter.id) if supporter and supporter.role=="supporter" else None
    if supporter and supporter.role!="supporter": raise ValueError("Use a supporter account to book personal tickets")
    if attendee_birth_dates is None:
        validate_vip_ages(event,lines,vip_birth_dates)
        dates=iter(vip_birth_dates)
        attendee_birth_dates=[next(dates) if tc.name=="VIP" else "" for tc,count in lines for _ in range(count)]
    birth_dates=validate_attendees(event,lines,profile,personal_index,attendee_birth_dates,disability_indices)
    required=("full_name","email","address1","city","postcode","country")
    if any(not str(customer_data.get(key,"")).strip() for key in required) or "@" not in customer_data.get("email",""): raise ValueError("Enter a valid name, email and postal address")
    vip_qty=sum(count for tc,count in lines if tc.name=="VIP")
    priority_qty=qty if not stored.get('away_season_ticket_id') and event.priority_until and now<utc(event.priority_until) else 0
    discounted_vip=vip_qty if vip_season_holder and club_key(event.home_team)==club_key("Glentoran") else 0
    entitlement=max(priority_qty,discounted_vip)
    priority=None
    membership=None
    if entitlement:
        code=str(priority_code or "").strip()
        membership=db.scalar(select(SeasonTicket).where(SeasonTicket.club_name==club_key(event.home_team),SeasonTicket.number==code))
        if membership:
            day=london_date(event.starts_at)
            if not supporter or membership.user_id!=supporter.id or not membership.active or not membership.valid_from<=day<=membership.valid_until:
                raise ValueError("A valid season-ticket number belonging to your account is required")
            units_classes=[tc for tc,count in lines for _ in range(count)]
            if discounted_vip and (personal_index is None or units_classes[personal_index].name!="VIP"):
                raise ValueError("The season-ticket VIP price applies to your own VIP ticket")
            if priority_qty>1 or (priority_qty and personal_index is None): raise ValueError("Season-ticket priority access covers one personal ticket per booking")
            if priority_qty:
                prior=db.scalar(select(Ticket.id).where(Ticket.event_id==event.id,Ticket.attendee_user_id==supporter.id,Ticket.status.in_(["sold","scanned"])))
                if prior: raise ValueError("You already have a personal ticket for this fixture")
            discounted_vip=1 if discounted_vip else 0
        else:
            priority=db.scalar(select(PriorityIdentifier).where(func.upper(PriorityIdentifier.code)==code.upper()))
            if not priority or priority.used+entitlement>priority.maximum: raise ValueError("A valid season-ticket number with sufficient entitlement is required")
    money=lambda value: Decimal(value).quantize(Decimal("0.01"),rounding=ROUND_HALF_UP)
    units=[(tc,tc.price) for tc,count in lines for _ in range(count)]
    units=[(tc,Decimal("50") if discounted_vip and tc.name=="VIP" and (not membership or index==personal_index) else price) for index,(tc,price) in enumerate(units)]
    subtotal=money(sum((price for _,price in units),Decimal("0")))
    discount=money(voucher_discount(db,voucher_code,event.id,subtotal))
    gross=Decimal("0"); allocated=Decimal("0"); ticket_prices=[]
    for tc,price in units:
        gross+=price
        running=money((subtotal-discount)*gross/subtotal) if subtotal else Decimal("0")
        ticket_prices.append(running-allocated); allocated=running
    if any(tc.name=="Under 11" for tc,_ in lines) and not any(is_adult(tc) and net>0 for (tc,_),net in zip(units,ticket_prices)):
        raise ValueError("Under 11 tickets require a paying adult; this voucher would make the adult ticket free")
    customer=Customer(**{k:str(v).strip() for k,v in customer_data.items()}); db.add(customer); db.flush()
    order=Order(reference="GL-"+secrets.token_hex(4).upper(),customer_id=customer.id,event_id=event.id,subtotal=subtotal,discount=discount,total=subtotal-discount,supporter_id=supporter.id if supporter else None); db.add(order); db.flush()
    payment=SimulatedPaymentService().charge(order.total,payment_result); order.payment_status="successful" if payment.successful else "failed"; order.status="complete" if payment.successful else "failed"
    if payment.successful:
        ids=[r.id for r in reservations]
        changed=db.execute(update(Reservation).where(Reservation.id.in_(ids),Reservation.completed==False,Reservation.expires_at>now).values(completed=True).execution_options(synchronize_session="fetch"))
        if changed.rowcount!=len(ids):
            db.rollback(); raise ValueError("Reservation has expired or has already been completed")
        if priority:
            changed=db.execute(update(PriorityIdentifier).where(PriorityIdentifier.id==priority.id,PriorityIdentifier.used<=PriorityIdentifier.maximum-entitlement).values(used=PriorityIdentifier.used+entitlement))
            if changed.rowcount!=1:
                db.rollback(); raise ValueError("Season-ticket entitlement has already been used")
        index=0
        for r in reservations:
            for _ in range(r.quantity):
                tc,_=units[index]; net=ticket_prices[index]
                db.add(Ticket(public_id=ticket_prefix(event.home_team)+"-"+secrets.token_hex(6).upper(),qr_token=secrets.token_urlsafe(32),order_id=order.id,event_id=event.id,section_id=r.section_id,seat_id=r.seat_id,ticket_class_id=tc.id,price=net,status="sold",attendee_user_id=supporter.id if supporter and index==personal_index else None,attendee_birth_date=birth_dates[index]))
                index+=1
        if voucher_code: db.scalar(select(Voucher).where(func.upper(Voucher.code)==voucher_code.upper())).uses+=1
    db.commit(); db.refresh(order); return order

def scan_ticket(db, token, event_id, operator, gate=None, override=False):
    # Hardware scanners submit the opaque QR payload, while gate staff may need
    # to type the supporter-facing ticket ID when a code cannot be read.
    ticket=db.scalar(select(Ticket).where((Ticket.qr_token==token)|(func.upper(Ticket.public_id)==token.upper())))
    if not ticket: return scan_season_ticket(db,token,event_id,operator)
    if ticket.event_id!=event_id: return {"result":"WRONG FIXTURE","detail":"Select the ticket's fixture"}
    event=db.get(Event,event_id)
    if not event or event.cancelled or not event.published: return {"result":"INVALID FIXTURE","detail":"This fixture is cancelled or unavailable for admission"}
    if ticket.status in ["cancelled","refunded","expired"]: return {"result":"INVALID TICKET","detail":ticket.status.upper()+" — admission is not permitted"}
    prior=db.scalar(select(Scan).where(Scan.ticket_id==ticket.id,Scan.result=="valid"))
    if ticket.status=="scanned" or prior:return {"result":"ALREADY USED","detail":prior.scanned_at.isoformat() if prior else "Previously scanned"}
    if gate and ticket.section and ticket.section.stand_id and not override:
        stand=db.get(Stand,ticket.section.stand_id)
        if stand.gate and stand.gate!=gate:return {"result":"WRONG ENTRANCE","detail":f"Use {stand.gate}"}
    # The conditional write is the admission lock: concurrent scanners cannot
    # both move the same ticket from sold to scanned.
    changed=db.execute(update(Ticket).where(Ticket.id==ticket.id,Ticket.status=="sold").values(status="scanned"))
    if changed.rowcount != 1:
        db.rollback(); return {"result":"ALREADY USED","detail":"Previously scanned"}
    db.add(Scan(ticket_id=ticket.id,operator_id=operator.id,gate=gate,result="valid"))
    if ticket.attendee_user_id: db.add(SupporterAttendance(user_id=ticket.attendee_user_id,event_id=event_id,ticket_id=ticket.id,season_ticket_id=ticket.season_ticket_id,operator_id=operator.id))
    try: db.commit()
    except IntegrityError:
        db.rollback();return {"result":"ALREADY USED","detail":"Supporter has already entered this fixture"}
    return {"result":"VALID","detail":f"{ticket.ticket_class.name} · {ticket.section.name}"}
