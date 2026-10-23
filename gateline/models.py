from __future__ import annotations
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
import secrets
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base

def now(): return datetime.now(timezone.utc)
class Role(str, Enum): ADMIN="admin"; CLUB_ADMIN="club_admin"; GATE="gate"; SUPPORTER="supporter"
class Mode(str, Enum): ASSIGNED="assigned"; GENERAL="general"
class TicketStatus(str, Enum): RESERVED="reserved"; SOLD="sold"; SCANNED="scanned"; CANCELLED="cancelled"; REFUNDED="refunded"; EXPIRED="expired"

class User(Base):
    __tablename__="users"; id:Mapped[int]=mapped_column(primary_key=True); email:Mapped[str]=mapped_column(String(200),unique=True); name:Mapped[str]=mapped_column(String(120)); password_hash:Mapped[str]=mapped_column(String(255)); role:Mapped[str]=mapped_column(String(20)); gate:Mapped[str|None]=mapped_column(String(100),nullable=True)
    username:Mapped[str|None]=mapped_column(String(30),nullable=True,unique=True)
    managed_club:Mapped[str|None]=mapped_column(String(150),nullable=True)
class SupporterProfile(Base):
    __tablename__="supporter_profiles"
    user_id:Mapped[int]=mapped_column(ForeignKey("users.id"),primary_key=True)
    birth_date:Mapped[date|None]=mapped_column(Date,nullable=True)
    clubs_json:Mapped[str]=mapped_column(Text,default="[]")
    force_concession:Mapped[bool]=mapped_column(Boolean,default=False)
    disability_type:Mapped[str]=mapped_column(Text,default="")
    access_details:Mapped[str]=mapped_column(Text,default="")
    share_access_needs:Mapped[bool]=mapped_column(Boolean,default=False)
    address1:Mapped[str]=mapped_column(default="")
    address2:Mapped[str]=mapped_column(default="")
    city:Mapped[str]=mapped_column(default="")
    postcode:Mapped[str]=mapped_column(default="")
    country:Mapped[str]=mapped_column(default="United Kingdom")
class SeasonTicket(Base):
    __tablename__="season_tickets"
    id:Mapped[int]=mapped_column(primary_key=True)
    club_name:Mapped[str]=mapped_column(String(150))
    number:Mapped[str]=mapped_column(String(100))
    user_id:Mapped[int]=mapped_column(ForeignKey("users.id"))
    full_name:Mapped[str]=mapped_column(String(120))
    email:Mapped[str]=mapped_column(String(200))
    section:Mapped[str]=mapped_column(String(100))
    ticket_type:Mapped[str]=mapped_column(String(100))
    competition:Mapped[str]=mapped_column(default="NIFL Premiership")
    valid_from:Mapped[date]=mapped_column(Date)
    valid_until:Mapped[date]=mapped_column(Date)
    active:Mapped[bool]=mapped_column(Boolean,default=True)
    qr_token:Mapped[str]=mapped_column(unique=True,default=lambda:secrets.token_urlsafe(32))
    user:Mapped[User]=relationship()
    product_id:Mapped[int|None]=mapped_column(ForeignKey("season_products.id"),nullable=True)
    issuance_token:Mapped[str|None]=mapped_column(String(100),nullable=True,unique=True)
    __table_args__=(UniqueConstraint("club_name","number"),UniqueConstraint("product_id","user_id"))

class ClubManagement(Base):
    __tablename__="club_management"
    club_name:Mapped[str]=mapped_column(String(150),primary_key=True)
    name:Mapped[str]=mapped_column(String(150))
    display_name:Mapped[str]=mapped_column(String(150))
    short_name:Mapped[str]=mapped_column(String(30))
    contact_email:Mapped[str]=mapped_column(String(200),default="")
    address:Mapped[str]=mapped_column(Text,default="")
    description:Mapped[str]=mapped_column(Text,default="")
    primary_colour:Mapped[str]=mapped_column(String(7),default="#07583b")
    venue_id:Mapped[int|None]=mapped_column(ForeignKey("venues.id"),nullable=True)
    venue:Mapped[Venue|None]=relationship()

