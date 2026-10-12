"""Idempotent, explicitly requested demonstration fixture and test numbers."""
from datetime import date, datetime, time, timedelta, timezone
import json
from decimal import Decimal
from zoneinfo import ZoneInfo
from sqlalchemy import select
from .auth import hash_password
from .models import *
from .supporters import ensure_test_supporter, london_date
from .ticketing import configure_club_tickets, initialise_club_pricing

DEMO_CODES=(
    {'kind':'season','label':'Glentoran season ticket','number':'12345','details':'Phil McVeigh · Adult · Sydenham End · philmcveigh / password123!'},
    {'kind':'season','label':'Linfield away-access season ticket','number':'LF12345','details':'Linfield Test Fan · Adult · linfieldfan / Linfield123!'},
    {'kind':'priority','label':'Legacy priority identifier','number':'ST001234','details':'2 uses; not valid for free claims or away access'},
    {'kind':'priority','label':'Legacy priority identifier','number':'ST005678','details':'1 use; not valid for free claims or away access'},
    {'kind':'voucher','label':'Test voucher','number':'DEMO10','details':'10% off a paid test booking; maximum 100 uses'},
)


def ensure_demo_data(db):
    ensure_test_supporter(db)
    today=london_date();season_year=today.year if today.month>=7 else today.year-1
    away=db.scalar(select(User).where(User.username=='linfieldfan'))
    if not away:
        if db.scalar(select(User.id).where(User.email=='linfield.fan@gateline.test')): raise ValueError('The Linfield test email is already in use')
        away=User(username='linfieldfan',name='Linfield Test Fan',email='linfield.fan@gateline.test',role='supporter',password_hash=hash_password('Linfield123!'))
        db.add(away);db.flush();db.add(SupporterProfile(user_id=away.id,birth_date=date(1990,1,1),clubs_json='["Linfield"]'))
    if away.role!='supporter': raise ValueError('The Linfield test username belongs to a staff account')
    if not db.scalar(select(User.id).where(User.email=='awaygate@gateline.test')):
        db.add(User(name='Away Gate Operator',email='awaygate@gateline.test',role='gate',gate='Gate 2',password_hash=hash_password('AwayGate123!')))
    st=db.scalar(select(SeasonTicket).where(SeasonTicket.club_name=='linfield',SeasonTicket.number=='LF12345'))
    if st and st.user_id!=away.id: raise ValueError('Linfield season ticket LF12345 belongs to another supporter')
    if not st: db.add(SeasonTicket(club_name='linfield',number='LF12345',user_id=away.id,full_name=away.name,email=away.email,section='South Stand Half Way Line',ticket_type='Adult',valid_from=date(season_year,7,1),valid_until=date(season_year+1,6,30)))
    for code,maximum in [('ST001234',2),('ST005678',1)]:
        if not db.scalar(select(PriorityIdentifier.id).where(PriorityIdentifier.code==code)): db.add(PriorityIdentifier(code=code,maximum=maximum))
    if not db.scalar(select(Voucher.id).where(Voucher.code=='DEMO10')):
        db.add(Voucher(code='DEMO10',kind='percentage',value=10,starts_at=datetime.now(timezone.utc)-timedelta(days=1),expires_at=datetime.combine(date(season_year+1,6,30),time(23,59),tzinfo=ZoneInfo('Europe/London')).astimezone(timezone.utc),maximum_uses=100,enabled=True))
    existing=db.scalar(select(Event).where(Event.home_team=='Glentoran',Event.away_team=='Linfield',Event.competition=='NIFL League Cup'))
    if existing: db.commit();return existing
    venue=db.scalar(select(Venue).where(Venue.name=='The Oval'))
    if not venue: venue=Venue(name='The Oval',address='Belfast');db.add(venue);db.flush()
    sections={}
    for name,capacity,mode,gate in [('Sydenham End',400,'general','Gate 1'),('Grandstand Upper',100,'general','Gate 1'),('Lower Grandstand',120,'general','Gate 1'),('City End',200,'general','Gate 2'),('Railway Stand',60,'assigned','Gate 2')]:
        section=db.scalar(select(Section).join(Stand).where(Stand.venue_id==venue.id,Section.name==name))
        if not section:
            stand=Stand(venue_id=venue.id,name=name,gate=gate);db.add(stand);db.flush()
            section=Section(stand_id=stand.id,name=name,mode=mode,capacity=capacity);db.add(section);db.flush()
            if mode=='assigned':
                for letter in ('A','B','C'):
                    row=SeatRow(section_id=section.id,name=letter);db.add(row);db.flush()
                    db.add_all([Seat(row_id=row.id,number=str(number),available=True) for number in range(1,21)])
        sections[name]=section
    saturday=today+timedelta(days=(5-today.weekday())%7+21)
    kickoff=datetime.combine(saturday,time(15),tzinfo=ZoneInfo('Europe/London')).astimezone(timezone.utc)
    event=Event(title='Glentoran v Linfield',home_team='Glentoran',away_team='Linfield',competition='NIFL League Cup',venue_id=venue.id,starts_at=kickoff,sales_open=datetime.now(timezone.utc)-timedelta(hours=1),sales_close=kickoff,published=True,season_claim_required=True,description='Home season-ticket holders must claim a free match ticket. Away tickets require a Linfield season-ticket number. Away Disabled tickets are located in the home Lower Grandstand.')
    db.add(event);db.flush()
    for name,section in sections.items(): db.add(EventInventory(event_id=event.id,section_id=section.id,capacity=section.capacity,audience='away' if name in ('City End','Railway Stand') else 'home'))
    menu=initialise_club_pricing(db,'Glentoran')
    if not any(item['name']=='Disabled' for item in menu):
        menu.append({'name':'Disabled','price':'8','description':'Lower Grandstand accessibility admission','adult':False})
        db.get(ClubPricing,'glentoran').menu_json=json.dumps(menu)
    configure_club_tickets(db,event)
    for tc in event.classes:
        if tc.name=='Disabled': tc.section_id=sections['Lower Grandstand'].id
        name={'Grandstand Lower':'Lower Grandstand','VIP':'Grandstand Upper'}.get(tc.name,tc.name)
        if name in sections: tc.section_id=sections[name].id
    lower=sections['Lower Grandstand'].id
    if not any(tc.name=='Disabled' and tc.audience=='home' for tc in event.classes): db.add(TicketClass(event_id=event.id,name='Disabled',description='Home Lower Grandstand accessibility admission',price=Decimal('8'),adult_admission=False,section_id=lower))
    for name,price in [('Adult','15'),('Concession','8'),('Disabled','8')]:
        db.add(TicketClass(event_id=event.id,name=name,price=Decimal(price),adult_admission=name=='Adult',audience='away',section_id=lower if name=='Disabled' else None,description='Away Disabled section is in the home Lower Grandstand' if name=='Disabled' else 'Away supporter admission'))
    db.commit();return event
