"""
 STYLING.AI — AI Personal Stylist MVP
=====================================
Flask backend for wardrobe management and outfit generation.

Next Phase: Connect to OpenAI API in the `generate_outfit_ai()` route
by replacing the random selection logic with a GPT-4 Vision prompt.

Author: Asma Essaedi
Version: 1.0.0 (MVP)
"""

import os
import random
import sqlite3
import json
import io
import mimetypes
import smtplib
import ssl
from email.message import EmailMessage
from functools import wraps
from datetime import datetime

try:
    import certifi
except ModuleNotFoundError:
    certifi = None
try:
    from openai import OpenAI
except ModuleNotFoundError:
    OpenAI = None
try:
    import stripe
except ModuleNotFoundError:
    stripe = None
try:
    from PIL import Image, ImageOps
except ModuleNotFoundError:
    Image = None
    ImageOps = None
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, jsonify, g, flash, send_from_directory,
    make_response
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

# ---------------------------------------------------------------------------
# App Configuration
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def default_data_dir():
    """Choose a sensible local data directory unless DATA_DIR is explicitly set."""
    explicit = os.environ.get("DATA_DIR")
    if explicit:
        return explicit

    legacy_instance_dir = os.path.join(BASE_DIR, "instance")
    if os.path.exists(os.path.join(legacy_instance_dir, "stylist.db")):
        return legacy_instance_dir

    return BASE_DIR


DATA_DIR = default_data_dir()


def load_local_env():
    """Load KEY=VALUE pairs from a local .env file when variables are missing."""
    env_path = os.path.join(BASE_DIR, ".env")
    if not os.path.exists(env_path):
        return

    with open(env_path, "r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            os.environ.setdefault(key, value)


load_local_env()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-in-production-please")

# File upload settings
LEGACY_UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
UPLOAD_FOLDER = (
    LEGACY_UPLOAD_FOLDER
    if "DATA_DIR" not in os.environ and os.path.isdir(LEGACY_UPLOAD_FOLDER)
    else os.path.join(DATA_DIR, "uploads")
)
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
MAX_CONTENT_LENGTH = 8 * 1024 * 1024  # 8 MB
IMAGE_MIME_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

# Clothing categories used across the app
CATEGORIES = ["tops", "bottoms", "shoes", "outerwear", "accessories"]
PREVIEW_OCCASIONS = [
    "Everyday polish",
    "Work meeting",
    "Brunch",
    "Wedding guest",
    "Travel day",
]
STYLE_VIBES = [
    "Minimal",
    "Elevated",
    "Classic",
    "Bold",
    "Soft luxury",
    "Street style",
]

# ---------------------------------------------------------------------------
# Database Configuration (SQLite fallback & PostgreSQL wrapper for Render)
# ---------------------------------------------------------------------------

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None

DATABASE = os.path.join(DATA_DIR, "stylist.db")


class PostgreSQLWrapper:
    """Wrapper to make PostgreSQL connections match SQLite's interface."""
    def __init__(self, conn):
        self.conn = conn

    def execute(self, query, params=None):
        # Translate '?' placeholder to '%s' for PostgreSQL
        query_translated = query.replace('?', '%s')
        
        # Intercept SQLite-specific PRAGMA table_info calls
        if "PRAGMA table_info" in query:
            import re
            match = re.search(r"PRAGMA table_info\((\w+)\)", query)
            if match:
                table_name = match.group(1)
                cur = self.conn.cursor()
                cur.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
                    (table_name,)
                )
                columns = cur.fetchall()
                fake_rows = [(None, col[0]) for col in columns]
                
                class FakeCursor:
                    def __init__(self, rows):
                        self.rows = rows
                    def fetchall(self):
                        return self.rows
                    def fetchone(self):
                        return self.rows[0] if self.rows else None
                    def __iter__(self):
                        return iter(self.rows)
                return FakeCursor(fake_rows)

        cur = self.conn.cursor()
        try:
            if params is not None:
                cur.execute(query_translated, params)
            else:
                cur.execute(query_translated)
            return cur
        except Exception as e:
            self.conn.rollback()
            raise e

    def executescript(self, script_text):
        # Convert SQLite auto-increment syntax to PostgreSQL SERIAL
        translated = script_text.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
        cur = self.conn.cursor()
        try:
            cur.execute(translated)
            self.conn.commit()
            return cur
        except Exception as e:
            self.conn.rollback()
            raise e

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.conn.close()


def get_db():
    """Open a database connection scoped to the current request."""
    if "db" not in g:
        db_url = os.environ.get("DATABASE_URL")
        if db_url and psycopg2:
            # Render PostgreSQL URL starts with postgres://, but psycopg2 prefers postgresql://
            if db_url.startswith("postgres://"):
                db_url = db_url.replace("postgres://", "postgresql://", 1)
            conn = psycopg2.connect(db_url, cursor_factory=psycopg2.extras.DictCursor)
            g.db = PostgreSQLWrapper(conn)
        else:
            g.db = sqlite3.connect(DATABASE, detect_types=sqlite3.PARSE_DECLTYPES)
            g.db.row_factory = sqlite3.Row  # access columns by name
    return g.db