class SeasonProduct(Base):
    __tablename__="season_products"
    id:Mapped[int]=mapped_column(primary_key=True)
    club_name:Mapped[str]=mapped_column(ForeignKey("club_management.club_name"))
    title:Mapped[str]=mapped_column(String(200))
    section:Mapped[str]=mapped_column(String(100))
    ticket_type:Mapped[str]=mapped_column(String(100))
    competition:Mapped[str]=mapped_column(String(150))
    valid_from:Mapped[date]=mapped_column(Date)
    valid_until:Mapped[date]=mapped_column(Date)
    price:Mapped[Decimal]=mapped_column(Numeric(10,2))
    capacity:Mapped[int]=mapped_column(default=100)
    issued:Mapped[int]=mapped_column(default=0)
    enabled:Mapped[bool]=mapped_column(Boolean,default=False)
    concession_under:Mapped[int]=mapped_column(default=16)
    concession_over:Mapped[int]=mapped_column(default=65)

class SeasonPurchase(Base):
    __tablename__="season_purchases"
    id:Mapped[int]=mapped_column(primary_key=True)
    reference:Mapped[str]=mapped_column(String(40),unique=True)
    token:Mapped[str]=mapped_column(String(100),unique=True)
    user_id:Mapped[int]=mapped_column(ForeignKey("users.id"))
    product_id:Mapped[int]=mapped_column(ForeignKey("season_products.id"))
    season_ticket_id:Mapped[int|None]=mapped_column(ForeignKey("season_tickets.id"),nullable=True)
    total:Mapped[Decimal]=mapped_column(Numeric(10,2))
    payment_status:Mapped[str]=mapped_column(String(20))
    created_at:Mapped[datetime]=mapped_column(default=now)
    user:Mapped[User]=relationship()
    product:Mapped[SeasonProduct]=relationship()
    season_ticket:Mapped[SeasonTicket|None]=relationship()
class SupporterAttendance(Base):
    __tablename__="supporter_attendances"
    id:Mapped[int]=mapped_column(primary_key=True)
    user_id:Mapped[int]=mapped_column(ForeignKey("users.id"))
    season_ticket_id:Mapped[int|None]=mapped_column(ForeignKey("season_tickets.id"),nullable=True)
    ticket_id:Mapped[int|None]=mapped_column(ForeignKey("tickets.id"),nullable=True)
    event_id:Mapped[int]=mapped_column(ForeignKey("events.id"))
    scanned_at:Mapped[datetime]=mapped_column(default=now)
    operator_id:Mapped[int]=mapped_column(ForeignKey("users.id"))
    __table_args__=(UniqueConstraint("user_id","event_id"),)
class Club(Base):
    __tablename__="clubs"; id:Mapped[int]=mapped_column(primary_key=True); name:Mapped[str]=mapped_column(String(150)); short_name:Mapped[str]=mapped_column(String(30)); logo_url:Mapped[str|None]=mapped_column(nullable=True); primary_colour:Mapped[str]=mapped_column(default="#0b6b3a"); contact_email:Mapped[str]=mapped_column(String(200)); address:Mapped[str]=mapped_column(Text); currency:Mapped[str]=mapped_column(default="GBP")
class Venue(Base):
    __tablename__="venues"; id:Mapped[int]=mapped_column(primary_key=True); name:Mapped[str]=mapped_column(String(150)); address:Mapped[str]=mapped_column(Text); stands:Mapped[list[Stand]]=relationship(cascade="all, delete-orphan")
class Stand(Base):
    __tablename__="stands"; id:Mapped[int]=mapped_column(primary_key=True); venue_id:Mapped[int]=mapped_column(ForeignKey("venues.id")); name:Mapped[str]=mapped_column(String(100)); gate:Mapped[str|None]=mapped_column(nullable=True); sections:Mapped[list[Section]]=relationship(cascade="all, delete-orphan")
class Section(Base):
    __tablename__="sections"; id:Mapped[int]=mapped_column(primary_key=True); stand_id:Mapped[int]=mapped_column(ForeignKey("stands.id")); name:Mapped[str]=mapped_column(String(100)); mode:Mapped[str]=mapped_column(String(20)); capacity:Mapped[int]; rows:Mapped[list[SeatRow]]=relationship(cascade="all, delete-orphan")
class SeatRow(Base):
    __tablename__="seat_rows"; id:Mapped[int]=mapped_column(primary_key=True); section_id:Mapped[int]=mapped_column(ForeignKey("sections.id")); name:Mapped[str]=mapped_column(String(20)); seats:Mapped[list[Seat]]=relationship(cascade="all, delete-orphan")
class Seat(Base):
    __tablename__="seats"; id:Mapped[int]=mapped_column(primary_key=True); row_id:Mapped[int]=mapped_column(ForeignKey("seat_rows.id")); number:Mapped[str]=mapped_column(String(20)); available:Mapped[bool]=mapped_column(Boolean,default=True); __table_args__=(UniqueConstraint("row_id","number"),)
