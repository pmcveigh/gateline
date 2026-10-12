"""Club-only administration and season-ticket sales configuration."""
from datetime import date, datetime, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo
import secrets, re
from io import BytesIO
import qrcode
from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy import func, select, update
from .auth import hash_password, require, verify
from .database import get_db
from .management import check_club, check_event, club_record, event_scope, require_manager
from .models import *
from .season_sales import amount, issue_holder, normalise_type, purchase_season
from .supporters import london_date
from .ticketing import club_key


def install_management(app,render):
    def path(club): return '/admin/clubs/'+quote(club.name,safe='')
    def owned_club(db,name,user):
        check_club(user,name);return club_record(db,name)
    def log(db,user,action,entity,identity): db.add(AuditLog(user_id=user.id,action=action,entity=entity,entity_id=str(identity)))
    def utc(value): return value.replace(tzinfo=ZoneInfo('Europe/London')).astimezone(timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    def has_bookings(db,event):
        return bool(db.scalar(select(Ticket.id).where(Ticket.event_id==event.id)) or db.scalar(select(Reservation.id).where(Reservation.event_id==event.id,Reservation.completed==False,Reservation.expires_at>datetime.now(timezone.utc))))

    @app.get('/admin/clubs/{name}',response_class=HTMLResponse)
    def overview(name:str,request:Request,q:str='',user=Depends(require_manager),db=Depends(get_db)):
        club=owned_club(db,name,user)
        events=[e for e in db.scalars(select(Event).order_by(Event.starts_at.desc())) if (e.owner_club or club_key(e.home_team))==club.club_name]
        memberships=db.scalars(select(SeasonTicket).where(SeasonTicket.club_name==club.club_name)).all()
        products=db.scalars(select(SeasonProduct).where(SeasonProduct.club_name==club.club_name)).all()
        match_sales=db.scalar(select(func.coalesce(func.sum(Order.total),0)).join(Event).where(Order.payment_status=='successful',Event.id.in_([e.id for e in events]))) or 0
        season_sales=db.scalar(select(func.coalesce(func.sum(SeasonPurchase.total),0)).join(SeasonProduct).where(SeasonPurchase.payment_status=='successful',SeasonProduct.club_name==club.club_name)) or 0
        displayed=[e for e in events if q.casefold() in (e.title+' '+e.competition+' '+e.venue.name).casefold()]
        return render(request,'club_management.html',club=club,events=displayed,q=q,memberships=memberships,products=products,match_sales=match_sales,season_sales=season_sales,event_count=len(events))

    @app.get('/admin/clubs/{name}/details',response_class=HTMLResponse)
    def details(name:str,request:Request,user=Depends(require_manager),db=Depends(get_db)):
        return render(request,'club_details.html',club=owned_club(db,name,user),venues=db.scalars(select(Venue).order_by(Venue.name)).all())

    @app.post('/admin/clubs/{name}/details')
    def save_details(name:str,request:Request,display_name:str=Form(),short_name:str=Form(),contact_email:str=Form(''),address:str=Form(''),description:str=Form(''),primary_colour:str=Form('#07583b'),venue_id:str=Form(''),user=Depends(require_manager),db=Depends(get_db)):
        from .management import update_club_details
        club=owned_club(db,name,user)
        try:
            update_club_details(db,club,display_name,short_name,contact_email,address,description,primary_colour,int(venue_id) if venue_id else None)
            log(db,user,'club.details_updated','club',club.club_name);db.commit()
        except ValueError as error:
            db.rollback();return render(request,'club_details.html',status_code=400,club=club,venues=db.scalars(select(Venue)).all(),error=str(error))
        return RedirectResponse(path(club)+'/details?saved=1',303)

    @app.get('/admin/clubs/{name}/season-tickets',response_class=HTMLResponse)
    def holders(name:str,request:Request,q:str='',user=Depends(require_manager),db=Depends(get_db)):
        club=owned_club(db,name,user)
        rows=db.scalars(select(SeasonTicket).where(SeasonTicket.club_name==club.club_name).order_by(SeasonTicket.full_name)).all()
        rows=[st for st in rows if q.casefold() in (' '.join([st.full_name,st.email,st.number,st.section,st.ticket_type])).casefold()]
        return render(request,'season_registry.html',club=club,name=club.display_name,memberships=rows,q=q)

    @app.get('/admin/clubs/{name}/season-tickets/new',response_class=HTMLResponse)
    def new_holder(name:str,request:Request,user=Depends(require_manager),db=Depends(get_db)):
        club=owned_club(db,name,user);token=secrets.token_urlsafe(24)
        request.session['season_issue']={**request.session.get('season_issue',{}),club.club_name:token}
        return render(request,'season_issue.html',club=club,products=db.scalars(select(SeasonProduct).where(SeasonProduct.club_name==club.club_name)).all(),token=token,today=london_date())

    @app.post('/admin/clubs/{name}/season-tickets/new')
    def add_holder(name:str,request:Request,full_name:str=Form(),email:str=Form(),birth_date:str=Form(''),product_id:str=Form(''),section:str=Form(''),ticket_type:str=Form('Adult'),competition:str=Form('NIFL Premiership'),valid_from:str=Form(''),valid_until:str=Form(''),token:str=Form(),user=Depends(require_manager),db=Depends(get_db)):
        club=owned_club(db,name,user)
        if not secrets.compare_digest(token.encode(),request.session.get('season_issue',{}).get(club.club_name,'').encode()): raise HTTPException(400,'Refresh the issue form and retry')
        try:
            product=db.get(SeasonProduct,int(product_id)) if product_id else None
            if product_id and (not product or product.club_name!=club.club_name): raise ValueError('Choose a season product belonging to this club')
            start=product.valid_from if product else date.fromisoformat(valid_from)
            end=product.valid_until if product else date.fromisoformat(valid_until)
            st,password=issue_holder(db,club,full_name,email,birth_date,section,ticket_type,competition,start,end,token,user,product)
        except ValueError as error:
            db.rollback();return render(request,'season_issue.html',status_code=400,club=club,products=db.scalars(select(SeasonProduct).where(SeasonProduct.club_name==club.club_name)).all(),token=token,today=london_date(),error=str(error))
        response=render(request,'season_issued.html',club=club,membership=st,password=password)
        response.headers['Cache-Control']='no-store';return response

    @app.post('/admin/clubs/{name}/season-tickets/{pass_id}/state')
    def holder_state(name:str,pass_id:int,request:Request,active:bool=Form(False),reason:str=Form(),user=Depends(require_manager),db=Depends(get_db)):
        club=owned_club(db,name,user);st=db.get(SeasonTicket,pass_id)
        if not st or st.club_name!=club.club_name: raise HTTPException(404)
        if not reason.strip(): raise HTTPException(400,'Enter a reason')
        st.active=active;log(db,user,'season.activated' if active else 'season.suspended','season_ticket',st.id);db.commit()
        return RedirectResponse(path(club)+'/season-tickets',303)

    @app.get('/admin/clubs/{name}/season-tickets/{pass_id}',response_class=HTMLResponse)
    def admin_pass(name:str,pass_id:int,request:Request,user=Depends(require_manager),db=Depends(get_db)):
        club=owned_club(db,name,user);st=db.get(SeasonTicket,pass_id)
        if not st or st.club_name!=club.club_name: raise HTTPException(404)
        return render(request,'admin_season_pass.html',club=club,membership=st)

    @app.get('/admin/clubs/{name}/season-tickets/{pass_id}/qr.png')
    def admin_pass_qr(name:str,pass_id:int,user=Depends(require_manager),db=Depends(get_db)):
        club=owned_club(db,name,user);st=db.get(SeasonTicket,pass_id)
        if not st or st.club_name!=club.club_name: raise HTTPException(404)
        image=BytesIO();qrcode.make(st.qr_token).save(image,'PNG');image.seek(0)
        return StreamingResponse(image,media_type='image/png')

    @app.get('/admin/clubs/{name}/season-products',response_class=HTMLResponse)
    def products(name:str,request:Request,user=Depends(require_manager),db=Depends(get_db)):
        club=owned_club(db,name,user)
        rows=db.scalars(select(SeasonProduct).where(SeasonProduct.club_name==club.club_name).order_by(SeasonProduct.valid_from.desc())).all()
        purchases=db.scalars(select(SeasonPurchase).join(SeasonProduct).where(SeasonProduct.club_name==club.club_name).order_by(SeasonPurchase.created_at.desc())).all()
        return render(request,'season_products.html',club=club,products=rows,purchases=purchases)

    @app.post('/admin/clubs/{name}/season-products')
    def save_product(name:str,request:Request,title:str=Form(),section:str=Form(),ticket_type:str=Form(),competition:str=Form(),valid_from:date=Form(),valid_until:date=Form(),price:str=Form(),capacity:int=Form(),enabled:bool=Form(False),product_id:int=Form(0),concession_under:int=Form(16),concession_over:int=Form(65),user=Depends(require_manager),db=Depends(get_db)):
        club=owned_club(db,name,user);product=db.get(SeasonProduct,product_id) if product_id else None
        if product_id and (not product or product.club_name!=club.club_name): raise HTTPException(404)
        ticket_type=normalise_type(ticket_type)
        try:
            value=amount(price)
            if not title.strip() or len(title)>200 or not section.strip() or len(section)>100 or not ticket_type.strip() or len(ticket_type)>100 or not competition.strip() or len(competition)>150 or valid_from>valid_until or not 1<=capacity<=1000000 or not 0<=concession_under<=concession_over<=120: raise ValueError('Check the season product details, dates, limits and capacity')
            if product and product.issued and (section,ticket_type,competition,valid_from,valid_until)!=(product.section,product.ticket_type,product.competition,product.valid_from,product.valid_until): raise ValueError('Issued products keep their allocation and dates. Create a new product for a different season.')
            if product and capacity<product.issued: raise ValueError('Capacity cannot be lower than issued passes')
            if not product: product=SeasonProduct(club_name=club.club_name,issued=0);db.add(product)
            for key,value in dict(title=title.strip(),section=section.strip(),ticket_type=ticket_type.strip(),competition=competition.strip(),valid_from=valid_from,valid_until=valid_until,price=value,capacity=capacity,enabled=enabled,concession_under=concession_under,concession_over=concession_over).items(): setattr(product,key,value)
            db.flush();log(db,user,'season.product_updated','season_product',product.id);db.commit()
        except ValueError as error:
            db.rollback();return render(request,'season_products.html',status_code=400,club=club,products=db.scalars(select(SeasonProduct).where(SeasonProduct.club_name==club.club_name)).all(),purchases=[],error=str(error))
        return RedirectResponse(path(club)+'/season-products?saved=1',303)

    @app.get('/admin/clubs/{name}/activity',response_class=HTMLResponse)
    def activity(name:str,request:Request,user=Depends(require_manager),db=Depends(get_db)):
        club=owned_club(db,name,user)
        ids={'club':{club.club_name},'event':{str(e.id) for e in db.scalars(select(Event)) if (e.owner_club or club_key(e.home_team))==club.club_name},'season_ticket':{str(i) for i in db.scalars(select(SeasonTicket.id).where(SeasonTicket.club_name==club.club_name))},'season_product':{str(i) for i in db.scalars(select(SeasonProduct.id).where(SeasonProduct.club_name==club.club_name))}}
        rows=[log for log in db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc())) if log.entity_id in ids.get(log.entity,set())][:100]
        return render(request,'club_activity.html',club=club,logs=rows)

    @app.get('/admin/club-accounts',response_class=HTMLResponse)
    def club_accounts(request:Request,user=Depends(require('admin')),db=Depends(get_db)):
        rows=db.scalars(select(User).where(User.role=='club_admin').order_by(User.managed_club)).all()
        return render(request,'club_accounts.html',admins=rows,clubs=db.scalars(select(ClubManagement).order_by(ClubManagement.name)).all())

    @app.post('/admin/club-accounts')
    def create_club_account(request:Request,club_name:str=Form(),full_name:str=Form(),email:str=Form(),username:str=Form(),user=Depends(require('admin')),db=Depends(get_db)):
        club=db.get(ClubManagement,club_key(club_name));email=email.strip().casefold();username=username.strip().casefold()
        if not club or not full_name.strip() or len(full_name)>120 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email) or len(email)>200 or not re.fullmatch(r'[a-z0-9_.-]{3,30}',username): raise HTTPException(400,'Check club, name, email and username')
        if db.scalar(select(User.id).where((func.lower(User.email)==email)|(User.username==username))): raise HTTPException(409,'That username or email is already in use')
        password=secrets.token_urlsafe(15)
        admin=User(name=full_name.strip(),email=email,username=username,role='club_admin',managed_club=club.club_name,password_hash=hash_password(password));db.add(admin)
        log(db,user,'club.administrator_added','club',club.club_name);db.commit()
        response=render(request,'club_admin_created.html',admin=admin,password=password)
        response.headers['Cache-Control']='no-store';return response

    @app.get('/admin/settings',response_class=HTMLResponse)
    def staff_settings(request:Request,user=Depends(require_manager)):
        return render(request,'admin_settings.html')

    @app.post('/admin/settings')
    def staff_password(request:Request,current_password:str=Form(),new_password:str=Form(),confirmation:str=Form(),user=Depends(require_manager),db=Depends(get_db)):
        if len(current_password.encode())>72 or not verify(current_password,user.password_hash) or len(new_password)<8 or len(new_password.encode())>72 or new_password!=confirmation:
            return render(request,'admin_settings.html',status_code=400,error='Check your current password and matching new passwords (8 characters minimum)')
        db.get(User,user.id).password_hash=hash_password(new_password);log(db,user,'user.password_changed','user',user.id);db.commit()
        return RedirectResponse('/admin/settings?saved=1',303)

    @app.post('/admin/events/{event_id}/edit')
    def amend_event(event_id:int,request:Request,title:str=Form(),away_team:str=Form(),competition:str=Form(),venue_id:int=Form(),starts_at:datetime=Form(),sales_open:datetime=Form(),sales_close:datetime=Form(),description:str=Form(''),season_claim_required:bool=Form(False),user=Depends(require_manager),db=Depends(get_db)):
        event=check_event(user,db.get(Event,event_id));start,opening,closing=map(utc,[starts_at,sales_open,sales_close])
        venue=db.get(Venue,venue_id)
        if not venue or not title.strip() or len(title)>200 or not away_team.strip() or len(away_team)>150 or not competition.strip() or len(competition)>150 or opening>=closing or closing>start or len(description)>5000: raise HTTPException(400,'Check fixture details and dates')
        booked=has_bookings(db,event)
        if booked and (event.venue_id!=venue_id or event.season_claim_required!=season_claim_required): raise HTTPException(409,'The venue and season-claim policy cannot change after tickets or reservations exist')
        if event.venue_id!=venue_id:
            event.inventories.clear();db.flush()
            for stand in venue.stands:
                for section in stand.sections: event.inventories.append(EventInventory(section_id=section.id,capacity=section.capacity))
            for tc in event.classes: tc.section_id=None
        event.title=title.strip();event.away_team=away_team.strip();event.competition=competition.strip();event.venue_id=venue_id;event.starts_at=start;event.sales_open=opening;event.sales_close=closing;event.description=description.strip();event.season_claim_required=season_claim_required
        db.execute(update(Reservation).where(Reservation.event_id==event.id,Reservation.completed==False,Reservation.expires_at>closing).values(expires_at=closing).execution_options(synchronize_session='fetch'))
        log(db,user,'event.amended','event',event.id);db.commit();return RedirectResponse(f'/admin/events/{event.id}?saved=1',303)

    @app.post('/admin/events/{event_id}/inventory/{inventory_id}')
    def inventory(event_id:int,inventory_id:int,request:Request,capacity:int=Form(),held:int=Form(0),audience:str=Form('home'),user=Depends(require_manager),db=Depends(get_db)):
        event=check_event(user,db.get(Event,event_id));inv=db.get(EventInventory,inventory_id)
        if not inv or inv.event_id!=event.id: raise HTTPException(404)
        sold=db.scalar(select(func.count(Ticket.id)).where(Ticket.event_id==event.id,Ticket.section_id==inv.section_id,Ticket.status.in_(['sold','scanned']))) or 0
        reserved=db.scalar(select(func.coalesce(func.sum(Reservation.quantity),0)).where(Reservation.event_id==event.id,Reservation.section_id==inv.section_id,Reservation.completed==False,Reservation.expires_at>datetime.now(timezone.utc))) or 0
        if audience not in ('home','away') or held<0 or capacity<0 or capacity>inv.section.capacity or capacity-held<sold+reserved: raise HTTPException(409,'Allocation must fit the section and existing tickets/reservations')
        if (sold or reserved) and audience!=inv.audience: raise HTTPException(409,'Audience cannot change with active tickets or reservations')
        inv.capacity=capacity;inv.held=held;inv.audience=audience;log(db,user,'event.inventory_updated','event',event.id);db.commit();return RedirectResponse(f'/admin/events/{event.id}#inventory',303)

    @app.post('/admin/events/{event_id}/ticket-types')
    def fixture_class(event_id:int,request:Request,class_id:int=Form(0),name:str=Form(),price:str=Form(),description:str=Form(''),audience:str=Form('home'),section_id:str=Form(''),adult:bool=Form(False),enabled:bool=Form(False),maximum:int=Form(10),concession_under:int=Form(16),concession_over:int=Form(65),user=Depends(require_manager),db=Depends(get_db)):
        event=check_event(user,db.get(Event,event_id));tc=db.get(TicketClass,class_id) if class_id else None
        if class_id and (not tc or tc.event_id!=event.id): raise HTTPException(404)
        name=normalise_type(name)
        try: value=amount(price);section=int(section_id) if section_id else None
        except ValueError as error: raise HTTPException(400,str(error))
        if not name.strip() or len(name)>100 or audience not in ('home','away') or not 0<=maximum<=10 or not 0<=concession_under<=concession_over<=120 or (section and section not in {inv.section_id for inv in event.inventories}): raise HTTPException(400,'Check ticket type details and allocation')
        if any(other.id!=class_id and other.audience==audience and other.name.casefold()==name.strip().casefold() for other in event.classes): raise HTTPException(409,'Ticket names must be unique within an audience')
        issued=db.scalar(select(Ticket.id).where(Ticket.ticket_class_id==class_id)) if tc else None
        if issued and (tc.name!=name.strip() or tc.audience!=audience or tc.section_id!=section): raise HTTPException(409,'Issued ticket types keep their name and allocation')
        if not tc: tc=TicketClass(event_id=event.id);db.add(tc)
        for key,value in dict(name=name.strip(),price=value,description=description.strip(),audience=audience,section_id=section,adult_admission=adult,enabled=enabled,maximum=maximum,concession_under=concession_under,concession_over=concession_over).items(): setattr(tc,key,value)
        log(db,user,'event.ticket_type_updated','event',event.id);db.commit();return RedirectResponse(f'/admin/events/{event.id}#ticket-types',303)

    @app.get('/season-tickets/products/{product_id}',response_class=HTMLResponse)
    def season_buy(product_id:int,request:Request,db=Depends(get_db)):
        product=db.get(SeasonProduct,product_id)
        if not product: raise HTTPException(404)
        user=request.state.user
        if not user: return RedirectResponse(f'/account/login?next=/season-tickets/products/{product.id}',303)
        if user.role in ('admin','club_admin'):
            check_club(user,product.club_name)
            return render(request,'season_buy.html',product=product,preview=True,token='')
        if user.role!='supporter': raise HTTPException(403)
        if not product.enabled: raise HTTPException(404)
        token=secrets.token_urlsafe(24);request.session['season_purchase']={**request.session.get('season_purchase',{}),str(product.id):token}
        return render(request,'season_buy.html',product=product,preview=False,token=token)

    @app.post('/season-tickets/products/{product_id}')
    def pay_season(product_id:int,request:Request,token:str=Form(),test_result:str=Form('success'),user=Depends(require('supporter')),db=Depends(get_db)):
        product=db.get(SeasonProduct,product_id)
        if not product: raise HTTPException(404)
        if not secrets.compare_digest(token.encode(),request.session.get('season_purchase',{}).get(str(product.id),'').encode()): raise HTTPException(400,'Refresh the purchase page and retry')
        try: receipt=purchase_season(db,product,db.get(User,user.id),token,test_result)
        except ValueError as error:
            db.rollback();return render(request,'season_buy.html',status_code=400,product=product,token=token,error=str(error))
        return RedirectResponse(f'/season-tickets/purchases/{receipt.reference}',303)

    @app.get('/season-tickets/purchases/{reference}',response_class=HTMLResponse)
    def receipt(reference:str,request:Request,db=Depends(get_db)):
        row=db.scalar(select(SeasonPurchase).where(SeasonPurchase.reference==reference));user=request.state.user
        if not row or not user: raise HTTPException(404)
        if user.role=='supporter':
            if row.user_id!=user.id: raise HTTPException(404)
        else: check_club(user,row.product.club_name)
        return render(request,'season_purchase.html',purchase=row)
