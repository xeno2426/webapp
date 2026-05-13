from flask import Flask, request, redirect, session, send_from_directory, jsonify, render_template
from flask_socketio import SocketIO, join_room, emit as socket_emit
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from datetime import datetime, timedelta
import os, json, hashlib, base64, secrets, sys, hmac, logging
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

for _name, _val in [("SECRET_KEY", SECRET_KEY), ("ADMIN_KEY", ADMIN_KEY), ("MASTER_KEY", SECRET_MASTER_KEY)]:
    if not _val:
        sys.exit(f"FATAL: environment variable {_name} is not set. App cannot start.")

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)

# Fix 1.11 — restrict WebSocket CORS to our own domain only.
socketio = SocketIO(app, cors_allowed_origins=[APP_URL], async_mode="threading",
                    logger=False, engineio_logger=False)

# Fix 4.3 — enable sensible global rate limits; tighter limits applied per-route below.
limiter  = Limiter(get_remote_address, app=app, default_limits=["300 per day", "60 per hour"])

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
    except: return text

def decrypt_text(token):
    if not token: return ""
    try: return get_cipher().decrypt(token.encode()).decode()
    except: return token

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

def secure_random_filename(original):
    ext = ("." + original.rsplit(".", 1)[1].lower()) if "." in original else ""
    return f"{secrets.token_urlsafe(16)}{ext}"

def time_ago(ts):
    if not ts: return ""
    try:
        if isinstance(ts, str):
            ts = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        s = int((datetime.now() - ts).total_seconds())
        if s < 60:    return "just now"
        if s < 3600:  return f"{s//60}m ago"
        if s < 86400: return f"{s//3600}h ago"
        return ts.strftime("%b %d")
    except: return str(ts)

def user_upload_dir(u):
    p = os.path.join(UPLOADS_ROOT, u)
    os.makedirs(p, exist_ok=True)
    return p

IMAGE_EXTS = {"png","jpg","jpeg","gif","webp","bmp"}
AUDIO_EXTS = {"mp3","wav","m4a","ogg","oga","aac"}
VIDEO_EXTS = {"mp4","webm","mov","m4v"}

def build_messages(chat_data, me):
    messages = []
    for i, msg in enumerate(chat_data):
        sender  = msg.get("from") or msg.get("sender","")
        deleted = msg.get("deleted", False)
        text    = "This message was deleted" if deleted else decrypt_text(msg.get("text",""))
        ftype   = msg.get("ftype","text")
        filename= msg.get("filename","") or ""
        url     = msg.get("url","") or ""
        ext     = filename.rsplit(".",1)[1].lower() if "." in filename else ""
        msg_id  = msg.get("id", i)

        reply = None
        ri = msg.get("reply_to")
        if isinstance(ri, int) and ri > 0:
            rm = next((m for m in chat_data if (m.get("id") or 0) == ri), None)
            if rm:
                reply = {"id": ri,
                         "author": rm.get("from") or rm.get("sender",""),
                         "text": (decrypt_text(rm.get("text","")) or "[attachment]")[:40]}

        raw_reactions = msg.get("reactions") or {}
        if isinstance(raw_reactions, str):
            try: raw_reactions = json.loads(raw_reactions)
            except: raw_reactions = {}
        reaction_counts = {}
        for em in raw_reactions.values():
            reaction_counts[em] = reaction_counts.get(em,0) + 1

        seen_by = msg.get("seen_by") or []
        seen_by_others = [u for u in seen_by if u != me]

        messages.append({
            "id":       msg_id,
            "index":    i,
            "sender":   sender,
            "text":     text,
            "time":     time_ago(msg.get("created_at") or msg.get("time","")),
            "ftype":    ftype,
            "filename": filename,
            "url":      url,
            "ext":      ext,
            "is_image": ext in IMAGE_EXTS and ftype == "file",
            "is_audio": ext in AUDIO_EXTS and ftype == "file",
            "is_video": ext in VIDEO_EXTS and ftype == "file",
            "seen":     msg.get("seen", False),
            "deleted":  deleted,
            "reply":    reply,
            "reactions":reaction_counts,
            "my_reaction": raw_reactions.get(me,""),
            "seen_by_others": seen_by_others,
            "align":    "me" if sender == me else "them",
        })
    return messages

@app.context_processor
def inject_globals():
    u = current_user()
    try:
        unread = db.count_unread(u) if u else 0
    except:
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
    room = data.get("room")
    if room:
        join_room(room)

