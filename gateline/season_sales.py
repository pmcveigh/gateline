"""Season-ticket issuance, account linking and simulated purchases."""
from datetime import datetime, time, timezone
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import json, re, secrets
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from .auth import hash_password
from .models import *
from .supporters import london_date, parse_birth_date, validate_attendees
from .ticketing import club_key, ticket_prefix


def amount(raw):
    try: value=Decimal(str(raw))
    except InvalidOperation: raise ValueError('Enter a valid price')
    if not value.is_finite() or value<0 or value>Decimal("999999.99") or value.quantize(Decimal('.01'))!=value: raise ValueError('Prices require at most two decimal places and cannot be negative')
    return value


def normalise_type(name):
    name=name.strip()
    return {'adult':'Adult','concession':'Concession','under 11':'Under 11','vip':'VIP','child':'Child'}.get(name.casefold(),name)


def season_number(name): return ticket_prefix(name)+'-ST-'+secrets.token_hex(6).upper()


def mint_pass(db,user,club,section,ticket_type,competition,valid_from,valid_until,product_id=None,issuance_token=None):
    existing=db.scalar(select(SeasonTicket.id).where(SeasonTicket.club_name==club,SeasonTicket.user_id==user.id,func.lower(SeasonTicket.section)==section.casefold(),func.lower(SeasonTicket.ticket_type)==ticket_type.casefold(),SeasonTicket.active==True,SeasonTicket.valid_from<=valid_until,SeasonTicket.valid_until>=valid_from))
    if existing: raise ValueError('This supporter already has an overlapping season ticket for that section and type')
    st=SeasonTicket(club_name=club,number=season_number(club),user_id=user.id,full_name=user.name,email=user.email,section=section,ticket_type=ticket_type,competition=competition,valid_from=valid_from,valid_until=valid_until,product_id=product_id,issuance_token=issuance_token)
    db.add(st);db.flush();return st


def allocate_product(db,product,online=False):
    conditions=[SeasonProduct.id==product.id,SeasonProduct.issued<SeasonProduct.capacity]
    if online: conditions.extend([SeasonProduct.enabled==True,SeasonProduct.price==product.price])
    changed=db.execute(update(SeasonProduct).where(*conditions).values(issued=SeasonProduct.issued+1).execution_options(synchronize_session='fetch'))
    if changed.rowcount!=1: raise ValueError('This season-ticket product is no longer available')


def issue_holder(db,club,full_name,email,birth_date,section,ticket_type,competition,valid_from,valid_until,token,actor,product=None):
    from .management import check_club
    check_club(actor,club.club_name)
    prior=db.scalar(select(SeasonTicket).where(SeasonTicket.issuance_token==token))
    if prior:
        if prior.club_name!=club.club_name: raise ValueError('Invalid issuance request')
        return prior,None
    if not token or len(token)>100: raise ValueError('Refresh the issue form and try again')
    email=email.strip().casefold();full_name=full_name.strip()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email) or len(email)>200 or not full_name or len(full_name)>120: raise ValueError('Enter a valid holder name and email')
    user=db.scalar(select(User).where(func.lower(User.email)==email));password=None
    if user and user.role!='supporter': raise ValueError('A staff account cannot be used as a season-ticket holder')
    if not user:
        born=parse_birth_date(birth_date,True);password=secrets.token_urlsafe(15)
        user=User(username='fan-'+secrets.token_hex(6),name=full_name,email=email,role='supporter',password_hash=hash_password(password));db.add(user);db.flush()
        db.add(SupporterProfile(user_id=user.id,birth_date=born,clubs_json=json.dumps([club.name])))
    if product:
        if product.club_name!=club.club_name: raise ValueError('Choose a product belonging to this club')
        allocate_product(db,product)
        section,ticket_type,competition,valid_from,valid_until=product.section,product.ticket_type,product.competition,product.valid_from,product.valid_until
    if not section.strip() or not ticket_type.strip() or not competition.strip() or len(section)>100 or len(ticket_type)>100 or len(competition)>150 or valid_from>valid_until: raise ValueError('Check section, ticket type, competition and season dates')
    if normalise_type(ticket_type) in ('VIP','Under 11'):
        day=max(london_date(),valid_from)
        fixture=SimpleNamespace(starts_at=datetime.combine(day,time(15),tzinfo=ZoneInfo('Europe/London')))
        validate_attendees(fixture,[(TicketClass(name=normalise_type(ticket_type),price=0),1)],db.get(SupporterProfile,user.id),0,[''])
    st=mint_pass(db,user,club.club_name,section.strip(),normalise_type(ticket_type),competition.strip(),valid_from,valid_until,product.id if product else None,token)
    db.add(AuditLog(user_id=actor.id,action='season.issued',entity='season_ticket',entity_id=str(st.id)))
    try: db.commit()
    except IntegrityError:
        db.rollback();raise ValueError('The holder or season ticket already exists. Refresh and retry.')
    return st,password


def purchase_season(db,product,user,token,result):
    from .services import SimulatedPaymentService
    prior=db.scalar(select(SeasonPurchase).where(SeasonPurchase.token==token))
    if prior:
        if prior.user_id!=user.id or prior.product_id!=product.id: raise ValueError('Invalid purchase request')
        return prior
    if not product.enabled or product.valid_until<london_date() or product.issued>=product.capacity: raise ValueError('This season ticket is not currently on sale')
    if user.role!='supporter': raise ValueError('Sign in with a supporter account')
    profile=db.get(SupporterProfile,user.id)
    day=max(london_date(),product.valid_from)
    fixture=SimpleNamespace(starts_at=datetime.combine(day,time(15),tzinfo=ZoneInfo('Europe/London')))
    tc=TicketClass(name=product.ticket_type,price=product.price,concession_under=product.concession_under,concession_over=product.concession_over)
    validate_attendees(fixture,[(tc,1)],profile,0,[''])
    payment=SimulatedPaymentService().charge(product.price,result)
    receipt=SeasonPurchase(reference='GL-ST-'+secrets.token_hex(6).upper(),token=token,user_id=user.id,product_id=product.id,total=product.price,payment_status='successful' if payment.successful else 'failed')
    if payment.successful:
        allocate_product(db,product,True)
        st=mint_pass(db,user,product.club_name,product.section,product.ticket_type,product.competition,product.valid_from,product.valid_until,product.id)
        receipt.season_ticket_id=st.id
        db.add(AuditLog(user_id=user.id,action='season.purchased',entity='season_ticket',entity_id=str(st.id)))
    db.add(receipt)
    try: db.commit()
    except IntegrityError:
        db.rollback();raise ValueError('This purchase or season ticket has already been processed')
    return receipt
