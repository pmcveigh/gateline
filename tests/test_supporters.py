from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from gateline import main
from gateline.auth import hash_password, verify
from gateline.database import Base, get_db
from gateline.models import *
from gateline.services import checkout, reserve, scan_ticket
from gateline.supporters import *
from gateline.ticketing import configure_club_tickets, menu_for_club, save_club_pricing, upgrade_club_tickets
from test_ticketing import booking, club_fixture, customer


def supporter(db, born=date(1992,3,17), forced=False):
    user=register_supporter(db,'fan','Test Fan','fan@example.com','Password123!','Password123!',born.isoformat(),['Glentoran'])
    profile=db.get(SupporterProfile,user.id);profile.force_concession=forced;db.commit()
    return user,profile


@pytest.fixture
def portal(tmp_path,monkeypatch):
    engine=create_engine(f'sqlite:///{tmp_path}/portal.db',connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        ensure_test_supporter(db)
        db.add(User(name='Admin',email='admin@test.test',password_hash=hash_password('Test123!'),role='admin'))
        venue=Venue(name='The Oval',address='Belfast');db.add(venue);db.flush()
        stand=Stand(venue_id=venue.id,name='Terrace');db.add(stand);db.flush()
        section=Section(stand_id=stand.id,name='General Admission',mode='general',capacity=100);db.add(section);db.flush()
        now=datetime.now(timezone.utc)
        for club,competition in [('Linfield','NIFL Premiership'),('Glentoran','Irish Cup'),('Glentoran','NIFL Premiership')]:
            event=Event(home_team=club,away_team='Visitors',title=f'{club} v Visitors',competition=competition,venue_id=venue.id,published=True,starts_at=now+timedelta(days=2),sales_open=now-timedelta(days=1),sales_close=now+timedelta(days=1))
            db.add(event);db.flush();db.add(EventInventory(event_id=event.id,section_id=section.id,capacity=100));configure_club_tickets(db,event)
        db.commit()
    def dependency():
        with Session(engine) as db: yield db
    monkeypatch.setattr(main,'engine',engine);monkeypatch.setattr(main,'LOG_DIR',tmp_path/'logs')
    main.app.dependency_overrides[get_db]=dependency
    client=TestClient(main.app)
    yield client,engine
    client.close();main.app.dependency_overrides.pop(get_db);engine.dispose()


def sign_in(client):
    response=client.post('/account/login',data={'identity':'philmcveigh','password':'password123!'},follow_redirects=False)
    assert response.status_code==303 and response.headers['location']=='/account'


def test_test_identity_and_season_record_are_exact_and_idempotent(booking):
    db,_,_,_=booking
    first=ensure_test_supporter(db);second=ensure_test_supporter(db)
    assert first.id==second.id and verify('password123!',first.password_hash)
    assert db.get(SupporterProfile,first.id).birth_date==date(1992,3,17)
    assert json.loads(db.get(SupporterProfile,first.id).clubs_json)==['Glentoran']
    st=db.scalar(select(SeasonTicket))
    assert (st.club_name,st.number,st.full_name,st.email,st.section,st.ticket_type)==('glentoran','12345','Phil McVeigh','phil.mcveigh@gateline.com','Sydenham End','Adult')
    first.password_hash=hash_password('Changed123!');db.commit();ensure_test_supporter(db)
    assert verify('Changed123!',first.password_hash)


def test_signup_login_role_isolation_and_duplicate_validation(portal):
    client,engine=portal
    assert client.get('/register').status_code==200
    data=dict(username='newfan',full_name='New Fan',email='new@test.test',password='Password123!',confirmation='Password123!',birth_date='2000-01-01',clubs=['Linfield','Glentoran'])
    response=client.post('/register',data=data)
    assert response.status_code==200 and 'Hello, New Fan' in response.text
    assert client.get('/admin').status_code==403 and client.get('/gate').status_code==403
    assert client.get('/account/season-tickets/1').status_code==404
    client.post('/logout')
    duplicate=client.post('/register',data=data)
    assert duplicate.status_code==400 and 'already in use' in duplicate.text
    data['username']='other';data['email']='other@test.test';data['birth_date']='2099-01-01'
    assert client.post('/register',data=data).status_code==400
    assert client.post('/account/login',data={'identity':'new@test.test','password':'Password123!'}).status_code==200
    client.post('/logout')
    assert client.post('/account/login',data={'identity':'newfan','password':'wrong'}).status_code==401


def test_dashboard_favourites_notifications_and_season_coverage(portal):
    client,engine=portal;sign_in(client)
    page=client.get('/account');assert page.status_code==200
    assert page.text.index('href="/events/2"')<page.text.index('href="/events/1"')
    assert 'Tickets available: Glentoran v Visitors' in page.text
    assert 'Covered by season ticket' in page.text
    assert 'Tickets available: Linfield' not in page.text
    assert '12345' in client.get('/account/profile').text and client.get('/account/season-tickets/1/qr.png').headers['content-type']=='image/png'
    assert '1992-03-17' in client.get('/account/profile').text
    assert client.get('/admin/clubs/Glentoran/season-tickets').status_code==403
    client.post('/logout');client.post('/login',data={'email':'admin@test.test','password':'Test123!'})
    registry=client.get('/admin/clubs/Glentoran/season-tickets')
    assert registry.status_code==200 and 'Sydenham End' in registry.text and 'phil.mcveigh@gateline.com' in registry.text


@pytest.mark.parametrize('age,allowed',[(15,True),(16,False),(65,False),(66,True)])
def test_concession_boundaries_use_match_day_age(booking,age,allowed):
    db,event,_,classes=booking
    tc=db.get(TicketClass,classes['Concession']);day=london_date(event.starts_at)
    born=day.replace(year=day.year-age)
    user,profile=supporter(db,born)
    if allowed: assert validate_attendees(event,[(tc,1)],profile,0,[''])==[born]
    else:
        with pytest.raises(ValueError,match='under 16 or over 65'): validate_attendees(event,[(tc,1)],profile,0,['2015-01-01'])


def test_under_11_and_vip_use_own_saved_age_and_guest_birth_dates(booking):
    db,event,section,classes=booking;user,profile=supporter(db)
    adult=db.get(TicketClass,classes['Adult']);child=db.get(TicketClass,classes['Under 11']);vip=db.get(TicketClass,classes['VIP'])
    with pytest.raises(ValueError,match='under 11'): validate_attendees(event,[(child,1)],profile,0,['2018-01-01'])
    with pytest.raises(ValueError,match='18'): validate_attendees(event,[(vip,1)],None,None,['2018-01-01'])
    r=reserve(db,event.id,section.id,2,[],{adult.id:1,child.id:1})
    order=checkout(db,r.token,None,customer(),supporter=user,personal_index=0,attendee_birth_dates=['2018-01-01','2018-01-01'])
    assert order.tickets[0].attendee_birth_date==date(1992,3,17)
    assert order.tickets[1].attendee_user_id is None
    assert order.supporter_id==user.id


def test_disability_preference_recommends_access_then_concession_and_adult_remains_available(booking):
    db,event,section,classes=booking;user,profile=supporter(db,forced=True)
    disabled=TicketClass(event_id=event.id,name='Disabled Access',price=8);db.add(disabled);db.commit();db.expire(event,['classes'])
    assert [tc.name for tc in preferred_classes(event,profile)][:2]==['Disabled Access','Concession']
    for tc in [disabled,db.get(TicketClass,classes['Concession']),db.get(TicketClass,classes['Adult'])]:
        assert validate_attendees(event,[(tc,1)],profile,0,['1992-03-17'])
    r=reserve(db,event.id,section.id,1,[],{classes['Concession']:1})
    assert checkout(db,r.token,None,customer(),supporter=user,personal_index=0,attendee_birth_dates=['']).total==Decimal('8')
    db.get(TicketClass,classes['Concession']).enabled=False;disabled.enabled=False;db.commit()
    assert 'Adult' in {tc.name for tc in preferred_classes(event,profile)}
    r=reserve(db,event.id,section.id,1,[],{classes['Adult']:1})
    assert checkout(db,r.token,None,customer(),supporter=user,personal_index=0,attendee_birth_dates=['']).total==Decimal('15')


def test_concession_and_access_guests_require_age_or_disability_declaration(booking):
    db,event,_,classes=booking;tc=db.get(TicketClass,classes['Concession'])
    with pytest.raises(ValueError): validate_attendees(event,[(tc,1)],None,None,[''])
    assert validate_attendees(event,[(tc,1)],None,None,[''],[0])==[None]
    assert validate_attendees(event,[(tc,1)],None,None,['2018-01-01'])==[date(2018,1,1)]


def test_edited_default_prices_and_concession_ages_survive_restart(booking):
    db,event,_,classes=booking
    save_club_pricing(db,'Glentoran',['Adult','Concession'],['20','9'],['Adult','Local concession'],['adult','other'],['16','18'],['65','60'])
    upgrade_club_tickets(db);upgrade_club_tickets(db)
    classes={tc.name:tc for tc in event.classes if tc.enabled}
    assert classes['Adult'].price==20 and classes['Concession'].price==9
    assert classes['Concession'].concession_under==18 and classes['Concession'].concession_over==60
    save_club_pricing(db,'Glentoran',['Adult'],['20'],['Adult'],['adult']);upgrade_club_tickets(db)
    assert {tc.name for tc in event.classes if tc.enabled}=={'Adult'}


def test_migration_preserves_explicit_owner_menu_without_reintroducing_removed_types(booking):
    db,event,_,_=booking
    pricing=db.get(ClubPricing,'glentoran');pricing.menu_json='[]';pricing.portal_defaults_applied=False
    db.add(AuditLog(action='club.pricing_updated',entity='club',entity_id='glentoran'))
    for tc in event.classes: tc.enabled=False
    db.commit();upgrade_club_tickets(db)
    assert menu_for_club(db,'Glentoran')==[] and not preferred_classes(event,None)


def test_verified_vip_discount_is_owned_club_scoped_and_one_personal_ticket(booking):
    db,event,section,classes=booking;user=ensure_test_supporter(db);st=db.scalar(select(SeasonTicket))
    st.valid_until=london_date(event.starts_at)+timedelta(days=1);db.commit()
    r=reserve(db,event.id,section.id,2,[],{classes['VIP']:2})
    for kwargs in ({},dict(supporter=user,personal_index=None),dict(supporter=user,personal_index=0,attendee_birth_dates=['','2018-01-01'])):
        with pytest.raises(ValueError): checkout(db,r.token,None,customer(),priority_code='12345',vip_season_holder=True,vip_birth_dates=['1992-03-17','1990-01-01'],**kwargs)
    order=checkout(db,r.token,None,customer(),priority_code='12345',vip_season_holder=True,supporter=user,personal_index=0,attendee_birth_dates=['','1990-01-01'])
    assert order.total==Decimal('120') and [t.price for t in order.tickets]==[Decimal('50'),Decimal('70')]
    assert st.number=='12345'
    st.active=False;db.commit();r=reserve(db,event.id,section.id,1,[],{classes['VIP']:1})
    with pytest.raises(ValueError,match='season-ticket'): checkout(db,r.token,None,customer(),priority_code='12345',vip_season_holder=True,supporter=user,personal_index=0,attendee_birth_dates=[''])


@pytest.mark.parametrize('season_first',[False,True])
def test_attendance_counts_own_ticket_or_season_pass_once_and_never_guests(booking,season_first):
    db,event,section,classes=booking;user=ensure_test_supporter(db);st=db.scalar(select(SeasonTicket));st.valid_until=london_date(event.starts_at)+timedelta(days=1)
    operator=User(name='Gate',email='gate@x.test',password_hash='unused',role='gate');db.add(operator);db.commit()
    r=reserve(db,event.id,section.id,2,[],{classes['Adult']:2})
    order=checkout(db,r.token,None,customer(),supporter=user,personal_index=0,attendee_birth_dates=['',''])
    assert scan_ticket(db,order.tickets[1].qr_token,event.id,operator)['result']=='VALID'
    assert dashboard_data(db,user)['attended']==set()
    first,second=(st.qr_token,order.tickets[0].qr_token) if season_first else (order.tickets[0].qr_token,st.qr_token)
    assert scan_ticket(db,first,event.id,operator)['result']=='VALID'
    assert scan_ticket(db,second,event.id,operator)['result']=='ALREADY USED'
    assert dashboard_data(db,user)['attended']=={event.id}
    assert dashboard_data(db,user)['purchased']=={event.id}
    assert len(db.scalars(select(SupporterAttendance)).all())==1


def test_season_ticket_wrong_club_competition_and_expiry_do_not_admit(booking):
    db,event,_,_=booking;ensure_test_supporter(db);st=db.scalar(select(SeasonTicket));st.valid_until=london_date(event.starts_at)+timedelta(days=1);db.commit()
    operator=User(name='Gate',email='gate@x.test',password_hash='unused',role='gate');db.add(operator);db.commit()
    event.home_team='Linfield';db.commit()
    assert scan_ticket(db,st.qr_token,event.id,operator)['result']=='WRONG FIXTURE'
    event.home_team='Glentoran';event.competition='Irish Cup';db.commit()
    assert scan_ticket(db,st.qr_token,event.id,operator)['result']=='WRONG FIXTURE'
    event.competition=st.competition;st.valid_until=london_date(event.starts_at)-timedelta(days=1);db.commit()
    assert scan_ticket(db,st.qr_token,event.id,operator)['result']=='WRONG FIXTURE'


def test_profile_sharing_is_consent_based_and_admin_only_with_revocation(portal):
    client,engine=portal;sign_in(client)
    data=dict(full_name='Phil McVeigh',birth_date='1992-03-17',clubs=['Glentoran'],force_concession='true',disability_type='Mobility condition',access_details='Step-free entrance please',share_access_needs='true')
    assert client.post('/account/profile',data=data).status_code==200
    public=client.get('/events/3');assert 'Mobility condition' not in public.text
    assert public.text.index('<b>Concession')<public.text.index('<b>Adult')
    assert client.get('/admin/events/3/attendance').status_code==403
    client.post('/logout');client.post('/login',data={'email':'admin@test.test','password':'Test123!'})
    assert 'Step-free entrance please' in client.get('/admin/events/3/attendance').text
    client.post('/logout');sign_in(client);data.pop('share_access_needs');client.post('/account/profile',data=data)
    client.post('/logout');client.post('/login',data={'email':'admin@test.test','password':'Test123!'})
    assert 'Step-free entrance please' not in client.get('/admin/events/3/attendance').text


def test_own_booking_visibility_guest_order_not_claimed_by_email_and_notifications_stop(portal):
    client,engine=portal;sign_in(client)
    with Session(engine) as db:
        user=db.scalar(select(User).where(User.username=='philmcveigh'));event=db.get(Event,2)
        adult=next(tc for tc in event.classes if tc.name=='Adult')
        r=reserve(db,event.id,1,1,[],{adult.id:1})
        own=checkout(db,r.token,None,customer(),supporter=user,personal_index=0,attendee_birth_dates=[''])
        own_ref=own.reference;ticket_id=own.tickets[0].public_id
        r=reserve(db,event.id,1,1,[],{adult.id:1})
        guest=checkout(db,r.token,None,{**customer(),'email':user.email})
        guest_ref=guest.reference
    assert client.get('/orders/'+own_ref).status_code==200
    assert client.get('/tickets/'+ticket_id).status_code==200
    assert client.get('/tickets/'+ticket_id+'/qr.png').status_code==200
    assert client.get('/orders/'+guest_ref).status_code==404
    assert 'Tickets available: Glentoran' not in client.get('/account').text
    client.post('/logout')
    assert client.get('/orders/'+own_ref).status_code==404
    client.post('/register',data=dict(username='otherfan',full_name='Other Fan',email='other@example.com',password='Password123!',confirmation='Password123!',birth_date='1990-01-01'))
    assert client.get('/orders/'+own_ref).status_code==404
    assert client.get('/tickets/'+ticket_id+'/qr.png').status_code==404


def test_dashboard_concession_toggle_and_notifications_require_available_sales(portal):
    client,engine=portal;sign_in(client)
    assert client.post('/account/concession',data={'force_concession':'true'}).status_code==200
    with Session(engine) as db:
        user=db.scalar(select(User).where(User.username=='philmcveigh'))
        assert db.get(SupporterProfile,user.id).force_concession
        event=db.get(Event,2)
        assert [e.id for e in dashboard_data(db,user)['notices']]==[2]
        inventory=event.inventories[0];inventory.held=inventory.capacity;db.commit()
        assert dashboard_data(db,user)['notices']==[]
        inventory.held=0;event.sales_suspended=True;db.commit()
        assert dashboard_data(db,user)['notices']==[]
        event.sales_suspended=False
        for tc in event.classes: tc.maximum=0
        db.commit();assert dashboard_data(db,user)['notices']==[]
    client.post('/account/concession',data={})
    with Session(engine) as db: assert not db.get(SupporterProfile,user.id).force_concession
