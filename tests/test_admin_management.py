from datetime import date, datetime, timedelta, timezone
import re, secrets
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from gateline.auth import hash_password, verify
from gateline.management import initialise_management
from gateline.models import *
from gateline.services import reserve, checkout
from gateline.clubs import LEAGUES
from gateline.ticketing import club_key
from test_supporters import portal
from test_ticketing import customer

@pytest.fixture
def managed(portal):
    client,engine=portal
    with Session(engine) as db: initialise_management(db,['Glentoran','Linfield'])
    return client,engine

def login(client,identity='glentoran.admin',password='ClubAdmin123!'):
    response=client.post('/login',data={'email':identity,'password':password},follow_redirects=False)
    assert response.status_code==303
    return response

def issue_token(client):
    page=client.get('/admin/clubs/Glentoran/season-tickets/new')
    assert page.status_code==200
    return re.search(r'name="token" value="([^"]+)"',page.text).group(1)

def test_all_clubs_have_isolated_accounts_and_global_admin_is_preserved(managed):
    client,engine=managed
    with Session(engine) as db:
        initial=db.scalar(select(User).where(User.email=='admin@test.test')).password_hash
        initialise_management(db)
        assert {u.managed_club for u in db.scalars(select(User).where(User.role=='club_admin'))}=={club_key(entry.name) for entries in LEAGUES.values() for entry in entries}
        admin=db.scalar(select(User).where(User.username=='glentoran.admin'));admin.password_hash=hash_password('Changed123!');db.commit()
        initialise_management(db)
        assert verify('Changed123!',admin.password_hash)
        assert db.scalar(select(User).where(User.email=='admin@test.test')).password_hash==initial
        assert db.get(ClubManagement,'banbridge town').venue_id
    login(client,'admin@test.test','Test123!')
    assert client.get('/admin/club-accounts').status_code==200

@pytest.mark.parametrize('path',[
 '/admin/clubs/Linfield','/admin/clubs/Linfield/details','/admin/clubs/Linfield/pricing',
 '/admin/clubs/Linfield/season-tickets','/admin/clubs/Linfield/season-products','/admin/clubs/Linfield/activity',
 '/admin/events/1','/admin/events/1/attendance','/admin/events/1/tickets.csv',
 '/admin/clubs/Linfield/season-tickets/new'])
def test_club_admin_cannot_read_another_clubs_resources(managed,path):
    client,_=managed;login(client)
    assert client.get(path).status_code==404

@pytest.mark.parametrize('path,data',[
 ('/admin/events/1/state',{'action':'cancel','reason':'wrong club'}),
 ('/admin/events/1/publish',{}),
 ('/admin/clubs/Linfield/pricing',{}),
 ('/admin/clubs/Linfield/details',{'display_name':'Changed','short_name':'Other'}),
 ('/admin/clubs/Linfield/season-products',{'title':'Fake','section':'Area','ticket_type':'Adult','competition':'League','valid_from':'2027-07-01','valid_until':'2028-06-30','price':'1','capacity':100}),
 ])
def test_cross_club_writes_are_rejected(managed,path,data):
    client,_=managed;login(client)
    assert client.post(path,data=data).status_code==404

def test_club_scope_applies_to_admin_search_orders_qr_and_cancellation(managed):
    client,engine=managed
    with Session(engine) as db:
        foreign=db.get(Event,1);own=db.get(Event,2)
        records=[]
        for event in (foreign,own):
            tc=next(tc for tc in event.classes if tc.name=='Adult')
            row=reserve(db,event.id,1,1,[],{tc.id:1})
            order=checkout(db,row.token,None,customer());records.append((order.reference,order.tickets[0].public_id,order.tickets[0].id))
    login(client)
    admin=client.get('/admin');assert '/admin/events/1' not in admin.text and '/admin/events/2' in admin.text
    for ref,public_id,ticket_id in records[:1]:
        assert ref not in client.get('/admin/search',params={'q':'Test Fan'}).text
        assert client.get('/orders/'+ref).status_code==404
        assert client.get('/tickets/'+public_id).status_code==404
        assert client.get('/tickets/'+public_id+'/qr.png').status_code==404
        assert client.post(f'/admin/tickets/{ticket_id}/cancel',data={'reason':'No'}).status_code==404
    assert client.get('/orders/'+records[1][0]).status_code==200
    assert client.get('/tickets/'+records[1][1]+'/qr.png').status_code==200
    assert client.get('/admin/club-accounts').status_code==403
    assert client.get('/admin?q=not-a-match').status_code==200
    assert '/admin/events/2' not in client.get('/admin?q=not-a-match').text


