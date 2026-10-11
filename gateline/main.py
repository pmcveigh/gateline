from datetime import datetime, timezone
from io import BytesIO, StringIO
from decimal import Decimal
from pathlib import Path
from typing import Annotated
from urllib.parse import quote
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
from .ticketing import configure_club_tickets, is_adult, minimum_adult_price, selected_classes, upgrade_club_tickets, VIP_MIN_AGE

app=FastAPI(title="Gateline",version=__version__)
app.mount("/static",StaticFiles(directory="gateline/static"),name="static"); templates=Jinja2Templates(directory="gateline/templates")
LOG_DIR=Path(os.path.expanduser(os.getenv("GATELINE_LOG_DIR", "~/gateline/logs")))
@app.on_event("startup")
def startup():
    Base.metadata.create_all(engine)
    upgrade_schema()
    with Session(engine) as db: upgrade_club_tickets(db)
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
def render(request,template_name,status_code=200,**ctx): return templates.TemplateResponse(request,template_name,{"user":request.state.user,"version":__version__,"quote":quote,"minimum_adult_price":minimum_adult_price,"local_time":local_time,**ctx},status_code=status_code)

OptionalVenueId=Annotated[int|None,BeforeValidator(lambda value: None if value=="" else value)]

def utc_dt(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

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
def home(request:Request,club:str="",venue:OptionalVenueId=None,competition:str="",date:str="",db:Session=Depends(get_db)):
    query=select(Event).options(selectinload(Event.classes)).where(Event.published==True,Event.cancelled==False,Event.starts_at>=datetime.now(timezone.utc))
    directory_club=find_club(club)
    if club:
        names=directory_club.filter_names if directory_club else (club,)
        query=query.where(or_(Event.home_team.in_(names),Event.away_team.in_(names)))
    if venue: query=query.where(Event.venue_id==venue)
    if competition: query=query.where(Event.competition==competition)
    events=db.scalars(query.order_by(Event.starts_at)).all()
    if date: events=[event for event in events if local_time(event.starts_at).date().isoformat()==date]
    clubs=sorted({name for event in db.scalars(select(Event).where(Event.published==True)) for name in (event.home_team,event.away_team)})
    venues=db.scalars(select(Venue).join(Event).where(Event.published==True).distinct().order_by(Venue.name)).all()
    competitions=db.scalars(select(Event.competition).where(Event.published==True).distinct().order_by(Event.competition)).all()
    calendar=build_calendar(events)
    return render(request,"home.html",events=events,calendar=calendar,club_groups=build_club_groups(clubs),venues=venues,competitions=competitions,filters={"club":directory_club.name if directory_club else club,"venue":venue,"competition":competition,"date":date})
@app.get("/clubs/{name}",response_class=HTMLResponse)
def club_profile(name:str,request:Request,db:Session=Depends(get_db)):
    directory_club=find_club(name)
    names=directory_club.filter_names if directory_club else (name,)
    events=db.scalars(select(Event).options(selectinload(Event.classes)).where(Event.published==True,or_(Event.home_team.in_(names),Event.away_team.in_(names))).order_by(Event.starts_at)).all()
    club=db.scalar(select(Club).where(or_(Club.name.in_(names),Club.short_name.in_(names))))
    if not directory_club and not club and not events: raise HTTPException(404,"Club not found")
    return render(request,"profile.html",kind="Club",name=directory_club.display_name if directory_club else club.name if club else name,subtitle=f"{directory_club.stadium} · {directory_club.location}" if directory_club else club.address if club else None,directory_club=directory_club,events=events)
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
    for inv in event.inventories:
        sold=db.scalar(select(func.count(Ticket.id)).where(Ticket.event_id==event.id,Ticket.section_id==inv.section_id,Ticket.status.in_(["sold","scanned"]))) or 0
        held=db.scalar(select(func.coalesce(func.sum(Reservation.quantity),0)).where(Reservation.event_id==event.id,Reservation.section_id==inv.section_id,Reservation.completed==False,Reservation.expires_at>now)) or 0
        availability[inv.section_id]=max(0,inv.capacity-inv.held-sold-held)
    on_sale=not event.cancelled and not event.sales_suspended and utc_dt(event.sales_open)<=now<=utc_dt(event.sales_close)
    return render(request,"event.html",status_code=status_code,event=event,availability=availability,on_sale=on_sale,selection=selection,error=error,is_adult=is_adult)
@app.post("/events/{event_id}/reserve")
def make_reservation(event_id:int,request:Request,section_id:int=Form(),quantity:int=Form(1),seat_ids:str=Form(""),class_ids:list[int]=Form([]),ticket_quantities:list[int]=Form([]),db:Session=Depends(get_db)):
    selection=None
    try:
        if class_ids or ticket_quantities:
            if len(class_ids)!=len(ticket_quantities) or len(set(class_ids))!=len(class_ids): raise ValueError("Invalid ticket selection")
            selection={class_id:count for class_id,count in zip(class_ids,ticket_quantities) if count!=0}
            quantity=sum(selection.values())
        r=reserve(db,event_id,section_id,quantity,[int(x) for x in seat_ids.split(",") if x],selection)
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
    form=form or {}
    lines=selected_classes(event,selection,quantity) if selection else []
    if not selection and form.get("class_id"):
        try: lines=selected_classes(event,{int(form['class_id']):quantity},quantity)
        except ValueError: pass
    vip_count=sum(count for tc,count in lines if tc.name=="VIP")
    ticket_subtotal=sum((tc.price*count for tc,count in lines),Decimal("0")) if lines else (event.classes[0].price*quantity if event.classes else Decimal("0"))
    now=datetime.now(timezone.utc)
    expired=any(row.completed or utc_dt(row.expires_at)<=now for row in rows)
    return render(request,"checkout.html",status_code=status_code,reservation=r,event=event,lines=lines,quantity=quantity,ticket_subtotal=ticket_subtotal,vip_count=vip_count,vip_min_age=VIP_MIN_AGE,selection=selection,form=form,error=error,expired=expired,expires_ms=int((now if expired else utc_dt(r.expires_at)).timestamp()*1000),server_now_ms=int(now.timestamp()*1000))
@app.post("/checkout/{token}")
def complete(token:str,request:Request,full_name:str=Form(),email:str=Form(),address1:str=Form(),address2:str=Form(""),city:str=Form(),postcode:str=Form(),country:str=Form(),class_id:int|None=Form(None),priority_code:str=Form(""),voucher_code:str=Form(""),test_result:str=Form("success"),vip_season_holder:bool=Form(False),vip_birth_dates:list[str]=Form([]),db:Session=Depends(get_db)):
    customer=dict(full_name=full_name,email=email,address1=address1,address2=address2,city=city,postcode=postcode,country=country)
    try: order=checkout(db,token,class_id,customer,test_result,priority_code or None,voucher_code or None,vip_season_holder,vip_birth_dates)
    except ValueError as e: return render_checkout(request,db,token,{**customer,"class_id":class_id,"priority_code":priority_code,"voucher_code":voucher_code,"vip_season_holder":vip_season_holder,"vip_birth_dates":vip_birth_dates},str(e),400)
    return RedirectResponse(f"/orders/{order.reference}?access={order.access_token}",303)
@app.get("/orders/{reference}",response_class=HTMLResponse)
def confirmation(reference:str,request:Request,access:str="",db:Session=Depends(get_db)):
    order=db.scalar(select(Order).where(Order.reference==reference));
    if not order: raise HTTPException(404)
    if (not request.state.user or request.state.user.role!="admin") and not secrets.compare_digest(access,order.access_token): raise HTTPException(404)
    return render(request,"confirmation.html",order=order,access=access)
@app.get("/tickets/{public_id}",response_class=HTMLResponse)
def ticket_view(public_id:str,request:Request,access:str="",db:Session=Depends(get_db)):
    ticket=db.scalar(select(Ticket).where(Ticket.public_id==public_id));
    if not ticket: raise HTTPException(404)
    if (not request.state.user or request.state.user.role!="admin") and not secrets.compare_digest(access,ticket.order.access_token): raise HTTPException(404)
    return render(request,"ticket.html",ticket=ticket,event=db.get(Event,ticket.event_id),access=access)
@app.get("/tickets/{public_id}/qr.png")
def qr(public_id:str,access:str="",db:Session=Depends(get_db)):
    ticket=db.scalar(select(Ticket).where(Ticket.public_id==public_id));
    if not ticket or not secrets.compare_digest(access,ticket.order.access_token):raise HTTPException(404)
    out=BytesIO(); qrcode.make(ticket.qr_token).save(out,"PNG"); out.seek(0); return StreamingResponse(out,media_type="image/png")

@app.get("/login",response_class=HTMLResponse)
def login_page(request:Request):return render(request,"login.html")
@app.post("/login")
def login(request:Request,email:str=Form(),password:str=Form(),db:Session=Depends(get_db)):
    user=db.scalar(select(User).where(User.email==email.lower()))
    if not user or not verify(password,user.password_hash):raise HTTPException(401,"Incorrect credentials")
    request.session["user_id"]=user.id; db.add(AuditLog(user_id=user.id,action="user.login",entity="user",entity_id=str(user.id))); db.commit(); return RedirectResponse("/admin" if user.role=="admin" else "/gate",303)
@app.post("/logout")
def logout(request:Request):request.session.clear();return RedirectResponse("/",303)
@app.get("/admin",response_class=HTMLResponse)
def admin(request:Request,user=Depends(require("admin")),db:Session=Depends(get_db)):
    events=db.scalars(select(Event).order_by(Event.starts_at)).all(); return render(request,"admin.html",events=events,venues=db.scalars(select(Venue).order_by(Venue.name)).all())
@app.get("/admin/events/new",response_class=HTMLResponse)
def new_event(request:Request,user=Depends(require("admin")),db:Session=Depends(get_db)):
    return render(request,"event_admin.html",event=None,venues=db.scalars(select(Venue).order_by(Venue.name)).all())
@app.post("/admin/events")
def create_event(request:Request,title:str=Form(),home_team:str=Form(),away_team:str=Form(),competition:str=Form(),venue_id:int=Form(),starts_at:datetime=Form(),sales_open:datetime=Form(),sales_close:datetime=Form(),adult_price:Decimal=Form(Decimal("15")),user=Depends(require("admin")),db:Session=Depends(get_db)):
    venue=db.get(Venue,venue_id)
    if not venue or sales_open>=sales_close or sales_close>starts_at or adult_price<0: raise HTTPException(422,"Check venue, dates and price")
    london=ZoneInfo("Europe/London"); to_utc=lambda value:(value.replace(tzinfo=london) if value.tzinfo is None else value).astimezone(timezone.utc)
    event=Event(title=title.strip(),home_team=home_team.strip(),away_team=away_team.strip(),competition=competition.strip(),venue_id=venue_id,starts_at=to_utc(starts_at),sales_open=to_utc(sales_open),sales_close=to_utc(sales_close),published=False);db.add(event);db.flush()
    for stand in venue.stands:
        for section in stand.sections: db.add(EventInventory(event_id=event.id,section_id=section.id,capacity=section.capacity))
    db.add(TicketClass(event_id=event.id,name="Adult",description="Standard admission",price=adult_price,minimum=0,maximum=10));db.flush()
    configure_club_tickets(db,event)
    db.add(AuditLog(user_id=user.id,action="event.created",entity="event",entity_id=str(event.id)));db.commit();return RedirectResponse(f"/admin/events/{event.id}",303)
@app.get("/admin/events/{event_id}",response_class=HTMLResponse)
def admin_event(event_id:int,request:Request,user=Depends(require("admin")),db:Session=Depends(get_db)):
    event=db.get(Event,event_id)
    if not event: raise HTTPException(404)
    return render(request,"event_admin.html",event=event,venues=db.scalars(select(Venue).order_by(Venue.name)).all())
@app.post("/admin/events/{event_id}/state")
def event_state(event_id:int,request:Request,action:str=Form(),reason:str=Form(""),user=Depends(require("admin")),db:Session=Depends(get_db)):
    event=db.get(Event,event_id)
    if not event: raise HTTPException(404)
    if action=="publish":
        if not event.inventories or not event.classes: raise HTTPException(409,"Configure inventory and ticket classes before publishing")
        event.published=True
    elif action=="unpublish": event.published=False
    elif action=="suspend": event.sales_suspended=True
    elif action=="reopen": event.sales_suspended=False
    elif action=="cancel": event.cancelled=True; event.sales_suspended=True
    elif action=="archive": event.archived=True; event.published=False
    else: raise HTTPException(422,"Unknown fixture action")
    db.add(AuditLog(user_id=user.id,action=f"event.{action}:{reason[:200]}",entity="event",entity_id=str(event.id)));db.commit();return RedirectResponse(f"/admin/events/{event.id}",303)
@app.post("/admin/events/{event_id}/publish")
def publish(event_id:int,request:Request,user=Depends(require("admin")),db:Session=Depends(get_db)):
    e=db.get(Event,event_id);e.published=not e.published;db.add(AuditLog(user_id=user.id,action="event.published" if e.published else "event.unpublished",entity="event",entity_id=str(e.id)));db.commit();return RedirectResponse("/admin",303)
@app.get("/admin/events/{event_id}/attendance",response_class=HTMLResponse)
def attendance(event_id:int,request:Request,user=Depends(require("admin")),db:Session=Depends(get_db)):
    event=db.get(Event,event_id)
    if not event: raise HTTPException(404)
    tickets=db.scalars(select(Ticket).where(Ticket.event_id==event_id)).all(); capacity=db.scalar(select(func.sum(EventInventory.capacity-EventInventory.held)).where(EventInventory.event_id==event_id)) or 0
    now=datetime.now(timezone.utc); reserved=db.scalar(select(func.coalesce(func.sum(Reservation.quantity),0)).where(Reservation.event_id==event_id,Reservation.completed==False,Reservation.expires_at>now)) or 0
    valid=[t for t in tickets if t.status in ("sold","scanned")]; scanned=sum(t.status=="scanned" for t in valid); cancelled=sum(t.status in ("cancelled","refunded") for t in tickets)
    orders=db.scalars(select(Order).where(Order.event_id==event_id,Order.payment_status=="successful")).all(); gross=sum((o.total for o in orders),Decimal("0")); discounts=sum((o.discount for o in orders),Decimal("0"))
    stats={"capacity":capacity,"reserved":reserved,"issued":len(valid),"available":max(0,capacity-reserved-len(valid)),"scanned":scanned,"yet":max(0,len(valid)-scanned),"cancelled":cancelled,"sales":gross,"discounts":discounts,"utilisation":round(100*len(valid)/capacity,1) if capacity else 0,"admission_rate":round(100*scanned/len(valid),1) if valid else 0}
    return render(request,"attendance.html",event=event,tickets=tickets,capacity=capacity,stats=stats,updated=now)
@app.post("/admin/tickets/{ticket_id}/cancel")
def cancel(ticket_id:int,request:Request,reason:str=Form(""),user=Depends(require("admin")),db:Session=Depends(get_db)):
    t=db.get(Ticket,ticket_id)
    if not t: raise HTTPException(404)
    if t.status not in ("cancelled","refunded"):
        t.status="cancelled";t.cancelled_at=datetime.now(timezone.utc);t.cancelled_by=user.id;t.cancellation_reason=reason[:500];db.add(AuditLog(user_id=user.id,action="ticket.cancelled",entity="ticket",entity_id=str(t.id)));db.commit()
    return RedirectResponse(f"/admin/events/{t.event_id}/attendance",303)
@app.get("/admin/search",response_class=HTMLResponse)
def search(request:Request,q:str="",user=Depends(require("admin")),db:Session=Depends(get_db)):
    orders=db.scalars(select(Order).join(Customer).where(or_(Order.reference.ilike(f"%{q}%"),Customer.full_name.ilike(f"%{q}%"),Customer.email.ilike(f"%{q}%")))).all() if q else []; tickets=db.scalars(select(Ticket).where(Ticket.public_id.ilike(f"%{q}%"))).all() if q else [];return render(request,"search.html",q=q,orders=orders,tickets=tickets)
@app.get("/admin/events/{event_id}/tickets.csv")
def export_tickets(event_id:int,user=Depends(require("admin")),db:Session=Depends(get_db)):
    out=StringIO(); w=csv.writer(out);w.writerow(["Ticket ID","Order reference","Status","Class","Section","Price"])
    for t in db.scalars(select(Ticket).where(Ticket.event_id==event_id)):w.writerow([t.public_id,t.order.reference,t.status,t.ticket_class.name,t.section.name,t.price])
    return StreamingResponse(iter([out.getvalue()]),media_type="text/csv",headers={"Content-Disposition":"attachment; filename=tickets.csv"})
@app.get("/gate",response_class=HTMLResponse)
def gate(request:Request,user=Depends(require("gate")),db:Session=Depends(get_db)):return render(request,"gate.html",events=db.scalars(select(Event).options(selectinload(Event.classes)).where(Event.published==True)).all())
@app.post("/gate/scan")
def gate_scan(request:Request,event_id:int=Form(),token:str=Form(),user=Depends(require("gate")),db:Session=Depends(get_db)):return scan_ticket(db,token.strip(),event_id,user,user.gate)
