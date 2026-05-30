# Asma Essaedi — MVP

> AI-Powered Personal Stylist · Flask · SQLite · Vanilla JS

---

## Quick Start

```bash
# 1. Create a virtual environment
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the app (auto-creates DB on first launch)
python app.py
```

Open **http://localhost:5000** in your browser.

For the AI try-on preview, also set:

```bash
export OPENAI_API_KEY="sk-..."
```

---

## File Structure

```
stylist/
├── app.py                    # Flask application (all routes + DB logic)
├── requirements.txt
├── instance/
│   └── stylist.db            # SQLite database (auto-created)
├── static/
│   ├── css/style.css         # All styles
│   ├── js/main.js            # Client-side JS
│   └── uploads/              # User-uploaded clothing images
└── templates/
    ├── base.html             # Layout shell
    ├── index.html            # Landing page
    ├── login.html
    ├── signup.html
    ├── dashboard.html        # Main stylist dashboard
    └── add_item.html         # Wardrobe upload form
```

---

## Next Phase: OpenAI Integration

The app now includes an AI try-on preview flow:

- Select wardrobe items from the dashboard
- Upload a full-body user photo
- Generate a styling preview with OpenAI image generation

The current random outfit picker in `generate_outfit()` is still a simple MVP.

To enable AI preview generation, install dependencies and set:

```python
export OPENAI_API_KEY="sk-..."
```

---

## Stripe Integration

The app now includes:

- `POST /api/upgrade-intent` to create a Stripe Checkout Session
- `POST /stripe/webhook` to mark users as `pro` after payment succeeds

Set your Stripe recurring price to `$20/month` and use that price ID in `STRIPE_PRICE_ID`.

### Stripe Setup

```bash
export SECRET_KEY="change-me"
export STRIPE_SECRET_KEY="sk_test_..."
export STRIPE_PRICE_ID="price_..."
export STRIPE_WEBHOOK_SECRET="whsec_..."
export APP_BASE_URL="http://127.0.0.1:5000"
```

### Password Reset Email Setup

Forgot-password links are sent by email through SMTP. For Gmail, use a Google App Password rather than your normal Gmail password.

1. In your Google account, turn on 2-Step Verification.
2. Go to **Google Account > Security > App passwords**.
3. Create an app password for this Flask app.
4. Put the app password in `.env` locally or in your Render environment variables.

Local `.env` example for Gmail:

```bash
APP_BASE_URL="http://127.0.0.1:5000"
GMAIL_ADDRESS="youraddress@gmail.com"
GMAIL_APP_PASSWORD="your-16-character-google-app-password"
MAIL_FROM_NAME="Asma Essaedi"
```

The app automatically uses `smtp.gmail.com:587` when `GMAIL_ADDRESS` ends with `@gmail.com`. You can also use the generic SMTP variables below for Gmail or another provider:

```bash
export SMTP_HOST="smtp.gmail.com"
export SMTP_PORT="587"
export SMTP_USERNAME="youraddress@gmail.com"
export SMTP_PASSWORD="your-16-character-google-app-password"
export MAIL_FROM="youraddress@gmail.com"
export MAIL_FROM_NAME="Asma Essaedi"
```

Use the Stripe CLI to forward webhook events locally:

```bash
stripe listen --forward-to http://127.0.0.1:5000/stripe/webhook
```

Copy the webhook signing secret from the Stripe CLI output into `STRIPE_WEBHOOK_SECRET`.

---

## Environment Variables (Production)

| Variable            | Description                          |
|---------------------|--------------------------------------|
| `SECRET_KEY`        | Flask session secret (required)      |
| `OPENAI_API_KEY`    | OpenAI key for AI styling (Phase 2)  |
| `STRIPE_SECRET_KEY` | Stripe secret key                    |
| `STRIPE_PRICE_ID`   | Stripe recurring monthly price ID    |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook signing secret   |
| `APP_BASE_URL`      | Public base URL for Stripe redirects |
| `SMTP_HOST`         | SMTP server for password reset emails |
| `SMTP_PORT`         | SMTP port, defaults to `587` |
| `SMTP_USERNAME`     | SMTP username |
| `SMTP_PASSWORD`     | SMTP password |
| `SMTP_USE_SSL`      | Set to `true` for SMTP SSL, optional |
| `MAIL_FROM`         | Sender email address |
| `MAIL_FROM_NAME`    | Sender display name, optional |
| `GMAIL_ADDRESS`     | Gmail sender address, alternative to `SMTP_USERNAME` |
| `GMAIL_APP_PASSWORD`| Gmail app password, alternative to `SMTP_PASSWORD` |

---

## Deploying To Render

This project now includes [render.yaml](/Users/asmaessaedi/Documents/New%20project/styling_ai_fixed/render.yaml) for Render.

Use these settings if you create the service manually:

- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn app:app`

In Render, set these environment variables:

- `DATA_DIR=/var/data`
- `APP_BASE_URL=https://your-domain.com`
- `OPENAI_API_KEY=...`
- `STRIPE_SECRET_KEY=...`
- `STRIPE_PRICE_ID=...`
- `STRIPE_WEBHOOK_SECRET=...`
- `SMTP_HOST=...`
- `SMTP_USERNAME=...`
- `SMTP_PASSWORD=...`
- `MAIL_FROM=...`
- Or use `GMAIL_ADDRESS=...` and `GMAIL_APP_PASSWORD=...` for Gmail

Do not upload or commit `.env` to GitHub. Set secrets in the Render dashboard instead.

Because this app uses SQLite and stores uploaded clothing images, attach a Render persistent disk and mount it at `/var/data`.
