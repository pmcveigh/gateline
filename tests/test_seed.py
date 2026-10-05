from scripts.seed import COMPETITIONS, email_slug


def test_seed_covers_all_requested_clubs_and_stadiums():
    clubs = [club for competition in COMPETITIONS.values() for club, _ in competition]
    venues = {venue for competition in COMPETITIONS.values() for _, venue in competition}

    assert len(clubs) == 36
    assert len(set(clubs)) == 36
    assert len(venues) == 28
    assert {len(clubs) for clubs in COMPETITIONS.values()} == {8, 12, 16}


def test_shared_stadiums_are_reused_by_the_expected_clubs():
    home_venues = {
        club: venue
        for competition in COMPETITIONS.values()
        for club, venue in competition
    }

    assert home_venues["Bangor"] == home_venues["Ards"] == "Clandeboye Park"
    assert home_venues["Cliftonville"] == home_venues["Newington"] == "Solitude"
    assert home_venues["Derry City Women"] == home_venues["Institute"]
    assert email_slug("Queen’s University") == "queen-s-university"