def test_club_details_and_event_create_amend_inventory_and_class_controls(managed):
    client,engine=managed;login(client)
    response=client.post('/admin/clubs/Glentoran/details',data={'display_name':'Glentoran FC','short_name':'Glens','contact_email':'tickets@glens.test','address':'The Oval','description':'Club info','primary_colour':'#008844','venue_id':1})
    assert response.status_code==200 and 'Glentoran FC' in response.text
    now=datetime.now(timezone.utc)
    payload={'title':'Glentoran v Ards','home_team':'Glentoran','away_team':'Ards','competition':'Test Cup','venue_id':1,'starts_at':(now+timedelta(days=3)).isoformat(),'sales_open':(now-timedelta(days=1)).isoformat(),'sales_close':(now+timedelta(days=2)).isoformat()}
    rejected=client.post('/admin/events',data={**payload,'home_team':'Linfield'},follow_redirects=False)
    assert rejected.status_code==404
    created=client.post('/admin/events',data=payload,follow_redirects=False);assert created.status_code==303
    event_id=int(created.headers['location'].split('/')[-1])
    payload['title']='Glentoran v Ards (updated)';payload['description']='Revised fixture'
    assert client.post(f'/admin/events/{event_id}/edit',data=payload).status_code==200
    with Session(engine) as db:
        event=db.get(Event,event_id);assert event.owner_club=='glentoran' and event.description=='Revised fixture'
        inv=event.inventories[0];inv_id=inv.id
    assert client.post(f'/admin/events/{event_id}/inventory/{inv_id}',data={'capacity':50,'held':5,'audience':'home'}).status_code==200
    assert client.post(f'/admin/events/{event_id}/ticket-types',data={'name':'Adult Terrace','price':'19','audience':'home','adult':'true','enabled':'true','maximum':10}).status_code==200
    assert 'event.amended' in client.get('/admin/clubs/Glentoran/activity').text


def test_event_changes_protect_existing_bookings_and_scope_child_ids(managed):
    client,engine=managed;login(client)
    with Session(engine) as db:
        event=db.get(Event,2);foreign=db.get(Event,1)
        tc=event.classes[0];other=foreign.classes[0];inv=event.inventories[0]
        r=reserve(db,event.id,inv.section_id,1,[],{tc.id:1});order=checkout(db,r.token,None,customer())
        dates={key:getattr(event,key).isoformat() for key in ('starts_at','sales_open','sales_close')}
        inv_id=inv.id;tc_id=tc.id;other_id=other.id
    payload={**dates,'title':'Updated fixture','away_team':'Visitors','competition':'Cup','venue_id':1,'season_claim_required':'true'}
    assert client.post('/admin/events/2/edit',data=payload).status_code==409
    assert client.post(f'/admin/events/2/inventory/{inv_id}',data={'capacity':0,'held':0,'audience':'home'}).status_code==409
    assert client.post('/admin/events/2/ticket-types',data={'class_id':other_id,'name':'Other','price':'20'}).status_code==404
    assert client.post('/admin/events/2/ticket-types',data={'class_id':tc_id,'name':'Renamed','price':'20','audience':'home'}).status_code==409


def test_issue_creates_new_supporter_pass_and_shows_password_once(managed):
    client,engine=managed;login(client);token=issue_token(client)
    with Session(engine) as db: product=db.scalar(select(SeasonProduct).where(SeasonProduct.ticket_type=='Adult'));product_id=product.id
    data={'token':token,'full_name':'New Season Fan','email':'newseason@example.com','birth_date':'1990-01-01','product_id':product_id}
    response=client.post('/admin/clubs/Glentoran/season-tickets/new',data=data)
    assert response.status_code==200 and response.headers['cache-control']=='no-store'
    password=re.search(r'id="initial-password">([^<]+)',response.text).group(1)
    with Session(engine) as db:
        fan=db.scalar(select(User).where(User.email=='newseason@example.com'));assert fan.role=='supporter' and verify(password,fan.password_hash)
        st=db.scalar(select(SeasonTicket).where(SeasonTicket.user_id==fan.id));assert st.section=='Sydenham End' and st.ticket_type=='Adult'
        assert st.number.startswith('GLENTORAN-ST-');st_id=st.id
        assert db.get(SupporterProfile,fan.id).birth_date==date(1990,1,1)
    assert client.get(f'/admin/clubs/Glentoran/season-tickets/{st_id}/qr.png').status_code==200
    again=client.post('/admin/clubs/Glentoran/season-tickets/new',data=data)
    assert 'id="initial-password"' not in again.text
    with Session(engine) as db: assert len(db.scalars(select(SeasonTicket).where(SeasonTicket.user_id==fan.id)).all())==1
    client.post('/logout')
    assert client.post('/account/login',data={'identity':'newseason@example.com','password':password}).status_code==200


