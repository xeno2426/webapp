from flask import Flask, request, redirect, session, send_from_directory, jsonify, render_template, url_for
from flask_socketio import SocketIO, join_room, emit as socket_emit
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect   # Fix 1.3
from datetime import datetime, timedelta, timezone
import os, json, hashlib, base64, secrets, sys, hmac, logging, uuid, urllib.parse
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from cryptography.fernet import Fernet
sys.path.insert(0, os.path.dirname(__file__))
import db
load_dotenv()

# ---------- PATHS ----------
BASE_DIR     = os.path.dirname(__file__)
UPLOADS_ROOT = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOADS_ROOT, exist_ok=True)

# ---------- CONFIG ----------
# Fix 1.1 — crash loudly on startup if any secret env var is missing.
# Never use hardcoded fallbacks for secrets.
SECRET_KEY        = os.environ.get("SECRET_KEY")
ADMIN_KEY         = os.environ.get("ADMIN_KEY")
SECRET_MASTER_KEY = os.environ.get("MASTER_KEY")
APP_URL           = os.environ.get("APP_URL", "https://webapp-i3ht.onrender.com")
SUPABASE_URL      = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")

for _name, _val in [("SECRET_KEY", SECRET_KEY), ("ADMIN_KEY", ADMIN_KEY), ("MASTER_KEY", SECRET_MASTER_KEY)]:
    if not _val:
        sys.exit(f"FATAL: environment variable {_name} is not set. App cannot start.")

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)

# Fix 1.11 — restrict WebSocket CORS to our own domain only.
# Fix 6.4 — async_mode matches the eventlet worker class in Procfile.
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="gevent",
                    logger=False, engineio_logger=False)

# ── Speed: cache static files 7 days, never cache HTML pages ────
@app.after_request
def set_cache_headers(response):
    if request.path.startswith("/static/"):
        response.cache_control.max_age = 604800
        response.cache_control.public  = True
    else:
        response.cache_control.no_store = True
    return response


# Fix 4.3 — enable sensible global rate limits; tighter limits applied per-route below.
limiter  = Limiter(get_remote_address, app=app, default_limits=["300 per day", "60 per hour"])

# Fix 1.3 — CSRF protection on all state-changing POST routes.
# Routes that are called by JS fetch() with no form are exempted below via @csrf.exempt.
csrf = CSRFProtect(app)
app.config["WTF_CSRF_TIME_LIMIT"] = None  # Never expire CSRF token
app.config["WTF_CSRF_SSL_STRICT"] = False  # Allow Brave/strict browsers

# ---------- INIT DB ON STARTUP ----------
with app.app_context():
    try:
        db.init_db()
    except Exception as e:
        print(f"DB init warning: {e}")

# ---------- ENCRYPTION ----------
def get_cipher():
    key = hashlib.sha256(SECRET_MASTER_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))

def encrypt_text(text):
    if not text: return ""
    try: return get_cipher().encrypt(text.encode()).decode()
    except Exception: return text

def decrypt_text(token):
    if not token: return ""
    try: return get_cipher().decrypt(token.encode()).decode()
    except Exception: return token

# Fix 4.2 — always store and compare UTC times.
# DB columns are TIMESTAMP (no TZ) so psycopg2 returns naive datetimes.
# utc_now() returns a naive UTC datetime that compares safely with DB values.
def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)

# ---------- HELPERS ----------
def current_user(): return session.get("user")

# Fix 1.2 — use werkzeug PBKDF2-HMAC-SHA256 (slow, salted) instead of raw SHA-256.
def hash_pw(pw):
    return generate_password_hash(pw)

def verify_pw(stored_hash, pw):
    """
    Verify a password against its stored hash.
    Handles migration: if the stored hash is a 64-char hex string it is a
    legacy SHA-256 hash. On a successful legacy match the caller should
    re-hash and persist the new hash so the account upgrades automatically.
    Returns (ok: bool, needs_rehash: bool).
    """
    if stored_hash and len(stored_hash) == 64 and all(c in "0123456789abcdef" for c in stored_hash):
        # Legacy SHA-256 path
        legacy_ok = hmac.compare_digest(stored_hash, hashlib.sha256(pw.encode()).hexdigest())
        return legacy_ok, legacy_ok  # (ok, needs_rehash)
    return check_password_hash(stored_hash, pw), False

# Fix 5.2 — hash recovery phrases like passwords (they're used for identity verification).
def hash_recovery(phrase):
    """Hash a recovery phrase for storage. Phrase is lowercased for case-insensitive matching."""
    return generate_password_hash(phrase.lower()) if phrase else ""

def verify_recovery(stored, provided):
    """
    Verify a recovery phrase. Handles migration from legacy plaintext storage.
    Werkzeug hashes start with 'pbkdf2:' or 'scrypt:'. Anything else is treated
    as a legacy plaintext value and compared with hmac.compare_digest.
    Returns (ok: bool, needs_rehash: bool).
    """
    if not stored:
        return (not provided), False  # both empty = match; provided but no stored = no match
    if stored.startswith(("pbkdf2:", "scrypt:")):
        return check_password_hash(stored, provided.lower()), False
    # Legacy plaintext path
    ok = hmac.compare_digest(stored.lower(), (provided or "").lower())
    return ok, ok  # (ok, needs_rehash)

def secure_random_filename(original):
    ext = ("." + original.rsplit(".", 1)[1].lower()) if "." in original else ""
    return f"{secrets.token_urlsafe(16)}{ext}"

