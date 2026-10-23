from datetime import date
from html.parser import HTMLParser

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from gateline import database
from gateline.main import COMPETITION_ORDER
from gateline.models import Event, Seat, SeatRow, SupporterProfile, Ticket, User
from gateline.services import checkout, reserve, reservation_rows
from gateline.supporters import register_supporter
from test_browse import BrowseParser, client
from test_supporters import portal, sign_in
from test_ticketing import booking, customer


class Fields(HTMLParser):
    def __init__(self, html):
        super().__init__(); self.fields=[]; self.open_details=[]; self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag=='input': self.fields.append(attrs)
        if tag=='details' and 'open' in attrs: self.open_details.append(attrs)


def test_multiselect_filters_union_within_groups_and_intersect_across_groups(client):
    response=client.get('/',params=[('club','Cliftonville'),('club','Glentoran')])
    assert set(BrowseParser(response.text).events)=={'/events/1','/events/5'}
    filtered=client.get('/',params=[('club','Cliftonville'),('club','Glentoran'),('competition','NIFL Championship')])
    assert not BrowseParser(filtered.text).events
    assert 'No fixtures match' in filtered.text
    response=client.get('/',params=[('competition','NIFL Premiership'),('competition',"NIFL Women's Premiership")])
    assert set(BrowseParser(response.text).events)=={'/events/1','/events/2','/events/4','/events/5'}
    fields=Fields(response.text)
    assert not fields.open_details
    assert [item['value'] for item in fields.fields if item.get('name')=='competition']==list(COMPETITION_ORDER)
    assert len([item for item in fields.fields if item.get('name')=='competition' and 'checked' in item])==2
    assert response.text.index('Reset filters') < response.text.index('<summary id="club-picker-title">')
    assert response.text.index('<summary>Competition') < response.text.index('<summary>Stadium')
    cleared=client.get('/')
    assert not [item for item in Fields(cleared.text).fields if 'checked' in item]


def test_stadium_multiselect_and_blank_value(client):
    assert client.get('/',params=[('venue',''),('venue','1')]).status_code==200
    assert set(BrowseParser(client.get('/',params=[('venue','1'),('venue','999')]).text).events)=={f'/events/{i}' for i in range(1,6)}


def test_checkout_requests_birth_dates_only_for_restricted_tickets_and_requires_names(client):
    import re
    page=client.get('/events/5')
    pairs=re.findall(r'<b>([^<]+) <span.*?name="class_ids" value="(\d+)"',page.text,re.S)
    classes={name.strip():int(class_id) for name,class_id in pairs}
    reserved=client.post('/events/5/reserve',data={'section_id':1,'class_ids':[classes['Grandstand Lower']],'ticket_quantities':[2]},follow_redirects=False)
    path=reserved.headers['location']
    page=client.get(path)
    assert not [field for field in Fields(page.text).fields if field.get('name')=='attendee_birth_dates' and field.get('type')=='date']
    missing=client.post(path,data={**customer(),'attendee_birth_dates':['',''],'attendee_names':['Buyer Name','']})
    assert missing.status_code==400 and 'full name' in missing.text
    bought=client.post(path,data={**customer(),'attendee_birth_dates':['',''],'attendee_names':['Buyer Name','Guest Name']})
    assert bought.status_code==200
    assert 'Buyer Name' in bought.text and 'Guest Name' in bought.text
    restricted=client.post('/events/5/reserve',data={'section_id':1,'class_ids':[classes['Grandstand Lower'],classes['Under 11']],'ticket_quantities':[1,1]},follow_redirects=False)
    page=client.get(restricted.headers['location'])
    dates=[field for field in Fields(page.text).fields if field.get('name')=='attendee_birth_dates']
    assert [field['type'] for field in dates]==['hidden','date']


def test_auto_allocated_seats_exclude_active_reservations_and_sold_tickets(booking):
    db,event,section,classes=booking
    section.mode='assigned'
    row=SeatRow(section_id=section.id,name='A');db.add(row);db.flush()
    db.add_all(Seat(row_id=row.id,number=str(number)) for number in range(1,4));db.commit()
    adult=classes['Grandstand Lower']
    first=reserve(db,event.id,section.id,1,[],{adult:1},auto_assign=True)
    order=checkout(db,first.token,None,customer(),attendee_names=['Ticket Holder'])
    second=reserve(db,event.id,section.id,2,[],{adult:2},auto_assign=True)
    seats=[r.seat_id for r in reservation_rows(db,second.token)]
    assert len(set(seats))==2 and order.tickets[0].seat_id not in seats
    with pytest.raises(ValueError,match="unavailable"): reserve(db,event.id,section.id,1,[],{adult:1},auto_assign=True)


