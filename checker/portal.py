"""HTML parsers and constants for the Estonian MFA booking portal."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import date

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://broneering.mfa.ee/en/"
USER_AGENT = (
    "visa-availability-dashboard "
    "(+https://github.com/josephjoel3099/visa-appointment-checker)"
)

_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b|\b(\d{2})\.(\d{2})\.(\d{4})\b")


class PortalError(Exception):
    """Raised when the portal's HTML does not look as expected."""


@dataclass(frozen=True)
class Service:
    id: str
    name: str


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def parse_embassies(html: str) -> dict[str, str]:
    select = _soup(html).select_one('select[name="broneering[esindus]"]')
    if select is None:
        raise PortalError("embassy select not found")
    return {
        opt["value"]: opt.get_text(strip=True)
        for opt in select.find_all("option")
        if opt.get("value")
    }


def parse_token(html: str) -> str:
    field = _soup(html).select_one('input[name="broneering[_token]"]')
    if field is None or not field.get("value"):
        raise PortalError("form token not found")
    return field["value"]


def parse_services(html: str) -> list[Service]:
    select = _soup(html).select_one('select[name="broneering[toiming]"]')
    if select is None:
        raise PortalError("services select not found")
    services: list[Service] = []
    seen: set[str] = set()
    for opt in select.find_all("option"):
        value = opt.get("value")
        name = opt.get_text(strip=True)
        if not value or not name or name in seen:
            continue
        seen.add(name)
        services.append(Service(id=value, name=name))
    return services


def parse_dates(html: str) -> list[str] | None:
    soup = _soup(html)
    for tag in soup(["script", "style"]):
        tag.decompose()
    texts = [soup.get_text(" ")]
    for tag in soup.find_all(True):
        for attr in ("data-date", "data-day", "value"):
            val = tag.get(attr)
            if isinstance(val, str):
                texts.append(val)
    found: set[str] = set()
    for text in texts:
        for m in _DATE_RE.finditer(text):
            if m.group(1):
                y, mo, d = m.group(1), m.group(2), m.group(3)
            else:
                y, mo, d = m.group(6), m.group(5), m.group(4)
            try:
                found.add(date(int(y), int(mo), int(d)).isoformat())
            except ValueError:
                continue
    return sorted(found) or None


@dataclass
class DatesResult:
    dates: list[str] | None
    pages: dict[str, str]


class Portal:
    """HTTP client: fresh session and fresh CSRF token for every call."""

    def __init__(
        self,
        session_factory=requests.Session,
        sleep=time.sleep,
        base_url: str = BASE_URL,
        timeout: float = 15,
        attempts: int = 3,
    ):
        self._session_factory = session_factory
        self._sleep = sleep
        self._base_url = base_url
        self._timeout = timeout
        self._attempts = attempts

    def _new_session(self):
        session = self._session_factory()
        session.headers["User-Agent"] = USER_AGENT
        return session

    def _request(self, session, method: str, **kwargs) -> str:
        accepted = (200,) if method == "GET" else (200, 422)
        send = session.get if method == "GET" else session.post
        last_error = "no attempts made"
        for attempt in range(self._attempts):
            if attempt:
                self._sleep(1.0 * 2 ** (attempt - 1))
            try:
                resp = send(self._base_url, timeout=self._timeout, **kwargs)
            except requests.RequestException as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                continue
            status = resp.status_code
            if status in accepted:
                return resp.text
            if status == 429 or status >= 500:
                last_error = f"HTTP {status}"
                continue
            raise PortalError(f"{method} {self._base_url} returned HTTP {status}")
        raise PortalError(
            f"{method} {self._base_url} failed after {self._attempts} attempts: "
            f"{last_error}"
        )

    def _services_page(self, session, embassy_id: str) -> tuple[str, str, dict[str, str]]:
        home = self._request(session, "GET")
        form = {
            "broneering[esindus]": embassy_id,
            "broneering[isikuteArv]": "1",
            "broneering[_token]": parse_token(home),
        }
        services_html = self._request(session, "POST", data=form)
        return home, services_html, form

    def list_embassies(self) -> dict[str, str]:
        return parse_embassies(self._request(self._new_session(), "GET"))

    def list_services(self, embassy_id: str) -> list[Service]:
        _, services_html, _ = self._services_page(self._new_session(), embassy_id)
        return parse_services(services_html)

    def list_dates(self, embassy_id: str, service_id: str) -> DatesResult:
        session = self._new_session()
        home, services_html, form = self._services_page(session, embassy_id)
        form = {
            **form,
            "broneering[_token]": parse_token(services_html),
            "broneering[toiming]": service_id,
        }
        after = self._request(session, "POST", data=form)
        return DatesResult(
            dates=parse_dates(after),
            pages={"home": home, "services": services_html, "after_service": after},
        )
