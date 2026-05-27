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


def get_services_for_embassy():
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
    )

    # Step 1: Load the main page to get the form + session cookie
    resp = session.get(BASE_URL, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # Find the embassy select and get the value for New Delhi
    embassy_select = soup.find("select", {"name": "unit"}) or soup.find("select")
    if not embassy_select:
        raise RuntimeError("Could not find embassy dropdown on the page.")

    embassy_value = None
    for option in embassy_select.find_all("option"):
        if TARGET_EMBASSY.lower() in option.text.strip().lower():
            embassy_value = option.get("value", option.text.strip())
            break

    if embassy_value is None:
        raise RuntimeError(f"Could not find '{TARGET_EMBASSY}' in dropdown options.")

    print(f"Found embassy option: '{TARGET_EMBASSY}' (value={embassy_value})")

    # Step 2: POST the form selecting New Delhi to get the services dropdown
    # Find the form action
    form = soup.find("form")
    form_action = BASE_URL
    if form and form.get("action"):
        action = form["action"]
        if action.startswith("http"):
            form_action = action
        else:
            form_action = "https://broneering.mfa.ee" + action

    # Collect all hidden inputs
    payload = {}
    for hidden in soup.find_all("input", {"type": "hidden"}):
        if hidden.get("name"):
            payload[hidden["name"]] = hidden.get("value", "")

    # Add the embassy selection
    payload["unit"] = embassy_value

    # Also look for person count field
    persons_select = soup.find("select", {"name": "persons"})
    if persons_select:
        first_option = persons_select.find("option")
        if first_option:
            payload["persons"] = first_option.get("value", "1")
    else:
        payload["persons"] = "1"

    resp2 = session.post(form_action, data=payload, timeout=15)
    resp2.raise_for_status()

    soup2 = BeautifulSoup(resp2.text, "html.parser")

    # Step 3: Look for the services dropdown
    services = []
    for select in soup2.find_all("select"):
        options = [o.text.strip() for o in select.find_all("option") if o.text.strip()]
        # Heuristic: the services select will contain visa-related text
        if any(
            "visa" in o.lower() or "service" in o.lower() or "application" in o.lower()
            for o in options
        ):
            services = options
            break

    # Fallback: grab all option texts from the page
    if not services:
        all_options = [
            o.text.strip() for o in soup2.find_all("option") if o.text.strip()
        ]
        services = all_options

    return services


def send_email_notification(services_found):
    sender = os.environ["GMAIL_SENDER"]
    recipient = os.environ["GMAIL_RECIPIENT"]
    app_password = os.environ["GMAIL_APP_PASSWORD"]

    subject = "🇪🇪 Estonia D-Visa Slot Available in New Delhi!"
    body = f"""Good news! The Estonia visa booking portal now shows the D-visa option for New Delhi.

Service detected: "{TARGET_SERVICE}"

Book your appointment now:
{BASE_URL}

--- All services currently listed for New Delhi ---
{chr(10).join(f"  • {s}" for s in services_found)}

---
This is an automated alert from your Estonia Visa Checker.
"""

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
    print(f"Checking Estonia visa portal for D-visa availability in New Delhi...")

    try:
        services = get_services_for_embassy()
    except Exception as e:
        print(f"❌ Error fetching services: {e}")
        sys.exit(1)

    print(f"\nServices found ({len(services)}):")
    for s in services:
        print(f"  • {s}")

    # Check if D-visa option exists
    dvisa_found = any(TARGET_SERVICE.lower() in s.lower() for s in services)

    if dvisa_found:
        print(f"\n🎉 D-visa option IS available! Sending email notification...")
        try:
            send_email_notification(services)
        except Exception as e:
            print(f"❌ Failed to send email: {e}")
            sys.exit(1)
    else:
        print(f"\n⏳ D-visa option not yet available. No notification sent.")


if __name__ == "__main__":
    main()
