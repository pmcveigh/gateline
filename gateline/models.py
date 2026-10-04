from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base

def now(): return datetime.now(timezone.utc)
class Role(str, Enum): ADMIN="admin"; GATE="gate"
class Mode(str, Enum): ASSIGNED="assigned"; GENERAL="general"
class TicketStatus(str, Enum): RESERVED="reserved"; SOLD="sold"; SCANNED="scanned"; CANCELLED="cancelled"; REFUNDED="refunded"; EXPIRED="expired"

class User(Base):
    __tablename__="users"; id:Mapped[int]=mapped_column(primary_key=True); email:Mapped[str]=mapped_column(String(200),unique=True); name:Mapped[str]=mapped_column(String(120)); password_hash:Mapped[str]=mapped_column(String(255)); role:Mapped[str]=mapped_column(String(20)); gate:Mapped[str|None]=mapped_column(String(100),nullable=True)
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
    __tablename__="events"; id:Mapped[int]=mapped_column(primary_key=True); title:Mapped[str]=mapped_column(String(200)); home_team:Mapped[str]; away_team:Mapped[str]; competition:Mapped[str]; venue_id:Mapped[int]=mapped_column(ForeignKey("venues.id")); starts_at:Mapped[datetime]=mapped_column(DateTime(timezone=True)); sales_open:Mapped[datetime]=mapped_column(DateTime(timezone=True)); sales_close:Mapped[datetime]=mapped_column(DateTime(timezone=True)); priority_until:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True); description:Mapped[str]=mapped_column(Text,default=""); published:Mapped[bool]=mapped_column(Boolean,default=False); cancelled:Mapped[bool]=mapped_column(Boolean,default=False); venue:Mapped[Venue]=relationship(); inventories:Mapped[list[EventInventory]]=relationship(cascade="all, delete-orphan"); classes:Mapped[list[TicketClass]]=relationship(cascade="all, delete-orphan")
class EventInventory(Base):
    __tablename__="event_inventory"; id:Mapped[int]=mapped_column(primary_key=True); event_id:Mapped[int]=mapped_column(ForeignKey("events.id")); section_id:Mapped[int]=mapped_column(ForeignKey("sections.id")); capacity:Mapped[int]; held:Mapped[int]=mapped_column(default=0); section:Mapped[Section]=relationship(); __table_args__=(UniqueConstraint("event_id","section_id"),)
class TicketClass(Base):
    __tablename__="ticket_classes"; id:Mapped[int]=mapped_column(primary_key=True); event_id:Mapped[int]=mapped_column(ForeignKey("events.id")); name:Mapped[str]; description:Mapped[str]=mapped_column(default=""); price:Mapped[Decimal]=mapped_column(Numeric(10,2)); minimum:Mapped[int]=mapped_column(default=0); maximum:Mapped[int]=mapped_column(default=10)
class PriorityIdentifier(Base):
    __tablename__="priority_identifiers"; id:Mapped[int]=mapped_column(primary_key=True); code:Mapped[str]=mapped_column(unique=True); maximum:Mapped[int]=mapped_column(default=1); used:Mapped[int]=mapped_column(default=0)
class Voucher(Base):
    __tablename__="vouchers"; id:Mapped[int]=mapped_column(primary_key=True); code:Mapped[str]=mapped_column(unique=True); kind:Mapped[str]; value:Mapped[Decimal]=mapped_column(Numeric(10,2)); starts_at:Mapped[datetime]; expires_at:Mapped[datetime]; maximum_uses:Mapped[int]; uses:Mapped[int]=mapped_column(default=0); event_id:Mapped[int|None]=mapped_column(ForeignKey("events.id"),nullable=True); enabled:Mapped[bool]=mapped_column(default=True)
class Customer(Base):
    __tablename__="customers"; id:Mapped[int]=mapped_column(primary_key=True); full_name:Mapped[str]; email:Mapped[str]; address1:Mapped[str]; address2:Mapped[str]=mapped_column(default=""); city:Mapped[str]; postcode:Mapped[str]; country:Mapped[str]
class Order(Base):
    __tablename__="orders"; id:Mapped[int]=mapped_column(primary_key=True); reference:Mapped[str]=mapped_column(unique=True,index=True); customer_id:Mapped[int]=mapped_column(ForeignKey("customers.id")); event_id:Mapped[int]=mapped_column(ForeignKey("events.id")); subtotal:Mapped[Decimal]=mapped_column(Numeric(10,2)); discount:Mapped[Decimal]=mapped_column(Numeric(10,2),default=0); total:Mapped[Decimal]=mapped_column(Numeric(10,2)); payment_status:Mapped[str]=mapped_column(default="pending"); status:Mapped[str]=mapped_column(default="pending"); created_at:Mapped[datetime]=mapped_column(default=now); customer:Mapped[Customer]=relationship(); event:Mapped[Event]=relationship(); tickets:Mapped[list[Ticket]]=relationship()
class Reservation(Base):
    __tablename__="reservations"; id:Mapped[int]=mapped_column(primary_key=True); token:Mapped[str]=mapped_column(unique=True); event_id:Mapped[int]=mapped_column(ForeignKey("events.id")); section_id:Mapped[int]=mapped_column(ForeignKey("sections.id")); seat_id:Mapped[int|None]=mapped_column(ForeignKey("seats.id"),nullable=True); quantity:Mapped[int]=mapped_column(default=1); expires_at:Mapped[datetime]; completed:Mapped[bool]=mapped_column(default=False); __table_args__=(UniqueConstraint("event_id","seat_id"),)
class Ticket(Base):
    __tablename__="tickets"; id:Mapped[int]=mapped_column(primary_key=True); public_id:Mapped[str]=mapped_column(unique=True,index=True); qr_token:Mapped[str]=mapped_column(unique=True,index=True); order_id:Mapped[int]=mapped_column(ForeignKey("orders.id")); event_id:Mapped[int]=mapped_column(ForeignKey("events.id")); section_id:Mapped[int]=mapped_column(ForeignKey("sections.id")); seat_id:Mapped[int|None]=mapped_column(ForeignKey("seats.id"),nullable=True); ticket_class_id:Mapped[int]=mapped_column(ForeignKey("ticket_classes.id")); price:Mapped[Decimal]=mapped_column(Numeric(10,2)); status:Mapped[str]=mapped_column(default=TicketStatus.SOLD.value); complimentary:Mapped[bool]=mapped_column(default=False); cancelled_at:Mapped[datetime|None]=mapped_column(nullable=True); cancelled_by:Mapped[int|None]=mapped_column(ForeignKey("users.id"),nullable=True); cancellation_reason:Mapped[str|None]=mapped_column(nullable=True); section:Mapped[Section]=relationship(); seat:Mapped[Seat|None]=relationship(); ticket_class:Mapped[TicketClass]=relationship(); order:Mapped[Order]=relationship(back_populates="tickets")
class Scan(Base):
    __tablename__="scans"; id:Mapped[int]=mapped_column(primary_key=True); ticket_id:Mapped[int]=mapped_column(ForeignKey("tickets.id")); operator_id:Mapped[int]=mapped_column(ForeignKey("users.id")); gate:Mapped[str|None]; scanned_at:Mapped[datetime]=mapped_column(default=now); result:Mapped[str]
class AuditLog(Base):
    __tablename__="audit_logs"; id:Mapped[int]=mapped_column(primary_key=True); user_id:Mapped[int|None]=mapped_column(ForeignKey("users.id"),nullable=True); action:Mapped[str]; entity:Mapped[str]; entity_id:Mapped[str]; created_at:Mapped[datetime]=mapped_column(default=now)