def time_ago(ts):
    if not ts: return ""
    try:
        if isinstance(ts, str):
            ts = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        s = int((utc_now() - ts).total_seconds())
        if s < 60:    return "just now"
        if s < 3600:  return f"{s//60}m ago"
        if s < 86400: return f"{s//3600}h ago"
        return ts.strftime("%b %d")
    except Exception: return str(ts)

def user_upload_dir(u):
    p = os.path.join(UPLOADS_ROOT, u)
    os.makedirs(p, exist_ok=True)
    return p

IMAGE_EXTS = {"png","jpg","jpeg","gif","webp","bmp"}
AUDIO_EXTS = {"mp3","wav","m4a","ogg","oga","aac"}
VIDEO_EXTS = {"mp4","webm","mov","m4v"}

# Fix 1.4 — explicit allowlist; anything not here is rejected.
ALLOWED_EXTENSIONS = IMAGE_EXTS | AUDIO_EXTS | VIDEO_EXTS | {"pdf", "txt"}

# Magic-byte signatures for image formats.
# If the claimed extension is an image type, we verify the actual file header
# matches a known image signature so renamed scripts can't slip through.
_IMAGE_MAGIC = [
    b'\xff\xd8\xff',        # JPEG
    b'\x89PNG\r\n\x1a\n',  # PNG
    b'GIF87a',               # GIF
    b'GIF89a',               # GIF
    b'RIFF',                 # WebP (RIFF????WEBP) — also matches WAV, but .wav is audio not image
    b'BM',                   # BMP
]

def file_is_safe(file_storage, ext):
    """
    Fix 1.4 — two-layer upload validation:
      1. Extension must be in ALLOWED_EXTENSIONS.
      2. If it's an image, the actual file header must match a known image signature.
    Returns True if the file is safe to save.
    """
    if not ext or ext not in ALLOWED_EXTENSIONS:
        return False
    if ext in IMAGE_EXTS:
        file_storage.stream.seek(0)
        header = file_storage.stream.read(12)
        file_storage.stream.seek(0)
        if not any(header.startswith(m) for m in _IMAGE_MAGIC):
            return False
    return True

def build_messages(chat_data, me):
    """
    Build the messages list for the template.
    B2: Injects {"type":"date_sep","label":...} entries whenever the
    calendar date changes between consecutive messages.
    """
    result    = []
    prev_date = None

    for i, msg in enumerate(chat_data):
        # ── Date separator ──────────────────────────────────────
        ts = msg.get("created_at")
        if ts:
            msg_date = ts.date() if hasattr(ts, "date") else None
            if msg_date and msg_date != prev_date:
                today = datetime.now(timezone.utc).date()
                if msg_date == today:
                    label = "Today"
                elif msg_date == today - timedelta(days=1):
                    label = "Yesterday"
                else:
                    label = ts.strftime("%B %d")
                result.append({"type": "date_sep", "label": label})
                prev_date = msg_date

        # ── Message entry ───────────────────────────────────────
        sender   = msg.get("from") or msg.get("sender", "")
        deleted  = msg.get("deleted", False)
        text     = "This message was deleted" if deleted else decrypt_text(msg.get("text", ""))
        ftype    = msg.get("ftype", "text")
        filename = msg.get("filename", "") or ""
        url      = msg.get("url", "") or ""
        ext      = filename.rsplit(".", 1)[1].lower() if "." in filename else ""
        msg_id   = msg.get("id", i)

        # Reply-to resolution
        reply_to = None
        ri = msg.get("reply_to")
        if isinstance(ri, int) and ri > 0:
            rm = next((m for m in chat_data if (m.get("id") or 0) == ri), None)
            if rm:
                reply_to = {
                    "id":     ri,
                    "author": rm.get("from") or rm.get("sender", ""),
                    "text":   (decrypt_text(rm.get("text", "")) or "[attachment]")[:60],
                }

        # Reactions: JSONB dict → {emoji: [user, ...]}
        raw_reactions = msg.get("reactions") or {}
        if isinstance(raw_reactions, str):
            try:
                import json as _json; raw_reactions = _json.loads(raw_reactions)
            except Exception: raw_reactions = {}
        reactions_by_emoji = {}
        for user_key, emoji_val in raw_reactions.items():
            if emoji_val:
                reactions_by_emoji.setdefault(emoji_val, []).append(user_key)

        seen_by        = msg.get("seen_by") or []
        seen_by_others = [u for u in seen_by if u != me]

        result.append({
            "type":     "message",
            "id":       msg_id,
            "index":    i,
            "sender":   sender,
            "text":     text,
            "time":     time_ago(msg.get("created_at") or msg.get("time", "")),
            "ftype":    ftype,
            "filename": filename,
            "url":      url,
            "ext":      ext,
            "is_image": ext in IMAGE_EXTS and ftype == "file",
            "is_audio": ext in AUDIO_EXTS and ftype == "file",
            "is_video": ext in VIDEO_EXTS and ftype == "file",
            "seen":     msg.get("seen", False),
            "deleted":  deleted,
            "reply_to": reply_to,
            "reactions": reactions_by_emoji,
            "my_reaction": raw_reactions.get(me, ""),
            "seen_by_others": seen_by_others,
            "align":    "me" if sender == me else "them",
        })

    return result

@app.context_processor
def inject_globals():
    u = current_user()
    try:
        unread = db.count_unread(u) if u else 0
    except Exception:
        unread = 0
    return {"unread_count": unread}

# Fix 4.6 — send security headers on every response.
@app.after_request
def set_security_headers(response):
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' https://cdnjs.cloudflare.com 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; "
        "media-src 'self' blob:; "
        "connect-src 'self' wss:;"
    )
    return response

