from flask import Flask, request, redirect, session, send_from_directory, jsonify, render_template
from datetime import datetime, timedelta
import os, json, hashlib, base64, secrets
from werkzeug.utils import secure_filename
from cryptography.fernet import Fernet

# ---------- PATHS ----------
BASE_DIR    = os.path.dirname(__file__)
DATA_DIR    = os.path.join(BASE_DIR, "data")
UPLOADS_ROOT = os.path.join(BASE_DIR, "uploads")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOADS_ROOT, exist_ok=True)

USERS_FILE  = os.path.join(DATA_DIR, "users.json")
GROUPS_FILE = os.path.join(DATA_DIR, "groups.json")
STORIES_FILE = os.path.join(BASE_DIR, "stories.json")
STORY_TTL_HOURS = 16

# ---------- CONFIG ----------
ADMIN_KEY        = os.environ.get("ADMIN_KEY", "XENO-ADMIN-2426")
SECRET_MASTER_KEY = os.environ.get("MASTER_KEY", "MY_SUPER_SECRET_KEY_123")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "CHANGE_THIS_SECRET_KEY")
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)

# ---------- ENCRYPTION ----------
def get_cipher():
    key = hashlib.sha256(SECRET_MASTER_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))

def encrypt_text(text):
    if not text: return ""
    return get_cipher().encrypt(text.encode()).decode()

def decrypt_text(token):
    if not token: return ""
    try:
        return get_cipher().decrypt(token.encode()).decode()
    except Exception:
        return token   # old plain-text fallback

# ---------- HELPERS ----------
def secure_random_filename(original, prefix=""):
    ext = ("." + original.rsplit(".", 1)[1].lower()) if "." in original else ""
    return f"{prefix}{secrets.token_urlsafe(16)}{ext}"

def time_ago(ts_str):
    try:
        dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        s  = int((datetime.now() - dt).total_seconds())
        if s < 60:    return "just now"
        if s < 3600:  return f"{s//60}m ago"
        if s < 86400: return f"{s//3600}h ago"
        return dt.strftime("%b %d")
    except Exception:
        return ts_str

def load_json(path, default):
    if not os.path.exists(path): return default
    try:
        with open(path) as f: return json.load(f)
    except Exception: return default

def save_json(path, data):
    with open(path, "w") as f: json.dump(data, f, indent=2)

def load_users():            return load_json(USERS_FILE, {})
def save_users(u):           save_json(USERS_FILE, u)
def load_groups():           return load_json(GROUPS_FILE, {})
def save_groups(g):          save_json(GROUPS_FILE, g)
def notes_file(u):           return os.path.join(DATA_DIR, f"notes_{u}.json")
def load_notes(u):           return load_json(notes_file(u), [])
def save_notes(u, n):        save_json(notes_file(u), n)
def chat_path(u1, u2):
    a, b = sorted([u1, u2])
    return os.path.join(DATA_DIR, f"chat_{a}__{b}.json")
def load_chat(u1, u2):       return load_json(chat_path(u1, u2), [])
def save_chat(u1, u2, d):    save_json(chat_path(u1, u2), d)
def group_chat_path(gid):    return os.path.join(DATA_DIR, f"group_{gid}.json")
def load_group_chat(gid):    return load_json(group_chat_path(gid), [])
def save_group_chat(gid, d): save_json(group_chat_path(gid), d)
def user_upload_dir(u):
    p = os.path.join(UPLOADS_ROOT, u)
    os.makedirs(p, exist_ok=True)
    return p

