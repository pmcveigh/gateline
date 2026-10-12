"""Supporter profiles, personal eligibility, verified season tickets and dashboards."""
from collections import Counter
from datetime import date, datetime, timezone
import json, re
from zoneinfo import ZoneInfo
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from .auth import hash_password
from .clubs import LEAGUES
from .models import *
from .ticketing import club_key, offered_classes


def london_date(value=None):
    value=value or datetime.now(timezone.utc)
    if value.tzinfo is None: value=value.replace(tzinfo=timezone.utc)
    return value.astimezone(ZoneInfo("Europe/London")).date()


def age_on(birth_date, day):
    if birth_date is None: return None
    return day.year-birth_date.year-((day.month,day.day)<(birth_date.month,birth_date.day))


def parse_birth_date(raw, required=False):
    if not raw:
        if required: raise ValueError("Enter your date of birth")
        return None
    try: born=date.fromisoformat(raw)
    except (TypeError,ValueError): raise ValueError("Enter a valid date of birth")
    if born>london_date(): raise ValueError("Date of birth cannot be in the future")
    return born


def club_choices(db):
    names={entry.name for clubs in LEAGUES.values() for entry in clubs}
    names.update(db.scalars(select(Event.home_team).distinct()).all())
    return sorted(names)


def clean_interests(db, clubs):
    known={club_key(name):name for name in club_choices(db)}
    if any(club_key(name) not in known for name in clubs): raise ValueError("Choose clubs from the available list")
    return sorted({known[club_key(name)] for name in clubs})


def register_supporter(db, username, full_name, email, password, confirmation, birth_date, clubs):
    username=username.strip().casefold();email=email.strip().casefold();full_name=full_name.strip()
    if not re.fullmatch(r"[a-z0-9_.-]{3,30}",username): raise ValueError("Use a username of 3–30 letters, numbers, dots, underscores or hyphens")
    if not full_name or len(full_name)>120: raise ValueError("Enter your full name")
    if len(email)>200 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",email): raise ValueError("Enter a valid email address")
    if len(password)<8 or len(password.encode())>72: raise ValueError("Use a password of at least 8 characters and no more than 72 bytes")
    if password!=confirmation: raise ValueError("Passwords do not match")
    born=parse_birth_date(birth_date,True);interests=clean_interests(db,clubs)
    if db.scalar(select(User).where((func.lower(User.email)==email)|(User.username==username))): raise ValueError("That username or email is already in use")
    user=User(username=username,name=full_name,email=email,password_hash=hash_password(password),role="supporter")
    try:
        db.add(user);db.flush()
        db.add(SupporterProfile(user_id=user.id,birth_date=born,clubs_json=json.dumps(interests)))
        db.commit()
    except IntegrityError:
        db.rollback();raise ValueError("That username or email is already in use")
    db.refresh(user);return user


def profile_for(db,user):
    profile=db.get(SupporterProfile,user.id)
    if not profile:
        profile=SupporterProfile(user_id=user.id);db.add(profile);db.flush()
    return profile


def save_profile(db,user,full_name,birth_date,clubs,force_concession,disability_type,access_details,share_access_needs,address1,address2,city,postcode,country):
    if not full_name.strip() or len(full_name.strip())>120: raise ValueError("Enter your full name")
    born=parse_birth_date(birth_date,True);interests=clean_interests(db,clubs)
    if len(disability_type)>300 or len(access_details)>2000: raise ValueError("Keep the disability type under 300 characters and access details under 2,000")
    profile=profile_for(db,user);user.name=full_name.strip()
    profile.birth_date=born;profile.clubs_json=json.dumps(interests);profile.force_concession=force_concession
    profile.disability_type=disability_type.strip();profile.access_details=access_details.strip();profile.share_access_needs=share_access_needs
    for field,value in dict(address1=address1,address2=address2,city=city,postcode=postcode,country=country).items(): setattr(profile,field,value.strip())
    for membership in db.scalars(select(SeasonTicket).where(SeasonTicket.user_id==user.id)):
        membership.full_name=user.name;membership.email=user.email
    db.commit();return profile


def ensure_test_supporter(db):
    """Create the explicitly requested test identity once; preserve later edits."""
    user=db.scalar(select(User).where(User.username=="philmcveigh"))
    if not user:
        if db.scalar(select(User).where(func.lower(User.email)=="phil.mcveigh@gateline.com")):
            raise ValueError("The test account email already belongs to another identity")
        user=User(username="philmcveigh",name="Phil McVeigh",email="phil.mcveigh@gateline.com",password_hash=hash_password("password123!"),role="supporter")
        db.add(user);db.flush()
        db.add(SupporterProfile(user_id=user.id,birth_date=date(1992,3,17),clubs_json=json.dumps(["Glentoran"])))
    elif user.role!="supporter":
        raise ValueError("The test username belongs to a different identity")
    profile_for(db,user)
    membership=db.scalar(select(SeasonTicket).where(SeasonTicket.club_name==club_key("Glentoran"),SeasonTicket.number=="12345"))
    if membership and membership.user_id!=user.id: raise ValueError("Glentoran season ticket 12345 belongs to another supporter")
    if not membership:
        today=london_date();year=today.year if today.month>=7 else today.year-1
        db.add(SeasonTicket(club_name=club_key("Glentoran"),number="12345",user_id=user.id,full_name="Phil McVeigh",email="phil.mcveigh@gateline.com",section="Sydenham End",ticket_type="Adult",valid_from=date(year,7,1),valid_until=date(year+1,6,30)))
    db.commit();return user