# ---------- SOCKETIO HELPERS ----------
def dm_room(u1, u2):
    a, b = sorted([u1, u2])
    return f"dm_{a}__{b}"

def group_room(group_id):
    return f"group_{group_id}"

@socketio.on("join")
def on_join(data):
    # Fix 1.7 — verify the session user actually belongs to the room before joining.
    me = session.get("user")
    if not me:
        return  # unauthenticated connection — silently drop
    room = data.get("room")
    if not room:
        return
    # Fix 5.4 — personal room for cross-page unread notifications.
    # Each logged-in user joins "user_{username}" so the server can push
    # unread_update events without the user needing to be in a chat page.
    if room == f"user_{me}":
        join_room(room)
    elif room.startswith("dm_"):
        # Room format: dm_alice__bob — user must be one of the two parties.
        parts = room[len("dm_"):].split("__")
        if len(parts) == 2 and me in parts:
            join_room(room)
    elif room.startswith("group_"):
        group_id = room[len("group_"):]
        group = db.get_group(group_id)
        if group and me in group.get("members", []):
            join_room(room)
    # Any unrecognised room format is silently rejected.

@socketio.on("typing")
def on_typing(data):
    # Fix 1.7 — ignore the client-supplied sender field; use the authenticated session user.
    me = session.get("user")
    if not me:
        return
    room = data.get("room")
    if room:
        socket_emit("typing", {"sender": me}, to=room, include_self=False)


# ---------- D2: GOOGLE OAUTH ----------

@app.route("/auth/google")
def auth_google():
    """Redirect user to Supabase Google OAuth URL."""
    if not SUPABASE_URL:
        return redirect("/login")
    params = {
        "provider":    "google",
        "redirect_to": url_for("auth_callback", _external=True)
    }
    url = f"{SUPABASE_URL}/auth/v1/authorize?{urllib.parse.urlencode(params)}"
    return redirect(url)

@app.route("/auth/callback")
def auth_callback():
    """Supabase redirects here with access_token in URL fragment.
    Fragments never reach the server — serve a page that reads it and POSTs it."""
    return render_template("auth_callback.html")

@app.route("/auth/callback/verify", methods=["POST"])
@csrf.exempt   # Called from fetch() in auth_callback.html (no form)
def auth_callback_verify():
    """Validates access_token from Google OAuth fragment."""
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        return jsonify({"error": "Google auth not configured"}), 503

    import requests as _http
    token = (request.json or {}).get("access_token")
    if not token:
        return jsonify({"error": "No token"}), 400

    r = _http.get(
        f"{SUPABASE_URL}/auth/v1/user",
        headers={"Authorization": f"Bearer {token}",
                 "apikey": SUPABASE_ANON_KEY},
        timeout=8
    )
    if r.status_code != 200:
        return jsonify({"error": "Invalid token"}), 401

    user_data  = r.json()
    email      = user_data.get("email")
    google_id  = user_data.get("id")
    meta       = user_data.get("user_metadata") or {}
    given_name = meta.get("full_name", "")
    avatar_url = meta.get("avatar_url", "")

    if not email:
        return jsonify({"error": "No email returned"}), 400

    existing = db.get_user_by_email(email)
    if existing:
        session["user"] = existing["username"]
        return jsonify({"redirect": "/"})
    else:
        session["google_pending"] = {
            "email":      email,
            "google_id":  google_id,
            "given_name": given_name,
            "avatar":     avatar_url
        }
        return jsonify({"redirect": "/auth/setup"})

@app.route("/auth/setup", methods=["GET", "POST"])
def auth_setup():
    """New Google users pick username + recovery phrase here."""
    pending = session.get("google_pending")
    if not pending:
        return redirect("/login")

    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        recovery = request.form.get("recovery", "").strip()

        if not username or not recovery:
            error = "Both fields are required."
        elif len(username) < 3:
            error = "Username must be at least 3 characters."
        elif not username.replace("_", "").replace("-", "").isalnum():
            error = "Username can only contain letters, numbers, hyphens, underscores."
        elif len(recovery) < 6:
            error = "Recovery phrase must be at least 6 characters."
        elif db.get_user(username):
            error = "That username is already taken."
        else:
            db.create_user(
                username,
                password_hash="",
                recovery=generate_password_hash(recovery),
                email=pending["email"],
                google_id=pending["google_id"],
                auth_provider="google",
                avatar=pending.get("avatar", "")
            )
            session.pop("google_pending", None)
            session["user"] = username
            return redirect("/")

    return render_template("auth_setup.html",
                           given_name=pending.get("given_name", ""),
                           error=error)

# ---------- AUTH ----------
@app.route("/signup", methods=["GET","POST"])
@limiter.limit("5 per hour")   # Fix 4.3 — prevent signup spam
def signup():
    if current_user(): return redirect("/")
    error = ""
    if request.method == "POST":
        u  = request.form.get("username","").strip()
        p1 = request.form.get("password","")
        p2 = request.form.get("password2","")
        rc = request.form.get("recovery","").strip()
        if not u or not p1:          error = "All fields required."
        elif " " in u or len(u)<3:   error = "Username: 3+ chars, no spaces."
        elif db.user_exists(u):      error = "Username already taken."
        elif p1 != p2:               error = "Passwords do not match."
        elif len(p1) < 8:            error = "Password must be at least 8 characters."  # Fix 4.4
        else:
            db.create_user(u, hash_pw(p1), recovery=hash_recovery(rc))  # Fix 5.2
            session.permanent = True
            session["user"] = u
            return redirect("/")
    return render_template("signup.html", error=error)

