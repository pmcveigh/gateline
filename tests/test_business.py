from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from gateline.database import Base
from gateline.models import *
from gateline.services import checkout, reserve, scan_ticket, voucher_discount

@pytest.fixture
def db():
 engine=create_engine("sqlite://",connect_args={"check_same_thread":False});Base.metadata.create_all(engine);d=sessionmaker(engine,expire_on_commit=False)()
 v=Venue(name="Ground",address="Road");d.add(v);d.flush();st=Stand(venue_id=v.id,name="Stand",gate="G1");d.add(st);d.flush();sec=Section(stand_id=st.id,name="A",mode="general",capacity=2);d.add(sec);d.flush();now=datetime.now(timezone.utc);e=Event(title="A v B",home_team="A",away_team="B",competition="League",venue_id=v.id,starts_at=now+timedelta(days=1),sales_open=now-timedelta(days=1),sales_close=now+timedelta(days=1),published=True);d.add(e);d.flush();d.add(EventInventory(event_id=e.id,section_id=sec.id,capacity=2));tc=TicketClass(event_id=e.id,name="Adult",price=Decimal("10"));op=User(email="g@x",name="Gate",password_hash="x",role="gate",gate="G1");d.add_all([tc,op]);d.commit();yield d,{"event":e,"section":sec,"class":tc,"operator":op};d.close()

def customer():return dict(full_name="Test Fan",email="fan@example.com",address1="1 Road",address2="",city="Belfast",postcode="BT1",country="UK")
def test_capacity_and_expiry(db):
 d,x=db;r=reserve(d,x["event"].id,x["section"].id,2,[])
 with pytest.raises(ValueError):reserve(d,x["event"].id,x["section"].id,1,[])
 r.expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);d.commit();assert reserve(d,x["event"].id,x["section"].id,1,[])
def test_payment_creates_individual_tickets_and_failed_does_not(db):
 d,x=db;r=reserve(d,x["event"].id,x["section"].id,2,[]);o=checkout(d,r.token,x["class"].id,customer());assert len(o.tickets)==2 and o.tickets[0].qr_token!=o.tickets[1].qr_token
 # Add capacity for failed transaction, whose order remains auditable but issues no tickets.
 d.scalar(select(EventInventory)).capacity=3;d.commit();r=reserve(d,x["event"].id,x["section"].id,1,[]);o=checkout(d,r.token,x["class"].id,customer(),"fail");assert o.payment_status=="failed" and not o.tickets
def test_checkout_accepts_sqlite_naive_expiry(db):
 d,x=db;r=reserve(d,x["event"].id,x["section"].id,1,[])
 # SQLite returns DateTime values without their UTC tzinfo; checkout must normalize them.
 r.expires_at=r.expires_at.replace(tzinfo=None);d.commit()
 assert checkout(d,r.token,x["class"].id,customer()).status=="complete"
def test_priority_voucher_and_scanning(db):
 d,x=db;now=datetime.now(timezone.utc);x["event"].priority_until=now+timedelta(hours=1);p=PriorityIdentifier(code="ST1",maximum=1);v=Voucher(code="SAVE",kind="percentage",value=10,starts_at=now-timedelta(hours=1),expires_at=now+timedelta(hours=1),maximum_uses=1,enabled=True);d.add_all([p,v]);d.commit();r=reserve(d,x["event"].id,x["section"].id,1,[])
 with pytest.raises(ValueError):checkout(d,r.token,x["class"].id,customer(),priority_code="BAD")
 o=checkout(d,r.token,x["class"].id,customer(),priority_code="ST1",voucher_code="SAVE");assert o.total==Decimal("9.00")
 t=o.tickets[0];assert scan_ticket(d,t.qr_token,x["event"].id,x["operator"])["result"]=="VALID";assert scan_ticket(d,t.public_id.lower(),x["event"].id,x["operator"])["result"]=="ALREADY USED"
 t.status="cancelled";d.commit();assert scan_ticket(d,t.qr_token,x["event"].id,x["operator"])["result"]=="INVALID TICKET"
 t.status="refunded";d.commit();assert scan_ticket(d,t.qr_token,x["event"].id,x["operator"])["result"]=="INVALID TICKET"
