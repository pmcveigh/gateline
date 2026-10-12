from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from gateline.allocations import claim_season_ticket, claim_target
from gateline.demo import DEMO_CODES, ensure_demo_data
from gateline.models import *
from gateline.services import checkout, reserve, scan_ticket
from gateline.supporters import dashboard_data
from gateline.ticketing import menu_for_club, offered_classes, save_club_pricing, upgrade_club_tickets
from test_supporters import portal, sign_in
from test_ticketing import customer


@pytest.fixture
def cup(portal):
    client,engine=portal
    with Session(engine) as db:
        event=ensure_demo_data(db);event_id=event.id
    return client,engine,event_id


def lookup(db,event_id):
    event=db.get(Event,event_id)
    phil=db.scalar(select(User).where(User.username=='philmcveigh'))
    away=db.scalar(select(User).where(User.username=='linfieldfan'))
    home_st=db.scalar(select(SeasonTicket).where(SeasonTicket.club_name=='glentoran',SeasonTicket.number=='12345'))
    away_st=db.scalar(select(SeasonTicket).where(SeasonTicket.club_name=='linfield',SeasonTicket.number=='LF12345'))
    return event,phil,away,home_st,away_st


def test_default_matches_page_is_separate_from_stats_settings_tickets_and_history(cup):
    client,_,_=cup;sign_in(client)
    page=client.get('/account')
    assert page.text.index('id="notifications"')<page.text.index('id="your-matches"')<page.text.index('id="other-matches"')
    assert 'class="stats dashboard"' not in page.text
    assert 'name="force_concession"' not in page.text and '<h2>Booking history' not in page.text
    profile=client.get('/account/profile');assert 'Matches bought' in profile.text and 'Matches attended' in profile.text
    assert 'name="force_concession"' not in profile.text
    settings=client.get('/account/settings');assert 'name="force_concession"' in settings.text and 'name="birth_date"' in settings.text and 'name="new_password"' in settings.text
    assert client.get('/account/tickets').status_code==200
    assert client.get('/account/history').status_code==200


def test_fixture_and_test_numbers_are_idempotent_and_documented(cup):
    client,engine,event_id=cup
    with Session(engine) as db:
        for _ in range(2): assert ensure_demo_data(db).id==event_id
        event,phil,away,home_st,away_st=lookup(db,event_id)
        assert event.season_claim_required and event.competition=='NIFL League Cup'
        assert {inv.section.name for inv in event.inventories}=={'Sydenham End','Grandstand Upper','Lower Grandstand','City End','Railway Stand'}
        assert {tc.name:tc.price for tc in event.classes if tc.audience=='away'}=={'Adult':Decimal('15'),'Concession':Decimal('8'),'Disabled':Decimal('8')}
        assert db.scalar(select(Voucher).where(Voucher.code=='DEMO10')).value==10
        away.password_hash='changed';db.commit();ensure_demo_data(db);assert away.password_hash=='changed'
    from pathlib import Path
    readme=Path('README.md').read_text()
    for code in DEMO_CODES:
        assert code['number'] in client.get(f'/events/{event_id}').text
        assert code['number'] in client.get('/account/login').text
        assert code['number'] in readme


def test_claim_uses_registered_type_section_and_zero_price_without_payment(cup):
    client,engine,event_id=cup;sign_in(client)
    with Session(engine) as db:
        event,phil,_,st,_=lookup(db,event_id)
        st_id=st.id
        assert event_id in dashboard_data(db,phil)['claimable']
    page=client.get(f'/events/{event_id}');assert 'Adult · Sydenham End · £0.00' in page.text
    with patch('gateline.services.SimulatedPaymentService.charge',side_effect=AssertionError('Free claims must not charge')):
        response=client.post(f'/events/{event_id}/season-claim',data={'membership_id':st_id,'section_id':99999,'ticket_type':'VIP','price':'-100'},follow_redirects=False)
    assert response.status_code==303
    again=client.post(f'/events/{event_id}/season-claim',data={'membership_id':st_id},follow_redirects=False)
    assert again.headers['location']==response.headers['location']
    with Session(engine) as db:
        event,phil,_,st,_=lookup(db,event_id)
        tickets=db.scalars(select(Ticket).where(Ticket.event_id==event_id)).all();assert len(tickets)==1
        ticket=tickets[0]
        assert (ticket.ticket_class.name,ticket.section.name,ticket.price,ticket.attendee_user_id,ticket.season_ticket_id)==('Adult','Sydenham End',Decimal('0'),phil.id,st.id)
        assert ticket.complimentary and ticket.order.total==0 and ticket.order.payment_status=='successful'
        dashboard=dashboard_data(db,phil)
        assert dashboard['claimed']=={event_id} and dashboard['purchased']==set()
        assert event_id not in {event.id for event in dashboard['notices']}
        public_id=ticket.public_id
    assert public_id in client.get('/account/tickets').text
    assert 'Season-ticket claim' in client.get('/account/history').text
    assert client.get('/tickets/'+public_id+'/qr.png').status_code==200