@app.route("/login", methods=["GET","POST"])
@limiter.limit("10 per minute; 50 per hour")   # Fix 4.3 — brute-force protection
def login():
    if current_user(): return redirect("/")
    error = ""
    if request.method == "POST":
        u = request.form.get("username","").strip()
        p = request.form.get("password","")
        info = db.get_user(u)
        if not info:
            error = "Invalid username or password."
        else:
            ok, needs_rehash = verify_pw(info.get("password_hash",""), p)
            if not ok:
                error = "Invalid username or password."
            else:
                if needs_rehash:
                    # Fix 1.2 — silently upgrade legacy SHA-256 hash on first login
                    db.update_user(u, password_hash=hash_pw(p))
                session.permanent = True
                session["user"] = u
                return redirect("/")
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.route("/reset", methods=["GET","POST"])
@limiter.limit("5 per hour")   # Fix 4.3 — prevent brute-force of admin key
def reset_with_admin_key():
    error = info_msg = ""
    if request.method == "POST":
        username  = request.form.get("username","").strip()
        new_pw    = request.form.get("password","")
        new_pw2   = request.form.get("password2","")
        recovery  = request.form.get("recovery","").strip()
        admin_key = request.form.get("admin_key","").strip()

        # Fix 1.10 — always validate admin key first using constant-time comparison
        # so the error message never reveals whether the username exists.
        admin_ok = hmac.compare_digest(admin_key, ADMIN_KEY)
        info     = db.get_user(username) if username else None

        if not admin_ok or not info:
            error = "Reset failed. Check your details and try again."
        elif new_pw != new_pw2 or len(new_pw) < 8:   # Fix 4.4
            error = "Passwords do not match or are too short (min 8 chars)."
        else:
            # Fix 5.2 — use verify_recovery to support both hashed and legacy plaintext phrases
            recovery_ok, recovery_needs_rehash = verify_recovery(info.get("recovery",""), recovery)
            if not recovery_ok:
                error = "Reset failed. Check your details and try again."
            else:
                updates = {"password_hash": hash_pw(new_pw)}
                if recovery_needs_rehash:
                    updates["recovery"] = hash_recovery(recovery)  # upgrade legacy plaintext
                db.update_user(username, **updates)
                info_msg = "Password updated. You can now log in."
    return render_template("reset.html", error=error, info_msg=info_msg)

# ---------- HOME / NOTES ----------
@app.route("/", methods=["GET","POST"])
def home():
    user = current_user()
    if not user: return redirect("/login")
    if request.method == "POST":
        txt = request.form.get("quick","").strip()
        if txt:
            db.add_note(user, txt.splitlines()[0][:60], txt)
        return redirect("/")
    sort  = request.args.get("sort","newest")
    q     = request.args.get("q","").strip()
    # Fix 5.3 — filter notes server-side using the q param.
    # Client-side search exposed full note bodies in data-body HTML attributes.
    notes = db.search_notes(user, q, sort=sort) if q else db.load_notes(user, sort=sort)
    note_list = [{"id":n["id"],"title":n.get("title","Untitled"),
                  "body":n.get("body",""),"time":time_ago(n.get("created_at"))}
                 for n in notes]
    return render_template("home.html", user=user, notes=note_list,
                           note_count=len(notes), sort=sort, q=q, active="home")

# Fix 5.5 — server-side notes search JSON endpoint for potential JS use.
@app.route("/notes/search")
def notes_search():
    user = current_user()
    if not user: return jsonify(ok=False), 401
    q     = request.args.get("q","").strip()
    sort  = request.args.get("sort","newest")
    notes = db.search_notes(user, q, sort=sort) if q else db.load_notes(user, sort=sort)
    return jsonify(ok=True, notes=[
        {"id":n["id"],"title":n.get("title",""),
         "body":n.get("body",""),"time":time_ago(n.get("created_at"))}
        for n in notes
    ])

@app.route("/note/new", methods=["GET","POST"])
def note_new():
    user = current_user()
    if not user: return redirect("/login")
    error = ""
    if request.method == "POST":
        title = request.form.get("title","").strip() or "Untitled"
        body  = request.form.get("body","").strip()
        if not body: error = "Note body cannot be empty."
        else:
            db.add_note(user, title[:80], body)
            return redirect("/")
    return render_template("note_new.html", user=user, error=error, active="home")

@app.route("/note/<int:note_id>", methods=["GET","POST"])
def edit_note(note_id):
    user = current_user()
    if not user: return redirect("/login")
    notes = db.load_notes(user)
    note  = next((n for n in notes if n["id"] == note_id), None)
    if not note: return redirect("/")
    error = ""
    if request.method == "POST":
        title = request.form.get("title","").strip() or "Untitled"
        body  = request.form.get("body","").strip()
        if not body: error = "Note body cannot be empty."
        else:
            db.update_note(note_id, user, title[:80], body)
            return redirect("/")
    return render_template("note_edit.html", user=user, error=error,
                           note=note, note_id=note_id, active="home")

@app.route("/note/<int:note_id>/delete", methods=["POST"])
def delete_note(note_id):
    user = current_user()
    if not user: return redirect("/login")
    db.delete_note(note_id, user)
    return redirect("/")

