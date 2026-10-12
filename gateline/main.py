from datetime import datetime, timezone
from io import BytesIO, StringIO
from decimal import Decimal
from pathlib import Path
from typing import Annotated
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo
import csv, json, os, qrcode, secrets
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from pydantic import BeforeValidator
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload
from starlette.middleware.sessions import SessionMiddleware
from . import __version__
from .auth import require, verify
from .clubs import LEAGUES, build_club_groups, find_club
from .database import Base, engine, get_db, upgrade_schema
from .models import *
from .services import checkout, reserve, reservation_rows, scan_ticket
from .supporters import access_needs_for_event, active_memberships, ensure_test_supporter, preferred_classes, profile_for, restriction
from .accounts import install_accounts
from .admin_management import install_management
from .management import check_club, check_event, club_record, event_scope, initialise_management, require_manager
from .allocations import claim_memberships, claim_season_ticket, claim_target, classes_for_inventory, verify_away_membership
from .demo import DEMO_CODES, ensure_demo_data
from .ticketing import canonical_club, club_key, configure_club_tickets, is_adult, menu_for_club, minimum_adult_price, offered_classes, save_club_pricing, selected_classes, upgrade_club_tickets, VIP_MIN_AGE

app=FastAPI(title="Gateline",version=__version__)
app.mount("/static",StaticFiles(directory="gateline/static"),name="static"); templates=Jinja2Templates(directory="gateline/templates")
LOG_DIR=Path(os.path.expanduser(os.getenv("GATELINE_LOG_DIR", "~/gateline/logs")))
@app.on_event("startup")
def startup():
    Base.metadata.create_all(engine)
    upgrade_schema()
    with Session(engine) as db:
        upgrade_club_tickets(db)
        ensure_demo_data(db)
        initialise_management(db)
    LOG_DIR.mkdir(parents=True,exist_ok=True)
@app.middleware("http")
async def load_user(request,call_next):
    request.state.user=None
    uid=request.session.get("user_id")
    if uid:
        with Session(engine) as db: request.state.user=db.get(User,uid)
    return await call_next(request)
@app.middleware("http")
async def log_session(request,call_next):
    session_id=request.session.setdefault("log_session_id",secrets.token_hex(12))
    started=datetime.now(timezone.utc)
    try:
        response=await call_next(request); status=response.status_code
    except Exception:
        status=500
        raise
    finally:
        LOG_DIR.mkdir(parents=True,exist_ok=True)
        entry={"at":started.isoformat(),"method":request.method,"path":request.url.path,"status":status}
        with (LOG_DIR/f"{session_id}.log").open("a",encoding="utf-8") as log: log.write(json.dumps(entry)+"\n")
    return response
app.add_middleware(SessionMiddleware,secret_key=__import__('os').getenv("SECRET_KEY",secrets.token_hex(32)),https_only=False,same_site="lax")
def render(request,template_name,status_code=200,**ctx): return templates.TemplateResponse(request,template_name,{"user":request.state.user,"version":__version__,"demo_codes":DEMO_CODES,"quote":quote,"minimum_adult_price":minimum_adult_price,"local_time":local_time,"filter_url":fixture_filter_url,"offered_classes":offered_classes,**ctx},status_code=status_code)

install_accounts(app,render)
install_management(app,render)

OptionalVenueId=Annotated[int|None,BeforeValidator(lambda value: None if value=="" else value)]