def test_claim_honours_other_registered_types_and_sections(cup):
    _,engine,event_id=cup
    with Session(engine) as db:
        event,phil,_,st,_=lookup(db,event_id)
        st.section='Lower Grandstand';st.ticket_type='Concession';db.commit()
        # A club-issued season category remains authoritative for the claim.
        order=claim_season_ticket(db,event_id,phil,st.id)
        assert order.tickets[0].section.name=='Lower Grandstand'
        assert order.tickets[0].ticket_class.name=='Concession' and order.total==0


def test_claim_rejects_wrong_owner_expired_membership_and_unavailable_sales(cup):
    client,engine,event_id=cup;sign_in(client)
    with Session(engine) as db:
        event,phil,away,home_st,away_st=lookup(db,event_id)
        assert client.post(f'/events/{event_id}/season-claim',data={'membership_id':away_st.id}).status_code==409
        home_st.active=False;db.commit()
        assert client.post(f'/events/{event_id}/season-claim',data={'membership_id':home_st.id}).status_code==409
        home_st.active=True;home_st.valid_until=event.starts_at.date()-timedelta(days=1);db.commit()
        assert client.post(f'/events/{event_id}/season-claim',data={'membership_id':home_st.id}).status_code==409
        home_st.valid_until=event.starts_at.date()+timedelta(days=1);event.sales_suspended=True;db.commit()
        assert client.post(f'/events/{event_id}/season-claim',data={'membership_id':home_st.id}).status_code==409
        assert db.scalar(select(Ticket.id).where(Ticket.event_id==event_id)) is None


def test_claim_consumes_capacity_and_rejects_seat_tampering(cup):
    client,engine,event_id=cup;sign_in(client)
    with Session(engine) as db:
        event,phil,_,st,_=lookup(db,event_id)
        inv,_=claim_target(event,st);inv.capacity=1
        seat=db.scalar(select(Seat).join(SeatRow).join(Section).where(Section.name=='Railway Stand'));db.commit()
        assert client.post(f'/events/{event_id}/season-claim',data={'membership_id':st.id,'seat_id':seat.id}).status_code==409
        order=claim_season_ticket(db,event_id,phil,st.id)
        adult=order.tickets[0].ticket_class
        with pytest.raises(ValueError,match='unavailable'): reserve(db,event_id,inv.section_id,1,[],{adult.id:1})


def test_claim_ticket_must_be_scanned_and_attendance_counts_once(cup):
    _,engine,event_id=cup
    with Session(engine) as db:
        event,phil,_,st,_=lookup(db,event_id)
        operator=User(email='gate@demo.test',name='Gate',role='gate',password_hash='unused');db.add(operator);db.commit()
        assert scan_ticket(db,st.qr_token,event_id,operator)['result']=='CLAIM REQUIRED'
        order=claim_season_ticket(db,event_id,phil,st.id);ticket=order.tickets[0]
        assert dashboard_data(db,phil)['attended']==set()
        assert scan_ticket(db,ticket.qr_token,event_id,operator)['result']=='VALID'
        assert scan_ticket(db,ticket.qr_token,event_id,operator)['result']=='ALREADY USED'
        dashboard=dashboard_data(db,phil)
        assert dashboard['attended']=={event_id} and dashboard['season_attendance'][st.id]==1