def test_issue_links_existing_customer_without_changing_credentials_or_profile(managed):
    client,engine=managed;login(client);token=issue_token(client)
    with Session(engine) as db:
        phil=db.scalar(select(User).where(User.username=='philmcveigh'));original_hash=phil.password_hash
        product=db.scalar(select(SeasonProduct).where(SeasonProduct.ticket_type=='Adult'));product_id=product.id
    response=client.post('/admin/clubs/Glentoran/season-tickets/new',data={'token':token,'full_name':'Different submitted name','email':'phil.mcveigh@gateline.com','birth_date':'2099-01-01','product_id':product_id})
    assert response.status_code==200 and 'login details have not changed' in response.text
    with Session(engine) as db:
        assert db.get(User,phil.id).password_hash==original_hash
        assert db.get(User,phil.id).name=='Phil McVeigh'
        assert db.get(SupporterProfile,phil.id).birth_date==date(1992,3,17)
        assert len(db.scalars(select(SeasonTicket).where(SeasonTicket.user_id==phil.id)).all())==2


def test_issue_rejects_staff_emails_and_invalid_new_account_dob_without_mutation(managed):
    client,engine=managed;login(client);token=issue_token(client)
    with Session(engine) as db: product_id=db.scalar(select(SeasonProduct.id))
    data={'token':token,'full_name':'Fan','email':'admin@test.test','birth_date':'1990-01-01','product_id':product_id}
    assert client.post('/admin/clubs/Glentoran/season-tickets/new',data=data).status_code==400
    assert client.post('/admin/clubs/Glentoran/season-tickets/new',data={**data,'email':'invalidnew@example.com','birth_date':'2099-01-01'}).status_code==400
    with Session(engine) as db:
        assert db.scalar(select(User.id).where(User.email=='invalidnew@example.com')) is None
        assert db.get(SeasonProduct,product_id).issued==0


def purchase_token(client,product_id):
    page=client.get(f'/season-tickets/products/{product_id}');assert page.status_code==200
    return re.search(r'name="token" type="hidden" value="([^"]+)"',page.text).group(1)

def supporter_login(client):
    client.post('/account/login',data={'identity':'philmcveigh','password':'password123!'})


def test_existing_customer_buys_glentoran_season_and_replays_do_not_duplicate(managed):
    client,engine=managed;supporter_login(client)
    with Session(engine) as db: product_id=db.scalar(select(SeasonProduct.id).where(SeasonProduct.ticket_type=='Adult'))
    token=purchase_token(client,product_id)
    response=client.post(f'/season-tickets/products/{product_id}',data={'token':token,'test_result':'success','price':'0'},follow_redirects=False)
    assert response.status_code==303
    again=client.post(f'/season-tickets/products/{product_id}',data={'token':token},follow_redirects=False)
    assert response.headers['location']==again.headers['location']
    receipt=client.get(response.headers['location']);assert '£250.00' in receipt.text and 'View & print season ticket' in receipt.text
    with Session(engine) as db:
        row=db.scalar(select(SeasonPurchase));assert row.total==250 and row.user.username=='philmcveigh'
        assert db.get(SeasonProduct,product_id).issued==1 and row.season_ticket.number.startswith('GLENTORAN-ST-')
    assert 'Glentoran' in client.get('/account/history').text
    client.post('/logout');login(client)
    assert '£250.00' in client.get('/admin/clubs/Glentoran/season-products').text
    assert client.get(response.headers['location']).status_code==200
    client.post('/logout');login(client,'linfield.admin')
    assert client.get(response.headers['location']).status_code==404


def test_declined_season_purchase_does_not_issue_or_consume_capacity(managed):
    client,engine=managed;supporter_login(client)
    with Session(engine) as db: product_id=db.scalar(select(SeasonProduct.id).where(SeasonProduct.ticket_type=='Adult'))
    token=purchase_token(client,product_id)
    response=client.post(f'/season-tickets/products/{product_id}',data={'token':token,'test_result':'fail'})
    assert 'Test payment declined' in response.text
    with Session(engine) as db:
        receipt=db.scalar(select(SeasonPurchase));assert receipt.payment_status=='failed' and receipt.season_ticket_id is None
        assert db.get(SeasonProduct,product_id).issued==0


def test_season_purchase_checks_concession_age_and_disability_and_normal_adult_is_available(managed):
    client,engine=managed;supporter_login(client)
    with Session(engine) as db: product_id=db.scalar(select(SeasonProduct.id).where(SeasonProduct.ticket_type=='Concession'))
    token=purchase_token(client,product_id)
    assert client.post(f'/season-tickets/products/{product_id}',data={'token':token}).status_code==400
    with Session(engine) as db:
        phil=db.scalar(select(User).where(User.username=='philmcveigh'));db.get(SupporterProfile,phil.id).force_concession=True;db.commit()
    response=client.post(f'/season-tickets/products/{product_id}',data={'token':token});assert '£150.00' in response.text


