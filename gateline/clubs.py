"""Browse directory supplied by the club organiser, independent of ticket inventory."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ClubEntry:
    name: str
    stadium: str
    location: str
    capacity: str = ""
    position: str = ""
    label: str = ""
    aliases: tuple[str, ...] = ()

    @property
    def display_name(self):
        return self.label or self.name

    @property
    def filter_names(self):
        return (self.name, *self.aliases)


LEAGUES = {
    "NIFL Premiership": (
        ClubEntry("Ballymena United", "Ballymena Showgrounds", "Ballymena", "3,600", "9th"),
        ClubEntry("Bangor", "Clandeboye Park", "Bangor", "1,895", "1st (Promoted from NIFL Championship)"),
        ClubEntry("Carrick Rangers", "Loughshore Hotel Arena", "Carrickfergus", "1,500", "11th"),
        ClubEntry("Cliftonville", "Solitude", "Belfast", "3,200", "7th"),
        ClubEntry("Coleraine", "The Showgrounds", "Coleraine", "2,496", "6th"),
        ClubEntry("Crusaders", "Seaview", "Belfast", "3,383", "5th"),
        ClubEntry("Dungannon Swifts", "Stangmore Park", "Dungannon", "1,500", "4th"),
        ClubEntry("Glentoran", "The Oval", "Belfast", "6,050", "3rd"),
        ClubEntry("Larne", "Inver Park", "Larne", "3,250", "2nd"),
        ClubEntry("Limavady United", "Limavady Showgrounds", "Limavady"),
        ClubEntry("Linfield", "Windsor Park", "Belfast", "18,614", "1st (League winners)"),
        ClubEntry("Portadown", "Shamrock Park", "Portadown", "2,770", "8th"),
    ),
    "NIFL Championship": (
        ClubEntry("Annagh United", "BMG Arena", "Portadown", "1,250 (100 seated)"),
        ClubEntry("Ards", "Clandeboye Park", "Bangor", "2,000 (500 seated)"),
        ClubEntry("Armagh City", "Holm Park", "Armagh", "2,000 (500 seated)"),
        ClubEntry("Ballinamallard United", "Ferney Park", "Ballinamallard", "2,000 (250 seated)"),
        ClubEntry("Dundela", "Wilgar Park", "Belfast", "2,500"),
        ClubEntry("Glenavon", "Mourneview Park", "Lurgan", "3,302 (all seated)"),
        ClubEntry("Harland & Wolff Welders", "Blanchflower Stadium", "Belfast", "2,000"),
        ClubEntry("Institute", "Ryan McBride Brandywell Stadium", "Derry", "3,700"),
        ClubEntry("Loughgall", "Lakeview Park", "Loughgall", "1,300 (800 seated)"),
        ClubEntry("Moyola Park", "Mill Meadow", "Castledawson", "2,000"),
        ClubEntry("Newington", "Solitude", "Belfast", "3,054"),
        ClubEntry("Newry City", "Newry Showgrounds", "Newry", "2,809 (831 seated)"),
        ClubEntry("Queen's University", "Blanchflower Stadium", "Belfast", "2,000", aliases=("Queen’s University",)),
        ClubEntry("Rathfriland Rangers", "Iveagh Park", "Rathfriland", "1,000"),
        ClubEntry("Strabane Athletic", "Limavady Showgrounds", "Limavady", "1,500 (274 seated)"),
        ClubEntry("Warrenpoint Town", "Milltown", "Warrenpoint", "1,450"),
    ),
    "NCL Premier": (
        ClubEntry("Ballyclare Comrades", "Dixon Park", "Ballyclare"),
        ClubEntry("Ballymacash Rangers", "The Bluebell Stadium", "Lisburn"),
        ClubEntry("Banbridge Town", "Crystal Park", "Banbridge"),
        ClubEntry("Coagh United", "Hagan Park", "Coagh"),
        ClubEntry("Dergview", "Darragh Park", "Castlederg"),
        ClubEntry("Dollingstown", "Planters Park", "Dollingstown"),
        ClubEntry("Knockbreda", "Breda Park", "Belfast"),
        ClubEntry("Lisburn Distillery", "New Grosvenor Stadium", "Lisburn"),
        ClubEntry("Oxford Sunnyside", "Knockramer Park", "Lurgan"),
        ClubEntry("Portstewart", "Mullaghacall", "Portstewart"),
        ClubEntry("Rosario Y.C.", "Ulidia Playing Fields", "Belfast"),
        ClubEntry("St James' Swifts", "Donegal Celtic Park", "Belfast"),
    ),
    "NIFL Women's": (
        ClubEntry("Cliftonville Ladies", "Solitude", "Belfast (Oldpark)", "2,530", label="Cliftonville"),
        ClubEntry("Crusaders Strikers", "Seaview", "Belfast (Shore Road)", "3,383"),
        ClubEntry("Derry City Women", "Brandywell Stadium", "Derry", "6,300", label="Derry City"),
        ClubEntry("Glentoran Women", "Blanchflower Stadium", "Belfast (Sydenham)", "1,100", label="Glentoran"),
        ClubEntry("Larne Women", "Inver Park", "Larne", "3,250", label="Larne"),
        ClubEntry("Linfield Women", "New Midgley Park", "Belfast (Boucher Road)", "n/a", label="Linfield"),
        ClubEntry("Lisburn Ladies", "Bluebell Stadium", "Lisburn", "1,280"),
        ClubEntry("Lisburn Rangers", "Crewe Park", "Lisburn", "n/a"),
    ),
}


def find_club(name):
    return next((club for clubs in LEAGUES.values() for club in clubs if name in club.filter_names), None)


def build_club_groups(event_clubs):
    groups = list(LEAGUES.items())
    known = {name for clubs in LEAGUES.values() for club in clubs for name in club.filter_names}
    extra = sorted(set(event_clubs) - known)
    if extra:
        groups.append(("Other clubs", tuple(ClubEntry(name, "", "") for name in extra)))
    return groups
