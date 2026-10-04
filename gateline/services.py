from datetime import datetime, timedelta, timezone
from decimal import Decimal
import secrets
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from .models import *

class PaymentResult:
    def __init__(self, successful: bool): self.successful=successful; self.reference="TEST-"+secrets.token_hex(5).upper()
class PaymentService:
    def charge(self, amount: Decimal, test_result: str) -> PaymentResult: raise NotImplementedError
class SimulatedPaymentService(PaymentService):
    def charge(self, amount: Decimal, test_result: str) -> PaymentResult: return PaymentResult(test_result == "success")

def reserve(db:Session,event_id:int,section_id:int,quantity:int,seat_ids:list[int]) -> Reservation:
    now=datetime.now(timezone.utc); section=db.get(Section,section_id); inv=db.scalar(select(EventInventory).where(EventInventory.event_id==event_id,EventInventory.section_id==section_id))
    if not section or not inv or quantity < 1: raise ValueError("Invalid ticket selection")
    active=select(Reservation).where(Reservation.event_id==event_id,Reservation.section_id==section_id,Reservation.completed==False,Reservation.expires_at>now)
    if section.mode==Mode.ASSIGNED.value:
        if len(seat_ids)!=quantity: raise ValueError("Select every seat")
        sold=set(db.scalars(select(Ticket.seat_id).where(Ticket.event_id==event_id,Ticket.status.in_(["sold","scanned"]),Ticket.seat_id.in_(seat_ids))).all())
        held=set(db.scalars(active.where(Reservation.seat_id.in_(seat_ids)).with_only_columns(Reservation.seat_id)).all())
        if sold or held: raise ValueError("A selected seat is no longer available")
    else:
        sold=db.scalar(select(func.count(Ticket.id)).where(Ticket.event_id==event_id,Ticket.section_id==section_id,Ticket.status.in_(["sold","scanned"]))) or 0
        held=db.scalar(select(func.coalesce(func.sum(Reservation.quantity),0)).where(Reservation.event_id==event_id,Reservation.section_id==section_id,Reservation.completed==False,Reservation.expires_at>now)) or 0
        if sold+held+quantity > inv.capacity-inv.held: raise ValueError("Not enough tickets remain")
    token=secrets.token_urlsafe(20); expiry=now+timedelta(minutes=10)
    # One reservation row per assigned seat preserves the database uniqueness guard.
    rows=[]
    for seat in (seat_ids if seat_ids else [None]):
        row=Reservation(token=token if not rows else token+f"-{len(rows)}",event_id=event_id,section_id=section_id,seat_id=seat,quantity=1 if seat else quantity,expires_at=expiry); db.add(row); rows.append(row)
    db.commit(); return rows[0]

def voucher_discount(db, code, event_id, subtotal):
    if not code:return Decimal("0")
    now=datetime.now(timezone.utc); v=db.scalar(select(Voucher).where(func.upper(Voucher.code)==code.upper()))
    if not v or not v.enabled or v.starts_at>now or v.expires_at<now or v.uses>=v.maximum_uses or (v.event_id and v.event_id!=event_id): raise ValueError("Voucher code is not valid")
    return min(subtotal, v.value if v.kind=="fixed" else subtotal*v.value/100)

def checkout(db:Session, reservation_token:str, class_id:int, customer_data:dict, payment_result="success", priority_code=None, voucher_code=None):
    now=datetime.now(timezone.utc); reservations=db.scalars(select(Reservation).where((Reservation.token==reservation_token)|(Reservation.token.like(reservation_token+"-%")),Reservation.completed==False)).all()
    if not reservations or reservations[0].expires_at<now: raise ValueError("Reservation has expired")
    event=db.get(Event,reservations[0].event_id); tc=db.get(TicketClass,class_id); qty=sum(r.quantity for r in reservations)
    if not tc or tc.event_id!=event.id: raise ValueError("Invalid ticket class")
    if event.priority_until and now<event.priority_until:
        priority=db.scalar(select(PriorityIdentifier).where(PriorityIdentifier.code==priority_code))
        if not priority or priority.used+qty>priority.maximum: raise ValueError("A valid season-ticket number with sufficient entitlement is required")
    else: priority=None
    subtotal=tc.price*qty; discount=voucher_discount(db,voucher_code,event.id,subtotal); customer=Customer(**customer_data); db.add(customer); db.flush()
    order=Order(reference="GL-"+secrets.token_hex(4).upper(),customer_id=customer.id,event_id=event.id,subtotal=subtotal,discount=discount,total=subtotal-discount); db.add(order); db.flush()
    payment=SimulatedPaymentService().charge(order.total,payment_result); order.payment_status="successful" if payment.successful else "failed"; order.status="complete" if payment.successful else "failed"
    if payment.successful:
        for r in reservations:
            for _ in range(r.quantity): db.add(Ticket(public_id="TKT-"+secrets.token_hex(4).upper(),qr_token=secrets.token_urlsafe(32),order_id=order.id,event_id=event.id,section_id=r.section_id,seat_id=r.seat_id,ticket_class_id=tc.id,price=(subtotal-discount)/qty,status="sold"))
            r.completed=True
        if priority: priority.used+=qty
        if voucher_code: db.scalar(select(Voucher).where(func.upper(Voucher.code)==voucher_code.upper())).uses+=1
    db.commit(); db.refresh(order); return order

def scan_ticket(db, token, event_id, operator, gate=None, override=False):
    ticket=db.scalar(select(Ticket).where(Ticket.qr_token==token))
    if not ticket or ticket.event_id!=event_id or ticket.status in ["cancelled","refunded","expired"]: return {"result":"INVALID TICKET","detail": ticket.status.upper() if ticket else "UNKNOWN TICKET"}
    prior=db.scalar(select(Scan).where(Scan.ticket_id==ticket.id,Scan.result=="valid"))
    if ticket.status=="scanned" or prior:return {"result":"ALREADY USED","detail":prior.scanned_at.isoformat() if prior else "Previously scanned"}
    if gate and ticket.section and ticket.section.stand_id and not override:
        stand=db.get(Stand,ticket.section.stand_id)
        if stand.gate and stand.gate!=gate:return {"result":"WRONG ENTRANCE","detail":f"Use {stand.gate}"}
    ticket.status="scanned"; db.add(Scan(ticket_id=ticket.id,operator_id=operator.id,gate=gate,result="valid")); db.commit()
    return {"result":"VALID","detail":f"{ticket.ticket_class.name} · {ticket.section.name}"}