@app.teardown_appcontext
def close_db(error):
    """Close the database at the end of every request."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Create tables if they don't already exist."""
    db_url = os.environ.get("DATABASE_URL")
    if db_url and psycopg2:
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)
        conn = psycopg2.connect(db_url, cursor_factory=psycopg2.extras.DictCursor)
        db = PostgreSQLWrapper(conn)
    else:
        os.makedirs(DATA_DIR, exist_ok=True)
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        db = sqlite3.connect(DATABASE)

    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            email     TEXT    UNIQUE NOT NULL,
            password  TEXT    NOT NULL,
            name      TEXT    NOT NULL,
            tier      TEXT    NOT NULL DEFAULT 'free',   -- 'free' | 'pro'
            stripe_customer_id TEXT,
            stripe_subscription_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS wardrobe_items (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name        TEXT    NOT NULL,
            category    TEXT    NOT NULL,   -- tops | bottoms | shoes | outerwear | accessories
            color       TEXT    NOT NULL,
            image_path  TEXT    NOT NULL,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS look_previews (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            occasion     TEXT    NOT NULL,
            style_vibe   TEXT    NOT NULL,
            styling_goal TEXT,
            notes        TEXT    NOT NULL,
            items_json   TEXT    NOT NULL,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    existing_columns = {
        row[1] for row in db.execute("PRAGMA table_info(users)").fetchall()
    }
    if "stripe_customer_id" not in existing_columns:
        db.execute("ALTER TABLE users ADD COLUMN stripe_customer_id TEXT")
    if "stripe_subscription_id" not in existing_columns:
        db.execute("ALTER TABLE users ADD COLUMN stripe_subscription_id TEXT")
    if "onboarding_completed" not in existing_columns:
        db.execute("ALTER TABLE users ADD COLUMN onboarding_completed INTEGER DEFAULT 0")
    if "style_preference" not in existing_columns:
        db.execute("ALTER TABLE users ADD COLUMN style_preference TEXT")

    existing_columns_previews = {
        row[1] for row in db.execute("PRAGMA table_info(look_previews)").fetchall()
    }
    if "image_path" not in existing_columns_previews:
        db.execute("ALTER TABLE look_previews ADD COLUMN image_path TEXT")

    db.commit()
    db.close()
    print("[DB] Database initialised.")


def ensure_app_ready():
    """Initialize database tables once per process so fresh deploys don't crash."""
    if app.config.get("_db_ready"):
        return
    init_db()
    app.config["_db_ready"] = True


ensure_app_ready()


# ---------------------------------------------------------------------------
# Auth Helpers
# ---------------------------------------------------------------------------

def login_required(f):
    """Decorator: redirect to login if the user is not authenticated."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        if current_user() is None:
            session.clear()
            flash("Please log in again.", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def allowed_file(filename):
    """Return True if the file extension is in the allowed set."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def mime_type_for_image(filename):
    """Return a supported image MIME type for an uploaded wardrobe file."""
    ext = filename.rsplit(".", 1)[1].lower() if "." in filename else ""
    return IMAGE_MIME_TYPES.get(ext) or mimetypes.guess_type(filename)[0] or "application/octet-stream"


def optimized_image_reference(image_path, filename):
    """Return a compact image tuple for OpenAI image previews, optimized for memory usage."""
    import gc
    safe_name = secure_filename(filename)
    if Image is None:
        with open(image_path, "rb") as image_file:
            return safe_name, image_file.read(), mime_type_for_image(safe_name)

    try:
        with Image.open(image_path) as source:
            image = ImageOps.exif_transpose(source)
            
            # Downsize early to avoid memory bloat (512x512 is plenty for styling reference)
            image.thumbnail((512, 512), Image.Resampling.BILINEAR)
            
            if image.mode in {"RGBA", "LA"}:
                background = Image.new("RGB", image.size, "white")
                background.paste(image, mask=image.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")

            output = io.BytesIO()
            # Save at slightly lower quality without optimize=True to save CPU/memory
            image.save(output, format="JPEG", quality=75)
            data_bytes = output.getvalue()
            
            image.close()
            if 'background' in locals() and hasattr(background, "close"):
                background.close()
    finally:
        gc.collect()

    root = os.path.splitext(safe_name)[0] or "wardrobe-item"
    return f"{root}.jpg", data_bytes, "image/jpeg"




def wardrobe_item_payload(row):
    """Convert a wardrobe DB row into JSON-safe data for API responses."""
    item = dict(row)
    created_at = item.get("created_at")
    if isinstance(created_at, datetime):
        item["created_at"] = created_at.isoformat()
    elif created_at is not None:
        item["created_at"] = str(created_at)
    return item


def current_user():
    """Fetch the logged-in user row, or None."""
    if "user_id" not in session:
        return None
    db = get_db()
    return db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()


def reset_token_serializer():
    """Create a timed serializer for password reset tokens."""
    return URLSafeTimedSerializer(app.secret_key, salt="password-reset")


def build_reset_token(email):
    """Create a signed password reset token for a user email."""
    return reset_token_serializer().dumps(email)


def verify_reset_token(token, max_age=3600):
    """Validate a reset token and return the email or None."""
    try:
        return reset_token_serializer().loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None


def smtp_settings():
    """Return SMTP settings, with Gmail app-password aliases supported."""
    username = os.environ.get("SMTP_USERNAME") or os.environ.get("GMAIL_ADDRESS")
    password = os.environ.get("SMTP_PASSWORD") or os.environ.get("GMAIL_APP_PASSWORD")
    mail_from = os.environ.get("MAIL_FROM") or username
    use_ssl = os.environ.get("SMTP_USE_SSL", "").lower() in {"1", "true", "yes"}
    smtp_host = os.environ.get("SMTP_HOST")

    if not smtp_host and username and username.endswith("@gmail.com"):
        smtp_host = "smtp.gmail.com"

    default_port = "465" if use_ssl else "587"
    smtp_port = int(os.environ.get("SMTP_PORT", default_port))

    missing = []
    if not smtp_host:
        missing.append("SMTP_HOST")
    if not username:
        missing.append("SMTP_USERNAME or GMAIL_ADDRESS")
    if not password:
        missing.append("SMTP_PASSWORD or GMAIL_APP_PASSWORD")
    if not mail_from:
        missing.append("MAIL_FROM")

    return {
        "smtp_host": smtp_host,
        "smtp_port": smtp_port,
        "use_ssl": use_ssl,
        "username": username,
        "password": password,
        "mail_from": mail_from,
        "mail_from_name": os.environ.get("MAIL_FROM_NAME", "Asma Essaedi"),
        "missing": missing,
    }


def email_is_ready():
    """Return True when SMTP settings are configured."""
    return not smtp_settings()["missing"]


def send_email(to_email, subject, body):
    """Send a plain-text email using Resend API (HTTPS) if configured, otherwise fallback to SMTP."""
    resend_api_key = os.environ.get("RESEND_API_KEY")
    if resend_api_key:
        import requests
        from_email = os.environ.get("RESEND_FROM_EMAIL") or os.environ.get("MAIL_FROM") or "onboarding@resend.dev"
        from_name = os.environ.get("MAIL_FROM_NAME") or "Asma Essaedi"
        try:
            app.logger.info("Sending email via Resend API to %s", to_email)
            res = requests.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {resend_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": f"{from_name} <{from_email}>" if from_name else from_email,
                    "to": to_email,
                    "subject": subject,
                    "text": body,
                },
                timeout=10
            )
            res.raise_for_status()
            app.logger.info("Email sent successfully via Resend API.")
            return
        except Exception as e:
            app.logger.warning("Failed to send email via Resend API: %s. Trying SMTP fallback.", e)

    # Fallback to SMTP
    settings = smtp_settings()
    if settings["missing"]:
        missing = ", ".join(settings["missing"])
        raise RuntimeError(f"Email is not configured. Missing: {missing}")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"{settings['mail_from_name']} <{settings['mail_from']}>"
    message["To"] = to_email
    message.set_content(body)
    tls_context = ssl.create_default_context(cafile=certifi.where() if certifi else None)

    if settings["use_ssl"]:
        with smtplib.SMTP_SSL(settings["smtp_host"], settings["smtp_port"], context=tls_context, timeout=10) as smtp:
            smtp.login(settings["username"], settings["password"])
            smtp.send_message(message)
        return

    with smtplib.SMTP(settings["smtp_host"], settings["smtp_port"], timeout=10) as smtp:
        smtp.starttls(context=tls_context)
        smtp.login(settings["username"], settings["password"])
        smtp.send_message(message)


def send_password_reset_email(to_email, reset_link):
    """Email a password reset link to a user."""
    body = f"""Hi,

We received a request to reset your Asma Essaedi password.

Use this link to choose a new password:
{reset_link}

This link expires in 1 hour. If you did not request a password reset, you can ignore this email.

Asma Essaedi
"""
    send_email(to_email, "Reset your Asma Essaedi password", body)


def stripe_is_ready():
    """Return True when the required Stripe settings are available."""
    configure_stripe()
    return bool(stripe and stripe.api_key and os.environ.get("STRIPE_PRICE_ID"))


def configure_stripe():
    """Refresh Stripe's API key from the current environment."""
    if stripe:
        stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")


def openai_client():
    """Return an OpenAI client when the SDK and API key are available."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not OpenAI or not api_key:
        return None
    return OpenAI(api_key=api_key)


def app_base_url():
    """Use a configured public URL when available, otherwise derive from the request."""
    return os.environ.get("APP_BASE_URL", request.host_url.rstrip("/"))


def set_user_subscription_state(user_id, tier, customer_id=None, subscription_id=None):
    """Persist a user's billing tier and Stripe IDs."""
    db = get_db()
    db.execute(
        """
        UPDATE users
        SET tier = ?,
            stripe_customer_id = COALESCE(?, stripe_customer_id),
            stripe_subscription_id = ?
        WHERE id = ?
        """,
        (tier, customer_id, subscription_id, user_id)
    )
    db.commit()


def find_user_by_billing_reference(customer_id=None, subscription_id=None):
    """Look up a user by Stripe customer or subscription ID."""
    db = get_db()
    if subscription_id:
        user = db.execute(
            "SELECT * FROM users WHERE stripe_subscription_id = ?",
            (subscription_id,)
        ).fetchone()
        if user:
            return user
    if customer_id:
        return db.execute(
            "SELECT * FROM users WHERE stripe_customer_id = ?",
            (customer_id,)
        ).fetchone()
    return None


def ai_try_on_is_ready():
    """Return True when the AI try-on feature can call OpenAI."""
    return bool(OpenAI and os.environ.get("OPENAI_API_KEY"))


def build_style_notes(items, occasion, style_vibe, styling_goal):
    """Create concise stylist notes to make the preview feel guided and premium."""
    category_map = {item["category"]: item for item in items}
    notes = []

    top = category_map.get("tops")
    bottom = category_map.get("bottoms")
    outerwear = category_map.get("outerwear")
    shoes = category_map.get("shoes")
    accessories = category_map.get("accessories")

    if top and bottom:
        notes.append(
            f"The {top['color']} {top['name']} anchors the look while the {bottom['color']} {bottom['name']} keeps it grounded and easy to style."
        )
    if outerwear:
        notes.append(
            f"The {outerwear['name']} adds structure, which makes this feel more {style_vibe.lower()} for {occasion.lower()}."
        )
    if shoes:
        notes.append(
            f"{shoes['name']} helps the outfit feel finished instead of thrown together."
        )
    if accessories:
        notes.append(
            f"{accessories['name']} gives the look a more intentional final layer."
        )

    notes.append(
        f"This outfit is tuned for {occasion.lower()} with a {style_vibe.lower()} mood so it feels polished and wearable."
    )

    if styling_goal:
        notes.append(
            f"Styling priority: {styling_goal.strip().rstrip('.')}."
        )

    return notes[:4]


def save_look_preview(user_id, occasion, style_vibe, styling_goal, notes, items, image_path=None):
    """Persist recent look previews so users see ongoing value."""
    db = get_db()
    db.execute(
        """
        INSERT INTO look_previews (user_id, occasion, style_vibe, styling_goal, notes, items_json, image_path)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, occasion, style_vibe, styling_goal, "\n".join(notes), json.dumps(items, default=str), image_path)
    )
    db.commit()


def recent_previews_for_user(user_id, limit=6):
    """Fetch recent generated looks for dashboard history."""
    db = get_db()
    rows = db.execute(
        """
        SELECT id, occasion, style_vibe, styling_goal, notes, items_json, created_at, image_path
        FROM look_previews
        WHERE user_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (user_id, limit)
    ).fetchall()

    previews = []
    for row in rows:
        preview = dict(row)
        items_str = preview.pop("items_json") or "[]"
        preview["items"] = json.loads(items_str)
        notes_str = preview.pop("notes") or ""
        preview["notes"] = [note for note in notes_str.split("\n") if note]
        previews.append(preview)
    return previews


# ---------------------------------------------------------------------------
# Routes — Auth
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """Landing page: redirect to dashboard if logged in, else to login."""
    if current_user() is not None:
        return redirect(url_for("dashboard"))
    if "user_id" in session:
        session.clear()
    return render_template("index.html")


def validate_password_strength(password):
    """Validate that the password has at least 8 characters, a number, and a punctuation mark."""
    import string
    if len(password) < 8:
        return False, "Password must be at least 8 characters long."
    if not any(char.isdigit() for char in password):
        return False, "Password must contain at least one number."
    punctuation_set = set(string.punctuation)
    if not any(char in punctuation_set for char in password):
        return False, "Password must contain at least one punctuation mark (e.g. !, @, #, $, etc.)."
    return True, ""


@app.route("/signup", methods=["GET", "POST"])
def signup():
    """Create a new user account."""
    if request.method == "POST":
        name     = request.form.get("name", "").strip()
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not all([name, email, password]):
            flash("All fields are required.", "error")
            return redirect(url_for("signup"))

        is_valid, msg = validate_password_strength(password)
        if not is_valid:
            flash(msg, "error")
            return redirect(url_for("signup"))

        db = get_db()
        if db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone():
            flash("An account with that email already exists.", "error")
            return redirect(url_for("signup"))

        db.execute(
            "INSERT INTO users (name, email, password) VALUES (?, ?, ?)",
            (name, email, generate_password_hash(password))
        )
        db.commit()

        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        session["user_id"] = user["id"]
        return redirect(url_for("onboarding"))

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    """Authenticate an existing user."""
    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        db   = get_db()
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

        if not user or not check_password_hash(user["password"], password):
            flash("Invalid email or password.", "error")
            return redirect(url_for("login"))

        session["user_id"] = user["id"]
        
        if not dict(user).get("onboarding_completed"):
            return redirect(url_for("onboarding"))
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/onboarding", methods=["GET", "POST"])
@login_required
def onboarding():
    """Personalize the user's dashboard based on their preferences."""
    user = current_user()
    if dict(user).get("onboarding_completed"):
        return redirect(url_for("dashboard"))
        
    if request.method == "POST":
        style_goal = request.form.get("style_goal", "").strip()
        color_vibe = request.form.get("color_vibe", "").strip()
        
        preference_json = json.dumps({"style_goal": style_goal, "color_vibe": color_vibe})
        
        db = get_db()
        db.execute(
            "UPDATE users SET onboarding_completed = 1, style_preference = ? WHERE id = ?",
            (preference_json, user["id"])
        )
        db.commit()
        return redirect(url_for("dashboard"))
        
    return render_template("onboarding.html", user=user)
@app.route("/logout")
def logout():
    """Clear the session and redirect to the landing page."""
    session.clear()
    return redirect(url_for("index"))


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """Let a user request a password reset link."""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

        if user:
            token = build_reset_token(email)
            reset_link = f"{app_base_url()}{url_for('reset_password', token=token)}"
            try:
                app.logger.info("Password reset email send started. base_url=%s", app_base_url())
                send_password_reset_email(email, reset_link)
                app.logger.info("Password reset email sent successfully.")
            except Exception:
                app.logger.exception("Password reset email failed.")
                flash("We could not send the reset email right now. Please try again later.", "error")
                return redirect(url_for("forgot_password"))
        else:
            app.logger.info("Password reset requested for an email without an account.")

        flash("If an account exists for that email, a password reset link has been sent.", "success")
        return redirect(url_for("login"))

    return render_template("forgot_password.html")


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    """Allow a user to set a new password from a signed token."""
    email = verify_reset_token(token)
    if not email:
        flash("That reset link is invalid or has expired.", "error")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        is_valid, msg = validate_password_strength(password)
        if not is_valid:
            flash(msg, "error")
            return redirect(url_for("reset_password", token=token))

        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return redirect(url_for("reset_password", token=token))

        db = get_db()
        db.execute(
            "UPDATE users SET password = ? WHERE email = ?",
            (generate_password_hash(password), email)
        )
        db.commit()
        flash("Your password has been reset. Log in with your new password.", "success")
        return redirect(url_for("login"))

    return render_template("reset_password.html", token=token, email=email)


# ---------------------------------------------------------------------------
# Routes — Dashboard & Wardrobe
# ---------------------------------------------------------------------------

@app.route("/dashboard")
@login_required
def dashboard():
    """Main stylist dashboard: shows wardrobe summary and outfit generation UI."""
    user = current_user()
    db   = get_db()

    if request.args.get("upgraded") == "1":
        flash("Your Pro subscription is active.", "success")
        return redirect(url_for("dashboard"))

    # Fetch all wardrobe items grouped by category for display
    items = db.execute(
        "SELECT * FROM wardrobe_items WHERE user_id = ? ORDER BY created_at DESC",
        (user["id"],)
    ).fetchall()

    # Count per category for the stats bar
    counts = {cat: 0 for cat in CATEGORIES}
    for item in items:
        if item["category"] in counts:
            counts[item["category"]] += 1

    return render_template(
        "dashboard.html",
        user=user,
        items=items,
        counts=counts,
        categories=CATEGORIES,
        preview_occasions=PREVIEW_OCCASIONS,
        style_vibes=STYLE_VIBES,
        recent_previews=recent_previews_for_user(user["id"])
    )


@app.route("/uploads/<path:filename>")
@login_required
def uploaded_file(filename):
    """Serve uploaded wardrobe images from the configured data directory."""
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


@app.route("/wardrobe/add", methods=["GET", "POST"])
@login_required
def add_item():
    """Upload a new clothing item to the wardrobe."""
    user = current_user()
    db = get_db()
    
    limit_reached = False
    if user["tier"] != "pro":
        count = db.execute("SELECT COUNT(*) as count FROM wardrobe_items WHERE user_id = ?", (user["id"],)).fetchone()["count"]
        if count >= 12:
            limit_reached = True

    if request.method == "POST":
        if limit_reached:
            flash("You have reached the 12-item limit on the Free plan. Upgrade to Pro to add more!", "error")
            return redirect(url_for("dashboard"))

        name     = request.form.get("name", "").strip()
        category = request.form.get("category", "").strip()
        color    = request.form.get("color", "").strip()
        file     = request.files.get("image")

        # Validation
        if not all([name, category, color, file]):
            flash("All fields including an image are required.", "error")
            return redirect(url_for("add_item"))

        if category not in CATEGORIES:
            flash("Invalid category.", "error")
            return redirect(url_for("add_item"))

        if not allowed_file(file.filename):
            flash("Image must be PNG, JPG, JPEG, or WEBP.", "error")
            return redirect(url_for("add_item"))

        # Save the file with a timestamped, safe filename ending in .jpg
        filename = secure_filename(f"{user['id']}_{int(datetime.utcnow().timestamp())}_{name}.jpg")
        save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        
        # Optimize and resize image early during upload to save disk space and runtime memory
        try:
            if Image is not None:
                file.seek(0)
                with Image.open(file.stream) as img:
                    img = ImageOps.exif_transpose(img)
                    img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                    if img.mode in {"RGBA", "LA"}:
                        background = Image.new("RGB", img.size, "white")
                        background.paste(img, mask=img.getchannel("A"))
                        img = background
                    else:
                        img = img.convert("RGB")
                    img.save(save_path, "JPEG", quality=80)
            else:
                file.seek(0)
                file.save(save_path)
        except Exception as upload_err:
            app.logger.warning(f"Failed to optimize upload: {upload_err}")
            file.seek(0)
            file.save(save_path)

        # Persist to database
        db = get_db()
        db.execute(
            "INSERT INTO wardrobe_items (user_id, name, category, color, image_path) VALUES (?, ?, ?, ?, ?)",
            (user["id"], name, category, color, filename)
        )
        db.commit()

        flash("Item added to your wardrobe.", "success")
        return redirect(url_for("dashboard"))
    return render_template("add_item.html", user=user, categories=CATEGORIES, limit_reached=limit_reached)


@app.route("/wardrobe/delete/<int:item_id>", methods=["POST"])
@login_required
def delete_item(item_id):
    """Remove a clothing item from the wardrobe (and delete its image file)."""
    user = current_user()
    db   = get_db()

    item = db.execute(
        "SELECT * FROM wardrobe_items WHERE id = ? AND user_id = ?",
        (item_id, user["id"])
    ).fetchone()

    if not item:
        return jsonify({"error": "Item not found"}), 404

    # Remove image file from disk
    image_path = os.path.join(app.config["UPLOAD_FOLDER"], item["image_path"])
    if os.path.exists(image_path):
        os.remove(image_path)

    db.execute("DELETE FROM wardrobe_items WHERE id = ?", (item_id,))
    db.commit()

    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Routes — AI Stylist (Core Feature)
# -----------------------------------------------------------------------------------

@app.route("/api/generate-outfit", methods=["POST"])
@login_required
def generate_outfit():
    """
    Generate a smart outfit from the user's wardrobe based on context.
    """
    user = current_user()
    db   = get_db()
    context = request.form.get("context", "").strip() or "Something nice for today."

    client = openai_client()
    
    # Get all items
    rows = db.execute(
        "SELECT id, category, name, color, image_path FROM wardrobe_items WHERE user_id = ?",
        (user["id"],)
    ).fetchall()
    items = [wardrobe_item_payload(row) for row in rows]
    
    if not items:
        return jsonify({"error": "Your wardrobe is empty. Add some items first!"}), 400

    if client is None:
        # Fallback to random logic if OpenAI is not configured
        def pick(category):
            cat_items = [i for i in items if i["category"] == category]
            return random.choice(cat_items) if cat_items else None
        outfit = {"top": pick("tops"), "bottom": pick("bottoms"), "shoes": pick("shoes")}
        note = "Randomly selected because OpenAI is not configured."
    else:
        # AI generate
        items_json = json.dumps([{"id": i["id"], "category": i["category"], "name": i["name"], "color": i["color"]} for i in items])
        
        prompt = f"""You are a personal stylist. The user needs an outfit for: "{context}".
Here is their wardrobe inventory in JSON:
{items_json}

Please select the best combination of items for this context. You can pick up to 4 items (e.g. top, bottom, shoes, outerwear).
You MUST respond with a valid JSON object with EXACTLY two keys:
1. "item_ids": A list of the chosen item IDs (integers).
2. "note": A short, friendly stylist note explaining why you picked this outfit (max 2 sentences).
"""
        try:
            response = client.chat.completions.create(
                model=os.environ.get("OPENAI_LANGUAGE_MODEL", "gpt-4o"),
                messages=[
                    {"role": "system", "content": "You are a professional stylist that exclusively outputs raw, valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=400,
                response_format={"type": "json_object"}
            )
            content = response.choices[0].message.content.strip()
            if content.startswith("```"):
                content = content.replace("```json", "").replace("```", "").strip()
            
            ai_result = json.loads(content)
            chosen_ids = ai_result.get("item_ids", [])
            note = ai_result.get("note", "Here is your outfit for the occasion.")
            
            outfit_items = [i for i in items if i["id"] in chosen_ids]
            outfit = {
                "top": next((i for i in outfit_items if i["category"] == "tops"), None),
                "bottom": next((i for i in outfit_items if i["category"] == "bottoms"), None),
                "shoes": next((i for i in outfit_items if i["category"] == "shoes"), None),
                "outerwear": next((i for i in outfit_items if i["category"] == "outerwear"), None),
                "accessories": next((i for i in outfit_items if i["category"] == "accessories"), None)
            }
        except Exception as exc:
            app.logger.exception("Generative styling failed.")
            return jsonify({"error": f"AI Generation failed: {exc}"}), 500

    item_ids = [i["id"] for i in outfit.values() if i]
    return jsonify({"outfit": outfit, "item_ids": item_ids, "note": note, "generated_at": datetime.utcnow().isoformat()})


@app.route("/api/preview-look", methods=["POST"])
@login_required
def preview_look():
    """
    Create an AI outfit preview from selected wardrobe items only.

    This is a visual styling mockup, not a physically accurate fit simulation
    of a specific person.
    """
    if not ai_try_on_is_ready():
        return jsonify({
            "error": "AI preview is not configured yet. Add OPENAI_API_KEY and install the openai package.",
        }), 500

    user = current_user()
    item_ids = request.form.getlist("item_ids")
    occasion = request.form.get("occasion", PREVIEW_OCCASIONS[0]).strip()
    style_vibe = request.form.get("style_vibe", STYLE_VIBES[0]).strip()
    styling_goal = request.form.get("styling_goal", "").strip()

    if occasion not in PREVIEW_OCCASIONS:
        occasion = PREVIEW_OCCASIONS[0]
    if style_vibe not in STYLE_VIBES:
        style_vibe = STYLE_VIBES[0]

    try:
        item_ids = [int(item_id) for item_id in item_ids]
    except ValueError:
        return jsonify({"error": "Selected wardrobe items were invalid."}), 400

    if len(item_ids) < 1:
        return jsonify({"error": "Select at least one clothing item."}), 400

    if len(item_ids) > 4:
        return jsonify({"error": "Select up to four items for one try-on preview."}), 400

    db = get_db()
    placeholders = ",".join("?" for _ in item_ids)
    rows = db.execute(
        f"""
        SELECT * FROM wardrobe_items
        WHERE user_id = ? AND id IN ({placeholders})
        ORDER BY created_at DESC
        """,
        (user["id"], *item_ids)
    ).fetchall()

    items = [wardrobe_item_payload(row) for row in rows]
    if len(items) != len(item_ids):
        return jsonify({"error": "One or more selected items could not be found."}), 404

    categories = {item["category"] for item in items}

    client = openai_client()
    if client is None:
        return jsonify({
            "error": "OpenAI is not configured yet. Add OPENAI_API_KEY and install the openai package.",
        }), 500

    styling_notes = ", ".join(
        f"{item['category']}: {item['name']} ({item['color']})" for item in items
    )

    prompt = (
        "Create a photorealistic fashion preview on a realistic editorial model. "
        "Use all provided images as garment references for the final look. "
        "Show a single person wearing the selected outfit in a clean full-body studio-style composition. "
        "Match garment colors, silhouettes, layering, and textures closely to the reference items. "
        "Do not add extra garments that were not provided. "
        "Do not copy branding, watermarks, or product-shot backgrounds from the references. "
        "Use a simple neutral background and clear front-facing pose. "
        f"The intended occasion is {occasion.lower()} and the styling vibe is {style_vibe.lower()}. "
        f"User styling goal: {styling_goal or 'Look polished and expensive without feeling overdone'}. "
        f"Selected outfit pieces: {styling_notes}. "
        "This is a wardrobe-planning visualization, not a shopping ad."
    )

    try:
        result = client.images.generate(
            model=os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-1.5"),
            prompt=prompt,
            size=os.environ.get("OPENAI_IMAGE_SIZE", "1024x1024"),
            n=1
        )
        image_result = result.data[0]
        image_b64 = getattr(image_result, "b64_json", None)
        image_url = getattr(image_result, "url", None)
        import base64
        import urllib.request
        
        preview_filename = None
        if image_b64:
            image_data = base64.b64decode(image_b64)
            preview_filename = secure_filename(f"preview_{user['id']}_{int(datetime.utcnow().timestamp())}.png")
            preview_path = os.path.join(app.config["UPLOAD_FOLDER"], preview_filename)
            with open(preview_path, "wb") as f:
                f.write(image_data)
            image_src = url_for("uploaded_file", filename=preview_filename)
        elif image_url:
            preview_filename = secure_filename(f"preview_{user['id']}_{int(datetime.utcnow().timestamp())}.png")
            preview_path = os.path.join(app.config["UPLOAD_FOLDER"], preview_filename)
            try:
                urllib.request.urlretrieve(image_url, preview_path)
                image_src = url_for("uploaded_file", filename=preview_filename)
            except Exception as download_err:
                app.logger.warning(f"Failed to download preview from URL: {download_err}")
                image_src = image_url
                preview_filename = None
        else:
            return jsonify({"error": "OpenAI returned a preview without image data. Try again."}), 502
    except Exception as exc:
        app.logger.exception("OpenAI try-on preview failed.")
        return jsonify({"error": f"Unable to create AI preview: {exc}"}), 500

    notes = build_style_notes(items, occasion, style_vibe, styling_goal)
    save_look_preview(user["id"], occasion, style_vibe, styling_goal, notes, items, preview_filename)

    return jsonify({
        "image_data_url": image_src,
        "image_url": image_src,
        "selected_items": items,
        "occasion": occasion,
        "style_vibe": style_vibe,
        "styling_goal": styling_goal,
        "notes": notes,
        "recent_previews": recent_previews_for_user(user["id"]),
    })


@app.route("/api/analyze-closet", methods=["POST"])
@login_required
def analyze_closet():
    """Generates an AI wardrobe analysis for all users."""
    user = current_user()

    client = openai_client()
    if client is None:
        return jsonify({"error": "OpenAI is not configured."}), 500
        
    db = get_db()
    items = db.execute(
        "SELECT category, color, name FROM wardrobe_items WHERE user_id = ?",
        (user["id"],)
    ).fetchall()
    
    if not items:
        return jsonify({"error": "Your wardrobe is empty. Add items first!"}), 400
        
    wardrobe_list = ", ".join(f"{item['color']} {item['category']} ({item['name']})" for item in items)
    
    prompt = f"""You are a high-end fashion stylist analyzing a user's closet.
Their current wardrobe consists of: {wardrobe_list}.

Please provide an analysis containing exactly three sections formatted visually appealing using HTML (use tags like <h3>, <ul>, <li>, <p>, <strong>):
1. 'Style Vibe': A brief summary of their current aesthetic based on these pieces.
2. 'Missing Essentials': 3-4 foundational pieces they should buy next to complete their wardrobe.
3. 'Color Palette': Suggested color palette (3-4 colors) to compliment what they own.
Return ONLY valid HTML elements inside a single div wrapper, no markdown wrappers, no html wrappers padding, just the inner HTML."""

    try:
        response = client.chat.completions.create(
            model=os.environ.get("OPENAI_LANGUAGE_MODEL", "gpt-4o"),
            messages=[
                {"role": "system", "content": "You are an expert personal stylist."}, 
                {"role": "user", "content": prompt}
            ],
            max_tokens=800
        )
        analysis_html = response.choices[0].message.content
        # sometimes markdown ```html block creeps in
        analysis_html = analysis_html.replace("```html", "").replace("```", "").strip()
        return jsonify({"analysis": analysis_html})
    except Exception as exc:
        app.logger.exception("OpenAI closet analysis failed.")
        return jsonify({"error": f"Failed to analyze closet: {exc}"}), 500


@app.route("/api/analyze-image", methods=["POST"])
@login_required
def analyze_image():
    """Analyze an uploaded wardrobe image using GPT-4o Vision and return suggested name, category, and color."""
    if "image" not in request.files:
        return jsonify({"error": "No image file provided."}), 400
        
    file = request.files["image"]
    if not file or not allowed_file(file.filename):
        return jsonify({"error": "Invalid image file type."}), 400

    client = openai_client()
    if not client:
        return jsonify({"error": "OpenAI not configured."}), 503

    try:
        import base64
        file_bytes = file.read()
        file.seek(0)
        
        # Downscale image to 512x512 to save tokens and speed up API call
        if Image:
            try:
                img_io = io.BytesIO(file_bytes)
                with Image.open(img_io) as img:
                    img.thumbnail((512, 512))
                    out_io = io.BytesIO()
                    img.save(out_io, format="JPEG", quality=80)
                    base64_image = base64.b64encode(out_io.getvalue()).decode("utf-8")
            except Exception as resize_err:
                app.logger.warning(f"Failed to resize image for vision analysis: {resize_err}")
                base64_image = base64.b64encode(file_bytes).decode("utf-8")
        else:
            base64_image = base64.b64encode(file_bytes).decode("utf-8")

        prompt = (
            "You are an expert fashion stylist. Analyze the uploaded garment image.\n"
            "Determine:\n"
            "1. A clean, descriptive name for the item (e.g., 'Black blazer', 'White linen shirt', 'Red sneakers'). Keep it short (2-4 words).\n"
            "2. The best category from: tops, bottoms, shoes, outerwear, accessories.\n"
            "3. The primary color of the item (e.g., 'black', 'white', 'cream', 'navy').\n\n"
            "Respond ONLY with a JSON object containing the keys \"name\", \"category\", and \"color\". Example response:\n"
            '{"name": "Black leather boots", "category": "shoes", "color": "black"}\n'
            "Do not include any markdown formatting, backticks, or explanation. Just return the raw JSON object."
        )

        response = client.chat.completions.create(
            model=os.environ.get("OPENAI_LANGUAGE_MODEL", "gpt-4o"),
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=150,
            response_format={"type": "json_object"}
        )
        
        content = response.choices[0].message.content.strip()
        data = json.loads(content)
        
        category = data.get("category", "").lower()
        if category not in CATEGORIES:
            data["category"] = ""
            
        return jsonify(data)
    except Exception as exc:
        app.logger.exception("AI image analysis failed.")
        return jsonify({"error": f"Failed to analyze image: {exc}"}), 500


@app.route("/api/upgrade-intent", methods=["POST"])
@login_required
def upgrade_intent():
    """Create a Stripe Checkout Session for the Pro subscription."""
    user = current_user()
    configure_stripe()
    if stripe is None:
        return jsonify({
            "error": "Stripe is not installed yet. Run: pip install -r requirements.txt",
        }), 500
    if not stripe_is_ready():
        missing = [
            name for name in ("STRIPE_SECRET_KEY", "STRIPE_PRICE_ID")
            if not os.environ.get(name)
        ]
        return jsonify({
            "error": "Stripe is not configured yet.",
            "missing": missing,
        }), 500

    try:
        checkout_session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[
                {
                    "price": os.environ["STRIPE_PRICE_ID"],
                    "quantity": 1,
                }
            ],
            success_url=f"{app_base_url()}{url_for('dashboard')}?upgraded=1",
            cancel_url=f"{app_base_url()}{url_for('dashboard')}",
            customer_email=user["email"],
            metadata={"user_id": str(user["id"])},
        )
    except Exception as exc:
        app.logger.exception("Stripe checkout session creation failed.")
        return jsonify({"error": f"Unable to start Stripe checkout: {exc}"}), 500

    return jsonify({"checkout_url": checkout_session.url})


@app.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    """Handle Stripe events and keep the user's billing tier in sync."""
    configure_stripe()
    payload = request.get_data(as_text=True)
    signature = request.headers.get("Stripe-Signature")
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET")

    try:
        if webhook_secret:
            event = stripe.Webhook.construct_event(payload, signature, webhook_secret)
        else:
            event = stripe.Event.construct_from(request.get_json(force=True), stripe.api_key)
    except Exception as exc:
        app.logger.warning("Invalid Stripe webhook payload: %s", exc)
        return jsonify({"error": "Invalid webhook payload"}), 400

    event_type = event["type"]
    data = event["data"]["object"]

    if event_type == "checkout.session.completed" and data.get("mode") == "subscription":
        user_id = data.get("metadata", {}).get("user_id")
        if user_id:
            set_user_subscription_state(
                int(user_id),
                "pro",
                customer_id=data.get("customer"),
                subscription_id=data.get("subscription"),
            )

    elif event_type in {"customer.subscription.created", "customer.subscription.updated"}:
        user = find_user_by_billing_reference(
            customer_id=data.get("customer"),
            subscription_id=data.get("id"),
        )
        if user:
            tier = "pro" if data.get("status") in {"active", "trialing", "past_due"} else "free"
            set_user_subscription_state(
                user["id"],
                tier,
                customer_id=data.get("customer"),
                subscription_id=data.get("id"),
            )

    elif event_type in {"customer.subscription.deleted", "customer.subscription.paused"}:
        user = find_user_by_billing_reference(
            customer_id=data.get("customer"),
            subscription_id=data.get("id"),
        )
        if user:
            set_user_subscription_state(
                user["id"],
                "free",
                customer_id=data.get("customer"),
                subscription_id=None,
            )

    return jsonify({"received": True})


# ---------------------------------------------------------------------------
# Diagnostics & Error Logging
# ---------------------------------------------------------------------------

@app.errorhandler(Exception)
def handle_exception(e):
    """Log any unhandled exception to a local file for diagnosis."""
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException) and e.code < 500:
        return e

    import traceback
    error_log_path = os.path.join(DATA_DIR, "last_error.log")
    try:
        with open(error_log_path, "w") as f:
            f.write(f"Exception Type: {type(e).__name__}\n")
            f.write(f"Exception Message: {str(e)}\n\n")
            traceback.print_exc(file=f)
    except Exception as log_err:
        app.logger.error(f"Failed to write to error log: {log_err}")
    
    return jsonify({
        "error": "Internal Server Error",
        "details": str(e)
    }), 500


@app.route("/api/view-error")
def view_last_error():
    """Diagnostic route to view the last server error."""
    if request.args.get("secret") != "asma-debug":
        return "Unauthorized", 401
    
    error_log_path = os.path.join(DATA_DIR, "last_error.log")
    if not os.path.exists(error_log_path):
        return "No errors logged yet."
        
    with open(error_log_path, "r") as f:
        content = f.read()
    return content, 200, {"Content-Type": "text/plain"}


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