@socketio.on("typing")
def on_typing(data):
    room   = data.get("room")
    sender = data.get("sender")
    if room and sender:
        socket_emit("typing", {"sender": sender}, to=room, include_self=False)

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
            db.create_user(u, hash_pw(p1), recovery=rc)
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
        elif (info.get("recovery","") or "").lower() != recovery.lower():
            error = "Reset failed. Check your details and try again."
        else:
            db.update_user(username, password_hash=hash_pw(new_pw))   # Fix 1.2
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
    notes = db.load_notes(user, sort=sort)
    note_list = [{"id":n["id"],"title":n.get("title","Untitled"),
                  "body":n.get("body",""),"time":time_ago(n.get("created_at"))}
                 for n in notes]
    return render_template("home.html", user=user, notes=note_list,
                           note_count=len(notes), sort=sort, active="home")

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
            db.update_user(user, recovery=request.form.get("recovery","").strip())
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
    db.update_user(me, last_seen=datetime.now())
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
    for f in sorted(friends_list):
        fi = db.get_user(f) or {}
        last_seen = fi.get("last_seen")
        online = False
        if last_seen:
            try:
                ts = last_seen if isinstance(last_seen, datetime) else datetime.strptime(str(last_seen), "%Y-%m-%d %H:%M:%S")
                online = (datetime.now() - ts) < timedelta(seconds=40)
            except: pass
        friends_data.append({"username":f,"online":online,
                              "unread":db.get_unread_dict(me).get(f,0)})

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
                # push to both users via WebSocket
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
            try:   idx = int(request.form.get("msg_index"))
            except: idx = None
            key = f"reply_to_{friend}"
            if idx is None or idx < 0: session.pop(key, None)
            else: session[key] = idx
        elif action == "delete":
            try: mid = int(request.form.get("msg_id"))
            except: mid = -1
            if mid > 0:
                msg = db.get_message_by_id(mid)
                if msg and msg.get("sender") == me:
                    db.soft_delete_message(mid)
        elif action == "react":
            try: mid = int(request.form.get("msg_id"))
            except: mid = -1
            emoji = request.form.get("emoji","❤️")
            if mid > 0: db.react_message(mid, me, emoji)
        return redirect(f"/chat/{friend}")

    # GET
    db.mark_seen(friend, me)
    db.reset_unread(me, friend)
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
            if datetime.now() - ts < timedelta(seconds=4): typing = friend
        except: pass

    return render_template("chat.html", user=me, friend=friend,
                           messages=messages, reply_pending=reply_pending,
                           typing=typing, active="friends",
                           socket_room=dm_room(me, friend))

@app.route("/typing/<friend>", methods=["POST"])
def typing(friend):
    me = current_user()
    if not me: return ("",401)
    db.update_user(me, typing_to=friend, typing_ts=datetime.now())
    return ("",204)

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
            except: sid = 0
            if sid: db.delete_story(sid, me)
            return redirect("/stories")

        file    = request.files.get("file")
        caption = (request.form.get("caption") or "").strip()
        if not file or not file.filename:
            error = "Select an image or video."
        else:
            fn    = secure_filename(file.filename)
            ext   = fn.rsplit(".",1)[1].lower() if "." in fn else ""
            saved = secure_random_filename(fn)
            file.save(os.path.join(user_upload_dir(me), saved))
            ftype = ("image" if ext in IMAGE_EXTS else
                     "video" if ext in VIDEO_EXTS else "file")
            url = f"/uploads/{me}/{saved}"
            db.add_story(me, url, ftype=ftype, caption=caption)
            session["story_posted"] = "Story posted!"
            return redirect("/stories")

    user_stories = db.load_stories()

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
        except: idx = 0
        if 0 <= idx < len(arr):
            s        = arr[idx]
            next_url = f"/stories?user={owner}&idx={idx+1}&view=1" if idx+1<len(arr) else "/stories"
            prev_url = f"/stories?user={owner}&idx={idx-1}&view=1" if idx-1>=0 else "/stories"
            if mark_view and me != owner:
                db.add_story_viewer(s["id"], me)
            viewers = s.get("viewers") or []
            viewers_line = ("No views yet." if not viewers
                            else f"Seen by ({len(viewers)}): " + ", ".join("@"+v for v in viewers))
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
            gid        = str(int(datetime.now().timestamp()))
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
        elif action == "set_reply":
            try:   idx = int(request.form.get("msg_index"))
            except: idx = None
            key = f"greply_to_{group_id}"
            if idx is None or idx < 0: session.pop(key, None)
            else: session[key] = idx
        elif action == "delete":
            try: mid = int(request.form.get("msg_id"))
            except: mid = -1
            if mid > 0:
                msg = db.get_group_message_by_id(mid)
                if msg and msg.get("sender") == me:
                    db.soft_delete_group_message(mid)
        elif action == "react":
            try: mid = int(request.form.get("msg_id"))
            except: mid = -1
            emoji = request.form.get("emoji","❤️")
            if mid > 0: db.react_group_message(mid, me, emoji)
        return redirect(f"/group/{group_id}")

    db.mark_group_seen(group_id, me)
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
                if datetime.now() - ts < timedelta(seconds=4): typing_users.append(m)
            except: pass

    return render_template("group_chat.html", user=me, group=group,
                           group_id=group_id, is_owner=(group.get("owner")==me),
                           messages=messages, reply_pending=reply_pending,
                           typing_users=typing_users,
                           avatar_url=group.get("avatar",""), active="groups",
                           socket_room=group_room(group_id))

@app.route("/gtyping/<group_id>", methods=["POST"])
def gtyping(group_id):
    me = current_user()
    if not me: return ("",401)
    db.update_user(me, typing_group=group_id, typing_group_ts=datetime.now())
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
    except:
        return jsonify(ok=False, unread=0)

@app.route("/ping", methods=["POST"])
def ping():
    me = current_user()
    if not me: return ("",401)
    db.update_user(me, last_seen=datetime.now())
    return ("",204)

if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"   # Fix 6.2 — never hardcode debug=True
    app.run(host="0.0.0.0", port=5000, debug=debug)
