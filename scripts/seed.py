from datetime import datetime, timezone
from pathlib import Path
from decimal import Decimal
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gateline.database import Base, engine, SessionLocal
from gateline.models import *
from gateline.auth import hash_password

Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
now=datetime.now(timezone.utc)
with SessionLocal() as db:
    clubs=[Club(name=f"{name} FC",short_name=name,contact_email=f"tickets@{name.lower()}.test",address=address,currency="GBP") for name,address in [("Glentoran","The Oval, Belfast"),("Linfield","Windsor Park, Belfast"),("Portadown","Shamrock Park, Portadown"),("Bangor","Clandeboye Park, Bangor"),("Coleraine","Coleraine Showgrounds, Coleraine")]]
    db.add_all(clubs)
    venues={}
    sections={}
    for name,address in [("The Oval","Parkgate Drive, Belfast"),("Shamrock Park","Brownstown Road, Portadown"),("Coleraine Showgrounds","Ballycastle Road, Coleraine")]:
        venue=Venue(name=name,address=address); db.add(venue); db.flush(); venues[name]=venue
        stand=Stand(venue_id=venue.id,name="Main Stand",gate="Gate 1"); db.add(stand); db.flush()
        section=Section(stand_id=stand.id,name="General Admission",mode="general",capacity=1000); db.add(section); db.flush(); sections[name]=section
    fixtures=[
        ("Glentoran v Linfield","Glentoran","Linfield","NIFL Premiership","The Oval",datetime(2026,10,10,15,0,tzinfo=timezone.utc)),
        ("Portadown v Bangor","Portadown","Bangor","NIFL League Cup","Shamrock Park",datetime(2026,10,14,19,45,tzinfo=timezone.utc)),
        ("Coleraine v Glentoran","Coleraine","Glentoran","NIFL Premiership","Coleraine Showgrounds",datetime(2025,10,16,19,45,tzinfo=timezone.utc)),
    ]
    for title,home,away,competition,venue_name,kickoff in fixtures:
        event=Event(title=title,home_team=home,away_team=away,competition=competition,venue_id=venues[venue_name].id,starts_at=kickoff,sales_open=now.replace(year=2024),sales_close=max(now,kickoff).replace(year=max(now.year,kickoff.year)+1),description=f"{title} at {venue_name}.",published=True)
        db.add(event); db.flush(); section=sections[venue_name]
        db.add(EventInventory(event_id=event.id,section_id=section.id,capacity=section.capacity))
        db.add_all([TicketClass(event_id=event.id,name=name,description=description,price=price) for name,description,price in [("Adult","Standard admission",Decimal("15")),("Concession","Eligible concessions",Decimal("10")),("Child","Under 16",Decimal("5"))]])
    db.add_all([PriorityIdentifier(code="ST001234",maximum=2),PriorityIdentifier(code="ST005678",maximum=1),User(email="admin@gateline.test",name="Demo Administrator",password_hash=hash_password("Admin123!"),role="admin"),User(email="gate@gateline.test",name="Gate 1 Operator",password_hash=hash_password("Gate123!"),role="gate",gate="Gate 1")]); db.commit()
print("Demo data created with 3 fixtures.")
