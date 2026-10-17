import pytest

from checker.portal import Portal

pytestmark = pytest.mark.live


def test_live_list_embassies():
    embassies = Portal().list_embassies()
    assert len(embassies) >= 30
    assert "40" in embassies


def test_live_list_services():
    assert isinstance(Portal().list_services("40"), list)
