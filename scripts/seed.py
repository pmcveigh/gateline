from datetime import datetime, timedelta, timezone
from gateline.database import Base, engine, SessionLocal
from gateline.models import *
from gateline.auth import hash_password

Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
now=datetime.now(timezone.utc)
with SessionLocal() as db:
 c=Club(name="Glentoran FC",short_name="Glentoran",contact_email="tickets@glentoran.com",address="The Oval, Belfast",currency="GBP"); v=Venue(name="The Oval",address="Parkgate Drive, Belfast"); db.add_all([c,v]);db.flush()
 main=Stand(venue_id=v.id,name="Main Stand",gate="Gate 1");city=Stand(venue_id=v.id,name="City End",gate="Gate 4");rail=Stand(venue_id=v.id,name="Railway Stand",gate="Gate 7");away=Stand(venue_id=v.id,name="Away Stand",gate="Gate 9");db.add_all([main,city,rail,away]);db.flush()
 sections=[]
 for stand,name,mode,cap in [(main,"Section A","assigned",40),(city,"General Admission","general",800),(rail,"General Admission","general",600),(away,"General Admission","general",500)]:
  s=Section(stand_id=stand.id,name=name,mode=mode,capacity=cap);db.add(s);db.flush();sections.append(s)
 row=SeatRow(section_id=sections[0].id,name="C");db.add(row);db.flush();db.add_all([Seat(row_id=row.id,number=str(i)) for i in range(1,41)])
 e=Event(title="Glentoran v Linfield",home_team="Glentoran",away_team="Linfield",competition="NIFL Premiership",venue_id=v.id,starts_at=now+timedelta(days=14),sales_open=now-timedelta(days=1),sales_close=now+timedelta(days=14),description="The Big Two derby at The Oval.",published=True);db.add(e);db.flush()
 db.add_all([EventInventory(event_id=e.id,section_id=s.id,capacity=s.capacity) for s in sections]);db.add_all([TicketClass(event_id=e.id,name=n,description=d,price=p) for n,d,p in [("Adult","Standard admission",15),("Concession","Eligible concessions",10),("Child","Under 16",5)]]);db.add_all([PriorityIdentifier(code="ST001234",maximum=2),PriorityIdentifier(code="ST005678",maximum=1),User(email="admin@gateline.test",name="Demo Administrator",password_hash=hash_password("Admin123!"),role="admin"),User(email="gate@gateline.test",name="Gate 1 Operator",password_hash=hash_password("Gate123!"),role="gate",gate="Gate 1")]);db.commit()
print("Demo data created.")
