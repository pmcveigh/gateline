"""Supporter and club season-ticket routes."""
from io import BytesIO
import json, re
import qrcode
from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from .auth import hash_password, require, verify
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
        next_path=request.query_params.get('next','')
        return RedirectResponse(next_path if re.fullmatch(r'/season-tickets/products/[0-9]+',next_path) else '/account',303)

    @app.get('/register', response_class=HTMLResponse)
    def registration(request:Request, db:Session=Depends(get_db)):
        return render(request,'register.html',clubs=club_choices(db),form={})

    @app.post('/register')
    def create_account(request:Request, username:str=Form(), full_name:str=Form(), email:str=Form(), password:str=Form(), confirmation:str=Form(), birth_date:str=Form(""), clubs:list[str]=Form([]), db:Session=Depends(get_db)):
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
        return RedirectResponse('/account/settings?saved=1',303)

    @app.get('/account/profile', response_class=HTMLResponse)
    def profile(request:Request,user=Depends(require('supporter')),db:Session=Depends(get_db)):
        return render(request,'account_profile.html',**dashboard_data(db,user))

    @app.get('/account/tickets', response_class=HTMLResponse)
    def bought_tickets(request:Request,user=Depends(require('supporter')),db:Session=Depends(get_db)):
        return render(request,'account_tickets.html',**dashboard_data(db,user))

    @app.get('/account/history', response_class=HTMLResponse)
    def history(request:Request,user=Depends(require('supporter')),db:Session=Depends(get_db)):
        return render(request,'account_history.html',**dashboard_data(db,user))

    @app.get('/account/settings', response_class=HTMLResponse)
    def settings(request:Request,user=Depends(require('supporter')),db:Session=Depends(get_db)):
        p=profile_for(db,user)
        return render(request,'account_settings.html',profile=p,interests=json.loads(p.clubs_json),clubs=club_choices(db))

    @app.post('/account/profile')
    @app.post('/account/settings')
    def update_profile(request:Request,full_name:str=Form(),birth_date:str=Form(""),clubs:list[str]=Form([]),force_concession:bool=Form(False),disability_type:str=Form(''),access_details:str=Form(''),share_access_needs:bool=Form(False),address1:str=Form(''),address2:str=Form(''),city:str=Form(''),postcode:str=Form(''),country:str=Form('United Kingdom'),email:str|None=Form(None),current_password:str=Form(''),new_password:str=Form(''),password_confirmation:str=Form(''),user=Depends(require('supporter')),db:Session=Depends(get_db)):
        stored=db.get(User,user.id)
        try:
            contact=(email if email is not None else stored.email).strip().casefold()
            if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',contact) or len(contact)>200: raise ValueError('Enter a valid email address')
            if contact!=stored.email or new_password:
                if len(current_password.encode())>72 or not verify(current_password,stored.password_hash): raise ValueError('Enter your current password to change your email or password')
                if db.scalar(select(User.id).where(func.lower(User.email)==contact,User.id!=stored.id)): raise ValueError('That email address is already in use')
            if new_password:
                if len(new_password)<8 or len(new_password.encode())>72: raise ValueError('Use a password of at least 8 characters and no more than 72 bytes')
                if new_password!=password_confirmation: raise ValueError('New passwords do not match')
                stored.password_hash=hash_password(new_password)
            stored.email=contact
            save_profile(db,stored,full_name,birth_date,clubs,force_concession,disability_type,access_details,share_access_needs,address1,address2,city,postcode,country)
        except ValueError as error:
            db.rollback()
            return render(request,'account_settings.html',status_code=400,profile=profile_for(db,user),interests=clubs,clubs=club_choices(db),error=str(error))
        return RedirectResponse('/account/settings?saved=1',303)

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