def covers_event(membership,event):
    competition=event.competition.replace("’","'").casefold();covered=membership.competition.replace("’","'").casefold()
    return membership.active and club_key(event.home_team)==membership.club_name and membership.valid_from<=london_date(event.starts_at)<=membership.valid_until and (competition==covered or competition.startswith(covered+" "))


def active_memberships(db,user):
    today=london_date()
    return db.scalars(select(SeasonTicket).where(SeasonTicket.user_id==user.id,SeasonTicket.active==True,SeasonTicket.valid_from<=today,SeasonTicket.valid_until>=today)).all()


def restriction(tc):
    name=tc.name.casefold()
    if name=="vip": return "vip"
    if name=="under 11": return "child"
    if any(word in name for word in ("disabled","disability","accessible","wheelchair")): return "disability"
    if "concession" in name: return "concession"
    return "none"


def concession_eligible(tc,profile,day):
    age=age_on(profile.birth_date,day)
    return profile.force_concession or (age is not None and (age<tc.concession_under or age>tc.concession_over))


def preferred_classes(event,profile):
    classes=offered_classes(event)
    if not profile: return classes
    disabled=profile.force_concession or bool(profile.disability_type)
    day=london_date(event.starts_at)
    def rank(tc):
        kind=restriction(tc)
        if disabled and kind=="disability": return 0
        if kind=="concession" and concession_eligible(tc,profile,day): return 1
        return 2
    return sorted(classes,key=rank)


def validate_attendees(event,lines,profile,personal_index,birth_dates,disability_indices=()):
    units=[tc for tc,count in lines for _ in range(count)]
    if personal_index is not None and (not profile or personal_index<0 or personal_index>=len(units)): raise ValueError("Choose which ticket is yours")
    if len(birth_dates)!=len(units): raise ValueError("Enter attendee details for your selected tickets")
    day=london_date(event.starts_at);result=[]
    for index,(tc,raw) in enumerate(zip(units,birth_dates)):
        personal=profile is not None and index==personal_index
        born=profile.birth_date if personal else parse_birth_date(raw)
        disabled=(profile.force_concession or bool(profile.disability_type)) if personal else index in disability_indices
        forced=profile.force_concession if personal else index in disability_indices
        age=age_on(born,day);kind=restriction(tc)
        if kind=="vip" and (age is None or age<18): raise ValueError("VIP attendees must be aged 18 or above on the match date")
        if kind=="child" and (age is None or age>=11): raise ValueError("Under 11 tickets require an attendee aged under 11 on the match date")
        if kind=="concession" and not forced and (age is None or not(age<tc.concession_under or age>tc.concession_over)):
            raise ValueError(f"{tc.name} requires an attendee aged under {tc.concession_under} or over {tc.concession_over}, or a disability concession")
        if kind=="disability" and not disabled: raise ValueError("This ticket type requires a disability or access preference")
        result.append(born)
    return result


