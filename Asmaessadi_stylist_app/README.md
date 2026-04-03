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

Do not upload or commit `.env` to GitHub. Set secrets in the Render dashboard instead.

Because this app uses SQLite and stores uploaded clothing images, attach a Render persistent disk and mount it at `/var/data`.