class Event(Base):
    owner_club:Mapped[str|None]=mapped_column(String(150),nullable=True)
    season_claim_required:Mapped[bool]=mapped_column(Boolean,default=False,server_default="0")
    __tablename__="events"; id:Mapped[int]=mapped_column(primary_key=True); title:Mapped[str]=mapped_column(String(200)); home_team:Mapped[str]; away_team:Mapped[str]; competition:Mapped[str]; venue_id:Mapped[int]=mapped_column(ForeignKey("venues.id")); starts_at:Mapped[datetime]=mapped_column(DateTime(timezone=True)); sales_open:Mapped[datetime]=mapped_column(DateTime(timezone=True)); sales_close:Mapped[datetime]=mapped_column(DateTime(timezone=True)); priority_until:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True); description:Mapped[str]=mapped_column(Text,default=""); published:Mapped[bool]=mapped_column(Boolean,default=False); cancelled:Mapped[bool]=mapped_column(Boolean,default=False); sales_suspended:Mapped[bool]=mapped_column(Boolean,default=False); archived:Mapped[bool]=mapped_column(Boolean,default=False); venue:Mapped[Venue]=relationship(); inventories:Mapped[list[EventInventory]]=relationship(cascade="all, delete-orphan"); classes:Mapped[list[TicketClass]]=relationship(cascade="all, delete-orphan")
class EventInventory(Base):
    audience:Mapped[str]=mapped_column(String(20),default="home",server_default="home")
    __tablename__="event_inventory"; id:Mapped[int]=mapped_column(primary_key=True); event_id:Mapped[int]=mapped_column(ForeignKey("events.id")); section_id:Mapped[int]=mapped_column(ForeignKey("sections.id")); capacity:Mapped[int]; held:Mapped[int]=mapped_column(default=0); section:Mapped[Section]=relationship(); __table_args__=(UniqueConstraint("event_id","section_id"),)
class TicketClass(Base):
    audience:Mapped[str]=mapped_column(String(20),default="home",server_default="home")
    section_id:Mapped[int|None]=mapped_column(ForeignKey("sections.id"),nullable=True)
    __tablename__="ticket_classes"; id:Mapped[int]=mapped_column(primary_key=True); event_id:Mapped[int]=mapped_column(ForeignKey("events.id")); name:Mapped[str]; description:Mapped[str]=mapped_column(default=""); price:Mapped[Decimal]=mapped_column(Numeric(10,2)); minimum:Mapped[int]=mapped_column(default=0); maximum:Mapped[int]=mapped_column(default=10)
    enabled:Mapped[bool]=mapped_column(Boolean,default=True,server_default="1")
    adult_admission:Mapped[bool|None]=mapped_column(Boolean,nullable=True)
    concession_under:Mapped[int]=mapped_column(default=16,server_default="16")
    concession_over:Mapped[int]=mapped_column(default=65,server_default="65")
class ClubPricing(Base):
    __tablename__="club_pricing"
    club_name:Mapped[str]=mapped_column(String(150),primary_key=True)
    menu_json:Mapped[str]=mapped_column(Text,default="[]")
    portal_defaults_applied:Mapped[bool]=mapped_column(Boolean,default=False,server_default="0")
class PriorityIdentifier(Base):
    __tablename__="priority_identifiers"; id:Mapped[int]=mapped_column(primary_key=True); code:Mapped[str]=mapped_column(unique=True); maximum:Mapped[int]=mapped_column(default=1); used:Mapped[int]=mapped_column(default=0)
class Voucher(Base):
    __tablename__="vouchers"; id:Mapped[int]=mapped_column(primary_key=True); code:Mapped[str]=mapped_column(unique=True); kind:Mapped[str]; value:Mapped[Decimal]=mapped_column(Numeric(10,2)); starts_at:Mapped[datetime]; expires_at:Mapped[datetime]; maximum_uses:Mapped[int]; uses:Mapped[int]=mapped_column(default=0); event_id:Mapped[int|None]=mapped_column(ForeignKey("events.id"),nullable=True); enabled:Mapped[bool]=mapped_column(default=True)
class Customer(Base):
    __tablename__="customers"; id:Mapped[int]=mapped_column(primary_key=True); full_name:Mapped[str]; email:Mapped[str]; address1:Mapped[str]; address2:Mapped[str]=mapped_column(default=""); city:Mapped[str]; postcode:Mapped[str]; country:Mapped[str]
