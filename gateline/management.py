"""Club management identities and resource ownership boundaries."""
import hashlib, re
from fastapi import HTTPException, Request
from sqlalchemy import func, or_, select
from .auth import current_user, hash_password
from .clubs import LEAGUES
from .models import *
from .ticketing import canonical_club, club_key, ticket_prefix

CLUB_ADMIN_PASSWORD='ClubAdmin123!'


def require_manager(request:Request):
    user=current_user(request)
    if user.role not in ('admin','club_admin') or (user.role=='club_admin' and not user.managed_club): raise HTTPException(403,'You do not have permission')
    return user


def check_club(user,name):
    if user.role not in ('admin','club_admin') or (user.role=='club_admin' and user.managed_club!=club_key(name)): raise HTTPException(404,'Club not found')


def check_event(user,event):
    if not event: raise HTTPException(404,'Fixture not found')
    if user.role not in ('admin','club_admin') or (user.role=='club_admin' and user.managed_club!=(event.owner_club or club_key(event.home_team))): raise HTTPException(404,'Fixture not found')
    return event


def event_scope(user,club=None):
    if user.role=='admin' and not club: return True
    key=club_key(club) if club else user.managed_club
    entry=canonical_club(key or '')
    aliases=entry.filter_names if entry else (key,)
    return or_(Event.owner_club==key,(Event.owner_club.is_(None)) & func.lower(Event.home_team).in_([name.casefold() for name in aliases if name]))


def club_record(db,name):
    key=club_key(name);record=db.get(ClubManagement,key)
    if record: return record
    canonical=canonical_club(name);display=canonical.name if canonical else name.strip()
    venue=db.scalar(select(Venue).where(Venue.name==canonical.stadium)) if canonical else None
    if canonical and not venue:
        venue=Venue(name=canonical.stadium,address=canonical.location);db.add(venue);db.flush()
        stand=Stand(venue_id=venue.id,name='Main Stand',gate='Gate 1');db.add(stand);db.flush()
        db.add(Section(stand_id=stand.id,name='General Admission',mode='general',capacity=1000))
    event=db.scalar(select(Event).where(func.lower(Event.home_team)==key))
    if not venue and event: venue=event.venue
    record=ClubManagement(club_name=key,name=display,display_name=display,short_name=display[:30],venue_id=venue.id if venue else None,address=canonical.location if canonical else '')
    db.add(record);db.flush();return record


def admin_username(name):
    slug=ticket_prefix(name).lower()
    if len(slug)>24: slug=slug[:18]+'-'+hashlib.sha256(club_key(name).encode()).hexdigest()[:5]
    return slug+'.admin'


def initialise_management(db,names=None):
    names=names if names is not None else {entry.name for entries in LEAGUES.values() for entry in entries}|set(db.scalars(select(Event.home_team)).all())
    password_hash=None
    for name in sorted(names):
        club=club_record(db,name);username=admin_username(club.name);email=username+'@gateline.test'
        user=db.scalar(select(User).where((User.username==username)|(User.email==email)))
        if user:
            if user.role!='club_admin' or user.managed_club!=club.club_name: raise ValueError(f'The demo administrator identity for {club.name} is already in use')
            continue
        if password_hash is None: password_hash=hash_password(CLUB_ADMIN_PASSWORD)
        db.add(User(username=username,email=email,name=club.display_name+' Administrator',role='club_admin',managed_club=club.club_name,password_hash=password_hash))
    for event in db.scalars(select(Event).where(Event.owner_club.is_(None))): event.owner_club=club_key(event.home_team)
    glentoran=db.get(ClubManagement,'glentoran')
    if glentoran and not db.scalar(select(SeasonProduct.id).where(SeasonProduct.club_name=='glentoran')):
        from .supporters import london_date
        today=london_date();year=today.year+1 if today.month>=7 else today.year
        from datetime import date
        for kind,price in [('Adult','250'),('Concession','150')]:
            db.add(SeasonProduct(club_name='glentoran',title=f'Glentoran {year}/{str(year+1)[-2:]} {kind}',section='Sydenham End',ticket_type=kind,competition='NIFL Premiership',valid_from=date(year,7,1),valid_until=date(year+1,6,30),price=price,capacity=200,enabled=True))
    db.commit()


def update_club_details(db,club,display_name,short_name,email,address,description,colour,venue_id):
    if not display_name.strip() or len(display_name.strip())>150 or not short_name.strip() or len(short_name.strip())>30: raise ValueError('Enter a display name and short name')
    if email and (len(email)>200 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email)): raise ValueError('Enter a valid contact email')
    if not re.fullmatch(r'#[a-fA-F0-9]{6}',colour): raise ValueError('Choose a valid club colour')
    if venue_id is not None and not db.get(Venue,venue_id): raise ValueError('Choose a valid venue')
    if len(address)>1000 or len(description)>3000: raise ValueError('Keep the address under 1,000 characters and description under 3,000')
    club.display_name=display_name.strip();club.short_name=short_name.strip();club.contact_email=email.strip();club.address=address.strip();club.description=description.strip();club.primary_colour=colour;club.venue_id=venue_id
    # Keep the established public Club record in step without renaming ownership.
    for row in db.scalars(select(Club)):
        if club_key(row.name)==club.club_name:
            row.short_name=club.short_name;row.contact_email=club.contact_email;row.address=club.address;row.primary_colour=colour