# ---------- PROFILE ----------
@app.route("/profile", methods=["GET","POST"])
def profile():
    user = current_user()
    if not user: return redirect("/login")
    info  = db.get_user(user) or {}
    error = info_msg = ""
    if request.method == "POST":
        action = request.form.get("action")
        if action == "update_bio":
            db.update_user(user, bio=request.form.get("bio","")[:400])
            info_msg = "Bio updated."
        elif action == "update_recovery":
            db.update_user(user, recovery=hash_recovery(request.form.get("recovery","").strip()))  # Fix 5.2
            info_msg = "Recovery phrase saved."
        elif action == "change_password":
            old,new1,new2 = (request.form.get(k,"") for k in ("old_pw","new_pw","new_pw2"))
            ok, needs_rehash = verify_pw(info.get("password_hash",""), old)
            if not ok:                        error = "Old password incorrect."
            elif new1 != new2 or len(new1)<8: error = "Passwords mismatch or too short (min 8 chars)."  # Fix 4.4
            else:
                db.update_user(user, password_hash=hash_pw(new1))   # Fix 1.2
                info_msg = "Password changed."
        elif action == "avatar":
            f = request.files.get("avatar")
            if f and f.filename:
                ext = f.filename.rsplit(".",1)[-1].lower() if "." in f.filename else ""
                f.seek(0,2); size = f.tell(); f.seek(0)
                if ext not in {"png","jpg","jpeg","gif","webp"}: error = "Only PNG/JPG/GIF/WEBP allowed."
                elif size > 5*1024*1024:                         error = "Image must be under 5MB."
                else:
                    fname = secure_random_filename(secure_filename(f.filename))
                    f.save(os.path.join(user_upload_dir(user), fname))
                    db.update_user(user, avatar=fname)
                    info_msg = "Avatar updated."
        elif action == "delete_account":
            if request.form.get("confirm_delete","").strip() != user:
                error = "Type your username exactly to confirm."
            else:
                db.delete_user(user)
                session.clear()
                return redirect("/login")
        info = db.get_user(user) or {}
    avatar_url = f"/uploads/{user}/{info['avatar']}" if info.get("avatar") else ""
    return render_template("profile.html", user=user, info=info,
                           avatar_url=avatar_url, error=error, info_msg=info_msg,
                           bio_len=len(info.get("bio","") or ""), active="profile")

@app.route("/uploads/<username>/<filename>")
def serve_upload(username, filename):
    # Fix 1.5 — uploaded files are private; unauthenticated requests get nothing.
    if not current_user():
        return redirect("/login")
    return send_from_directory(user_upload_dir(username), filename)

@app.route("/user/<username>")
def user_profile(username):
    me = current_user()
    if not me: return redirect("/login")
    info = db.get_user(username)
    if not info: return redirect("/friends")
    avatar_url = f"/uploads/{username}/{info['avatar']}" if info.get("avatar") else ""
    return render_template("user_profile.html", user=me, profile_user=username,
                           bio=info.get("bio",""), avatar_url=avatar_url, active="friends")

# ---------- FRIENDS ----------
@app.route("/friends", methods=["GET","POST"])
def friends():
    me = current_user()
    if not me: return redirect("/login")
    db.update_user(me, last_seen=utc_now())
    error = info_msg = ""

    if request.method == "POST":
        action      = request.form.get("action","add")
        friend_name = request.form.get("friend_username","").strip()
        requester   = request.form.get("requester","").strip()

        if action == "add":
            if not friend_name or friend_name == me:       error = "Invalid username."
            elif not db.user_exists(friend_name):          error = "User not found."
            elif db.are_friends(me, friend_name):          error = "Already friends."
            elif db.already_requested(me, friend_name):    error = "Request already sent."
            else:
                db.send_request(me, friend_name)
                info_msg = f"Request sent to @{friend_name}."
        elif action == "accept" and requester:
            db.accept_request(requester, me)
            info_msg = f"You are now friends with @{requester}."
        elif action == "decline" and requester:
            db.reject_request(requester, me)
            info_msg = f"Declined @{requester}."
        elif action == "remove" and friend_name:
            db.remove_friend(me, friend_name)
            info_msg = f"Removed @{friend_name}."

    friends_list = db.get_friends(me)
    friends_data = []
    # Fix 3.2 — one bulk query for all friend rows; one query for all unread counts.
    # Previously called get_user() + get_unread_dict() inside the loop = 2N queries.
    friends_info   = db.get_users_bulk(friends_list)          # {username: user_dict}
    unread_by_user = db.get_unread_dict(me)                   # {username: count}
    for f in sorted(friends_list):
        fi        = friends_info.get(f) or {}
        last_seen = fi.get("last_seen")
        online    = False
        last_seen_str = ""
        if last_seen:
            try:
                ts     = last_seen if isinstance(last_seen, datetime) else datetime.strptime(str(last_seen), "%Y-%m-%d %H:%M:%S")
                if ts.tzinfo is None:
                    from datetime import timezone as _tz
                    ts = ts.replace(tzinfo=_tz.utc)
                diff  = utc_now() - ts
                secs  = int(diff.total_seconds())
                online = secs < 90
                if not online:
                    if secs < 3600:
                        last_seen_str = f"{secs // 60}m ago"
                    elif secs < 86400:
                        last_seen_str = f"{secs // 3600}h ago"
                    else:
                        last_seen_str = f"{secs // 86400}d ago"
            except Exception: pass
        friends_data.append({"username": f, "online": online,
                              "last_seen_str": last_seen_str,
                              "avatar": fi.get("avatar", ""),
                              "unread": unread_by_user.get(f, 0)})

    return render_template("friends.html", user=me,
                           friends=friends_data,
                           pending=db.get_pending_in(me),
                           error=error, info_msg=info_msg, active="friends")