def load_stories():
    try:
        with open(STORIES_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception: return {}

def save_stories(d):
    try:
        with open(STORIES_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2)
    except Exception: pass

def current_user():  return session.get("user")
def hash_pw(pw):     return hashlib.sha256(pw.encode()).hexdigest()

def count_unread(username):
    info = load_users().get(username, {})
    return sum(int(v) for v in info.get("unread", {}).values() if str(v).isdigit())

@app.context_processor
def inject_globals():
    """Auto-inject unread_count into every template."""
    u = current_user()
    return {"unread_count": count_unread(u) if u else 0}

def build_messages(chat_data, me):
    """Turn raw chat JSON into clean dicts for templates."""
    IMAGE_EXTS = {"png","jpg","jpeg","gif","webp","bmp"}
    AUDIO_EXTS = {"mp3","wav","m4a","ogg","oga","aac"}
    messages = []
    for i, msg in enumerate(chat_data):
        sender   = msg.get("from", "")
        deleted  = msg.get("deleted", False)
        text_raw = "This message was deleted" if deleted else decrypt_text(msg.get("text",""))
        ftype    = msg.get("ftype", "text")
        filename = msg.get("filename", "") or ""
        url      = msg.get("url", "")
        ext      = filename.rsplit(".", 1)[1].lower() if "." in filename else ""

        # reply preview
        reply = None
        ri = msg.get("reply_to")
        if isinstance(ri, int) and 0 <= ri < len(chat_data):
            rm = chat_data[ri]
            reply = {
                "author": rm.get("from",""),
                "text":   (decrypt_text(rm.get("text","")) or "[attachment]")[:40],
            }

        # reactions
        raw_reactions = msg.get("reactions", {}) or {}
        reaction_counts = {}
        for em in raw_reactions.values():
            reaction_counts[em] = reaction_counts.get(em, 0) + 1

        # seen_by (group chats)
        seen_by = msg.get("seen_by", [])
        seen_by_others = [u for u in seen_by if u != me] if isinstance(seen_by, list) else []

        messages.append({
            "index":       i,
            "sender":      sender,
            "text":        text_raw,
            "time":        time_ago(msg.get("time","")),
            "ftype":       ftype,
            "filename":    filename,
            "url":         url,
            "ext":         ext,
            "is_image":    ext in IMAGE_EXTS and ftype == "file",
            "is_audio":    ext in AUDIO_EXTS and ftype == "file",
            "seen":        msg.get("seen", False),
            "deleted":     deleted,
            "reply":       reply,
            "reactions":   reaction_counts,
            "seen_by_others": seen_by_others,
            "align":       "me" if sender == me else "them",
        })
    return messages

# ---------- AUTH ROUTES ----------
@app.route("/signup", methods=["GET","POST"])
def signup():
    if current_user(): return redirect("/")
    users = load_users()
    error = ""
    if request.method == "POST":
        u  = request.form.get("username","").strip()
        p1 = request.form.get("password","")
        p2 = request.form.get("password2","")
        rc = request.form.get("recovery","").strip()
        if not u or not p1 or not p2:       error = "All fields required."
        elif " " in u or len(u) < 3:        error = "Username: 3+ chars, no spaces."
        elif u in users:                     error = "Username already taken."
        elif p1 != p2:                       error = "Passwords do not match."
        elif len(p1) < 4:                    error = "Password too short."
        else:
            users[u] = {"password_hash": hash_pw(p1), "bio":"", "avatar":"",
                        "friends":[], "recovery":rc, "unread":{}}
            save_users(users)
            session["user"] = u
            return redirect("/")
    return render_template("signup.html", error=error)

@app.route("/login", methods=["GET","POST"])
def login():
    if current_user(): return redirect("/")
    users = load_users()
    error = ""
    if request.method == "POST":
        u = request.form.get("username","").strip()
        p = request.form.get("password","")
        info = users.get(u)
        if not info:                              error = "User not found."
        elif info.get("password_hash") != hash_pw(p): error = "Wrong password."
        else:
            session.permanent = True
            session["user"] = u
            return redirect("/")
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.route("/reset", methods=["GET","POST"])
def reset_with_admin_key():
    users = load_users()
    error = info_msg = ""
    if request.method == "POST":
        username  = request.form.get("username","").strip()
        new_pw    = request.form.get("password","")
        new_pw2   = request.form.get("password2","")
        recovery  = request.form.get("recovery","").strip()
        admin_key = request.form.get("admin_key","").strip()
        if admin_key != ADMIN_KEY:                         error = "Admin key wrong."
        elif not username or username not in users:        error = "User not found."
        elif new_pw != new_pw2 or len(new_pw) < 4:        error = "Passwords empty/short/mismatch."
        elif (users[username].get("recovery","").lower() != recovery.lower()):
            error = "Recovery phrase mismatch."
        else:
            users[username]["password_hash"] = hash_pw(new_pw)
            save_users(users)
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
            notes = load_notes(user)
            notes.insert(0, {"title": txt.splitlines()[0][:60],
                             "body": txt,
                             "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
            save_notes(user, notes)
        return redirect("/")
    sort  = request.args.get("sort","newest")
    notes = load_notes(user)
    indexed = list(enumerate(notes))
    if sort == "oldest": indexed = indexed[::-1]
    note_list = [{"index":i, "title":n.get("title","Untitled"),
                  "body":n.get("body",""), "time":time_ago(n.get("time",""))} for i,n in indexed]
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
            notes = load_notes(user)
            notes.insert(0, {"title":title[:80],"body":body,
                             "time":datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
            save_notes(user, notes)
            return redirect("/")
    return render_template("note_new.html", user=user, error=error, active="home")

@app.route("/note/<int:index>", methods=["GET","POST"])
def edit_note(index):
    user = current_user()
    if not user: return redirect("/login")
    notes = load_notes(user)
    if index < 0 or index >= len(notes): return redirect("/")
    error = ""
    if request.method == "POST":
        title = request.form.get("title","").strip() or "Untitled"
        body  = request.form.get("body","").strip()
        if not body: error = "Note body cannot be empty."
        else:
            notes[index].update({"title":title[:80],"body":body})
            save_notes(user, notes)
            return redirect("/")
    n = notes[index]
    return render_template("note_edit.html", user=user, error=error,
                           note=n, index=index, active="home")

@app.route("/note/<int:index>/delete", methods=["POST"])
def delete_note(index):
    user = current_user()
    if not user: return redirect("/login")
    notes = load_notes(user)
    if 0 <= index < len(notes):
        notes.pop(index)
        save_notes(user, notes)
    return redirect("/")

# ---------- PROFILE ----------
@app.route("/profile", methods=["GET","POST"])
def profile():
    user = current_user()
    if not user: return redirect("/login")
    users = load_users()
    info  = users.get(user, {})
    error = info_msg = ""
    if request.method == "POST":
        action = request.form.get("action")
        if action == "update_bio":
            info["bio"] = request.form.get("bio","")[:400]
            users[user] = info; save_users(users); info_msg = "Bio updated."
        elif action == "update_recovery":
            info["recovery"] = request.form.get("recovery","").strip()
            users[user] = info; save_users(users); info_msg = "Recovery phrase saved."
        elif action == "change_password":
            old, new1, new2 = (request.form.get(k,"") for k in ("old_pw","new_pw","new_pw2"))
            if info.get("password_hash") != hash_pw(old): error = "Old password incorrect."
            elif new1 != new2 or len(new1) < 4:           error = "Passwords mismatch or too short."
            else:
                info["password_hash"] = hash_pw(new1)
                users[user] = info; save_users(users); info_msg = "Password changed."
        elif action == "avatar":
            f = request.files.get("avatar")
            if f and f.filename:
                allowed = {"png","jpg","jpeg","gif","webp"}
                ext = f.filename.rsplit(".",1)[-1].lower() if "." in f.filename else ""
                f.seek(0,2); size = f.tell(); f.seek(0)
                if ext not in allowed:      error = "Only PNG/JPG/GIF/WEBP allowed."
                elif size > 5*1024*1024:    error = "Image must be under 5MB."
                else:
                    fname = secure_filename(f.filename)
                    f.save(os.path.join(user_upload_dir(user), fname))
                    info["avatar"] = fname; users[user] = info
                    save_users(users); info_msg = "Avatar updated."
        elif action == "delete_account":
            if request.form.get("confirm_delete","").strip() != user:
                error = "Type your username exactly to confirm."
            else:
                for uname, uinfo in users.items():
                    if uname == user: continue
                    uinfo["friends"] = [f for f in uinfo.get("friends",[]) if f != user]
                    if user in uinfo.get("friend_requests",[]): uinfo["friend_requests"].remove(user)
                users.pop(user, None); save_users(users)
                session.clear(); return redirect("/login")
    avatar_url = f"/uploads/{user}/{info['avatar']}" if info.get("avatar") else ""
    return render_template("profile.html", user=user, info=info,
                           avatar_url=avatar_url, error=error, info_msg=info_msg,
                           bio_len=len(info.get("bio","")), active="profile")

@app.route("/uploads/<username>/<filename>")
def serve_upload(username, filename):
    return send_from_directory(user_upload_dir(username), filename)

@app.route("/user/<username>")
def user_profile(username):
    me = current_user()
    if not me: return redirect("/login")
    users = load_users()
    info  = users.get(username)
    if not info: return redirect("/friends")
    avatar_url = f"/uploads/{username}/{info['avatar']}" if info.get("avatar") else ""
    return render_template("user_profile.html", user=me, profile_user=username,
                           bio=info.get("bio",""), avatar_url=avatar_url, active="friends")

# ---------- FRIENDS ----------
@app.route("/friends", methods=["GET","POST"])
def friends():
    me = current_user()
    if not me: return redirect("/login")
    users = load_users()
    info  = users.get(me, {})
    info["last_seen"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    users[me] = info; save_users(users)
    error = info_msg = ""

    if request.method == "POST":
        action      = request.form.get("action","add")
        friend_name = request.form.get("friend_username","").strip()
        requester   = request.form.get("requester","").strip()

        if action == "add":
            if not friend_name or friend_name == me:           error = "Invalid username."
            elif friend_name not in users:                      error = "User not found."
            elif friend_name in info.get("friends",[]):        error = "Already friends."
            elif me in users[friend_name].get("friend_requests",[]): error = "Request already sent."
            else:
                other = users.get(friend_name,{})
                reqs  = other.get("friend_requests",[])
                if me not in reqs: reqs.append(me)
                other["friend_requests"] = reqs
                users[friend_name] = other; save_users(users)
                info = users[me]; info_msg = f"Request sent to @{friend_name}."
        elif action == "accept":
            reqs = info.get("friend_requests",[])
            if requester in reqs:
                reqs.remove(requester)
                info["friend_requests"] = reqs
                info.setdefault("friends",[])
                if requester not in info["friends"]: info["friends"].append(requester)
                users[me] = info
                other = users.get(requester,{})
                if me not in other.get("friends",[]): other.setdefault("friends",[]).append(me)
                users[requester] = other; save_users(users)
                info = users[me]; info_msg = f"You are now friends with @{requester}."
        elif action == "decline":
            reqs = info.get("friend_requests",[])
            if requester in reqs:
                reqs.remove(requester); info["friend_requests"] = reqs
                users[me] = info; save_users(users)
                info = users[me]; info_msg = f"Declined @{requester}."
        elif action == "remove":
            if friend_name in info.get("friends",[]):
                info["friends"] = [f for f in info["friends"] if f != friend_name]
                users[me] = info
                other = users.get(friend_name,{})
                other["friends"] = [f for f in other.get("friends",[]) if f != me]
                users[friend_name] = other; save_users(users)
                info_msg = f"Removed @{friend_name}."

    # build friends data
    friends_data = []
    for f in sorted(info.get("friends",[])):
        fi = users.get(f,{})
        last_seen = fi.get("last_seen")
        online = False
        if last_seen:
            try:
                ts = datetime.strptime(last_seen, "%Y-%m-%d %H:%M:%S")
                online = (datetime.now() - ts) < timedelta(seconds=40)
            except Exception: pass
        friends_data.append({"username":f, "online":online,
                              "unread":info.get("unread",{}).get(f,0)})

    return render_template("friends.html", user=me,
                           friends=friends_data,
                           pending=info.get("friend_requests",[]),
                           error=error, info_msg=info_msg, active="friends")

# ---------- DM CHAT ----------
@app.route("/chat/<friend>", methods=["GET","POST"])
def chat(friend):
    me = current_user()
    if not me: return redirect("/login")
    users = load_users()
    if friend not in users: return redirect("/friends")
    my_info = users.get(me,{})
    if friend not in my_info.get("friends",[]): return redirect("/friends")

    if request.method == "POST":
        action = request.form.get("action","send")
        if action == "send":
            txt  = request.form.get("message","").strip()
            file = request.files.get("file")
            ftype = fname = url = ""
            if file and file.filename:
                ftype = "file"
                saved = secure_random_filename(secure_filename(file.filename))
                path  = os.path.join(user_upload_dir(me), saved)
                file.save(path)
                fname = saved; url = f"/uploads/{me}/{saved}"
            else: ftype = "text"
            if txt or ftype == "file":
                data = load_chat(me, friend)
                ri   = session.pop(f"reply_to_{friend}", None)
                data.append({"from":me,"to":friend,"text":encrypt_text(txt),
                             "time":datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                             "ftype":ftype,"filename":fname,"url":url,
                             "seen":False,"reply_to":ri,"reactions":{},"deleted":False})
                save_chat(me, friend, data)
                # update unread for friend
                finfo = users.get(friend,{})
                finfo.setdefault("unread",{})[me] = finfo.get("unread",{}).get(me,0) + 1
                users[friend] = finfo; save_users(users)
        elif action == "set_reply":
            try: idx = int(request.form.get("msg_index"))
            except: idx = None
            if idx is None or idx < 0: session.pop(f"reply_to_{friend}", None)
            else:                      session[f"reply_to_{friend}"] = idx
        elif action == "delete":
            try: idx = int(request.form.get("msg_index"))
            except: idx = -1
            data = load_chat(me, friend)
            if 0 <= idx < len(data) and data[idx].get("from") == me:
                data[idx].update({"deleted":True,"text":"This message was deleted",
                                  "ftype":"text","filename":"","url":"","reactions":{}})
                save_chat(me, friend, data)
        elif action == "react":
            try: idx = int(request.form.get("msg_index"))
            except: idx = -1
            emoji = request.form.get("emoji","❤️")
            data  = load_chat(me, friend)
            if 0 <= idx < len(data):
                r = data[idx].get("reactions",{}) or {}
                if r.get(me) == emoji: r.pop(me)
                else: r[me] = emoji
                data[idx]["reactions"] = r; save_chat(me, friend, data)
        return redirect(f"/chat/{friend}")

    # GET
    chat_data = load_chat(me, friend)
    for msg in chat_data:
        if msg.get("to") == me and not msg.get("seen"):
            msg["seen"] = True
    save_chat(me, friend, chat_data)
    unread = my_info.get("unread",{})
    if friend in unread: unread[friend] = 0; my_info["unread"] = unread; users[me] = my_info; save_users(users)

    messages = build_messages(chat_data, me)

    # reply pending
    reply_pending = None
    ri = session.get(f"reply_to_{friend}")
    if isinstance(ri, int) and 0 <= ri < len(chat_data):
        rm = chat_data[ri]
        reply_pending = {"index":ri,"author":rm.get("from",""),
                         "text":(decrypt_text(rm.get("text","")) or "[attachment]")[:60]}

    # typing indicator
    friend_info = users.get(friend,{})
    typing = None
    ts_str  = friend_info.get("typing_ts")
    if ts_str and friend_info.get("typing_to") == me:
        try:
            ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
            if datetime.now() - ts < timedelta(seconds=4): typing = friend
        except Exception: pass

    return render_template("chat.html", user=me, friend=friend,
                           messages=messages, reply_pending=reply_pending,
                           typing=typing, active="friends")

@app.route("/typing/<friend>", methods=["POST"])
def typing(friend):
    me = current_user()
    if not me: return ("",401)
    users = load_users()
    info  = users.get(me,{})
    info["typing_to"] = friend
    info["typing_ts"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    users[me] = info; save_users(users)
    return ("",204)

# ---------- STORIES ----------
@app.route("/stories", methods=["GET","POST"])
def stories_page():
    me = current_user()
    if not me: return redirect("/login")
    users   = load_users()
    stories = load_stories()

    # expire old stories
    cutoff = int(datetime.now().timestamp()) - STORY_TTL_HOURS * 3600
    changed = False
    for uname, arr in list(stories.items()):
        if not isinstance(arr, list): arr = []
        new_arr = [s for s in arr if isinstance(s.get("created_ts"), int) and s["created_ts"] >= cutoff]
        if len(new_arr) != len(arr): changed = True
        stories[uname] = new_arr
    if changed: save_stories(stories)

    error = None
    if request.method == "POST":
        action = request.form.get("action","create")
        if action == "delete_story":
            sid = request.form.get("story_id")
            stories[me] = [s for s in stories.get(me,[]) if s.get("id") != sid]
            save_stories(stories)
            return redirect("/stories")
        file    = request.files.get("file")
        caption = (request.form.get("caption") or "").strip()
        if not file or not file.filename:
            error = "Select an image or video."
        else:
            fn   = secure_filename(file.filename)
            ext  = fn.rsplit(".",1)[1].lower() if "." in fn else ""
            saved = secure_random_filename(fn, prefix="story_")
            file.save(os.path.join(user_upload_dir(me), saved))
            ftype = ("image" if ext in {"png","jpg","jpeg","gif","webp","bmp"}
                     else "video" if ext in {"mp4","webm","mov","m4v"} else "file")
            stories.setdefault(me,[]).append({
                "id": str(int(datetime.now().timestamp()*1000)),
                "user": me, "caption": caption,
                "created_ts": int(datetime.now().timestamp()),
                "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "ftype": ftype, "filename": saved,
                "url": f"/uploads/{me}/{saved}", "viewers": [],
            })
            save_stories(stories)
            session["story_posted"] = "Story posted!"
            return redirect("/stories")

    # build grid cards
    user_stories = {}
    for uname, arr in stories.items():
        if not isinstance(arr, list): continue
        arr = sorted(arr, key=lambda s: s.get("created_ts",0))
        if arr: user_stories[uname] = arr

    story_cards = []
    for uname, arr in user_stories.items():
        latest = arr[-1]
        viewers = set(v for s in arr for v in (s.get("viewers") or []))
        story_cards.append({"username":uname, "thumb_url":latest.get("url",""),
                            "view_count":len(viewers), "slide_count":len(arr)})

    # viewer
    owner  = request.args.get("user")
    idx_s  = request.args.get("idx","0")
    mark_view = request.args.get("view")
    current_story = None
    next_url = prev_url = "/stories"

    if owner and owner in user_stories:
        arr = user_stories[owner]
        try: idx = max(0, int(idx_s))
        except: idx = 0
        if 0 <= idx < len(arr):
            s = arr[idx]
            next_url = f"/stories?user={owner}&idx={idx+1}&view=1" if idx+1 < len(arr) else "/stories"
            prev_url = f"/stories?user={owner}&idx={idx-1}&view=1" if idx-1 >= 0 else "/stories"
            if mark_view and me != owner:
                viewers = s.get("viewers",[])
                if me not in viewers:
                    viewers.append(me); s["viewers"] = viewers
                    for j,s2 in enumerate(stories.get(owner,[])):
                        if s2.get("id") == s.get("id"):
                            stories[owner][j] = s; break
                    save_stories(stories)
            viewers_line = ("No views yet." if not s.get("viewers")
                            else f"Seen by ({len(s['viewers'])}): " +
                                 ", ".join("@"+v for v in s["viewers"]))
            try:
                dt = datetime.fromtimestamp(s.get("created_ts", 0))
                time_str = dt.strftime("%Y-%m-%d %H:%M")
            except: time_str = ""
            current_story = {"user":owner,"caption":s.get("caption",""),
                             "url":s.get("url",""),"ftype":s.get("ftype","image"),
                             "viewers_line":viewers_line,"time_str":time_str,
                             "id":s.get("id",""),"is_owner":(owner==me),
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
    groups = load_groups()
    my_groups = [{"id":gid,"name":g["name"],"member_count":len(g.get("members",[])),
                  "avatar":g.get("avatar","")}
                 for gid,g in groups.items() if me in g.get("members",[])]
    return render_template("groups.html", user=me, groups=my_groups, active="groups")

@app.route("/group/create", methods=["GET","POST"])
def create_group():
    me = current_user()
    if not me: return redirect("/login")
    users  = load_users()
    groups = load_groups()
    error  = ""
    if request.method == "POST":
        name    = request.form.get("name","").strip()
        members = [m.strip() for m in request.form.get("members","").split(",") if m.strip() in users]
        if me not in members: members.append(me)
        avatar_file = request.files.get("avatar")
        if not name:              error = "Group name required."
        elif len(members) < 2:   error = "Add at least 1 other valid user."
        else:
            gid = str(int(datetime.now().timestamp()))
            avatar_url = ""
            if avatar_file and avatar_file.filename:
                fn    = secure_filename(avatar_file.filename)
                saved = f"group_{gid}_{fn}"
                avatar_file.save(os.path.join(user_upload_dir(me), saved))
                avatar_url = f"/uploads/{me}/{saved}"
            groups[gid] = {"name":name,"owner":me,"members":members,
                           "created":datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                           "avatar":avatar_url}
            save_groups(groups); return redirect("/groups")
    return render_template("group_create.html", user=me, error=error, active="groups")

@app.route("/group/<group_id>", methods=["GET","POST"])
def group_chat(group_id):
    me = current_user()
    if not me: return redirect("/login")
    users  = load_users()
    groups = load_groups()
    group  = groups.get(group_id)
    if not group or me not in group.get("members",[]): return redirect("/groups")
    is_owner = (group.get("owner") == me)

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
                data = load_group_chat(group_id)
                ri   = session.pop(f"greply_to_{group_id}", None)
                data.append({"from":me,"group":group_id,"text":encrypt_text(txt),
                             "time":datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                             "ftype":ftype,"filename":fname,"url":url,
                             "reply_to":ri,"reactions":{},"deleted":False,"seen_by":[me]})
                save_group_chat(group_id, data)
        elif action == "set_reply":
            try: idx = int(request.form.get("msg_index"))
            except: idx = None
            key = f"greply_to_{group_id}"
            if idx is None or idx < 0: session.pop(key, None)
            else: session[key] = idx
        elif action == "delete":
            try: idx = int(request.form.get("msg_index"))
            except: idx = -1
            data = load_group_chat(group_id)
            if 0 <= idx < len(data) and data[idx].get("from") == me:
                data[idx].update({"deleted":True,"text":"This message was deleted",
                                  "ftype":"text","filename":"","url":"","reactions":{}})
                save_group_chat(group_id, data)
        elif action == "react":
            try: idx = int(request.form.get("msg_index"))
            except: idx = -1
            emoji = request.form.get("emoji","❤️")
            data  = load_group_chat(group_id)
            if 0 <= idx < len(data):
                r = data[idx].get("reactions",{}) or {}
                if r.get(me) == emoji: r.pop(me)
                else: r[me] = emoji
                data[idx]["reactions"] = r; save_group_chat(group_id, data)
        return redirect(f"/group/{group_id}")

    # GET
    chat_data = load_group_chat(group_id)
    changed = False
    for msg in chat_data:
        sb = msg.get("seen_by") or []
        if me not in sb: sb.append(me); msg["seen_by"] = sb; changed = True
    if changed: save_group_chat(group_id, chat_data)

    messages = build_messages(chat_data, me)

    # reply pending
    reply_pending = None
    ri = session.get(f"greply_to_{group_id}")
    if isinstance(ri, int) and 0 <= ri < len(chat_data):
        rm = chat_data[ri]
        reply_pending = {"index":ri,"author":rm.get("from",""),
                         "text":(decrypt_text(rm.get("text","")) or "[attachment]")[:60]}

    # typing users
    typing_users = []
    for m in group.get("members",[]):
        if m == me: continue
        info = users.get(m,{})
        ts_str = info.get("typing_group_ts")
        if ts_str and info.get("typing_group") == group_id:
            try:
                ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                if datetime.now() - ts < timedelta(seconds=4): typing_users.append(m)
            except Exception: pass

    avatar_url = group.get("avatar","") or ""
    return render_template("group_chat.html", user=me, group=group,
                           group_id=group_id, is_owner=is_owner,
                           messages=messages, reply_pending=reply_pending,
                           typing_users=typing_users, avatar_url=avatar_url, active="groups")

@app.route("/gtyping/<group_id>", methods=["POST"])
def gtyping(group_id):
    me = current_user()
    if not me: return ("",401)
    users = load_users()
    info  = users.get(me,{})
    info["typing_group"]    = group_id
    info["typing_group_ts"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    users[me] = info; save_users(users)
    return ("",204)

@app.route("/group/<group_id>/admin", methods=["GET","POST"])
def group_admin(group_id):
    me = current_user()
    if not me: return redirect("/login")
    users  = load_users()
    groups = load_groups()
    group  = groups.get(group_id)
    if not group or me not in group.get("members",[]): return redirect("/groups")
    if group.get("owner") != me: return redirect(f"/group/{group_id}")
    error = None
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add_member":
            uname = (request.form.get("username") or "").strip()
            if not uname:                               error = "Enter a username."
            elif uname not in users:                    error = f"@{uname} not found."
            elif uname in group.get("members",[]):      error = f"@{uname} already in group."
            else:
                group.setdefault("members",[]).append(uname)
                groups[group_id] = group; save_groups(groups)
                return redirect(f"/group/{group_id}/admin")
        elif action == "remove_member":
            member = request.form.get("member")
            if member and member != group.get("owner") and member in group.get("members",[]):
                group["members"] = [m for m in group["members"] if m != member]
                groups[group_id] = group; save_groups(groups)
            return redirect(f"/group/{group_id}/admin")
        elif action == "delete_group":
            groups.pop(group_id, None); save_groups(groups)
            return redirect("/groups")
    members = [{"username":m,"is_owner":(m==group.get("owner"))} for m in group.get("members",[])]
    avatar_url = group.get("avatar","") or ""
    return render_template("group_admin.html", user=me, group=group,
                           group_id=group_id, members=members,
                           avatar_url=avatar_url, error=error, active="groups")

# ---------- NOTIFICATION / PING ----------
@app.route("/unread.json")
def unread_json():
    me = current_user()
    if not me: return jsonify(ok=False, unread=0)
    info = load_users().get(me,{})
    unread_map = info.get("unread",{}) or {}
    total, senders = 0, []
    for sender, v in unread_map.items():
        try:
            c = int(v)
            if c > 0: total += c; senders.append(sender)
        except Exception: pass
    return jsonify(ok=True, unread=total, senders=senders)

@app.route("/ping", methods=["POST"])
def ping():
    me = current_user()
    if not me: return ("",401)
    users = load_users()
    info  = users.get(me,{})
    info["last_seen"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    users[me] = info; save_users(users)
    return ("",204)

# ---------- MAIN ----------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
