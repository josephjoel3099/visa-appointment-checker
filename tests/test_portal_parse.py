from pathlib import Path

import pytest

from checker.portal import (
    PortalError,
    Service,
    parse_dates,
    parse_embassies,
    parse_services,
    parse_token,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_embassies_home():
    result = parse_embassies(load("home.html"))
    assert len(result) == 40
    assert result["40"] == "Embassy of the Republic of Estonia in New Delhi"
    assert result["4"].endswith("London")
    assert "" not in result


def test_parse_token():
    assert parse_token(load("home.html")) == "TESTTOKEN"
    with pytest.raises(PortalError):
        parse_token("<html></html>")


def test_parse_services_none():
    assert parse_services(load("services_none.html")) == []


def test_parse_services_several():
    services = parse_services(load("services_several.html"))
    assert [s.name for s in services] == [
        "Long-stay visa (D-visa) application",
        "Short-stay visa (C-visa) application",
        "Residence permit application",
    ]
    assert [s.id for s in services] == ["501", "502", "503"]


def test_parse_services_dedupes_names():
    html = (
        '<select name="broneering[toiming]"><option value=""></option>'
        '<option value="501">Long-stay visa (D-visa) application</option>'
        '<option value="999">Long-stay visa (D-visa) application</option>'
        "</select>"
    )
    assert parse_services(html) == [
        Service(id="501", name="Long-stay visa (D-visa) application")
    ]


def test_parse_services_missing_select_raises():
    with pytest.raises(PortalError):
        parse_services("<html><body>Maintenance</body></html>")


def test_parse_dates_synthetic():
    assert parse_dates(load("after_service_synthetic.html")) == [
        "2026-11-03",
        "2026-11-04",
    ]


def test_parse_dates_none_found():
    assert parse_dates(load("services_none.html")) is None


def test_parse_dates_drops_invalid_dates():
    html = "<p>31.02.2026 2026-13-45 2026-11-03</p>"
    assert parse_dates(html) == ["2026-11-03"]


def test_parse_dates_only_invalid_returns_none():
    assert parse_dates("<p>31.02.2026 2026-13-45</p>") is None


def test_parse_services_kyiv_real_page():
    assert parse_services(load("services_kyiv.html")) == [
        Service("schengeni_viisa", "Schengen visa (C-visa) application"),
        Service("pikaajaline_viisa", "Long-stay visa (D-visa) application"),
        Service("e_residendi_digi_id", "Pick-up of e-resident's digital ID"),
    ]


def test_fixtures_contain_no_live_tokens():
    import re

    for path in FIXTURES.glob("*.html"):
        text = path.read_text(encoding="utf-8")
        for value in re.findall(r'(?:data-token|name="broneering\[_token\]"[^>]*value)="([^"]*)"', text):
            assert value == "TESTTOKEN", (path.name, value[:12])