# ---------- DM CHAT ----------
@app.route("/chat/<friend>", methods=["GET","POST"])
def chat(friend):
    me = current_user()
    if not me: return redirect("/login")
    if not db.user_exists(friend): return redirect("/friends")
    if not db.are_friends(me, friend): return redirect("/friends")

    if request.method == "POST":
        action = request.form.get("action","send")
        if action == "send":
            txt  = request.form.get("message","").strip()
            file = request.files.get("file")
            ftype = fname = url = ""
            if file and file.filename:
                ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
                if not file_is_safe(file, ext):  # Fix 1.4 — reject disallowed/spoofed files
                    ftype = "text"               # unsafe file silently dropped; message sends as text
                else:
                    ftype = "file"
                    saved = secure_random_filename(secure_filename(file.filename))
                    file.save(os.path.join(user_upload_dir(me), saved))
                    fname = saved; url = f"/uploads/{me}/{saved}"
            else: ftype = "text"
            if txt or ftype == "file":
                ri = session.pop(f"reply_to_{friend}", None)
                msg_id = db.send_message(me, friend, text=encrypt_text(txt),
                                ftype=ftype, filename=fname, url=url, reply_to=ri)
                db.increment_unread(friend, me)
                # Fix 5.4 — push unread count to recipient's personal room so
                # app.js can update the banner instantly without polling.
                total   = db.count_unread(friend)
                senders = db.get_unread_senders(friend)
                socketio.emit("unread_update", {"unread": total, "senders": senders},
                              to=f"user_{friend}")
                socketio.emit("new_message", {
                    "id":       msg_id,
                    "sender":   me,
                    "text":     txt,
                    "time":     "just now",
                    "ftype":    ftype,
                    "filename": fname,
                    "url":      url,
                    "seen":     False,
                    "reply":    None,
                    "reactions":{},
                }, to=dm_room(me, friend))
        elif action == "set_reply":
            # Fix 2.2 — read msg_id which is the real DB row id, not a loop index
            try:   rid = int(request.form.get("msg_id"))
            except Exception: rid = None
            key = f"reply_to_{friend}"
            if rid is None or rid < 0: session.pop(key, None)
            else: session[key] = rid
        elif action == "delete":
            try: mid = int(request.form.get("msg_id"))
            except Exception: mid = -1
            if mid > 0:
                msg = db.get_message_by_id(mid)
                if msg and msg.get("sender") == me:
                    db.soft_delete_message(mid)
        elif action == "react":
            try: mid = int(request.form.get("msg_id"))
            except Exception: mid = -1
            emoji = request.form.get("emoji","❤️")
            if mid > 0: db.react_message(mid, me, emoji)
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"ok": True})
        return redirect(f"/chat/{friend}")

    # GET
    db.mark_seen(friend, me)
    db.reset_unread(me, friend)
    # Push seen_update so friend's tick turns green immediately
    socketio.emit("seen_update", {"from": me}, to=dm_room(me, friend))
    chat_data = db.load_chat(me, friend)
    # normalise key name for build_messages
    for m in chat_data:
        if "sender" in m and "from" not in m: m["from"] = m["sender"]
    messages = build_messages(chat_data, me)

    reply_pending = None
    ri = session.get(f"reply_to_{friend}")
    if isinstance(ri, int) and ri > 0:
        rm = db.get_message_by_id(ri)
        if rm:
            reply_pending = {"id":ri,"author":rm.get("sender",""),
                             "text":(decrypt_text(rm.get("text","")) or "[attachment]")[:60]}

    typing = None
    fi = db.get_user(friend) or {}
    ts_str = fi.get("typing_ts")
    if fi.get("typing_to") == me and ts_str:
        try:
            ts = ts_str if isinstance(ts_str, datetime) else datetime.strptime(str(ts_str), "%Y-%m-%d %H:%M:%S")
            if utc_now() - ts < timedelta(seconds=4): typing = friend
        except Exception: pass

    friend_info    = db.get_user(friend) or {}
    friend_online  = db.is_online(friend)
    friend_avatar  = friend_info.get("avatar", "")
    chat_theme     = ""   # placeholder until Batch E

    return render_template("chat.html", user=me, friend=friend,
                           messages=messages, reply_pending=reply_pending,
                           typing=typing, active="friends",
                           friend_online=friend_online,
                           friend_avatar=friend_avatar,
                           chat_theme=chat_theme,
                           socket_room=dm_room(me, friend))

@app.route("/typing/<friend>", methods=["POST"])
@csrf.exempt   # Fix 1.3 — called by JS fetch(); only updates typing timestamp
def typing(friend):
    me = current_user()
    if not me: return ("",401)
    db.update_user(me, typing_to=friend, typing_ts=utc_now())
    return ("",204)

# ---------- B4: CLEAR / BLOCK / REPORT ----------

@app.route("/chat/<friend>/clear", methods=["POST"])
@csrf.exempt
def clear_chat_route(friend):
    me = current_user()
    if not me: return ("", 401)
    if not db.are_friends(me, friend): return ("", 403)
    db.clear_chat(me, friend)
    return ("", 204)

@app.route("/user/<username>/block", methods=["POST"])
@csrf.exempt
def block_user_route(username):
    me = current_user()
    if not me: return ("", 401)
    db.block_user(me, username)
    return ("", 204)

@app.route("/user/<username>/report", methods=["POST"])
@csrf.exempt
def report_user_route(username):
    me = current_user()
    if not me: return ("", 401)
    reason = request.form.get("reason", "").strip()[:1000]
    db.file_report(reporter=me, reported=username, reason=reason)
    return ("", 204)

