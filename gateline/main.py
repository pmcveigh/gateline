from datetime import datetime, timezone
from io import BytesIO, StringIO
import csv, qrcode, secrets
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware
from . import __version__
from .auth import require, verify
from .database import Base, engine, get_db
from .models import *
from .services import checkout, reserve, scan_ticket

app=FastAPI(title="Gateline",version=__version__)
app.add_middleware(SessionMiddleware,secret_key=__import__('os').getenv("SECRET_KEY",secrets.token_hex(32)),https_only=False,same_site="lax")
app.mount("/static",StaticFiles(directory="gateline/static"),name="static"); templates=Jinja2Templates(directory="gateline/templates")
@app.on_event("startup")
def startup(): Base.metadata.create_all(engine)
@app.middleware("http")
async def load_user(request,call_next):
    request.state.user=None
    uid=request.session.get("user_id")
    if uid:
        with Session(engine) as db: request.state.user=db.get(User,uid)
    return await call_next(request)
def render(request,name,**ctx): return templates.TemplateResponse(request,name,{"user":request.state.user,"version":__version__,**ctx})

@app.get("/",response_class=HTMLResponse)
def home(request:Request,db:Session=Depends(get_db)):
    now=datetime.now(timezone.utc); events=db.scalars(select(Event).where(Event.published==True,Event.cancelled==False,Event.sales_open<=now,Event.sales_close>=now)).all(); return render(request,"home.html",events=events)
@app.get("/events/{event_id}",response_class=HTMLResponse)
def event_page(event_id:int,request:Request,db:Session=Depends(get_db)):
    event=db.get(Event,event_id)
    if not event or not event.published: raise HTTPException(404)
    return render(request,"event.html",event=event)
@app.post("/events/{event_id}/reserve")
def make_reservation(event_id:int,section_id:int=Form(),quantity:int=Form(),seat_ids:str=Form(""),db:Session=Depends(get_db)):
    try:r=reserve(db,event_id,section_id,quantity,[int(x) for x in seat_ids.split(",") if x])
    except ValueError as e: raise HTTPException(409,str(e))
    return RedirectResponse(f"/checkout/{r.token}",303)
@app.get("/checkout/{token}",response_class=HTMLResponse)
def checkout_page(token:str,request:Request,db:Session=Depends(get_db)):
    r=db.scalar(select(Reservation).where(Reservation.token==token)); event=db.get(Event,r.event_id) if r else None
    if not r:return RedirectResponse("/")
    return render(request,"checkout.html",reservation=r,event=event)
@app.post("/checkout/{token}")
def complete(token:str,full_name:str=Form(),email:str=Form(),address1:str=Form(),address2:str=Form(""),city:str=Form(),postcode:str=Form(),country:str=Form(),class_id:int=Form(),priority_code:str=Form(""),voucher_code:str=Form(""),test_result:str=Form("success"),db:Session=Depends(get_db)):
    try: order=checkout(db,token,class_id,dict(full_name=full_name,email=email,address1=address1,address2=address2,city=city,postcode=postcode,country=country),test_result,priority_code or None,voucher_code or None)
    except ValueError as e: raise HTTPException(400,str(e))
    return RedirectResponse(f"/orders/{order.reference}",303)
@app.get("/orders/{reference}",response_class=HTMLResponse)
def confirmation(reference:str,request:Request,db:Session=Depends(get_db)):
    order=db.scalar(select(Order).where(Order.reference==reference));
    if not order: raise HTTPException(404)
    return render(request,"confirmation.html",order=order)
@app.get("/tickets/{public_id}",response_class=HTMLResponse)
def ticket_view(public_id:str,request:Request,db:Session=Depends(get_db)):
    ticket=db.scalar(select(Ticket).where(Ticket.public_id==public_id));
    if not ticket: raise HTTPException(404)
    return render(request,"ticket.html",ticket=ticket,event=db.get(Event,ticket.event_id))
@app.get("/tickets/{public_id}/qr.png")
def qr(public_id:str,db:Session=Depends(get_db)):
    ticket=db.scalar(select(Ticket).where(Ticket.public_id==public_id));
    if not ticket:raise HTTPException(404)
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
    events=db.scalars(select(Event).order_by(Event.starts_at)).all(); return render(request,"admin.html",events=events)
