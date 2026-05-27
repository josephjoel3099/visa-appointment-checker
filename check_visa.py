import os
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://broneering.mfa.ee/en"
TARGET_EMBASSY = "Embassy of the Republic of Estonia in New Delhi"
TARGET_SERVICE = "Long-stay visa (D-visa) application"
EMBASSY_VALUE = "40"  # hardcoded — confirmed from previous run


def get_services_for_embassy():
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )

    # ── Step 1: Load main page ────────────────────────────────────────────────
    print(f"[1] GET {BASE_URL}")
    resp = session.get(BASE_URL, timeout=20)
    resp.raise_for_status()
    print(f"    → {resp.status_code}  final URL: {resp.url}")

    soup = BeautifulSoup(resp.text, "html.parser")

    # Print raw form details so we know exactly what to submit
    form = soup.find("form")
    if form:
        print(f"    Form action={form.get('action')!r}  method={form.get('method')!r}")
        for inp in form.find_all(["input", "select", "button"]):
            print(
                f"      <{inp.name}> name={inp.get('name')!r} type={inp.get('type')!r} value={inp.get('value')!r}"
            )
    else:
        print("    ⚠ No <form> found on page!")
        print("    RAW HTML (first 3000 chars):")
        print(resp.text[:3000])
        raise RuntimeError("No form on main page")

    # ── Build payload ─────────────────────────────────────────────────────────
    payload = {}
    for inp in form.find_all("input"):
        if inp.get("name"):
            payload[inp["name"]] = inp.get("value", "")

    # Embassy select
    embassy_sel = form.find("select", {"name": True})
    if embassy_sel:
        payload[embassy_sel["name"]] = EMBASSY_VALUE
    else:
        payload["unit"] = EMBASSY_VALUE

    # Persons select — pick first valid option value
    for sel in form.find_all("select"):
        if sel.get("name") and sel.get("name") != (
            embassy_sel.get("name") if embassy_sel else "unit"
        ):
            first_opt = sel.find("option", value=True)
            payload[sel["name"]] = first_opt["value"] if first_opt else "1"

    # ── Determine submit URL ──────────────────────────────────────────────────
    action = form.get("action", "")
    method = form.get("method", "get").lower()

    if not action or action in ("/en", "/en/", "en"):
        # Try common next-step paths
        # The submit button text says "To the next page" — try /en with POST
        form_url = "https://broneering.mfa.ee/en"
    elif action.startswith("http"):
        form_url = action
    else:
        form_url = "https://broneering.mfa.ee" + action

    print(f"\n[2] {method.upper()} {form_url}")
    print(f"    payload: {payload}")

    if method == "post":
        resp2 = session.post(form_url, data=payload, timeout=20)
    else:
        resp2 = session.get(form_url, params=payload, timeout=20)

    print(f"    → {resp2.status_code}  final URL: {resp2.url}")

    if not resp2.ok:
        # Try the other method as fallback
        alt_method = "get" if method == "post" else "post"
        print(f"    ⚠ Got {resp2.status_code}, trying {alt_method.upper()} instead...")
        if alt_method == "post":
            resp2 = session.post(form_url, data=payload, timeout=20)
        else:
            resp2 = session.get(form_url, params=payload, timeout=20)
        print(f"    → {resp2.status_code}  final URL: {resp2.url}")
        resp2.raise_for_status()

    # ── Step 3: Parse services dropdown ──────────────────────────────────────
    print(f"\n[3] Parsing services page...")
    soup2 = BeautifulSoup(resp2.text, "html.parser")

    # Print ALL selects
    all_selects = soup2.find_all("select")
    print(f"    Found {len(all_selects)} <select>(s):")
    for sel in all_selects:
        opts = [o.text.strip() for o in sel.find_all("option") if o.text.strip()]
        print(f"      select[{sel.get('name')!r}]: {opts}")

    # Also print any forms on this page
    for f2 in soup2.find_all("form"):
        print(f"    Form2 action={f2.get('action')!r} method={f2.get('method')!r}")

    services = []
    for sel in all_selects:
        opts = [o.text.strip() for o in sel.find_all("option") if o.text.strip()]
        if any(
            "visa" in o.lower() or "application" in o.lower() or "service" in o.lower()
            for o in opts
        ):
            services = opts
            break

    if not services:
        print("    No service-like dropdown found. All page options:")
        services = [o.text.strip() for o in soup2.find_all("option") if o.text.strip()]
        print(f"    {services}")

    return services


def send_email_notification(services_found):
    sender = os.environ["GMAIL_SENDER"]
    recipient = os.environ["GMAIL_RECIPIENT"]
    app_password = os.environ["GMAIL_APP_PASSWORD"]

    subject = "🇪🇪 Estonia D-Visa Now Available in New Delhi!"
    body = (
        "Good news!\n\n"
        "The Estonia MFA booking portal now lists the D-visa option for New Delhi:\n\n"
        f'  "{TARGET_SERVICE}"\n\n'
        f"Book your appointment here:\n{BASE_URL}\n\n"
        "--- All services currently listed for New Delhi ---\n"
        + "\n".join(f"  • {s}" for s in services_found)
        + "\n\n---\nSent by your Estonia Visa Checker (GitHub Actions).\n"
    )

    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, app_password)
        server.sendmail(sender, recipient, msg.as_string())

    print("✅ Email notification sent!")


def main():
    print("=" * 60)
    print("Estonia D-Visa Availability Checker")
    print(f"Embassy value: {EMBASSY_VALUE} ({TARGET_EMBASSY})")
    print("=" * 60)

    try:
        services = get_services_for_embassy()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)

    print(f"\nServices found ({len(services)}):")
    for s in services:
        print(f"  • {s}")

    dvisa_found = any(TARGET_SERVICE.lower() in s.lower() for s in services)

    if dvisa_found:
        print(f"\n🎉 D-visa IS available! Sending email...")
        try:
            send_email_notification(services)
        except Exception as e:
            print(f"❌ Email failed: {e}")
            sys.exit(1)
    else:
        print(f"\n⏳ D-visa not yet available.")


if __name__ == "__main__":
    main()