def utc_dt(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

def fixture_filter_url(filters, **changes):
    values={**filters,**changes}
    query=urlencode({key:values[key] for key in ("club","venue","competition") if values.get(key) not in (None,"")})
    return "/?"+query if query else "/"

def local_time(value):
    return utc_dt(value).astimezone(ZoneInfo("Europe/London"))

def build_calendar(events):
    """Group fixtures by day, from the next kick-off to the furthest away."""
    calendar=[]
    for event in sorted(events,key=lambda item:item.starts_at):
        day=local_time(event.starts_at).date()
        if not calendar or calendar[-1][0]!=day: calendar.append((day,[]))
        calendar[-1][1].append(event)
    return calendar

@app.get("/",response_class=HTMLResponse)
def home(request:Request,club:str="",venue:OptionalVenueId=None,competition:str="",db:Session=Depends(get_db)):
    query=select(Event).options(selectinload(Event.classes)).where(Event.published==True,Event.cancelled==False,Event.starts_at>=datetime.now(timezone.utc))
    directory_club=find_club(club)
    if club:
        names=directory_club.filter_names if directory_club else (club,)
        query=query.where(or_(Event.home_team.in_(names),Event.away_team.in_(names)))
    if venue: query=query.where(Event.venue_id==venue)
    if competition: query=query.where(Event.competition==competition)
    events=db.scalars(query.order_by(Event.starts_at)).all()
    clubs=sorted({name for event in db.scalars(select(Event).where(Event.published==True)) for name in (event.home_team,event.away_team)})
    venues=db.scalars(select(Venue).join(Event).where(Event.published==True).distinct().order_by(Venue.name)).all()
    competitions=db.scalars(select(Event.competition).where(Event.published==True).distinct().order_by(Event.competition)).all()
    calendar=build_calendar(events)
    return render(request,"home.html",events=events,calendar=calendar,club_groups=build_club_groups(clubs),venues=venues,competitions=competitions,filters={"club":directory_club.name if directory_club else club,"venue":venue,"competition":competition})
@app.get("/clubs/{name}",response_class=HTMLResponse)
def club_profile(name:str,request:Request,db:Session=Depends(get_db)):
    directory_club=find_club(name)
    names=directory_club.filter_names if directory_club else (name,)
    events=db.scalars(select(Event).options(selectinload(Event.classes)).where(Event.published==True,or_(Event.home_team.in_(names),Event.away_team.in_(names))).order_by(Event.starts_at)).all()
    club=db.scalar(select(Club).where(or_(Club.name.in_(names),Club.short_name.in_(names))))
    if not directory_club and not club and not events: raise HTTPException(404,"Club not found")
    return render(request,"profile.html",kind="Club",name=directory_club.display_name if directory_club else club.name if club else name,subtitle=f"{directory_club.stadium} · {directory_club.location}" if directory_club else club.address if club else None,directory_club=directory_club,season_products=db.scalars(select(SeasonProduct).where(SeasonProduct.club_name==club_key(name),SeasonProduct.enabled==True)).all(),events=events)
@app.get("/venues/{venue_id}",response_class=HTMLResponse)
def venue_profile(venue_id:int,request:Request,db:Session=Depends(get_db)):
    venue=db.get(Venue,venue_id)
    if not venue: raise HTTPException(404)
    return render(request,"profile.html",kind="Stadium",name=venue.name,subtitle=venue.address,events=db.scalars(select(Event).options(selectinload(Event.classes)).where(Event.published==True,Event.venue_id==venue_id).order_by(Event.starts_at)).all())
@app.get("/competitions/{name:path}",response_class=HTMLResponse)
def competition_profile(name:str,request:Request,db:Session=Depends(get_db)):
    normalise=lambda value: value.replace("’","'").strip().casefold()
    key=normalise(name)
    aliases={normalise(league):normalise(league) for league in LEAGUES}
    aliases[normalise("NIFL Women's")]=normalise("NIFL Women's Premiership")
    known=db.scalars(select(Event.competition).distinct()).all()
    matching=[value for value in known if normalise(value)==key or (key in aliases and (normalise(value)==aliases[key] or normalise(value).startswith(aliases[key]+" ")))]
    if not matching and key not in aliases: raise HTTPException(404,"Competition not found")
    events=db.scalars(select(Event).options(selectinload(Event.classes)).where(Event.published==True,Event.competition.in_(matching)).order_by(Event.starts_at)).all()
    return render(request,"profile.html",kind="Competition",name=name,events=events)
@app.get("/events/{event_id}",response_class=HTMLResponse)
def event_page(event_id:int,request:Request,db:Session=Depends(get_db)):
    return render_event(request,db,event_id)

def render_event(request,db,event_id,selection=None,error=None,status_code=200):
    event=db.get(Event,event_id)
    if not event or not event.published: raise HTTPException(404)
    now=datetime.now(timezone.utc); availability={}
    unavailable_seats=set(db.scalars(select(Ticket.seat_id).where(Ticket.event_id==event_id,Ticket.seat_id.is_not(None),Ticket.status.in_(['sold','scanned']))).all())
    unavailable_seats.update(db.scalars(select(Reservation.seat_id).where(Reservation.event_id==event_id,Reservation.seat_id.is_not(None),Reservation.completed==False,Reservation.expires_at>now)).all())
    for inv in event.inventories:
        sold=db.scalar(select(func.count(Ticket.id)).where(Ticket.event_id==event.id,Ticket.section_id==inv.section_id,Ticket.status.in_(["sold","scanned"]))) or 0
        held=db.scalar(select(func.coalesce(func.sum(Reservation.quantity),0)).where(Reservation.event_id==event.id,Reservation.section_id==inv.section_id,Reservation.completed==False,Reservation.expires_at>now)) or 0
        availability[inv.section_id]=max(0,inv.capacity-inv.held-sold-held)
    on_sale=bool(offered_classes(event)) and not event.cancelled and not event.sales_suspended and utc_dt(event.sales_open)<=now<=utc_dt(event.sales_close)
    supporter=request.state.user if request.state.user and request.state.user.role=="supporter" else None
    profile=profile_for(db,supporter) if supporter else None
    away_access=None
    access_id=request.session.get('away_access',{}).get(str(event.id))
    if access_id:
        try: away_access=verify_away_membership(db,event,supporter,membership_id=access_id)
        except ValueError: pass
    classes=preferred_classes(event,profile)
    home_groups=[(inv,classes_for_inventory(event,inv,classes,'home')) for inv in event.inventories]
    away_groups=[(inv,classes_for_inventory(event,inv,classes,'away')) for inv in event.inventories] if away_access else []
    claims=[]
    for st in claim_memberships(db,event,supporter):
        prior=db.scalar(select(Ticket).where(Ticket.event_id==event.id,Ticket.season_ticket_id==st.id))
        try: inv,_=claim_target(event,st)
        except ValueError: inv=None
        claims.append((st,prior,inv))
    return render(request,"event.html",status_code=status_code,event=event,availability=availability,unavailable_seats=unavailable_seats,on_sale=on_sale,selection=selection,error=error,is_adult=is_adult,ticket_classes=classes,home_groups=home_groups,away_groups=away_groups,away_access=away_access,claims=claims,supporter_profile=profile,restriction=restriction)

@app.post('/events/{event_id}/away-access')
def unlock_away(event_id:int,request:Request,season_number:str=Form(),user=Depends(require('supporter')),db:Session=Depends(get_db)):
    event=db.get(Event,event_id)
    if not event or not event.published: raise HTTPException(404)
    try: st=verify_away_membership(db,event,user,season_number)
    except ValueError as error: return render_event(request,db,event_id,error=str(error),status_code=400)
    request.session['away_access']={**request.session.get('away_access',{}),str(event_id):st.id}
    return RedirectResponse(f'/events/{event_id}#away-tickets',303)

@app.post('/events/{event_id}/season-claim')
def season_claim(event_id:int,request:Request,membership_id:int=Form(),seat_id:int|None=Form(None),user=Depends(require('supporter')),db:Session=Depends(get_db)):
    try: order=claim_season_ticket(db,event_id,user,membership_id,seat_id)
    except ValueError as error: return render_event(request,db,event_id,error=str(error),status_code=409)
    return RedirectResponse(f'/orders/{order.reference}',303)
@app.post("/events/{event_id}/reserve")
def make_reservation(event_id:int,request:Request,section_id:int=Form(),quantity:int=Form(0),seat_ids:str=Form(""),class_ids:list[int]=Form([]),ticket_quantities:list[str]=Form([]),away_season_number:str=Form(''),db:Session=Depends(get_db)):
    selection=None
    try:
        if class_ids or ticket_quantities:
            if len(class_ids)!=len(ticket_quantities) or len(set(class_ids))!=len(class_ids): raise ValueError("Invalid ticket selection")
            counts=[int(value) if value.strip() else 0 for value in ticket_quantities]
            selection={class_id:count for class_id,count in zip(class_ids,counts) if count!=0}
            quantity=sum(selection.values())
        supporter=request.state.user if request.state.user and request.state.user.role=='supporter' else None
        r=reserve(db,event_id,section_id,quantity,[int(x) for x in seat_ids.split(",") if x],selection,supporter=supporter,away_season_number=away_season_number)
    except ValueError as e: return render_event(request,db,event_id,selection,str(e),409)
    return RedirectResponse(f"/checkout/{r.token}",303)
@app.get("/checkout/{token}",response_class=HTMLResponse)
def checkout_page(token:str,request:Request,db:Session=Depends(get_db)):
    return render_checkout(request,db,token)

def render_checkout(request,db,token,form=None,error=None,status_code=200):
    rows=reservation_rows(db,token)
    if not rows:return RedirectResponse("/",303)
    r=rows[0]; event=db.get(Event,r.event_id); quantity=sum(row.quantity for row in rows)
    stored=json.loads(r.selection_json or "{}")
    selection=stored.get("classes",stored)
    supporter=request.state.user if request.state.user and request.state.user.role=="supporter" else None
    profile=profile_for(db,supporter) if supporter else None
    if form is None:
        form={"full_name":supporter.name,"email":supporter.email,**{field:getattr(profile,field) for field in ("address1","address2","city","postcode","country")}} if profile else {}
        if supporter:
            memberships=[st for st in active_memberships(db,supporter) if st.club_name==club_key(event.home_team)]
            if memberships: form["priority_code"]=memberships[0].number
    selection_invalid=False
    try: lines=selected_classes(event,selection,quantity) if selection else []
    except ValueError as unavailable:
        lines=[];selection_invalid=True;error=error or str(unavailable)
    if not selection and form.get("class_id"):
        try: lines=selected_classes(event,{int(form['class_id']):quantity},quantity)
        except ValueError: pass
    vip_count=sum(count for tc,count in lines if tc.name=="VIP")
    ticket_subtotal=sum((tc.price*count for tc,count in lines),Decimal("0")) if lines else Decimal("0")
    now=datetime.now(timezone.utc)
    expired=selection_invalid or any(row.completed or utc_dt(row.expires_at)<=now for row in rows)
    units=[tc for tc,count in lines for _ in range(count)]
    away_booking=bool(stored.get('away_season_ticket_id'))
    if away_booking and (not supporter or supporter.id!=stored.get('supporter_id')): raise HTTPException(404)
    return render(request,"checkout.html",status_code=status_code,reservation=r,event=event,lines=lines,units=units,quantity=quantity,ticket_subtotal=ticket_subtotal,vip_count=vip_count,vip_min_age=VIP_MIN_AGE,selection=selection,form=form,error=error,supporter_profile=profile,restriction=restriction,away_booking=away_booking,vip_discount_allowed=not away_booking and club_key(event.home_team)==club_key("Glentoran"),expired=expired,expires_ms=int((now if expired else utc_dt(r.expires_at)).timestamp()*1000),server_now_ms=int(now.timestamp()*1000))
@app.post("/checkout/{token}")
def complete(token:str,request:Request,full_name:str=Form(),email:str=Form(),address1:str=Form(),address2:str=Form(""),city:str=Form(),postcode:str=Form(),country:str=Form(),class_id:int|None=Form(None),priority_code:str=Form(""),voucher_code:str=Form(""),test_result:str=Form("success"),vip_season_holder:bool=Form(False),vip_birth_dates:list[str]=Form([]),personal_index:int=Form(-1),attendee_birth_dates:list[str]=Form([]),disability_indices:list[int]=Form([]),db:Session=Depends(get_db)):
    customer=dict(full_name=full_name,email=email,address1=address1,address2=address2,city=city,postcode=postcode,country=country)
    supporter=request.state.user if request.state.user and request.state.user.role=="supporter" else None
    try: order=checkout(db,token,class_id,customer,test_result,priority_code or None,voucher_code or None,vip_season_holder,vip_birth_dates,supporter=supporter,personal_index=personal_index if personal_index!=-1 else None,attendee_birth_dates=attendee_birth_dates or None,disability_indices=disability_indices)
    except ValueError as e: return render_checkout(request,db,token,{**customer,"class_id":class_id,"priority_code":priority_code,"voucher_code":voucher_code,"vip_season_holder":vip_season_holder,"vip_birth_dates":vip_birth_dates,"attendee_birth_dates":attendee_birth_dates,"personal_index":personal_index,"disability_indices":disability_indices},str(e),400)
    return RedirectResponse(f"/orders/{order.reference}?access={order.access_token}",303)
@app.get("/orders/{reference}",response_class=HTMLResponse)
def confirmation(reference:str,request:Request,access:str="",db:Session=Depends(get_db)):
    order=db.scalar(select(Order).where(Order.reference==reference));
    if not order: raise HTTPException(404)
    if not owns_order(request,order) and not secrets.compare_digest(access,order.access_token): raise HTTPException(404)
    return render(request,"confirmation.html",order=order,access=access)
@app.get("/tickets/{public_id}",response_class=HTMLResponse)
def ticket_view(public_id:str,request:Request,access:str="",db:Session=Depends(get_db)):
    ticket=db.scalar(select(Ticket).where(Ticket.public_id==public_id));
    if not ticket: raise HTTPException(404)
    if not owns_order(request,ticket.order) and not secrets.compare_digest(access,ticket.order.access_token): raise HTTPException(404)
    seat_label=f'{db.get(SeatRow,ticket.seat.row_id).name}-{ticket.seat.number}' if ticket.seat else None
    return render(request,"ticket.html",ticket=ticket,event=db.get(Event,ticket.event_id),seat_label=seat_label,access=access)
@app.get("/tickets/{public_id}/qr.png")
def qr(public_id:str,request:Request,access:str="",db:Session=Depends(get_db)):
    ticket=db.scalar(select(Ticket).where(Ticket.public_id==public_id));
    if not ticket or (not owns_order(request,ticket.order) and not secrets.compare_digest(access,ticket.order.access_token)):raise HTTPException(404)
    out=BytesIO(); qrcode.make(ticket.qr_token).save(out,"PNG"); out.seek(0); return StreamingResponse(out,media_type="image/png")

def owns_order(request,order):
    user=request.state.user
    return bool(user and (user.role=="admin" or (user.role=="club_admin" and user.managed_club==(order.event.owner_club or club_key(order.event.home_team))) or (user.role=="supporter" and order.supporter_id==user.id)))

@app.get("/login",response_class=HTMLResponse)
def login_page(request:Request):return render(request,"login.html")
@app.post("/login")
def login(request:Request,email:str=Form(),password:str=Form(),db:Session=Depends(get_db)):
    identity=email.strip().casefold()
    user=db.scalar(select(User).where(or_(func.lower(User.email)==identity,User.username==identity)))
    if len(password.encode())>72 or not user or not verify(password,user.password_hash):raise HTTPException(401,"Incorrect credentials")
    request.session.clear();request.session["user_id"]=user.id; db.add(AuditLog(user_id=user.id,action="user.login",entity="user",entity_id=str(user.id))); db.commit(); return RedirectResponse("/admin" if user.role=="admin" else f"/admin/clubs/{quote(user.managed_club,safe='')}" if user.role=="club_admin" else "/account" if user.role=="supporter" else "/gate",303)
@app.post("/logout")
def logout(request:Request):request.session.clear();return RedirectResponse("/",303)
@app.get("/admin",response_class=HTMLResponse)
def admin(request:Request,q:str="",club:str="",user=Depends(require_manager),db:Session=Depends(get_db)):
    query=select(Event).join(Venue).where(event_scope(user))
    if club:
        check_club(user,club);query=query.where(event_scope(user,club))
    if q: query=query.where(or_(Event.title.ilike(f"%{q}%"),Event.competition.ilike(f"%{q}%"),Venue.name.ilike(f"%{q}%")))
    events=db.scalars(query.order_by(Event.starts_at)).all()
    return render(request,"admin.html",events=events,q=q,club_filter=club,venues=db.scalars(select(Venue).order_by(Venue.name)).all())
@app.get("/admin/clubs",response_class=HTMLResponse)
def club_pricing_index(request:Request,user=Depends(require_manager),db:Session=Depends(get_db)):
    names={entry.name for clubs in LEAGUES.values() for entry in clubs}
    names.update(db.scalars(select(Event.home_team).distinct()).all())
    by_key={club_key(name):name for name in sorted(names,reverse=True)}
    clubs=[name for name in sorted(by_key.values()) if user.role=='admin' or club_key(name)==user.managed_club]
    clubs.extend(row.name for row in db.scalars(select(ClubManagement)) if row.name not in clubs and (user.role=='admin' or row.club_name==user.managed_club))
    return render(request,"club_pricing_index.html",clubs=sorted(set(clubs)))

@app.get("/admin/clubs/{name}/pricing",response_class=HTMLResponse)
def club_pricing_page(name:str,request:Request,user=Depends(require_manager),db:Session=Depends(get_db)):
    check_club(user,name)
    return render(request,"club_pricing.html",name=name,club=club_record(db,name),menu=menu_for_club(db,name))

@app.post("/admin/clubs/{name}/pricing",response_class=HTMLResponse)
def update_club_pricing(name:str,request:Request,ticket_names:list[str]=Form([]),ticket_prices:list[str]=Form([]),ticket_descriptions:list[str]=Form([]),ticket_categories:list[str]=Form([]),concession_under:list[str]=Form([]),concession_over:list[str]=Form([]),user=Depends(require_manager),db:Session=Depends(get_db)):
    check_club(user,name)
    try:
        save_club_pricing(db,name,ticket_names,ticket_prices,ticket_descriptions,ticket_categories,concession_under or None,concession_over or None)
    except ValueError as error:
        menu=[{"name":title,"price":price,"description":description,"adult":category=="adult"} for title,price,description,category in zip(ticket_names,ticket_prices,ticket_descriptions,ticket_categories)]
        return render(request,"club_pricing.html",status_code=400,name=name,menu=menu,error=str(error))
    db.add(AuditLog(user_id=user.id,action="club.pricing_updated",entity="club",entity_id=club_key(name)));db.commit()
    return RedirectResponse(f"/admin/clubs/{quote(name,safe='')}/pricing?saved=1",303)

@app.get("/admin/events/new",response_class=HTMLResponse)
def new_event(request:Request,club:str="",user=Depends(require_manager),db:Session=Depends(get_db)):
    name=club or user.managed_club or ''
    if name: check_club(user,name)
    record=club_record(db,name) if name else None
    return render(request,"event_admin.html",event=None,home_club=record,venues=db.scalars(select(Venue).order_by(Venue.name)).all())
@app.post("/admin/events")
def create_event(request:Request,title:str=Form(),home_team:str=Form(),away_team:str=Form(),competition:str=Form(),venue_id:int=Form(),starts_at:datetime=Form(),sales_open:datetime=Form(),sales_close:datetime=Form(),user=Depends(require_manager),db:Session=Depends(get_db)):
    check_club(user,home_team)
    venue=db.get(Venue,venue_id)
    if not venue or sales_open>=sales_close or sales_close>starts_at: raise HTTPException(422,"Check venue and dates")
    london=ZoneInfo("Europe/London"); to_utc=lambda value:(value.replace(tzinfo=london) if value.tzinfo is None else value).astimezone(timezone.utc)
    home_entry=canonical_club(home_team);away_entry=canonical_club(away_team)
    home_team=home_entry.name if home_entry else home_team.strip();away_team=away_entry.name if away_entry else away_team.strip()
    if not home_team or len(home_team)>150 or not away_team or len(away_team)>150: raise HTTPException(422,"Enter valid club names")
    record=club_record(db,home_team)
    event=Event(owner_club=record.club_name,title=title.strip(),home_team=home_team,away_team=away_team,competition=competition.strip(),venue_id=venue_id,starts_at=to_utc(starts_at),sales_open=to_utc(sales_open),sales_close=to_utc(sales_close),published=False);db.add(event);db.flush()
    for stand in venue.stands:
        for section in stand.sections: db.add(EventInventory(event_id=event.id,section_id=section.id,capacity=section.capacity))
    configure_club_tickets(db,event)
    db.add(AuditLog(user_id=user.id,action="event.created",entity="event",entity_id=str(event.id)));db.commit();return RedirectResponse(f"/admin/events/{event.id}",303)
@app.get("/admin/events/{event_id}",response_class=HTMLResponse)
def admin_event(event_id:int,request:Request,user=Depends(require_manager),db:Session=Depends(get_db)):
    event=db.get(Event,event_id)
    check_event(user,event)
    return render(request,"event_admin.html",event=event,venues=db.scalars(select(Venue).order_by(Venue.name)).all())
@app.post("/admin/events/{event_id}/state")
def event_state(event_id:int,request:Request,action:str=Form(),reason:str=Form(""),user=Depends(require_manager),db:Session=Depends(get_db)):
    event=db.get(Event,event_id)
    check_event(user,event)
    if action=="publish":
        if not event.inventories or not offered_classes(event): raise HTTPException(409,"Configure inventory and ticket classes before publishing")
        event.published=True
    elif action=="unpublish": event.published=False
    elif action=="suspend": event.sales_suspended=True
    elif action=="reopen": event.sales_suspended=False
    elif action=="cancel": event.cancelled=True; event.sales_suspended=True
    elif action=="archive": event.archived=True; event.published=False
    else: raise HTTPException(422,"Unknown fixture action")
    db.add(AuditLog(user_id=user.id,action=f"event.{action}:{reason[:200]}",entity="event",entity_id=str(event.id)));db.commit();return RedirectResponse(f"/admin/events/{event.id}",303)
@app.post("/admin/events/{event_id}/publish")
def publish(event_id:int,request:Request,user=Depends(require_manager),db:Session=Depends(get_db)):
    e=db.get(Event,event_id)
    check_event(user,e)
    if not e.published and (not e.inventories or not offered_classes(e)): raise HTTPException(409,"Configure inventory and club pricing before publishing")
    e.published=not e.published;db.add(AuditLog(user_id=user.id,action="event.published" if e.published else "event.unpublished",entity="event",entity_id=str(e.id)));db.commit();return RedirectResponse("/admin",303)
@app.get("/admin/events/{event_id}/attendance",response_class=HTMLResponse)
def attendance(event_id:int,request:Request,user=Depends(require_manager),db:Session=Depends(get_db)):
    event=db.get(Event,event_id)
    check_event(user,event)
    tickets=db.scalars(select(Ticket).where(Ticket.event_id==event_id)).all(); capacity=db.scalar(select(func.sum(EventInventory.capacity-EventInventory.held)).where(EventInventory.event_id==event_id)) or 0
    now=datetime.now(timezone.utc); reserved=db.scalar(select(func.coalesce(func.sum(Reservation.quantity),0)).where(Reservation.event_id==event_id,Reservation.completed==False,Reservation.expires_at>now)) or 0
    valid=[t for t in tickets if t.status in ("sold","scanned")]; scanned=sum(t.status=="scanned" for t in valid); cancelled=sum(t.status in ("cancelled","refunded") for t in tickets)
    orders=db.scalars(select(Order).where(Order.event_id==event_id,Order.payment_status=="successful")).all(); gross=sum((o.total for o in orders),Decimal("0")); discounts=sum((o.discount for o in orders),Decimal("0"))
    stats={"capacity":capacity,"reserved":reserved,"issued":len(valid),"available":max(0,capacity-reserved-len(valid)),"scanned":scanned,"yet":max(0,len(valid)-scanned),"cancelled":cancelled,"sales":gross,"discounts":discounts,"utilisation":round(100*len(valid)/capacity,1) if capacity else 0,"admission_rate":round(100*scanned/len(valid),1) if valid else 0}
    season_admissions=db.scalar(select(func.count(SupporterAttendance.id)).where(SupporterAttendance.event_id==event_id,SupporterAttendance.season_ticket_id.is_not(None))) or 0
    return render(request,"attendance.html",event=event,tickets=tickets,capacity=capacity,stats=stats,updated=now,access_needs=access_needs_for_event(db,event),season_admissions=season_admissions)
@app.post("/admin/tickets/{ticket_id}/cancel")
def cancel(ticket_id:int,request:Request,reason:str=Form(""),user=Depends(require_manager),db:Session=Depends(get_db)):
    t=db.get(Ticket,ticket_id)
    if not t: raise HTTPException(404)
    check_event(user,db.get(Event,t.event_id))
    if t.status not in ("cancelled","refunded"):
        t.status="cancelled";t.cancelled_at=datetime.now(timezone.utc);t.cancelled_by=user.id;t.cancellation_reason=reason[:500];db.add(AuditLog(user_id=user.id,action="ticket.cancelled",entity="ticket",entity_id=str(t.id)));db.commit()
    return RedirectResponse(f"/admin/events/{t.event_id}/attendance",303)
@app.get("/admin/search",response_class=HTMLResponse)
def search(request:Request,q:str="",user=Depends(require_manager),db:Session=Depends(get_db)):
    orders=db.scalars(select(Order).join(Customer).join(Event).where(event_scope(user)).where(or_(Order.reference.ilike(f"%{q}%"),Customer.full_name.ilike(f"%{q}%"),Customer.email.ilike(f"%{q}%")))).all() if q else []
    tickets=db.scalars(select(Ticket).join(Event).where(event_scope(user)).where(Ticket.public_id.ilike(f"%{q}%"))).all() if q else []
    holders_query=select(SeasonTicket)
    purchase_query=select(SeasonPurchase).join(SeasonProduct).join(User,SeasonPurchase.user_id==User.id)
    if user.role=='club_admin':
        holders_query=holders_query.where(SeasonTicket.club_name==user.managed_club)
        purchase_query=purchase_query.where(SeasonProduct.club_name==user.managed_club)
    holders=db.scalars(holders_query.where(or_(SeasonTicket.number.ilike(f"%{q}%"),SeasonTicket.full_name.ilike(f"%{q}%"),SeasonTicket.email.ilike(f"%{q}%")))).all() if q else []
    purchases=db.scalars(purchase_query.where(or_(SeasonPurchase.reference.ilike(f"%{q}%"),User.name.ilike(f"%{q}%"),User.email.ilike(f"%{q}%")))).all() if q else []
    return render(request,"search.html",q=q,orders=orders,tickets=tickets,holders=holders,purchases=purchases)
@app.get("/admin/events/{event_id}/tickets.csv")
def export_tickets(event_id:int,user=Depends(require_manager),db:Session=Depends(get_db)):
    check_event(user,db.get(Event,event_id))
    out=StringIO(); w=csv.writer(out);w.writerow(["Ticket ID","Order reference","Status","Class","Section","Price"])
    for t in db.scalars(select(Ticket).where(Ticket.event_id==event_id)):w.writerow([t.public_id,t.order.reference,t.status,t.ticket_class.name,t.section.name,t.price])
    return StreamingResponse(iter([out.getvalue()]),media_type="text/csv",headers={"Content-Disposition":"attachment; filename=tickets.csv"})
@app.get("/gate",response_class=HTMLResponse)
def gate(request:Request,user=Depends(require("gate")),db:Session=Depends(get_db)):return render(request,"gate.html",events=db.scalars(select(Event).options(selectinload(Event.classes)).where(Event.published==True)).all())
@app.post("/gate/scan")
def gate_scan(request:Request,event_id:int=Form(),token:str=Form(),user=Depends(require("gate")),db:Session=Depends(get_db)):return scan_ticket(db,token.strip(),event_id,user,user.gate)
