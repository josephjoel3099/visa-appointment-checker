# 🇪🇪 Estonia D-Visa Checker

Automatically checks the [Estonia MFA booking portal](https://broneering.mfa.ee/en/) every hour for the **Long-stay visa (D-visa) application** option at the **Embassy of the Republic of Estonia in New Delhi**, and sends you a Gmail notification the moment it appears.

---

## Setup Instructions

### 1. Fork / Push this repo to GitHub

Create a new GitHub repository and push this code to it.

### 2. Get a Gmail App Password

You need a **Gmail App Password** (not your regular Gmail password):

1. Go to your Google Account → **Security**
2. Enable **2-Step Verification** if not already on
3. Go to **Security → App passwords**
4. Create a new app password (name it "Estonia Visa Checker")
5. Copy the 16-character password shown

> ⚠️ App passwords only work if 2FA is enabled on your Google account.

### 3. Add GitHub Secrets

In your GitHub repo, go to **Settings → Secrets and variables → Actions → New repository secret** and add these three secrets:

| Secret Name         | Value                                      |
|---------------------|--------------------------------------------|
| `GMAIL_SENDER`      | Your Gmail address (e.g. `you@gmail.com`)  |
| `GMAIL_RECIPIENT`   | Email to receive alerts (can be the same) |
| `GMAIL_APP_PASSWORD`| The 16-char app password from Step 2       |

### 4. Enable GitHub Actions

Go to the **Actions** tab in your repo and enable workflows if prompted.

### 5. Test it manually

Go to **Actions → Estonia D-Visa Checker → Run workflow** to trigger a manual run and confirm it works.

---

## How It Works

- GitHub Actions runs the checker **every hour** via a cron schedule
- The script visits the booking portal, selects **New Delhi**, and reads the available services
- If **"Long-stay visa (D-visa) application"** appears in the list, it sends you an email immediately
- If not available, it logs the current services and exits quietly

---

## Files

```
.github/
  workflows/
    check_visa.yml   ← GitHub Actions schedule & job
check_visa.py        ← The checker script
README.md
```