def test_manual_issued_capacity_and_sale_controls_are_enforced(managed):
    client,engine=managed;login(client)
    with Session(engine) as db:
        product=db.scalar(select(SeasonProduct).where(SeasonProduct.ticket_type=='Adult'));product.capacity=1;db.commit();pid=product.id
    token=issue_token(client)
    data={'token':token,'full_name':'Only Fan','email':'only@example.com','birth_date':'1990-01-01','product_id':pid}
    assert client.post('/admin/clubs/Glentoran/season-tickets/new',data=data).status_code==200
    token=issue_token(client)
    assert client.post('/admin/clubs/Glentoran/season-tickets/new',data={**data,'token':token,'email':'extra@example.com'}).status_code==400
    with Session(engine) as db:
        assert db.get(SeasonProduct,pid).issued==1
        assert db.scalar(select(User.id).where(User.email=='extra@example.com')) is None
    client.post('/logout');supporter_login(client);token=purchase_token(client,pid)
    assert client.post(f'/season-tickets/products/{pid}',data={'token':token}).status_code==400


def test_global_admin_can_add_club_admin_and_clubs_cannot_grant_roles(managed):
    client,engine=managed;login(client)
    data={'club_name':'linfield','full_name':'Second Admin','email':'secondadmin@example.com','username':'second.admin','role':'admin'}
    assert client.post('/admin/club-accounts',data=data).status_code==403
    client.post('/logout');login(client,'admin@test.test','Test123!')
    response=client.post('/admin/club-accounts',data=data)
    assert response.status_code==200 and response.headers['cache-control']=='no-store'
    with Session(engine) as db:
        user=db.scalar(select(User).where(User.username=='second.admin'))
        assert user.role=='club_admin' and user.managed_club=='linfield'
    assert client.post('/admin/club-accounts',data=data).status_code==409


def test_season_search_and_qr_remain_club_scoped(managed):
    client,engine=managed
    with Session(engine) as db:
        phil=db.scalar(select(User).where(User.username=='philmcveigh'))
        foreign=SeasonTicket(club_name='linfield',number='PRIVATE-LINFIELD-PASS',user_id=phil.id,full_name=phil.name,email=phil.email,section='Other section',ticket_type='Adult',valid_from=date(2027,7,1),valid_until=date(2028,6,30));db.add(foreign);db.commit();foreign_id=foreign.id
    login(client)
    page=client.get('/admin/search',params={'q':'Phil'})
    assert '12345' in page.text and 'PRIVATE-LINFIELD-PASS' not in page.text
    assert client.get(f'/admin/clubs/Glentoran/season-tickets/{foreign_id}/qr.png').status_code==404
    assert client.post(f'/admin/clubs/Glentoran/season-tickets/{foreign_id}/state',data={'active':'false','reason':'wrong club'}).status_code==404


def test_purchase_login_redirect_and_staff_preview_are_safe(managed):
    client,engine=managed
    with Session(engine) as db: pid=db.scalar(select(SeasonProduct.id))
    response=client.get(f'/season-tickets/products/{pid}')
    assert '/account/login' in str(response.url)
    response=client.post(f'/account/login?next=/season-tickets/products/{pid}',data={'identity':'philmcveigh','password':'password123!'})
    assert response.status_code==200 and 'Complete test season-ticket purchase' in response.text
    client.post('/logout');login(client)
    page=client.get(f'/season-tickets/products/{pid}')
    assert page.status_code==200 and 'Customer purchase preview' in page.text and 'Complete test season-ticket purchase' not in page.text
    assert client.post(f'/season-tickets/products/{pid}',data={'token':'fake'}).status_code==403


def test_issued_product_allocation_cannot_change_and_disabled_sale_is_preserved(managed):
    client,engine=managed;login(client)
    with Session(engine) as db: product=db.scalar(select(SeasonProduct).where(SeasonProduct.ticket_type=='Adult'));pid=product.id
    token=issue_token(client)
    assert client.post('/admin/clubs/Glentoran/season-tickets/new',data={'token':token,'full_name':'Buyer','email':'buyer@example.com','birth_date':'1990-01-01','product_id':pid}).status_code==200
    data={'product_id':pid,'title':'Adult offer','section':'Wrong section','ticket_type':'Adult','competition':'NIFL Premiership','valid_from':'2027-07-01','valid_until':'2028-06-30','price':'300','capacity':200}
    assert client.post('/admin/clubs/Glentoran/season-products',data=data).status_code==400
    data['section']='Sydenham End'
    assert client.post('/admin/clubs/Glentoran/season-products',data=data).status_code==200
    with Session(engine) as db:
        initialise_management(db,['Glentoran','Linfield'])
        assert not db.get(SeasonProduct,pid).enabled and db.get(SeasonProduct,pid).price==300
    client.post('/logout');supporter_login(client)
    assert client.get(f'/season-tickets/products/{pid}').status_code==404