class Order(Base):
    __tablename__="orders"; id:Mapped[int]=mapped_column(primary_key=True); reference:Mapped[str]=mapped_column(unique=True,index=True); access_token:Mapped[str]=mapped_column(String(64),unique=True,index=True,default=lambda:secrets.token_urlsafe(24)); customer_id:Mapped[int]=mapped_column(ForeignKey("customers.id")); event_id:Mapped[int]=mapped_column(ForeignKey("events.id")); subtotal:Mapped[Decimal]=mapped_column(Numeric(10,2)); discount:Mapped[Decimal]=mapped_column(Numeric(10,2),default=0); total:Mapped[Decimal]=mapped_column(Numeric(10,2)); payment_status:Mapped[str]=mapped_column(default="pending"); status:Mapped[str]=mapped_column(default="pending"); created_at:Mapped[datetime]=mapped_column(default=now); customer:Mapped[Customer]=relationship(); event:Mapped[Event]=relationship(); tickets:Mapped[list[Ticket]]=relationship()
    supporter_id:Mapped[int|None]=mapped_column(ForeignKey("users.id"),nullable=True,index=True)
class Reservation(Base):
    # Completed/expired rows are audit history, not a permanent uniqueness lock.
    __tablename__="reservations"; id:Mapped[int]=mapped_column(primary_key=True); token:Mapped[str]=mapped_column(unique=True); event_id:Mapped[int]=mapped_column(ForeignKey("events.id")); section_id:Mapped[int]=mapped_column(ForeignKey("sections.id")); seat_id:Mapped[int|None]=mapped_column(ForeignKey("seats.id"),nullable=True); quantity:Mapped[int]=mapped_column(default=1); expires_at:Mapped[datetime]; completed:Mapped[bool]=mapped_column(default=False)
    selection_json:Mapped[str]=mapped_column(Text,default="{}",server_default="{}")
class Ticket(Base):
    season_ticket_id:Mapped[int|None]=mapped_column(ForeignKey("season_tickets.id"),nullable=True)
    __table_args__=(UniqueConstraint("event_id","season_ticket_id"),)
    __tablename__="tickets"; id:Mapped[int]=mapped_column(primary_key=True); public_id:Mapped[str]=mapped_column(unique=True,index=True); qr_token:Mapped[str]=mapped_column(unique=True,index=True); order_id:Mapped[int]=mapped_column(ForeignKey("orders.id")); event_id:Mapped[int]=mapped_column(ForeignKey("events.id")); section_id:Mapped[int]=mapped_column(ForeignKey("sections.id")); seat_id:Mapped[int|None]=mapped_column(ForeignKey("seats.id"),nullable=True); ticket_class_id:Mapped[int]=mapped_column(ForeignKey("ticket_classes.id")); price:Mapped[Decimal]=mapped_column(Numeric(10,2)); status:Mapped[str]=mapped_column(default=TicketStatus.SOLD.value); complimentary:Mapped[bool]=mapped_column(default=False); cancelled_at:Mapped[datetime|None]=mapped_column(nullable=True); cancelled_by:Mapped[int|None]=mapped_column(ForeignKey("users.id"),nullable=True); cancellation_reason:Mapped[str|None]=mapped_column(nullable=True); section:Mapped[Section]=relationship(); seat:Mapped[Seat|None]=relationship(); ticket_class:Mapped[TicketClass]=relationship(); order:Mapped[Order]=relationship(back_populates="tickets")
    attendee_user_id:Mapped[int|None]=mapped_column(ForeignKey("users.id"),nullable=True)
    attendee_birth_date:Mapped[date|None]=mapped_column(Date,nullable=True)
    attendee_name:Mapped[str|None]=mapped_column(String(120),nullable=True)
class Scan(Base):
    __tablename__="scans"; id:Mapped[int]=mapped_column(primary_key=True); ticket_id:Mapped[int]=mapped_column(ForeignKey("tickets.id")); operator_id:Mapped[int]=mapped_column(ForeignKey("users.id")); gate:Mapped[str|None]; scanned_at:Mapped[datetime]=mapped_column(default=now); result:Mapped[str]
class AuditLog(Base):
    __tablename__="audit_logs"; id:Mapped[int]=mapped_column(primary_key=True); user_id:Mapped[int|None]=mapped_column(ForeignKey("users.id"),nullable=True); action:Mapped[str]; entity:Mapped[str]; entity_id:Mapped[str]; created_at:Mapped[datetime]=mapped_column(default=now)