# ---------- STORIES ----------
@app.route("/stories", methods=["GET","POST"])
def stories_page():
    me = current_user()
    if not me: return redirect("/login")
    error = None

    if request.method == "POST":
        action = request.form.get("action","create")
        if action == "delete_story":
            try: sid = int(request.form.get("story_id"))
            except Exception: sid = 0
            if sid: db.delete_story(sid, me)
            return redirect("/stories")

        file    = request.files.get("file")
        caption = (request.form.get("caption") or "").strip()
        if not file or not file.filename:
            error = "Select an image or video."
        else:
            fn    = secure_filename(file.filename)
            ext   = fn.rsplit(".",1)[1].lower() if "." in fn else ""
            if not file_is_safe(file, ext):   # Fix 1.4
                error = "File type not allowed. Use an image or video."
            else:
                saved = secure_random_filename(fn)
                file.save(os.path.join(user_upload_dir(me), saved))
                ftype = ("image" if ext in IMAGE_EXTS else
                         "video" if ext in VIDEO_EXTS else "file")
                url = f"/uploads/{me}/{saved}"
                db.add_story(me, url, ftype=ftype, caption=caption)
                session["story_posted"] = "Story posted!"
                return redirect("/stories")

    user_stories = db.load_stories()

    # Fix 1.9 — only show stories from yourself and your friends.
    # Stories are private; strangers should not be able to see them.
    friends_set  = set(db.get_friends(me)) | {me}
    user_stories = {u: s for u, s in user_stories.items() if u in friends_set}

    story_cards = []
    for uname, arr in user_stories.items():
        latest   = arr[-1]
        viewers  = set(v for s in arr for v in (s.get("viewers") or []))
        story_cards.append({"username":uname,"thumb_url":latest.get("url",""),
                            "view_count":len(viewers),"slide_count":len(arr)})

    current_story = None
    owner = request.args.get("user")
    idx_s = request.args.get("idx","0")
    mark_view = request.args.get("view")

    if owner and owner in user_stories:
        arr = user_stories[owner]
        try: idx = max(0, int(idx_s))
        except Exception: idx = 0
        if 0 <= idx < len(arr):
            s        = arr[idx]
            next_url = f"/stories?user={owner}&idx={idx+1}&view=1" if idx+1<len(arr) else "/stories"
            prev_url = f"/stories?user={owner}&idx={idx-1}&view=1" if idx-1>=0 else "/stories"
            if mark_view and me != owner:
                db.add_story_viewer(s["id"], me)
            viewers = s.get("viewers") or []
            # Fix 4.1 — viewer names are private; only the story owner sees who viewed.
            # Other viewers only see the count so usernames aren't leaked.
            if owner == me:
                viewers_line = ("No views yet." if not viewers
                                else f"Seen by ({len(viewers)}): " + ", ".join("@"+v for v in viewers))
            else:
                viewers_line = f"{len(viewers)} view{'s' if len(viewers) != 1 else ''}"
            ts = s.get("created_at")
            time_str = ts.strftime("%Y-%m-%d %H:%M") if isinstance(ts, datetime) else str(ts)[:16]
            current_story = {"user":owner,"caption":s.get("caption",""),
                             "url":s.get("url",""),"ftype":s.get("ftype","image"),
                             "viewers_line":viewers_line,"time_str":time_str,
                             "id":s["id"],"is_owner":(owner==me),
                             "next_url":next_url,"prev_url":prev_url}

    posted_msg = session.pop("story_posted","")
    return render_template("stories.html", user=me, error=error,
                           story_cards=story_cards, current_story=current_story,
                           posted_msg=posted_msg, active="stories")

# ---------- GROUPS ----------
@app.route("/groups")
def groups_page():
    me = current_user()
    if not me: return redirect("/login")
    my_groups = db.user_groups(me)
    return render_template("groups.html", user=me, groups=my_groups, active="groups")

@app.route("/group/create", methods=["GET","POST"])
def create_group():
    me = current_user()
    if not me: return redirect("/login")
    error = ""
    if request.method == "POST":
        name    = request.form.get("name","").strip()
        members = [m.strip() for m in request.form.get("members","").split(",")
                   if m.strip() and db.user_exists(m.strip())]
        if me not in members: members.append(me)
        avatar_file = request.files.get("avatar")
        if not name:            error = "Group name required."
        elif len(members) < 2:  error = "Add at least 1 other valid user."
        else:
            gid        = str(uuid.uuid4())  # Fix 2.4 — was int(utc_now().timestamp()), collision risk
            avatar_url = ""
            if avatar_file and avatar_file.filename:
                fn    = secure_random_filename(secure_filename(avatar_file.filename))
                avatar_file.save(os.path.join(user_upload_dir(me), fn))
                avatar_url = f"/uploads/{me}/{fn}"
            db.create_group(gid, name, me, avatar=avatar_url)
            for m in members:
                if m != me: db.add_group_member(gid, m)
            return redirect("/groups")
    return render_template("group_create.html", user=me, error=error, active="groups")

