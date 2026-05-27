import os
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

TARGET_EMBASSY = "Embassy of the Republic of Estonia in New Delhi"
TARGET_SERVICE = "Long-stay visa (D-visa) application"
BASE_URL = "https://broneering.mfa.ee/en/"

# The services dropdown has this name (confirmed from debug run)
SERVICES_SELECT_NAME = "broneering[toiming]"
EMBASSY_SELECT_NAME = "broneering[esindus]"


def get_services_for_embassy():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        print(f"[1] Navigating to {BASE_URL}")
        page.goto(BASE_URL, wait_until="networkidle")

        # Select the embassy — triggers Turbo auto-submit
        print(f"[2] Selecting: {TARGET_EMBASSY}")
        page.select_option(
            f"select[name='{EMBASSY_SELECT_NAME}']", label=TARGET_EMBASSY
        )

        # Wait for the services dropdown to appear
        print(f"[3] Waiting for services dropdown...")
        page.wait_for_selector(f"select[name='{SERVICES_SELECT_NAME}']", timeout=10000)
        print(f"    ✓ Services dropdown appeared")

        # Read the options
        options = page.query_selector_all(
            f"select[name='{SERVICES_SELECT_NAME}'] option"
        )
        services = [o.inner_text().strip() for o in options if o.inner_text().strip()]

        browser.close()
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
    print(f"Target:  {TARGET_EMBASSY}")
    print(f"Service: {TARGET_SERVICE}")
    print("=" * 60)

    try:
        services = get_services_for_embassy()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)

    print(f"\nServices currently available for New Delhi ({len(services)}):")
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
        print(f"\n⏳ D-visa not yet available. Will check again next hour.")


if __name__ == "__main__":
    main()
