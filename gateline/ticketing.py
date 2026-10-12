"""Club ticket menus and shared pricing/eligibility rules."""

from datetime import date, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal, InvalidOperation
import hashlib, json, re, unicodedata
from datetime import datetime
from .clubs import LEAGUES
from sqlalchemy import func, select
from .models import AuditLog, ClubPricing, Event, TicketClass


CLUB_TICKETS = {
    "Glentoran": (
        ("Grandstand Upper", "18", "Adult admission"),
        ("Grandstand Lower", "15", "Adult admission"),
        ("Sydenham End", "15", "Adult admission"),
        ("Concession", "8", "Eligible concessions"),
        ("Under 11", "1", "Must attend with a paying adult in this booking"),
        ("VIP", "70", "Adults only; £50 with a valid season-ticket number"),
    ),
    "Linfield": (
        ("South Stand Half Way Line", "18", "Adult admission"),
        ("General Admission", "15", "Adult admission"),
        ("Concession", "8", "Eligible concessions"),
        ("Under 11", "2", "Must attend with a paying adult in this booking"),
    ),
}
ADULT_NAMES = {"Adult", "General Admission", "Grandstand Upper", "Grandstand Lower", "Sydenham End", "South Stand Half Way Line", "VIP"}
VIP_MIN_AGE = 18


def is_adult(ticket_class):
    if ticket_class.name.casefold() in ("concession","child","under 11"): return False
    if ticket_class.name in ("Adult","VIP"): return True
    if ticket_class.adult_admission is not None: return ticket_class.adult_admission
    return ticket_class.name in ADULT_NAMES or ticket_class.name.lower().startswith("adult ")


def minimum_adult_price(event):
    prices = [tc.price for tc in offered_classes(event) if tc.audience=='home' and is_adult(tc) and tc.maximum > 0]
    return min(prices) if prices else None


def canonical_club(name):
    key=name.replace("’","'").strip().casefold()
    return next((entry for clubs in LEAGUES.values() for entry in clubs if any(alias.replace("’","'").casefold()==key for alias in entry.filter_names)),None)


def club_key(name):
    entry=canonical_club(name)
    return (entry.name if entry else name.strip()).casefold()


def ticket_prefix(name):
    entry=canonical_club(name)
    canonical=entry.name if entry else name.strip()
    ascii_name=unicodedata.normalize("NFKD",canonical.replace("’","").replace("'","")).encode("ascii","ignore").decode().upper()
    prefix=re.sub(r"[^A-Z0-9]+","-",ascii_name).strip("-")
    if entry: return prefix
    # Distinguish unknown club names when punctuation removal or truncation
    # would otherwise produce the same readable prefix.
    digest=hashlib.sha256(club_key(name).encode()).hexdigest()[:10].upper()
    return f"{prefix[:32] or 'CLUB'}-{digest}"


def offered_classes(event):
    return [tc for tc in event.classes if tc.enabled]


def legacy_generic(tc):
    return (tc.name,tc.description,tc.price) in (
        ("Adult","Standard admission",Decimal("15")),
        ("Child","Under 16",Decimal("5")),
    )


LEGACY_SEED_MENU={
    ("Adult","Standard admission",Decimal("15")),
    ("Concession","Eligible concessions",Decimal("10")),
    ("Child","Under 16",Decimal("5")),
}


def has_seed_defaults(classes):
    return LEGACY_SEED_MENU.issubset({(tc.name,tc.description,tc.price) for tc in classes})


def is_generic_seed_menu(classes):
    return {(tc.name,tc.description,tc.price) for tc in classes}==LEGACY_SEED_MENU


def menu_for_club(db, name):
    return initialise_club_pricing(db,name)


