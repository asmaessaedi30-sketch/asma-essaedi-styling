"""
 STYLING.AI — AI Personal Stylist MVP
=====================================
Flask backend for wardrobe management and outfit generation.

Next Phase: Connect to OpenAI API in the `generate_outfit_ai()` route
by replacing the random selection logic with a GPT-4 Vision prompt.

Author: Your Name
Version: 1.0.0 (MVP)
"""

import os
import random
import sqlite3
import json
from functools import wraps
from datetime import datetime

try:
    from openai import OpenAI
except ModuleNotFoundError:
    OpenAI = None
try:
    import stripe
except ModuleNotFoundError:
    stripe = None
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, jsonify, g, flash, send_from_directory
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

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

# Clothing categories used across the app
CATEGORIES = ["tops", "bottoms", "shoes", "outerwear", "accessories"]
PREVIEW_OCCASIONS = [
    "Everyday polish",
    "Work meeting",
    "Date night",
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
# Database Helpers
# ---------------------------------------------------------------------------

DATABASE = os.path.join(DATA_DIR, "stylist.db")


def get_db():
    """Open a database connection scoped to the current request."""
    if "db" not in g:
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


def save_look_preview(user_id, occasion, style_vibe, styling_goal, notes, items):
    """Persist recent look previews so users see ongoing value."""
    db = get_db()
    db.execute(
        """
        INSERT INTO look_previews (user_id, occasion, style_vibe, styling_goal, notes, items_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (user_id, occasion, style_vibe, styling_goal, "\n".join(notes), json.dumps(items))
    )
    db.commit()


def recent_previews_for_user(user_id, limit=6):
    """Fetch recent generated looks for dashboard history."""
    db = get_db()
    rows = db.execute(
        """
        SELECT id, occasion, style_vibe, styling_goal, notes, items_json, created_at
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
        preview["items"] = json.loads(preview.pop("items_json"))
        preview["notes"] = [note for note in preview["notes"].split("\n") if note]
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
        return redirect(url_for("dashboard"))

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
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    """Clear the session and redirect to the landing page."""
    session.clear()
    return redirect(url_for("index"))


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """Let a user request a password reset link."""
    reset_link = None

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

        if user:
            token = build_reset_token(email)
            reset_link = f"{app_base_url()}{url_for('reset_password', token=token)}"
            flash("Password reset link generated below. Open it to set a new password.", "success")
        else:
            flash("We couldn't find an account with that email.", "error")

    return render_template("forgot_password.html", reset_link=reset_link)


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

        if len(password) < 8:
            flash("Use at least 8 characters for your new password.", "error")
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

    if request.method == "POST":
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

        # Save the file with a timestamped, safe filename
        ext      = file.filename.rsplit(".", 1)[1].lower()
        filename = secure_filename(f"{user['id']}_{int(datetime.utcnow().timestamp())}_{name}.{ext}")
        save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
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

    return render_template("add_item.html", user=user, categories=CATEGORIES)


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
# ---------------------------------------------------------------------------

@app.route("/api/generate-outfit", methods=["POST"])
@login_required
def generate_outfit():
    """
    Generate a random outfit from the user's wardrobe.

    Current implementation: randomly selects one top, one bottom, and one pair
    of shoes from the database.

    ─────────────────────────────────────────────
    NEXT PHASE — OpenAI API Integration
    ─────────────────────────────────────────────
    Replace the random selection block below with a call to GPT-4 Vision.
    Suggested approach:

        import openai
        client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])

        # Build a prompt that includes base64-encoded item images and metadata
        # Ask the model to select the most stylistically cohesive combination
        # Parse the JSON response to get selected item IDs

    See: https://platform.openai.com/docs/guides/vision
    ─────────────────────────────────────────────
    """
    user = current_user()
    db   = get_db()

    def pick(category):
        rows = db.execute(
            "SELECT * FROM wardrobe_items WHERE user_id = ? AND category = ?",
            (user["id"], category)
        ).fetchall()
        return dict(random.choice(rows)) if rows else None

    top    = pick("tops")
    bottom = pick("bottoms")
    shoes  = pick("shoes")

    if not any([top, bottom, shoes]):
        return jsonify({"error": "Your wardrobe is empty. Add some items first!"}), 400

    outfit = {"top": top, "bottom": bottom, "shoes": shoes}
    return jsonify({"outfit": outfit, "generated_at": datetime.utcnow().isoformat()})


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

    if len(item_ids) < 2:
        return jsonify({"error": "Select at least two items, like a top and bottom."}), 400

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

    items = [dict(row) for row in rows]
    if len(items) != len(item_ids):
        return jsonify({"error": "One or more selected items could not be found."}), 404

    categories = {item["category"] for item in items}
    if "tops" not in categories or "bottoms" not in categories:
        return jsonify({"error": "Select at least one top and one bottom for the preview."}), 400

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

    image_files = []
    for item in items:
        image_path = os.path.join(app.config["UPLOAD_FOLDER"], item["image_path"])
        if not os.path.exists(image_path):
            return jsonify({"error": f"Missing image for {item['name']}."}), 500
        with open(image_path, "rb") as image_file:
            image_files.append((item["image_path"], image_file.read(), "image/jpeg"))

    try:
        result = client.images.edit(
            model=os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-1.5"),
            image=[(name, content, mime_type) for name, content, mime_type in image_files],
            prompt=prompt,
            size="1024x1536",
        )
        image_b64 = result.data[0].b64_json
    except Exception as exc:
        app.logger.exception("OpenAI try-on preview failed.")
        return jsonify({"error": f"Unable to create AI preview: {exc}"}), 500

    notes = build_style_notes(items, occasion, style_vibe, styling_goal)
    save_look_preview(user["id"], occasion, style_vibe, styling_goal, notes, items)

    return jsonify({
        "image_data_url": f"data:image/png;base64,{image_b64}",
        "selected_items": items,
        "occasion": occasion,
        "style_vibe": style_vibe,
        "styling_goal": styling_goal,
        "notes": notes,
        "recent_previews": recent_previews_for_user(user["id"]),
    })


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
# Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