@app.post("/admin/events")
def create_event(request:Request,title:str=Form(),home_team:str=Form(),away_team:str=Form(),competition:str=Form(),venue_id:int=Form(),starts_at:datetime=Form(),sales_open:datetime=Form(),sales_close:datetime=Form(),user=Depends(require("admin")),db:Session=Depends(get_db)):
    event=Event(title=title,home_team=home_team,away_team=away_team,competition=competition,venue_id=venue_id,starts_at=starts_at,sales_open=sales_open,sales_close=sales_close,published=False);db.add(event);db.flush();db.add(AuditLog(user_id=user.id,action="event.created",entity="event",entity_id=str(event.id)));db.commit();return RedirectResponse("/admin",303)
@app.post("/admin/events/{event_id}/publish")
def publish(event_id:int,request:Request,user=Depends(require("admin")),db:Session=Depends(get_db)):
    e=db.get(Event,event_id);e.published=not e.published;db.add(AuditLog(user_id=user.id,action="event.published" if e.published else "event.unpublished",entity="event",entity_id=str(e.id)));db.commit();return RedirectResponse("/admin",303)
@app.get("/admin/events/{event_id}/attendance",response_class=HTMLResponse)
def attendance(event_id:int,request:Request,user=Depends(require("admin")),db:Session=Depends(get_db)):
    tickets=db.scalars(select(Ticket).where(Ticket.event_id==event_id)).all(); capacity=db.scalar(select(func.sum(EventInventory.capacity)).where(EventInventory.event_id==event_id)) or 0;return render(request,"attendance.html",event=db.get(Event,event_id),tickets=tickets,capacity=capacity)
@app.post("/admin/tickets/{ticket_id}/cancel")
def cancel(ticket_id:int,request:Request,reason:str=Form(""),user=Depends(require("admin")),db:Session=Depends(get_db)):
    t=db.get(Ticket,ticket_id);t.status="cancelled";t.cancelled_at=datetime.now(timezone.utc);t.cancelled_by=user.id;t.cancellation_reason=reason;db.add(AuditLog(user_id=user.id,action="ticket.cancelled",entity="ticket",entity_id=str(t.id)));db.commit();return RedirectResponse(f"/admin/events/{t.event_id}/attendance",303)
@app.get("/admin/search",response_class=HTMLResponse)
def search(request:Request,q:str="",user=Depends(require("admin")),db:Session=Depends(get_db)):
    orders=db.scalars(select(Order).join(Customer).where(or_(Order.reference.ilike(f"%{q}%"),Customer.full_name.ilike(f"%{q}%"),Customer.email.ilike(f"%{q}%")))).all() if q else []; tickets=db.scalars(select(Ticket).where(Ticket.public_id.ilike(f"%{q}%"))).all() if q else [];return render(request,"search.html",q=q,orders=orders,tickets=tickets)
@app.get("/admin/events/{event_id}/tickets.csv")
def export_tickets(event_id:int,user=Depends(require("admin")),db:Session=Depends(get_db)):
    out=StringIO(); w=csv.writer(out);w.writerow(["Ticket ID","Order reference","Status","Class","Section","Price"])
    for t in db.scalars(select(Ticket).where(Ticket.event_id==event_id)):w.writerow([t.public_id,t.order.reference,t.status,t.ticket_class.name,t.section.name,t.price])
    return StreamingResponse(iter([out.getvalue()]),media_type="text/csv",headers={"Content-Disposition":"attachment; filename=tickets.csv"})
@app.get("/gate",response_class=HTMLResponse)
def gate(request:Request,user=Depends(require("gate")),db:Session=Depends(get_db)):return render(request,"gate.html",events=db.scalars(select(Event).where(Event.published==True)).all())
@app.post("/gate/scan")
def gate_scan(request:Request,event_id:int=Form(),token:str=Form(),user=Depends(require("gate")),db:Session=Depends(get_db)):return scan_ticket(db,token.strip(),event_id,user,user.gate)