def test_away_area_requires_owned_away_club_season_number(cup):
    client,engine,event_id=cup;sign_in(client)
    locked=client.get(f'/events/{event_id}')
    assert 'data-audience="away"' not in locked.text
    assert 'Disabled away fans' in locked.text and 'Lower Grandstand' in locked.text
    for code in ('12345','LF12345','ST001234','INVALID'):
        assert client.post(f'/events/{event_id}/away-access',data={'season_number':code}).status_code==400
    client.post('/logout');client.post('/account/login',data={'identity':'linfieldfan','password':'Linfield123!'})
    page=client.post(f'/events/{event_id}/away-access',data={'season_number':'LF12345'})
    assert page.status_code==200 and 'data-audience="away"' in page.text
    assert 'City End' in page.text and 'Railway Stand (seating)' in page.text
    assert 'Disabled · home section' in page.text


def test_away_reserve_and_checkout_recheck_access_and_allocations(cup):
    _,engine,event_id=cup
    with Session(engine) as db:
        event,phil,away,_,st=lookup(db,event_id)
        inv=next(inv for inv in event.inventories if inv.section.name=='City End')
        adult=next(tc for tc in event.classes if tc.audience=='away' and tc.name=='Adult')
        home_adult=next(tc for tc in event.classes if tc.audience=='home' and tc.name=='Adult')
        for kwargs in ({},dict(supporter=phil,away_season_number=st.number)):
            with pytest.raises(ValueError): reserve(db,event.id,inv.section_id,1,[],{adult.id:1},**kwargs)
        with pytest.raises(ValueError,match='available in this section'): reserve(db,event.id,inv.section_id,1,[],{home_adult.id:1},supporter=away,away_season_number=st.number)
        row=reserve(db,event.id,inv.section_id,1,[],{adult.id:1},supporter=away,away_season_number=st.number)
        with pytest.raises(ValueError,match='account'): checkout(db,row.token,None,customer(),supporter=phil,personal_index=0,attendee_birth_dates=[''])
        st.active=False;db.commit()
        with pytest.raises(ValueError,match='season-ticket'): checkout(db,row.token,None,customer(),supporter=away,personal_index=0,attendee_birth_dates=[''])
        st.active=True;db.commit()
        order=checkout(db,row.token,None,customer(),supporter=away,personal_index=0,attendee_birth_dates=[''],voucher_code='DEMO10')
        assert order.total==Decimal('13.50') and order.tickets[0].section.name=='City End'


def test_railway_away_tickets_use_assigned_seats(cup):
    _,engine,event_id=cup
    with Session(engine) as db:
        event,_,away,_,st=lookup(db,event_id)
        inv=next(inv for inv in event.inventories if inv.section.name=='Railway Stand')
        adult=next(tc for tc in event.classes if tc.audience=='away' and tc.name=='Adult')
        seats=db.scalars(select(Seat).join(SeatRow).where(SeatRow.section_id==inv.section_id).limit(2)).all()
        with pytest.raises(ValueError,match='distinct seats'): reserve(db,event.id,inv.section_id,2,[],{adult.id:2},supporter=away,away_season_number=st.number)
        row=reserve(db,event.id,inv.section_id,2,[seat.id for seat in seats],{adult.id:2},supporter=away,away_season_number=st.number)
        order=checkout(db,row.token,None,customer(),supporter=away,personal_index=0,attendee_birth_dates=['',''])
        assert order.total==30 and {ticket.seat_id for ticket in order.tickets}=={seat.id for seat in seats}
        gate=db.scalar(select(User).where(User.email=='awaygate@gateline.test'))
        assert scan_ticket(db,order.tickets[0].qr_token,event.id,gate,gate='Gate 1')['result']=='WRONG ENTRANCE'
        assert scan_ticket(db,order.tickets[0].qr_token,event.id,gate,gate=gate.gate)['result']=='VALID'


def test_home_and_away_disabled_share_physical_capacity_and_remain_at_home_lower_grandstand(cup):
    _,engine,event_id=cup
    with Session(engine) as db:
        event,phil,away,_,st=lookup(db,event_id)
        inv=next(inv for inv in event.inventories if inv.section.name=='Lower Grandstand');inv.capacity=1
        home=next(tc for tc in event.classes if tc.audience=='home' and tc.name=='Disabled')
        visiting=next(tc for tc in event.classes if tc.audience=='away' and tc.name=='Disabled')
        db.get(SupporterProfile,phil.id).force_concession=True
        db.get(SupporterProfile,away.id).force_concession=True;db.commit()
        row=reserve(db,event.id,inv.section_id,1,[],{home.id:1},supporter=phil)
        with pytest.raises(ValueError,match='unavailable'): reserve(db,event.id,inv.section_id,1,[],{visiting.id:1},supporter=away,away_season_number=st.number)
        row.expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);db.commit()
        row=reserve(db,event.id,inv.section_id,1,[],{visiting.id:1},supporter=away,away_season_number=st.number)
        order=checkout(db,row.token,None,customer(),supporter=away,personal_index=0,attendee_birth_dates=[''])
        assert order.total==8 and order.tickets[0].section.name=='Lower Grandstand'