def test_signed_in_tickets_are_grouped_by_event_with_safe_named_switching(portal):
    client,engine=portal
    with Session(engine) as db:
        user=db.scalar(select(User).where(User.username=='philmcveigh'))
        event=db.get(Event,1);section=event.inventories[0].section
        adult=next(tc for tc in event.classes if tc.name=='Adult')
        order=checkout(db,reserve(db,event.id,section.id,2,[],{adult.id:2}).token,None,customer(),supporter=user,personal_index=0,attendee_names=['Spoofed Name','Alex Guest'])
        first=order.tickets[0].public_id;second=order.tickets[1].public_id;token=order.access_token
        extra=checkout(db,reserve(db,event.id,section.id,1,[],{adult.id:1}).token,None,customer(),supporter=user,attendee_names=['Second Order Guest'])
        outsider=checkout(db,reserve(db,event.id,section.id,1,[],{adult.id:1}).token,None,customer(),attendee_names=['Private Other Customer'])
        private_id=outsider.tickets[0].public_id
    sign_in(client)
    dashboard=client.get('/account')
    assert 'supporter-dashboard' in dashboard.text and 'class="fixture-card"' in dashboard.text
    assert dashboard.text.index('id="your-matches"')<dashboard.text.index('id="other-matches"')
    assert '>Dashboard</a>' in dashboard.text and '>All Matches</a>' in dashboard.text
    assert '>Profile</a>' not in dashboard.text and '>Settings</a>' not in dashboard.text
    page=client.get('/account/tickets')
    assert page.text.count('<h3>Linfield v Visitors</h3>')==1
    assert 'Alex Guest' in page.text and 'Second Order Guest' in page.text
    viewed=client.get(f'/tickets/{first}?back=/account')
    assert 'Phil McVeigh' in viewed.text and 'Spoofed Name' not in viewed.text
    assert 'Alex Guest' in viewed.text and 'Second Order Guest' in viewed.text
    assert 'Private Other Customer' not in viewed.text
    assert 'href="/account">← Back' in viewed.text
    assert client.get(f'/tickets/{private_id}').status_code==404
    assert f'/tickets/{first}/qr.png' in viewed.text
    next_page=client.get(f'/tickets/{second}?back=/account')
    assert f'/tickets/{second}/qr.png' in next_page.text
    assert client.get(f'/tickets/{first}?back=//example.com').text.count('href="//example.com"')==0
    client.post('/logout')
    guest=client.get(f'/tickets/{first}',params={'access':token})
    assert 'Alex Guest' in guest.text and 'Second Order Guest' not in guest.text


def test_registration_and_adult_booking_do_not_require_date_of_birth(booking):
    db,event,section,classes=booking
    user=register_supporter(db,'nobirthday','No Birthday','no-birthday@example.com','Password123!','Password123!','',[])
    assert db.get(SupporterProfile,user.id).birth_date is None
    reserved=reserve(db,event.id,section.id,1,[],{classes['Grandstand Lower']:1})
    order=checkout(db,reserved.token,None,customer(),supporter=user,personal_index=0,attendee_names=['No Birthday'])
    assert order.tickets[0].attendee_birth_date is None


def test_restricted_personal_ticket_accepts_and_saves_new_date_of_birth(booking):
    db,event,section,classes=booking
    user=register_supporter(db,'nobirthday','No Birthday','no-birthday@example.com','Password123!','Password123!','',[])
    reserved=reserve(db,event.id,section.id,1,[],{classes['Concession']:1})
    order=checkout(db,reserved.token,None,customer(),supporter=user,personal_index=0,attendee_birth_dates=['1950-01-01'],attendee_names=['No Birthday'])
    assert order.tickets[0].attendee_birth_date==date(1950,1,1)
    assert db.get(SupporterProfile,user.id).birth_date==date(1950,1,1)


def test_existing_database_gains_ticket_holder_name_idempotently(booking,monkeypatch):
    db,_,_,_=booking
    engine=db.get_bind()
    with engine.begin() as connection: connection.execute(text('ALTER TABLE tickets DROP COLUMN attendee_name'))
    monkeypatch.setattr(database,'engine',engine)
    database.upgrade_schema();database.upgrade_schema()
    assert 'attendee_name' in {column['name'] for column in inspect(engine).get_columns('tickets')}
