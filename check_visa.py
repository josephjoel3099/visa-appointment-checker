import os
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

TARGET_EMBASSY = "Embassy of the Republic of Estonia in New Delhi"
TARGET_SERVICE = "Long-stay visa (D-visa) application"
BASE_URL = "https://broneering.mfa.ee/en/"


def get_services_for_embassy():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Capture network requests to find the Turbo endpoint
        turbo_responses = []

        def on_response(response):
            if (
                "broneering" in response.url
                or response.url.endswith("/en/")
                or response.url.endswith("/en")
            ):
                turbo_responses.append((response.url, response.status))

        page.on("response", on_response)

        print(f"[1] Navigating to {BASE_URL}")
        page.goto(BASE_URL, wait_until="networkidle")
        print(f"    URL: {page.url}")

        # Select the embassy — this triggers the Turbo auto-submit
        print(f"[2] Selecting embassy: {TARGET_EMBASSY}")
        page.select_option("select[name='broneering[esindus]']", label=TARGET_EMBASSY)

        # Wait for Turbo to update the DOM
        print(f"[3] Waiting for Turbo to load services dropdown...")
        try:
            # Wait for a new <select> to appear (the services one)
            page.wait_for_function(
                """() => {
                    const selects = document.querySelectorAll('select');
                    return selects.length > 1;
                }""",
                timeout=10000,
            )
            print("    ✓ New dropdown appeared")
        except Exception:
            # Maybe it loads inline — wait for network to settle
            page.wait_for_load_state("networkidle")
            print("    (waited for networkidle)")

        print(f"    Network requests seen: {turbo_responses}")

        # Scrape all selects
        selects = page.query_selector_all("select")
        print(f"[4] Found {len(selects)} <select>(s) after Turbo update:")

        services = []
        for sel in selects:
            name = sel.get_attribute("name")
            options = sel.query_selector_all("option")
            opts = [o.inner_text().strip() for o in options if o.inner_text().strip()]
            print(f"    select[{name!r}]: {opts}")
            if any(
                "visa" in o.lower()
                or "application" in o.lower()
                or "service" in o.lower()
                for o in opts
            ):
                services = opts

        if not services:
            # Also try clicking Next if there's no second dropdown yet
            print("[5] No services dropdown found yet — trying to click Next button...")
            try:
                page.click("button[name='edasi']")
                page.wait_for_load_state("networkidle")
                print(f"    URL after Next: {page.url}")
                selects2 = page.query_selector_all("select")
                print(f"    Found {len(selects2)} <select>(s) after Next:")
                for sel in selects2:
                    name = sel.get_attribute("name")
                    opts = [
                        o.inner_text().strip()
                        for o in sel.query_selector_all("option")
                        if o.inner_text().strip()
                    ]
                    print(f"    select[{name!r}]: {opts}")
                    if any(
                        "visa" in o.lower()
                        or "application" in o.lower()
                        or "service" in o.lower()
                        for o in opts
                    ):
                        services = opts
            except Exception as e:
                print(f"    Could not click Next: {e}")

        if not services:
            all_opts = [
                o.inner_text().strip()
                for o in page.query_selector_all("option")
                if o.inner_text().strip()
            ]
            print(f"    Fallback all options: {all_opts}")
            services = all_opts

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