def test_home_price_edit_preserves_away_model_and_section_restrictions(cup):
    _,engine,event_id=cup
    with Session(engine) as db:
        event,_,_,_,_=lookup(db,event_id)
        save_club_pricing(db,'Glentoran',['Adult','Concession','Disabled'],['22','9','8'],['Adult','Concession','Disabled'],['adult','other','other'])
        upgrade_club_tickets(db)
        assert {tc.name:tc.price for tc in offered_classes(event) if tc.audience=='away'}=={'Adult':Decimal('15'),'Concession':Decimal('8'),'Disabled':Decimal('8')}
        disabled=next(tc for tc in offered_classes(event) if tc.audience=='home' and tc.name=='Disabled')
        assert db.get(Section,disabled.section_id).name=='Lower Grandstand'


def test_settings_change_credentials_with_current_password_and_sync_season_record(cup):
    client,engine,_=cup;sign_in(client)
    data={'full_name':'Phil McVeigh','birth_date':'1992-03-17','clubs':['Glentoran'],'email':'newphil@example.com','new_password':'NewPassword123!','password_confirmation':'NewPassword123!'}
    assert client.post('/account/settings',data=data).status_code==400
    data['current_password']='password123!'
    assert client.post('/account/settings',data=data).status_code==200
    with Session(engine) as db:
        st=db.scalar(select(SeasonTicket).where(SeasonTicket.number=='12345'));assert st.email=='newphil@example.com'
        ensure_demo_data(db)  # Later edits are not reset by the test initializer.
    client.post('/logout')
    assert client.post('/account/login',data={'identity':'newphil@example.com','password':'NewPassword123!'}).status_code==200


def test_cancelled_claim_is_not_reissued_and_cancelled_fixture_does_not_admit(cup):
    _,engine,event_id=cup
    with Session(engine) as db:
        event,phil,_,st,_=lookup(db,event_id)
        order=claim_season_ticket(db,event_id,phil,st.id);ticket=order.tickets[0]
        ticket.status='cancelled';db.commit()
        with pytest.raises(ValueError,match='cancelled'): claim_season_ticket(db,event_id,phil,st.id)
        assert event_id not in dashboard_data(db,phil)['claimable']
        ticket.status='sold';event.cancelled=True
        operator=User(email='gate@demo.test',name='Gate',role='gate',password_hash='unused');db.add(operator);db.commit()
        assert scan_ticket(db,ticket.qr_token,event_id,operator)['result']=='INVALID FIXTURE'
        assert db.scalar(select(SupporterAttendance.id)) is None


def test_railway_seats_are_printed_and_occupied_seats_are_disabled(cup):
    client,engine,event_id=cup
    client.post('/account/login',data={'identity':'linfieldfan','password':'Linfield123!'})
    client.post(f'/events/{event_id}/away-access',data={'season_number':'LF12345'})
    with Session(engine) as db:
        event,_,away,_,st=lookup(db,event_id)
        inv=next(inv for inv in event.inventories if inv.section.name=='Railway Stand')
        adult=next(tc for tc in event.classes if tc.audience=='away' and tc.name=='Adult')
        seat=inv.section.rows[0].seats[0];seat_id=seat.id
        inv.held=inv.capacity;db.commit()
        with pytest.raises(ValueError,match='unavailable'): reserve(db,event.id,inv.section_id,1,[seat_id],{adult.id:1},supporter=away,away_season_number=st.number)
        inv.held=0;db.commit()
        reservation=reserve(db,event.id,inv.section_id,1,[seat_id],{adult.id:1},supporter=away,away_season_number=st.number)
        order=checkout(db,reservation.token,None,customer(),supporter=away,personal_index=0,attendee_birth_dates=[''])
        public_id=order.tickets[0].public_id
    printed=client.get('/tickets/'+public_id)
    assert 'Seat A-1' in printed.text and 'Away supporter' in printed.text
    page=client.get(f'/events/{event_id}')
    assert f'name="seat_choice" value="{seat_id}" disabled' in page.text
