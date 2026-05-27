import os
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://broneering.mfa.ee/en/"
TARGET_EMBASSY = "Embassy of the Republic of Estonia in New Delhi"
TARGET_SERVICE = "Long-stay visa (D-visa) application"


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
            "Referer": BASE_URL,
        }
    )

    # ── Step 1: Load main page, grab CSRF token + embassy value ──────────────
    print(f"[1] GET {BASE_URL}")
    resp = session.get(BASE_URL, timeout=20)
    resp.raise_for_status()
    print(f"    → {resp.status_code}  final URL: {resp.url}")

    soup = BeautifulSoup(resp.text, "html.parser")
    form = soup.find("form")
    if not form:
        raise RuntimeError("No <form> found on main page.")

    # Collect all hidden inputs (includes CSRF token)
    payload = {}
    for inp in form.find_all("input"):
        if inp.get("name"):
            payload[inp["name"]] = inp.get("value", "")

    # Find embassy select and resolve New Delhi's value
    embassy_sel = form.find("select", {"name": True})
    if not embassy_sel:
        raise RuntimeError("Embassy <select> not found.")

    embassy_field = embassy_sel["name"]
    embassy_value = None
    for opt in embassy_sel.find_all("option"):
        if TARGET_EMBASSY.lower() in opt.text.strip().lower():
            embassy_value = opt.get("value") or opt.text.strip()
            break
    if not embassy_value:
        raise RuntimeError(f"'{TARGET_EMBASSY}' not found in embassy dropdown.")

    payload[embassy_field] = embassy_value
    print(f"    Embassy field: {embassy_field!r} = {embassy_value!r}")

    # Person count field (text input, default already '1')
    # It's already in payload from the hidden/text inputs scan above.

    # ── CRITICAL: include the 'edasi' (Next) submit button ───────────────────
    # Without this the server doesn't know which button was clicked and returns 404
    payload["edasi"] = ""

    # POST to trailing-slash URL (avoid redirect that loses POST body)
    post_url = resp.url  # use the final redirected URL so session cookies match
    print(f"\n[2] POST {post_url}")
    print(f"    payload keys: {list(payload.keys())}")

    session.headers["Referer"] = post_url
    resp2 = session.post(post_url, data=payload, timeout=20, allow_redirects=True)
    print(f"    → {resp2.status_code}  final URL: {resp2.url}")

    if resp2.status_code == 404 or resp2.url == post_url:
        # If still on same page, the server may want Content-Type: application/x-www-form-urlencoded
        # and the Origin header set
        session.headers["Origin"] = "https://broneering.mfa.ee"
        session.headers["Content-Type"] = "application/x-www-form-urlencoded"
        resp2 = session.post(post_url, data=payload, timeout=20, allow_redirects=True)
        print(f"    retry → {resp2.status_code}  final URL: {resp2.url}")

    resp2.raise_for_status()

    # ── Step 3: Parse services dropdown from step-2 page ─────────────────────
    print(f"\n[3] Parsing step-2 page for services...")
    soup2 = BeautifulSoup(resp2.text, "html.parser")

    all_selects = soup2.find_all("select")
    print(f"    Found {len(all_selects)} <select>(s):")
    for sel in all_selects:
        opts = [o.text.strip() for o in sel.find_all("option") if o.text.strip()]
        print(f"      [{sel.get('name')!r}]: {opts}")

    # Check if we're still on the same page (POST didn't advance)
    if len(all_selects) == 1 and any(
        TARGET_EMBASSY.lower() in o.text.lower()
        for o in all_selects[0].find_all("option")
    ):
        print("\n    ⚠ Still on step-1 page — POST did not advance the form.")
        print(
            "    Page title:",
            soup2.find("title").text if soup2.find("title") else "N/A",
        )
        print("    Dumping raw HTML (first 2000 chars):")
        print(resp2.text[:2000])
        raise RuntimeError("Form submission did not advance to step 2.")

    services = []
    for sel in all_selects:
        opts = [o.text.strip() for o in sel.find_all("option") if o.text.strip()]
        if any(
            "visa" in o.lower() or "application" in o.lower() or "service" in o.lower()
            for o in opts
        ):
            services = opts
            print(f"    → Services from select[{sel.get('name')!r}]")
            break

    if not services:
        # Fallback: all options on page
        services = [o.text.strip() for o in soup2.find_all("option") if o.text.strip()]

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
    print(f"Target: {TARGET_EMBASSY}")
    print(f"Service: {TARGET_SERVICE}")
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