def dashboard_data(db,user):
    from .allocations import claim_memberships, claim_target, valid_membership
    profile=profile_for(db,user);interests={club_key(name) for name in json.loads(profile.clubs_json)}
    orders=db.scalars(select(Order).where(Order.supporter_id==user.id).options(selectinload(Order.tickets)).order_by(Order.created_at.desc())).all()
    successful=[order for order in orders if order.payment_status=="successful"]
    purchased={order.event_id for order in successful if any(ticket.season_ticket_id is None for ticket in order.tickets)}
    claimed={ticket.event_id for order in successful for ticket in order.tickets if ticket.season_ticket_id and ticket.status in ('sold','scanned')}
    valid={ticket.event_id for order in successful for ticket in order.tickets if ticket.status in ("sold","scanned")}
    memberships=active_memberships(db,user)
    admissions=db.scalars(select(SupporterAttendance).where(SupporterAttendance.user_id==user.id)).all()
    attended={admission.event_id for admission in admissions}
    season_attendance=Counter(admission.season_ticket_id for admission in admissions if admission.season_ticket_id)
    events=db.scalars(select(Event).where(Event.published==True,Event.cancelled==False,Event.archived==False,Event.starts_at>=datetime.now(timezone.utc)).options(selectinload(Event.classes))).all()
    fav=lambda event: club_key(event.home_team) in interests or club_key(event.away_team) in interests
    events.sort(key=lambda event:(not fav(event),event.starts_at,event.id))
    notices=[];covered={event.id for event in events if not event.season_claim_required and any(covers_event(st,event) for st in memberships)}
    previous_claims={ticket.event_id for order in successful for ticket in order.tickets if ticket.season_ticket_id}
    claimable={}
    for event in events:
        if event.id in previous_claims: continue
        eligible=claim_memberships(db,event,user)
        if eligible: claimable[event.id]=eligible
    now=datetime.now(timezone.utc)
    for event in events:
        if not (fav(event) or event.id in claimable) or event.id in valid or event.id in covered or event.sales_suspended or not any(tc.maximum>0 for tc in offered_classes(event)): continue
        opening=event.sales_open.replace(tzinfo=timezone.utc) if event.sales_open.tzinfo is None else event.sales_open
        closing=event.sales_close.replace(tzinfo=timezone.utc) if event.sales_close.tzinfo is None else event.sales_close
        if not opening<=now<=closing: continue
        inventories=[inv for inv in event.inventories if inv.audience=='home' or any(valid_membership(st,event,event.away_team) for st in memberships)]
        if event.id in claimable:
            inventories=[]
            for st in claimable[event.id]:
                try: inv,_=claim_target(event,st);inventories.append(inv)
                except ValueError: continue
        for inv in inventories:
            sold=db.scalar(select(func.count(Ticket.id)).where(Ticket.event_id==event.id,Ticket.section_id==inv.section_id,Ticket.status.in_(["sold","scanned"]))) or 0
            held=db.scalar(select(func.coalesce(func.sum(Reservation.quantity),0)).where(Reservation.event_id==event.id,Reservation.section_id==inv.section_id,Reservation.completed==False,Reservation.expires_at>now)) or 0
            if sold+held<inv.capacity-inv.held:
                notices.append(event);break
    areas=Counter((ticket.section.name,ticket.ticket_class.name) for order in successful for ticket in order.tickets if ticket.status in ("sold","scanned"))
    personal_events=[event for event in events if fav(event) or event.id in valid or event.id in covered or event.id in claimable]
    other_events=[event for event in events if event not in personal_events]
    attendance_history=[(admission,db.get(Event,admission.event_id)) for admission in sorted(admissions,key=lambda row:row.scanned_at,reverse=True)]
    season_purchases=db.scalars(select(SeasonPurchase).where(SeasonPurchase.user_id==user.id).order_by(SeasonPurchase.created_at.desc())).all()
    return dict(season_purchases=season_purchases,profile=profile,orders=orders,events=events,personal_events=personal_events,other_events=other_events,notices=notices,memberships=memberships,season_attendance=season_attendance,purchased=purchased,claimed=claimed,claimable=claimable,valid_bookings=valid,attendance_history=attendance_history,attended=attended,covered=covered,areas=areas,interests=interests)


def access_needs_for_event(db,event):
    tickets=db.scalars(select(Ticket).where(Ticket.event_id==event.id,Ticket.status.in_(["sold","scanned"]),Ticket.attendee_user_id.is_not(None))).all()
    people={ticket.attendee_user_id for ticket in tickets}
    for membership in db.scalars(select(SeasonTicket).where(SeasonTicket.active==True)):
        if not event.season_claim_required and covers_event(membership,event): people.add(membership.user_id)
    result=[]
    for user_id in sorted(people):
        user=db.get(User,user_id);profile=db.get(SupporterProfile,user_id)
        if profile and profile.share_access_needs and (profile.disability_type or profile.access_details):
            result.append((user,profile))
    return result


def scan_season_ticket(db,token,event_id,operator):
    event=db.get(Event,event_id)
    if not event: return {"result":"WRONG FIXTURE","detail":"Select a valid fixture"}
    membership=db.scalar(select(SeasonTicket).where((SeasonTicket.qr_token==token)|((SeasonTicket.number==token)&(SeasonTicket.club_name==club_key(event.home_team)))))
    if not membership: return {"result":"INVALID","detail":"Ticket not recognised"}
    if event.season_claim_required:
        return {"result":"CLAIM REQUIRED","detail":"Claim your match ticket and scan its QR code. A season pass alone does not admit you to this fixture."}
    if not covers_event(membership,event) or event.cancelled or not event.published: return {"result":"WRONG FIXTURE","detail":"Season ticket does not cover this fixture"}
    if db.scalar(select(SupporterAttendance).where(SupporterAttendance.user_id==membership.user_id,SupporterAttendance.event_id==event_id)):
        return {"result":"ALREADY USED","detail":"Supporter has already entered this fixture"}
    db.add(SupporterAttendance(user_id=membership.user_id,event_id=event_id,season_ticket_id=membership.id,operator_id=operator.id))
    try: db.commit()
    except IntegrityError:
        db.rollback();return {"result":"ALREADY USED","detail":"Supporter has already entered this fixture"}
    return {"result":"VALID","detail":f"{membership.full_name} · {membership.section} · {membership.ticket_type} · Season ticket"}
