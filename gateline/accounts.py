"""Supporter and club season-ticket routes."""
from io import BytesIO
import json
import qrcode
from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from .auth import require, verify
from .database import get_db
from .models import SeasonTicket, SupporterAttendance, User
from .supporters import club_choices, dashboard_data, profile_for, register_supporter, save_profile
from .ticketing import club_key


def install_accounts(app, render):
    @app.get('/account/login', response_class=HTMLResponse)
    def sign_in_page(request:Request):
        return render(request,'account_login.html')

    @app.post('/account/login')
    def sign_in(request:Request, identity:str=Form(), password:str=Form(), db:Session=Depends(get_db)):
        key=identity.strip().casefold()
        user=db.scalar(select(User).where(User.role=='supporter', (User.username==key)|(func.lower(User.email)==key)))
        if len(password.encode())>72 or not user or not verify(password,user.password_hash):
            return render(request,'account_login.html',status_code=401,error='Incorrect username or password',identity=identity)
        request.session.clear();request.session['user_id']=user.id
        return RedirectResponse('/account',303)

    @app.get('/register', response_class=HTMLResponse)
    def registration(request:Request, db:Session=Depends(get_db)):
        return render(request,'register.html',clubs=club_choices(db),form={})

    @app.post('/register')
    def create_account(request:Request, username:str=Form(), full_name:str=Form(), email:str=Form(), password:str=Form(), confirmation:str=Form(), birth_date:str=Form(), clubs:list[str]=Form([]), db:Session=Depends(get_db)):
        try: user=register_supporter(db,username,full_name,email,password,confirmation,birth_date,clubs)
        except ValueError as error:
            return render(request,'register.html',status_code=400,clubs=club_choices(db),form=dict(username=username,full_name=full_name,email=email,birth_date=birth_date,clubs=clubs),error=str(error))
        request.session.clear();request.session['user_id']=user.id
        return RedirectResponse('/account',303)

    @app.get('/account', response_class=HTMLResponse)
    def dashboard(request:Request,user=Depends(require('supporter')),db:Session=Depends(get_db)):
        return render(request,'account.html',**dashboard_data(db,user),club_key=club_key)

    @app.post('/account/concession')
    def concession_preference(request:Request,force_concession:bool=Form(False),user=Depends(require('supporter')),db:Session=Depends(get_db)):
        profile_for(db,user).force_concession=force_concession
        db.commit()
        return RedirectResponse('/account?saved=1',303)

    @app.get('/account/profile', response_class=HTMLResponse)
    def profile(request:Request,user=Depends(require('supporter')),db:Session=Depends(get_db)):
        p=profile_for(db,user)
        return render(request,'account_profile.html',profile=p,interests=json.loads(p.clubs_json),clubs=club_choices(db))

    @app.post('/account/profile')
    def update_profile(request:Request,full_name:str=Form(),birth_date:str=Form(),clubs:list[str]=Form([]),force_concession:bool=Form(False),disability_type:str=Form(''),access_details:str=Form(''),share_access_needs:bool=Form(False),address1:str=Form(''),address2:str=Form(''),city:str=Form(''),postcode:str=Form(''),country:str=Form('United Kingdom'),user=Depends(require('supporter')),db:Session=Depends(get_db)):
        try:
            save_profile(db,db.get(User,user.id),full_name,birth_date,clubs,force_concession,disability_type,access_details,share_access_needs,address1,address2,city,postcode,country)
        except ValueError as error:
            return render(request,'account_profile.html',status_code=400,profile=profile_for(db,user),interests=clubs,clubs=club_choices(db),error=str(error))
        return RedirectResponse('/account/profile?saved=1',303)

    def owned_pass(db,pass_id,user):
        st=db.get(SeasonTicket,pass_id)
        if not st or st.user_id!=user.id: raise HTTPException(404)
        return st

    @app.get('/account/season-tickets/{pass_id}',response_class=HTMLResponse)
    def season_pass(pass_id:int,request:Request,user=Depends(require('supporter')),db:Session=Depends(get_db)):
        st=owned_pass(db,pass_id,user)
        attended=db.scalar(select(func.count(SupporterAttendance.id)).where(SupporterAttendance.season_ticket_id==st.id)) or 0
        return render(request,'season_ticket.html',membership=st,attended=attended)

    @app.get('/account/season-tickets/{pass_id}/qr.png')
    def season_qr(pass_id:int,user=Depends(require('supporter')),db:Session=Depends(get_db)):
        st=owned_pass(db,pass_id,user);out=BytesIO();qrcode.make(st.qr_token).save(out,'PNG');out.seek(0)
        return StreamingResponse(out,media_type='image/png')

    @app.get('/admin/clubs/{name}/season-tickets',response_class=HTMLResponse)
    def season_registry(name:str,request:Request,user=Depends(require('admin')),db:Session=Depends(get_db)):
        memberships=db.scalars(select(SeasonTicket).where(SeasonTicket.club_name==club_key(name)).order_by(SeasonTicket.full_name)).all()
        return render(request,'season_registry.html',name=name,memberships=memberships)