def initialise_club_pricing(db, name):
    key=club_key(name)
    pricing=db.get(ClubPricing,key)
    defaults={"Adult":{"name":"Adult","price":"15","description":"Adult admission","adult":True},"Concession":{"name":"Concession","price":"8","description":"Under 16, over 65 or disability concession","adult":False}}
    if pricing:
        menu=json.loads(pricing.menu_json)
        if not pricing.portal_defaults_applied:
            edited=db.scalar(select(AuditLog.id).where(AuditLog.action=="club.pricing_updated",AuditLog.entity_id==key))
            if not edited:
                existing={item["name"] for item in menu}
                menu.extend(item for title,item in defaults.items() if title not in existing)
            pricing.menu_json=json.dumps(menu);pricing.portal_defaults_applied=True
        return menu
    entry=canonical_club(name)
    aliases=entry.filter_names if entry else (name.strip(),)
    events=db.scalars(select(Event).where(func.lower(Event.home_team).in_([alias.casefold() for alias in aliases])).order_by(Event.starts_at.desc(),Event.id.desc())).all()
    source=next((event for event in events if offered_classes(event)),None)
    bespoke=next((types for club,types in CLUB_TICKETS.items() if club_key(club)==key),())
    menu=dict(defaults)
    for title,price,description in bespoke:
        menu[title]={"name":title,"price":price,"description":description,"adult":title in ADULT_NAMES}
    if source and not is_generic_seed_menu(offered_classes(source)):
        for tc in source.classes:
            if not tc.enabled or tc.audience!='home' or (has_seed_defaults(source.classes) and legacy_generic(tc)): continue
            # Preserve genuinely configured prices and extra club-specific types.
            if bespoke and has_seed_defaults(source.classes) and (tc.name,tc.description,tc.price)==("Concession","Eligible concessions",Decimal("10")): continue
            menu[tc.name]={"name":tc.name,"price":str(tc.price),"description":tc.description,"adult":is_adult(tc),"concession_under":tc.concession_under,"concession_over":tc.concession_over}
    values=list(menu.values())
    db.add(ClubPricing(club_name=key,menu_json=json.dumps(values),portal_defaults_applied=True));db.flush()
    return values


def configure_club_tickets(db, event):
    """Start with club defaults, then respect the club's saved menu."""
    menu=initialise_club_pricing(db,event.home_team)
    existing={tc.name:tc for tc in event.classes if tc.audience=='home'}
    seeded=has_seed_defaults(existing.values())
    for entry in menu:
        if entry["name"] not in existing:
            db.add(TicketClass(event_id=event.id,name=entry["name"],price=Decimal(entry["price"]),description=entry["description"],adult_admission=entry["adult"],concession_under=entry.get("concession_under",16),concession_over=entry.get("concession_over",65),minimum=0,maximum=10))
        else:
            tc=existing[entry["name"]];tc.enabled=True
            if tc.adult_admission is None: tc.adult_admission=entry["adult"]
            if seeded: tc.price=Decimal(entry["price"])
    for tc in existing.values():
        if legacy_generic(tc) and tc.name not in {entry["name"] for entry in menu}: tc.enabled=False
    db.flush();db.expire(event,["classes"])


def upgrade_club_tickets(db):
    for clubs in LEAGUES.values():
        for club in clubs: initialise_club_pricing(db,club.name)
    for event in db.scalars(select(Event).order_by(Event.starts_at.desc(),Event.id.desc())).all():
        configure_club_tickets(db,event)
    db.commit()