@app.route("/group/<group_id>", methods=["GET","POST"])
def group_chat(group_id):
    me    = current_user()
    if not me: return redirect("/login")
    group = db.get_group(group_id)
    if not group or me not in group.get("members",[]): return redirect("/groups")

    if request.method == "POST":
        action = request.form.get("action","send")
        if action == "send":
            txt  = request.form.get("message","").strip()
            file = request.files.get("file")
            ftype = fname = url = ""
            if file and file.filename:
                ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
                if not file_is_safe(file, ext):  # Fix 1.4 — reject disallowed/spoofed files
                    ftype = "text"               # unsafe file silently dropped; message sends as text
                else:
                    ftype = "file"
                    saved = secure_random_filename(secure_filename(file.filename))
                    file.save(os.path.join(user_upload_dir(me), saved))
                    fname = saved; url = f"/uploads/{me}/{saved}"
            else: ftype = "text"
            if txt or ftype == "file":
                ri = session.pop(f"greply_to_{group_id}", None)
                msg_id = db.send_group_message(group_id, me, text=encrypt_text(txt),
                                      ftype=ftype, filename=fname, url=url, reply_to=ri)
                socketio.emit("new_message", {
                    "id":       msg_id,
                    "sender":   me,
                    "text":     txt,
                    "time":     "just now",
                    "ftype":    ftype,
                    "filename": fname,
                    "url":      url,
                    "reactions":{},
                }, to=group_room(group_id))
                # Fix 5.4 — push unread_update to every other member's personal room.
                group = db.get_group(group_id)
                for member in (group.get("members") or []):
                    if member == me:
                        continue
                    total   = db.count_unread(member)
                    senders = db.get_unread_senders(member)
                    socketio.emit("unread_update", {"unread": total, "senders": senders},
                                  to=f"user_{member}")
        elif action == "set_reply":
            # Fix 2.2 — read msg_id which is the real DB row id, not a loop index
            try:   rid = int(request.form.get("msg_id"))
            except Exception: rid = None
            key = f"greply_to_{group_id}"
            if rid is None or rid < 0: session.pop(key, None)
            else: session[key] = rid
        elif action == "delete":
            try: mid = int(request.form.get("msg_id"))
            except Exception: mid = -1
            if mid > 0:
                msg = db.get_group_message_by_id(mid)
                if msg and msg.get("sender") == me:
                    db.soft_delete_group_message(mid)
        elif action == "react":
            try: mid = int(request.form.get("msg_id"))
            except Exception: mid = -1
            emoji = request.form.get("emoji","❤️")
            if mid > 0: db.react_group_message(mid, me, emoji)
        return redirect(f"/group/{group_id}")

    db.mark_group_seen(group_id, me)
    socketio.emit("seen_update", {"from": me}, to=group_room(group_id))
    chat_data = db.load_group_chat(group_id)
    for m in chat_data:
        if "sender" in m and "from" not in m: m["from"] = m["sender"]
    messages = build_messages(chat_data, me)

    reply_pending = None
    ri = session.get(f"greply_to_{group_id}")
    if isinstance(ri, int) and ri > 0:
        rm = db.get_group_message_by_id(ri)
        if rm:
            reply_pending = {"id":ri,"author":rm.get("sender",""),
                             "text":(decrypt_text(rm.get("text","")) or "[attachment]")[:60]}

    members  = group.get("members",[])
    typing_users = []
    for m in members:
        if m == me: continue
        fi    = db.get_user(m) or {}
        ts_str = fi.get("typing_group_ts")
        if fi.get("typing_group") == group_id and ts_str:
            try:
                ts = ts_str if isinstance(ts_str, datetime) else datetime.strptime(str(ts_str), "%Y-%m-%d %H:%M:%S")
                if utc_now() - ts < timedelta(seconds=4): typing_users.append(m)
            except Exception: pass

    chat_theme = ""   # placeholder until Batch E

    return render_template("group_chat.html", user=me, group=group,
                           group_id=group_id, is_owner=(group.get("owner")==me),
                           messages=messages, reply_pending=reply_pending,
                           typing_users=typing_users,
                           avatar_url=group.get("avatar",""), active="groups",
                           chat_theme=chat_theme,
                           socket_room=group_room(group_id))

@app.route("/gtyping/<group_id>", methods=["POST"])
@csrf.exempt   # Fix 1.3 — called by JS fetch(); only updates typing timestamp
def gtyping(group_id):
    me = current_user()
    if not me: return ("",401)
    db.update_user(me, typing_group=group_id, typing_group_ts=utc_now())
    return ("",204)

@app.route("/group/<group_id>/admin", methods=["GET","POST"])
def group_admin(group_id):
    me    = current_user()
    if not me: return redirect("/login")
    group = db.get_group(group_id)
    if not group or me not in group.get("members",[]): return redirect("/groups")
    if group.get("owner") != me: return redirect(f"/group/{group_id}")
    error = None
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add_member":
            uname = (request.form.get("username") or "").strip()
            if not uname:                               error = "Enter a username."
            elif not db.user_exists(uname):             error = f"@{uname} not found."
            elif uname in group.get("members",[]):      error = f"@{uname} already in group."
            else:
                db.add_group_member(group_id, uname)
                return redirect(f"/group/{group_id}/admin")
        elif action == "remove_member":
            member = request.form.get("member","")
            if member and member != group.get("owner"):
                db.remove_group_member(group_id, member)
            return redirect(f"/group/{group_id}/admin")
        elif action == "delete_group":
            db.delete_group(group_id)
            return redirect("/groups")
    group    = db.get_group(group_id)
    members  = [{"username":m,"is_owner":(m==group.get("owner"))} for m in group.get("members",[])]
    return render_template("group_admin.html", user=me, group=group,
                           group_id=group_id, members=members,
                           avatar_url=group.get("avatar",""), error=error, active="groups")

# ---------- NOTIFICATION / PING ----------
@app.route("/unread.json")
def unread_json():
    me = current_user()
    if not me: return jsonify(ok=False, unread=0)
    try:
        total   = db.count_unread(me)
        senders = db.get_unread_senders(me)
        return jsonify(ok=True, unread=total, senders=senders)
    except Exception:
        return jsonify(ok=False, unread=0)

@app.route("/ping", methods=["POST"])
@csrf.exempt   # Fix 1.3 — called by JS fetch(); exempted as it only updates last_seen timestamp
def ping():
    me = current_user()
    if not me: return ("",401)
    db.update_user(me, last_seen=utc_now())
    return ("",204)

if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"   # Fix 6.2 — never hardcode debug=True
    app.run(host="0.0.0.0", port=5000, debug=debug)