def save_club_pricing(db, name, names, prices, descriptions, categories, concession_under=None, concession_over=None):
    if not (len(names)==len(prices)==len(descriptions)==len(categories)):
        raise ValueError("Check each ticket type and price")
    menu=[];seen=set()
    if concession_under is not None and (len(concession_under)!=len(names) or len(concession_over or [])!=len(names)): raise ValueError("Check concession age limits")
    for index,(title,raw_price,description,category) in enumerate(zip(names,prices,descriptions,categories)):
        title=title.strip();raw_price=raw_price.strip()
        title={"adult":"Adult","concession":"Concession","child":"Child","under 11":"Under 11","vip":"VIP"}.get(title.casefold(),title)
        if not title and not raw_price and not description.strip(): continue
        if not title or len(title)>100 or title.casefold() in seen or category not in ("adult","other"):
            raise ValueError("Each ticket type needs a unique name and admission category")
        try: price=Decimal(raw_price)
        except InvalidOperation: raise ValueError(f"Enter a price for {title}")
        if not price.is_finite() or price<0 or price>Decimal("999999.99") or price.quantize(Decimal("0.01"))!=price:
            raise ValueError("Prices must be non-negative amounts with at most two decimal places")
        seen.add(title.casefold())
        try: under=int(concession_under[index] or 16) if concession_under is not None else 16;over=int(concession_over[index] or 65) if concession_over is not None else 65
        except ValueError: raise ValueError("Enter whole numbers for concession ages")
        if not 0<=under<=over<=120: raise ValueError("Concession ages must be between 0 and 120, with the lower limit first")
        menu.append({"name":title,"price":str(price),"description":description.strip(),"adult":title=="VIP" or (category=="adult" and title not in ("Concession","Child","Under 11")),"concession_under":under,"concession_over":over})
    key=club_key(name)
    if not key or len(key)>150: raise ValueError("Enter a club name of at most 150 characters")
    pricing=db.get(ClubPricing,key)
    if pricing: pricing.menu_json=json.dumps(menu);pricing.portal_defaults_applied=True
    else: db.add(ClubPricing(club_name=key,menu_json=json.dumps(menu),portal_defaults_applied=True))
    # Keep class IDs and past tickets, while making the current club menu available
    # on future fixtures. Removed types remain as historical records.
    now=datetime.now(timezone.utc)
    for event in db.scalars(select(Event).where(Event.starts_at>now)).all():
        if club_key(event.home_team)!=key: continue
        existing={tc.name:tc for tc in event.classes if tc.audience=='home'}
        for tc in existing.values(): tc.enabled=tc.name in {entry["name"] for entry in menu}
        for entry in menu:
            tc=existing.get(entry["name"])
            if tc:
                tc.price=Decimal(entry["price"]);tc.description=entry["description"];tc.adult_admission=entry["adult"];tc.concession_under=entry["concession_under"];tc.concession_over=entry["concession_over"]
            else:
                db.add(TicketClass(event_id=event.id,name=entry["name"],price=Decimal(entry["price"]),description=entry["description"],adult_admission=entry["adult"],concession_under=entry["concession_under"],concession_over=entry["concession_over"]))
        db.flush();db.expire(event,["classes"])
    db.commit()

def selected_classes(event, selection, quantity):
    classes = {tc.id: tc for tc in offered_classes(event)}
    lines = []
    for class_id, count in selection.items():
        try:
            tc = classes.get(int(class_id))
        except (TypeError, ValueError):
            raise ValueError("Invalid ticket class")
        if not tc or not isinstance(count, int) or isinstance(count, bool) or count <= 0:
            raise ValueError("Invalid ticket selection")
        if count < tc.minimum or count > tc.maximum:
            raise ValueError("Ticket class quantity limit exceeded")
        lines.append((tc, count))
    if not lines or sum(count for _, count in lines) != quantity:
        raise ValueError("Ticket quantities must match the reservation")
    if any(tc.name == "Under 11" for tc, _ in lines) and not any(is_adult(tc) and tc.price > 0 for tc, _ in lines):
        raise ValueError("Under 11 tickets require a paying adult ticket in the same booking")
    return lines


def validate_vip_ages(event, lines, birth_dates):
    count = sum(qty for tc, qty in lines if tc.name == "VIP")
    if len(birth_dates) != count:
        raise ValueError("Enter a date of birth for each VIP attendee")
    kick_off = event.starts_at
    if kick_off.tzinfo is None: kick_off = kick_off.replace(tzinfo=timezone.utc)
    match_day = kick_off.astimezone(ZoneInfo("Europe/London")).date()
    for raw in birth_dates:
        try:
            born = date.fromisoformat(raw)
        except (TypeError, ValueError):
            raise ValueError("Enter a valid VIP attendee date of birth")
        age = match_day.year - born.year - ((match_day.month, match_day.day) < (born.month, born.day))
        if born > match_day or age < VIP_MIN_AGE:
            raise ValueError(f"VIP attendees must be aged {VIP_MIN_AGE} or above on the match date")
