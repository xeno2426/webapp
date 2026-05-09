from flask import (
    Flask,
    request,
    redirect,
    session,
    send_from_directory,
    jsonify,
    url_for,
)
from datetime import datetime, timedelta
import os, json, hashlib, html
from werkzeug.utils import secure_filename
from cryptography.fernet import Fernet
import base64
import hashlib
import secrets

# ---------- PATHS / FILES ----------

BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOADS_ROOT = os.path.join(BASE_DIR, "uploads")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOADS_ROOT, exist_ok=True)

USERS_FILE = os.path.join(DATA_DIR, "users.json")

ADMIN_KEY = "XENO-ADMIN-2426"

# ---------- FLASK APP ----------

app = Flask(__name__)
app.secret_key = "CHANGE_THIS_SECRET_KEY"   # change for production

# -------- CHAT ENCRYPTION --------

SECRET_MASTER_KEY = "MY_SUPER_SECRET_KEY_123"  # you can change this

def get_cipher():
    key = hashlib.sha256(SECRET_MASTER_KEY.encode()).digest()
    key = base64.urlsafe_b64encode(key)
    return Fernet(key)

def encrypt_text(text):
    if not text:
        return ""
    f = get_cipher()
    return f.encrypt(text.encode()).decode()

def decrypt_text(token):
    if not token:
        return ""
    f = get_cipher()
    try:
        # New encrypted messages
        return f.decrypt(token.encode()).decode()
    except Exception:
        # Old messages that were stored as plain text (not encrypted)
        return token

 # -------- SECURE RANDOM FILENAME (for all uploads) --------
def secure_random_filename(original, prefix=""):
    """
    Returns an unpredictable name like:
    story_w4R6k2s1Vq2nG4h7.png
    """
    original = original or "file"
    ext = ""
    if "." in original:
        ext = "." + original.rsplit(".", 1)[1].lower()
    token = secrets.token_urlsafe(16)  # random, URL-safe
    return f"{prefix}{token}{ext}"

# ---------- SMALL HELPERS ----------

def time_ago(ts_str):
    try:
        dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        diff = datetime.now() - dt
        s = int(diff.total_seconds())
        if s < 60: return "just now"
        if s < 3600: return f"{s//60}m ago"
        if s < 86400: return f"{s//3600}h ago"
        return dt.strftime("%b %d")
    except Exception:
        return ts_str


def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def load_users():
    return load_json(USERS_FILE, {})


def save_users(users):
    save_json(USERS_FILE, users)

 #---------note helper -------#
def notes_file(username: str) -> str:
    return os.path.join(DATA_DIR, f"notes_{username}.json")


def load_notes(username: str):
    return load_json(notes_file(username), [])


def save_notes(username: str, notes):
    save_json(notes_file(username), notes)

#-------chat helpers---------#
def chat_path(u1: str, u2: str) -> str:
    a, b = sorted([u1, u2])
    return os.path.join(DATA_DIR, f"chat_{a}__{b}.json")


def load_chat(u1: str, u2: str):
    return load_json(chat_path(u1, u2), [])


def save_chat(u1: str, u2: str, data):
    save_json(chat_path(u1, u2), data)

# -------- STORIES HELPERS --------
STORIES_FILE = os.path.join(os.path.dirname(__file__), "stories.json")
STORY_TTL_HOURS = 16  # stories disappear after 16 hours

def load_stories():
    try:
        with open(STORIES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    return data

def save_stories(data):
    try:
        with open(STORIES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

# ---------- GROUP CHAT HELPERS ----------

GROUPS_FILE = os.path.join(DATA_DIR, "groups.json")

def load_groups():
    return load_json(GROUPS_FILE, {})

def save_groups(groups):
    save_json(GROUPS_FILE, groups)

def group_chat_path(group_id):
    return os.path.join(DATA_DIR, f"group_{group_id}.json")

def load_group_chat(group_id):
    return load_json(group_chat_path(group_id), [])

def save_group_chat(group_id, data):
    save_json(group_chat_path(group_id), data)

def user_upload_dir(username: str) -> str:
    path = os.path.join(UPLOADS_ROOT, username)
    os.makedirs(path, exist_ok=True)
    return path


def current_user():
    return session.get("user")


def require_login():
    if not current_user():
        return redirect("/login")
    return None


def hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()


def count_unread(username: str) -> int:
    users = load_users()
    info = users.get(username, {})
    unread = info.get("unread", {})
    return sum(int(v) for v in unread.values())


# ---------- HTML SHELL & RENDER ----------

HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Xeno's WebApp</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
*{box-sizing:border-box}
body{
  margin:0;
  background:#020617;
  font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  color:#e5e7eb;
}
.app{
  min-height:100vh;
  padding:16px;
  display:flex;
  align-items:center;
  justify-content:center;
}
.card{
  width:100%;
  max-width:520px;
  background:rgba(15,23,42,0.98);
  border-radius:20px;
  box-shadow:0 20px 45px rgba(0,0,0,.8);
  padding:18px 18px 20px;
  border:1px solid rgba(148,163,184,.28);
}
.top{
  display:flex;
  justify-content:space-between;
  align-items:center;
  margin-bottom:8px;
}
.top span{
  font-size:14px;
  font-weight:600;
}
.top a{
  font-size:12px;
  color:#fecaca;
  text-decoration:none;
}
.nav{
  display:flex;
  margin-bottom:14px;
  border-radius:999px;
  background:#020617;
  padding:4px;
}
.nav a{
  flex:1;
  text-align:center;
  text-decoration:none;
  padding:7px 0;
  border-radius:999px;
  font-size:13px;
  color:#94a3b8;
  border:1px solid transparent;
}
.nav a.active{
  color:#e5e7eb;
  background:rgba(15,23,42,0.96);
  border-color:#0ea5e9;
}
.nav a .dot{
  display:inline-block;
  width:8px;
  height:8px;
  border-radius:50%;
  background:#ef4444;
  margin-left:6px;
}
h1{
  font-size:22px;
  margin:4px 0 6px;
}
p{
  font-size:13px;
  color:#94a3b8;
  margin:0 0 10px;
}
input,textarea{
  width:100%;
  background:#020617;
  color:#e5e7eb;
  border:1px solid #1f2937;
  border-radius:12px;
  padding:9px 10px;
  font-size:14px;
  margin-bottom:10px;
  outline:none;
}
input:focus,textarea:focus{
  border-color:#38bdf8;
  box-shadow:0 0 0 1px rgba(56,189,248,.5);
}
textarea{
  min-height:120px;
  resize:vertical;
}
.btn{
  width:100%;
  border:none;
  border-radius:999px;
  padding:10px;
  font-weight:600;
  font-size:15px;
  cursor:pointer;
  background:linear-gradient(135deg,#38bdf8,#6366f1);
  color:#020617;
}
.btn2{
  width:100%;
  margin-top:8px;
  border-radius:999px;
  padding:9px;
  font-size:13px;
  cursor:pointer;
  border:1px solid #1f2937;
  background:#020617;
  color:#e5e7eb;
}
.btn-small{
  display:inline-block;
  padding:6px 10px;
  border-radius:999px;
  font-size:12px;
  font-weight:500;
  border:none;
  cursor:pointer;
  background:linear-gradient(135deg,#38bdf8,#6366f1);
  color:#020617;
}
.btn-small.outline{
  background:transparent;
  color:#e5e7eb;
  border:1px solid #1f2937;
}
.btn-small.danger{
  background:#b91c1c;
  color:#fee2e2;
}
.error{
  background:rgba(248,113,113,.08);
  border:1px solid rgba(248,113,113,.7);
  color:#fecaca;
  border-radius:10px;
  padding:7px 10px;
  font-size:12px;
  margin-bottom:10px;
}
.info{
  background:rgba(56,189,248,.08);
  border:1px solid rgba(56,189,248,.6);
  color:#bae6fd;
  border-radius:10px;
  padding:7px 10px;
  font-size:12px;
  margin-bottom:10px;
}
.note-card{
  background:#020617;
  border:1px solid #1f2937;
  border-radius:14px;
  padding:10px 11px;
  margin-top:8px;
}
.note-title{
  font-size:15px;
  font-weight:600;
}
.note-time{
  font-size:11px;
  opacity:.7;
  margin-bottom:4px;
}
.note-body{
  font-size:13px;
}
.note-actions{
  margin-top:8px;
  display:flex;
  justify-content:space-between;
}
.note-actions form{
  margin:0;
}
a.link{
  color:#a855f7;
  font-size:13px;
  text-decoration:none;
}
a.link:hover{
  text-decoration:underline;
}

/* Chat */
.chat-box{
  margin-top:8px;
  border-radius:14px;
  border:1px solid #1f2937;
  background:rgba(15,23,42,0.96);
  max-height:60vh;
  overflow-y:auto;
  padding:8px;
  scroll-behavior:smooth;
}
.msg-row{
  display:flex;
  margin-bottom:6px;
}
.msg-bubble{
  max-width:80%;
  padding:7px 9px;
  border-radius:12px;
  font-size:13px;
}
.msg-bubble.me{
  margin-left:auto;
  background:linear-gradient(135deg,#38bdf8,#6366f1);
  color:#020617;
}
.msg-bubble.them{
  margin-right:auto;
  background:#111827;
  border:1px solid #1f2937;
}
.msg-author{
  font-weight:600;
  font-size:12px;
  margin-bottom:2px;
}
.msg-time{
  font-size:10px;
  opacity:.8;
  margin-left:6px;
}
.msg-file a{
  color:#bfdbfe;
  font-size:12px;
}
.chat-input-row{
  margin-top:10px;
}
.chat-input-row input[type=file]{
  background:#020617;
  border-radius:12px;
  border:1px solid #1f2937;
  padding:7px 10px;
}
.helper{
  font-size:11px;
  color:#9ca3af;
  margin-top:2px;
}

/* Friends */
.friend-card{
  background:#020617;
  border-radius:12px;
  border:1px solid #1f2937;
  padding:9px 10px;
  margin-top:8px;
  display:flex;
  justify-content:space-between;
  align-items:center;
  font-size:13px;
}
.friend-card small{
  opacity:.7;
}
.friend-card form{
  margin:0 0 0 6px;
  display:inline;
}
.friend-card .btn-small{
  font-size:12px;
}

/* Profile */
.avatar{
  width:70px;
  height:70px;
  border-radius:999px;
  object-fit:cover;
  border:2px solid #1f2937;
  margin-bottom:6px;
}
/* Custom Confirm Modal */
.modal-bg{
  position:fixed;
  inset:0;
  background:rgba(0,0,0,0.6);
  display:none;
  align-items:center;
  justify-content:center;
  z-index:999;
}

.modal-box{
  background:rgba(15,23,42,0.98);
  border:1px solid rgba(148,163,184,.28);
  border-radius:18px;
  padding:18px;
  width:90%;
  max-width:320px;
  text-align:center;
  box-shadow:0 20px 45px rgba(0,0,0,.8);
}

.modal-box h2{
  font-size:18px;
  margin-bottom:10px;
}

.modal-actions{
  display:flex;
  gap:10px;
  margin-top:14px;
}

.modal-actions button{
  flex:1;
}
/* Voice message player */
.voice-box{
  margin-top:6px;
  border-radius:999px;
  padding:6px 10px;
  background:linear-gradient(135deg,#38bdf8,#6366f1); /* like login button */
}

.voice-box audio{
  width:100%;
  display:block;
}
/* Image preview in chat */
.image-box{
  margin-top:6px;
  border-radius:14px;
  overflow:hidden;
  border:1px solid #1f2937;
}

.image-box img{
  width:100%;
  display:block;
}
/* Reply + reactions + actions */
.reply-preview{
  font-size:11px;
  color:#000000;   /* BLACK text */
  background:#e5e7eb;  /* light background for contrast */
  border-left:3px solid #2563eb;
  padding:6px 8px;
  margin-bottom:6px;
  border-radius:6px;
}

.msg-actions{
  margin-top:4px;
  font-size:11px;
  display:flex;
  gap:6px;
}

.msg-actions form{
  margin:0;
}

.msg-action-btn{
  background:transparent;
  border:none;
  color:#9ca3af;
  padding:0;
  cursor:pointer;
}

.msg-action-btn:hover{
  color:#e5e7eb;
}

.reaction-row{
  margin-top:3px;
  font-size:11px;
}

.reaction-chip{
  display:inline-block;
  padding:2px 6px;
  border-radius:999px;
  background:#020617;
  border:1px solid #1f2937;
  margin-right:4px;
}
/* Long-press reaction picker */
.reaction-picker{
  position:fixed;
  left:50%;
  top:60%;
  transform:translateX(-50%);
  background:#020617;
  border:1px solid #1f2937;
  border-radius:999px;
  padding:4px 8px;
  box-shadow:0 12px 30px rgba(0,0,0,.6);
  display:none;
  z-index:999;
}

.reaction-picker button{
  background:transparent;
  border:none;
  font-size:18px;
  padding:3px 4px;
  cursor:pointer;
}
.reply-cancel{
  margin-left:10px;
  font-size:12px;
  color:#ef4444;
  cursor:pointer;
  font-weight:600;
}
.reply-cancel:hover{
  text-decoration:underline;
}
/* Stories grid */
.stories-grid{
  display:grid;
  grid-template-columns:repeat(3,minmax(0,1fr));
  gap:14px;
  margin-top:10px;
}

.story-item{
  text-align:center;
  font-size:12px;
}

.story-circle{
  background:transparent;
  border:none;
  padding:0;
  cursor:pointer;
  display:flex;
  flex-direction:column;
  align-items:center;
}

.story-ring{
  padding:2px;
  border-radius:999px;
  background:linear-gradient(135deg,#60a5fa,#a855f7);
}

.story-thumb{
  width:64px;
  height:64px;
  border-radius:999px;
  object-fit:cover;
  background:#020617;
  display:block;
}

.story-name{
  font-size:12px;
  color:#e5e7eb;
  margin-top:4px;
}

.story-views{
  font-size:11px;
  color:#9ca3af;
  margin-top:2px;
}

/* FULLSCREEN STORIES */
.story-overlay{
  position:fixed;
  top:0;
  left:0;
  width:100vw;
  height:100vh;
  background:rgba(15,23,42,0.92);
  display:flex;
  align-items:center;
  justify-content:center;
  z-index:2000;
}

.story-viewer{
  position: relative;
  width:100%;
  max-width:420px;
  max-height:90vh;
  background:#020617;
  border-radius:24px;
  border:1px solid #1f2937;
  padding:16px 16px 18px;
  box-shadow:0 18px 45px rgba(0,0,0,0.9);
  display:flex;
  flex-direction:column;
}

.story-view-media{
  margin-top:8px;
  border-radius:16px;
  max-width:100%;
  max-height:70vh;
  display:block;
  object-fit:contain;
  /* your existing rules ... */
  -webkit-user-drag: none;
  -webkit-touch-callout: none;
  user-select: none;
}
.story-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.75);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
}

.story-progress{
  height:3px;
  border-radius:999px;
  background:#020617;
  border:1px solid #1f2937;
  margin-bottom:8px;
  overflow:hidden;
}

.story-progress-inner{
  height:100%;
  width:0%;
  background:linear-gradient(90deg,#60a5fa,#a855f7);
}

.story-view-header{
  display:flex;
  justify-content:space-between;
  font-size:12px;
  color:#9ca3af;
  margin-top:4px;
}

.story-view-media{
  margin-top:8px;
  border-radius:16px;
  max-width:100%;
  max-height:320px;
  display:block;
}

.story-view-caption{
  font-size:13px;
  margin-top:6px;
}

.story-view-views{
  font-size:11px;
  color:#9ca3af;
  margin-top:6px;
}
.story-delete-wrap {
  position: absolute;
  right: 14px;
  bottom: 14px;
  z-index: 20;
}

.story-delete-btn {
  position: relative;
  background: #e53935;
  color: white;
  border: none;
  padding: 8px 16px;
  border-radius: 999px;
  font-weight: 600;
}
/* Group avatars */
.group-avatar{
  width:24px;
  height:24px;
  border-radius:999px;
  object-fit:cover;
  margin-right:8px;
  vertical-align:middle;
}

.group-avatar-large{
  width:32px;
  height:32px;
  border-radius:999px;
  object-fit:cover;
  margin-right:8px;
  vertical-align:middle;
}
/* In-site notification banner */
.notif-banner{
  position:fixed;
  top:12px;
  left:50%;
  transform:translateX(-50%);
  background:#020617;
  border:1px solid #1f2937;
  border-radius:999px;
  padding:6px 14px;
  font-size:12px;
  color:#e5e7eb;
  display:flex;
  align-items:center;
  gap:10px;
  box-shadow:0 10px 30px rgba(0,0,0,.6);
  z-index:1000;
}

.notif-link{
  font-size:12px;
  color:#bfdbfe;
  text-decoration:underline;
}
/* Group delete confirm modal */
.gconfirm-overlay{
  position:fixed;
  inset:0;
  background:rgba(15,23,42,0.8);
  display:none;
  align-items:center;
  justify-content:center;
  z-index:1000;
}

.gconfirm-box{
  background:#020617;
  border-radius:18px;
  border:1px solid #1f2937;
  padding:18px 20px;
  max-width:320px;
  width:90%;
  box-shadow:0 18px 45px rgba(0,0,0,0.85);
}

.gconfirm-title{
  font-size:16px;
  font-weight:600;
  margin-bottom:6px;
}

.gconfirm-text{
  font-size:13px;
  color:#9ca3af;
  margin-bottom:14px;
}

.gconfirm-buttons{
  display:flex;
  justify-content:flex-end;
  gap:8px;
}
/* Red pill delete buttons (friends + group admin) */
button.btn-danger{
  background:#ef4444;
  color:#ffffff;
  border:none;
  padding:6px 18px;
  border-radius:999px;
  font-size:13px;
  font-weight:600;
  cursor:pointer;
}

button.btn-danger:hover{
  filter:brightness(1.05);
}
</style>
</head>
<body>
<div class="app">
  <div class="card">
    {TOP}
    {NAV}
    {CONTENT}
<!-- Custom Delete Confirm Modal -->
<div class="modal-bg" id="confirmModal">
  <div class="modal-box">
    <h2>Delete Friend?</h2>
    <p style="font-size:13px;color:#94a3b8;">
      Are you sure you want to delete this friend?
    </p>
    <div class="modal-actions">
      <button class="btn2" onclick="closeConfirm()">Cancel</button>
      <button class="btn-small danger" id="confirmYes">Delete</button>
    </div>
  </div>
</div>

  </div>
</div>
<script>
let deleteForm = null;

function openConfirm(form){
  deleteForm = form;
  document.getElementById("confirmModal").style.display = "flex";
  return false;
}

function closeConfirm(){
  document.getElementById("confirmModal").style.display = "none";
  deleteForm = null;
}

document.addEventListener("DOMContentLoaded", function(){
  const yesBtn = document.getElementById("confirmYes");
  if(yesBtn){
    yesBtn.onclick = function(){
      if(deleteForm){
        deleteForm.submit();
      }
    }
  }
});
</script>
<script>
document.addEventListener('DOMContentLoaded', function(){
  var banner = null;

  function ensureBanner(){
    if (banner) return banner;
    banner = document.createElement('div');
    banner.className = 'notif-banner';
    banner.style.display = 'none';
    banner.innerHTML = '<span id="notifText"></span><a href="/friends" class="notif-link">Open chats</a>';
    document.body.appendChild(banner);
    return banner;
  }

  function updateBanner(count, senders){
    var b = ensureBanner();
    var textEl = b.querySelector('#notifText');
    if (!textEl) return;

    if (!count || count <= 0){
      b.style.display = 'none';
      return;
    }

    var who = '';
    if (senders && senders.length > 0){
      var names = senders.slice(0,2).map(function(s){ return '@'+s; }).join(', ');
      if (senders.length > 2) names += ' +' + (senders.length-2) + ' more';
      who = ' from ' + names;
    }

    var msg = (count === 1)
      ? '1 new message' + who
      : count + ' new messages' + who;

    textEl.textContent = msg;
    b.style.display = 'flex';
  }

  function pollUnread(){
    fetch('/unread.json')
      .then(function(r){ return r.json(); })
      .then(function(data){
        if (!data || !data.ok) return;
        updateBanner(data.unread || 0, data.senders || []);
      })
      .catch(function(e){
        // ignore network errors silently
      });
  }

  // ping server to keep online status fresh
  function pingOnline(){
    fetch('/ping', {method:'POST'}).catch(function(){});
  }

  // first check + poll every 5 seconds
  pollUnread();
  setInterval(pollUnread, 5000);
  pingOnline();
  setInterval(pingOnline, 20000);
});
</script>
</body>
</html>
"""

def nav_html(active: str, user: str | None):
    if not user:
        return ""  # no nav on login/signup

    unread = count_unread(user)
    friends_label = "Friends"
    if unread > 0:
        friends_label += ' <span class="dot"></span>'

    def item(name, label, href):
        cls = "active" if active == name else ""
        return f'<a href="{href}" class="{cls}">{label}</a>'

    return (
        '<div class="nav">'
        + item("home", "Home", "/")
        + item("friends", friends_label, "/friends")
        + item("stories", "Stories", "/stories")
        + item("groups", "Groups", "/groups")
        + item("profile", "Profile", "/profile")
        + "</div>"
    )


def render(content: str, active: str = "", user: str | None = None):
    if user:
        top = f'<div class="top"><span>@{html.escape(user)}</span><a href="/logout">Logout</a></div>'
    else:
        top = '<div class="top"><span>Xeno WebApp</span><a href="/login">Login</a></div>'
    page = HTML.replace("{TOP}", top)
    page = page.replace("{NAV}", nav_html(active, user))
    page = page.replace("{CONTENT}", content)
    return page
#---------- in-site notfication--------
@app.route("/unread.json")
def unread_json():
    me = current_user()
    if not me:
        return jsonify(ok=False, unread=0)

    users = load_users()
    info = users.get(me, {})
    unread_map = info.get("unread", {}) or {}
    total = 0
    senders = []

    if isinstance(unread_map, dict):
        for sender, v in unread_map.items():
            try:
                count = int(v)
                if count > 0:
                    total += count
                    senders.append(sender)
            except Exception:
                pass

    return jsonify(ok=True, unread=total, senders=senders)

# ---------- AUTH ROUTES ----------

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user():
        return redirect("/")

    users = load_users()
    error = ""
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        p1 = request.form.get("password", "")
        p2 = request.form.get("password2", "")
        recovery = request.form.get("recovery", "").strip()

        if not u or not p1 or not p2:
            error = "All fields are required."
        elif " " in u or len(u) < 3:
            error = "Username must be at least 3 characters, no spaces."
        elif u in users:
            error = "Username already exists."
        elif p1 != p2:
            error = "Passwords do not match."
        elif len(p1) < 4:
            error = "Password too short."
        else:
            users[u] = {
                "password_hash": hash_pw(p1),
                "bio": "",
                "avatar": "",
                "friends": [],
                "recovery": recovery,
                "unread": {},
            }
            save_users(users)
            session["user"] = u
            return redirect("/")

    msg = f'<div class="error">{html.escape(error)}</div>' if error else ""
    content = f"""
<h1>Create account</h1>
<p>Make a new Xeno account.</p>
{msg}
<form method="post">
  <input name="username" placeholder="Username" required>
  <input name="password" type="password" placeholder="Password" required>
  <input name="password2" type="password" placeholder="Confirm password" required>
  <input name="recovery" placeholder="Secret phrase for recovery (optional)">
  <button class="btn" type="submit">Create account</button>
</form>
<form action="/login">
  <button class="btn2" type="submit">Back to login</button>
</form>
"""
    return render(content, active="", user=None)


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect("/")

    users = load_users()
    error = ""
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        p = request.form.get("password", "")
        info = users.get(u)
        if not info:
            error = "User not found."
        elif info.get("password_hash") != hash_pw(p):
            error = "Wrong password."
        else:
            session["user"] = u
            return redirect("/")

    msg = f'<div class="error">{html.escape(error)}</div>' if error else ""
    content = f"""
<h1>Login</h1>
<p>Welcome back.</p>
{msg}
<form method="post">
  <input name="username" placeholder="Username" required>
  <input name="password" type="password" placeholder="Password" required>
  <button class="btn" type="submit">Login</button>
</form>
<form action="/signup">
  <button class="btn2" type="submit">Create account</button>
</form>
<form action="/reset">
  <button class="btn2" type="submit">Reset password (admin key)</button>
</form>
"""
    return render(content, active="", user=None)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/reset", methods=["GET", "POST"])
def reset_with_admin_key():
    users = load_users()
    error = ""
    info_msg = ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        new_pw = request.form.get("password", "")
        new_pw2 = request.form.get("password2", "")
        recovery = request.form.get("recovery", "").strip()
        admin_key = request.form.get("admin_key", "").strip()

        if admin_key != ADMIN_KEY:
            error = "Admin key is wrong."
        elif not username or username not in users:
            error = "User not found."
        elif new_pw != new_pw2 or len(new_pw) < 4:
            error = "Passwords empty, short, or don't match."
        else:
            stored_recovery = users[username].get("recovery", "")
            if not stored_recovery or stored_recovery.lower() != recovery.lower():
                error = "Recovery phrase does not match."
            else:
                users[username]["password_hash"] = hash_pw(new_pw)
                save_users(users)
                info_msg = "Password updated. You can login now."

    block = ""
    if error:
        block = f'<div class="error">{html.escape(error)}</div>'
    elif info_msg:
        block = f'<div class="info">{html.escape(info_msg)}</div>'

    content = f"""
<h1>Reset password</h1>
<p>Use your recovery phrase + admin key.</p>
{block}
<form method="post">
  <input name="username" placeholder="Username" required>
  <input name="recovery" placeholder="Your recovery phrase" required>
  <input name="password" type="password" placeholder="New password" required>
  <input name="password2" type="password" placeholder="Confirm new password" required>
  <input name="admin_key" placeholder="Admin key" required>
  <button class="btn" type="submit">Change password</button>
</form>
<form action="/login">
  <button class="btn2" type="submit">Back to login</button>
</form>
"""
    return render(content, active="", user=None)

# ---------- HOME / NOTES ----------

@app.route("/", methods=["GET", "POST"])
def home():
    user = current_user()
    if not user:
        return redirect("/login")

    # quick note
    if request.method == "POST":
        txt = request.form.get("quick", "").strip()
        if txt:
            notes = load_notes(user)
            title_line = txt.splitlines()[0][:60] if txt.strip() else "Note"
            notes.insert(0, {
                "title": title_line,
                "body": txt,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
            save_notes(user, notes)
        return redirect("/")

    sort = request.args.get("sort", "newest")
    notes = load_notes(user)
    if sort == "oldest":
        notes_sorted = list(enumerate(notes))[::-1]
    else:
        notes_sorted = list(enumerate(notes))

    notes_html = ""
    for i, n in notes_sorted:
        title = html.escape(n.get("title", "Untitled"))
        body = html.escape(n.get("body", ""))
        t = time_ago(n.get("time", ""))
        notes_html += f"""
<div class="note-card" data-title="{html.escape(n.get('title','').lower())}" data-body="{html.escape(n.get('body','').lower())}">
  <div class="note-title">{title}</div>
  <div class="note-time">{t}</div>
  <div class="note-body" style="white-space:pre-wrap;">{body}</div>
  <div class="note-actions">
    <form method="get" action="/note/{i}">
      <button class="btn-small outline" type="submit">Edit</button>
    </form>
    <form method="post" action="/note/{i}/delete">
      <button class="btn-small outline" type="submit">Delete</button>
    </form>
  </div>
</div>
"""

    sort_active_new = "active" if sort == "newest" else ""
    sort_active_old = "active" if sort == "oldest" else ""

    content = f"""
<h1>Home</h1>
<p>Quick notes and reminders.</p>

<form method="post">
  <textarea name="quick" placeholder="Quick note..." maxlength="2000"
    oninput="document.getElementById('qcount').textContent=this.value.length+'/2000'"></textarea>
  <p style="font-size:11px;color:#64748b;text-align:right;margin-top:-8px;" id="qcount">0/2000</p>
  <button class="btn" type="submit">Save note</button>
</form>

<div style="display:flex;justify-content:space-between;align-items:center;margin-top:14px;">
  <p style="font-weight:500;margin:0;">Saved notes ({len(notes)})</p>
  <div style="display:flex;gap:6px;align-items:center;">
    <a href="/?sort=newest" class="btn-small {'outline' if sort!='newest' else ''}" style="font-size:11px;">Newest</a>
    <a href="/?sort=oldest" class="btn-small {'outline' if sort!='oldest' else ''}" style="font-size:11px;">Oldest</a>
  </div>
</div>

<p><a href="/note/new" class="link">+ New full note</a></p>

<input id="noteSearch" placeholder="Search notes..." oninput="filterNotes(this.value)"
  style="margin-bottom:8px;">

<div id="notesList">
{notes_html if notes_html else "<p style='font-size:13px;color:#64748b;'>No notes yet.</p>"}
</div>

<script>
function filterNotes(q){{
  q = q.toLowerCase();
  document.querySelectorAll('#notesList .note-card').forEach(function(c){{
    var t = (c.getAttribute('data-title')||'') + ' ' + (c.getAttribute('data-body')||'');
    c.style.display = t.includes(q) ? '' : 'none';
  }});
}}
</script>
"""
    return render(content, active="home", user=user)


@app.route("/note/new", methods=["GET", "POST"])
def note_new():
    user = current_user()
    if not user:
        return redirect("/login")

    error = ""
    if request.method == "POST":
        title = request.form.get("title", "").strip() or "Untitled"
        body = request.form.get("body", "").strip()
        if not body:
            error = "Note body cannot be empty."
        else:
            notes = load_notes(user)
            notes.insert(0, {
                "title": title[:80],
                "body": body,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
            save_notes(user, notes)
            return redirect("/")

    block = f'<div class="error">{html.escape(error)}</div>' if error else ""
    content = f"""
<h1>New note</h1>
<p>Create a full note.</p>
{block}
<form method="post">
  <input name="title" placeholder="Title">
  <textarea name="body" placeholder="Write your note..." required></textarea>
  <button class="btn" type="submit">Save note</button>
</form>
<p><a href="/" class="link">Back to Home</a></p>
"""
    return render(content, active="home", user=user)


@app.route("/note/<int:index>", methods=["GET", "POST"])
def edit_note(index):
    user = current_user()
    if not user:
        return redirect("/login")

    notes = load_notes(user)
    if index < 0 or index >= len(notes):
        return redirect("/")

    error = ""
    if request.method == "POST":
        title = request.form.get("title", "").strip() or "Untitled"
        body = request.form.get("body", "").strip()
        if not body:
            error = "Note body cannot be empty."
        else:
            notes[index]["title"] = title[:80]
            notes[index]["body"] = body
            save_notes(user, notes)
            return redirect("/")

    n = notes[index]
    block = f'<div class="error">{html.escape(error)}</div>' if error else ""
    content = f"""
<h1>Edit note</h1>
{block}
<form method="post">
  <input name="title" value="{html.escape(n.get('title',''))}">
  <textarea name="body">{html.escape(n.get('body',''))}</textarea>
  <button class="btn" type="submit">Save changes</button>
</form>
<p><a href="/" class="link">Back to Home</a></p>
"""
    return render(content, active="home", user=user)


@app.route("/note/<int:index>/delete", methods=["POST"])
def delete_note(index):
    user = current_user()
    if not user:
        return redirect("/login")

    notes = load_notes(user)
    if 0 <= index < len(notes):
        notes.pop(index)
        save_notes(user, notes)
    return redirect("/")

# ---------- PROFILE + UPLOADS ----------

@app.route("/profile", methods=["GET", "POST"])
def profile():
    user = current_user()
    if not user:
        return redirect("/login")

    users = load_users()
    info = users.get(user, {})
    error = ""
    info_msg = ""

    if request.method == "POST":
        action = request.form.get("action")

        if action == "update_bio":
            bio = request.form.get("bio", "")[:400]
            info["bio"] = bio
            users[user] = info
            save_users(users)
            info_msg = "Bio updated."

        elif action == "update_recovery":
            rec = request.form.get("recovery", "").strip()
            info["recovery"] = rec
            users[user] = info
            save_users(users)
            info_msg = "Recovery phrase updated."

        elif action == "change_password":
            old = request.form.get("old_pw", "")
            new1 = request.form.get("new_pw", "")
            new2 = request.form.get("new_pw2", "")
            if info.get("password_hash") != hash_pw(old):
                error = "Old password incorrect."
            elif new1 != new2 or len(new1) < 4:
                error = "New passwords don't match or are too short."
            else:
                info["password_hash"] = hash_pw(new1)
                users[user] = info
                save_users(users)
                info_msg = "Password changed."

        elif action == "avatar":
            file = request.files.get("avatar")
            if file and file.filename:
                allowed = {"png", "jpg", "jpeg", "gif", "webp"}
                ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
                file.seek(0, 2)
                size = file.tell()
                file.seek(0)
                if ext not in allowed:
                    error = "Only PNG, JPG, GIF, WEBP images allowed."
                elif size > 5 * 1024 * 1024:
                    error = "Image must be under 5MB."
                else:
                    filename = secure_filename(file.filename)
                    updir = user_upload_dir(user)
                    path = os.path.join(updir, filename)
                    file.save(path)
                    info["avatar"] = filename
                    users[user] = info
                    save_users(users)
                    info_msg = "Avatar updated."

        elif action == "delete_account":
            confirm = request.form.get("confirm_delete", "").strip()
            if confirm != user:
                error = "Type your username exactly to confirm deletion."
            else:
                # remove from friends lists
                for uname, uinfo in users.items():
                    if uname == user:
                        continue
                    uinfo["friends"] = [f for f in uinfo.get("friends", []) if f != user]
                    uinfo.get("friend_requests", [])
                    if user in uinfo.get("friend_requests", []):
                        uinfo["friend_requests"].remove(user)
                users.pop(user, None)
                save_users(users)
                session.clear()
                return redirect("/login")

    avatar_url = ""
    if info.get("avatar"):
        avatar_url = f'/uploads/{user}/{info["avatar"]}'

    bio_val = html.escape(info.get("bio", ""))
    rec_val = html.escape(info.get("recovery", ""))
    bio_len = len(info.get("bio", ""))

    block = ""
    if error:
        block = f'<div class="error">{html.escape(error)}</div>'
    elif info_msg:
        block = f'<div class="info">{html.escape(info_msg)}</div>'

    avatar_html = f'<img src="{avatar_url}" class="avatar" alt="avatar">' if avatar_url else ""

    content = f"""
<h1>Profile</h1>
<p>Manage your profile, avatar and security.</p>
{block}
{avatar_html}

<form method="post" enctype="multipart/form-data">
  <input type="hidden" name="action" value="avatar">
  <input type="file" name="avatar" accept="image/png,image/jpeg,image/gif,image/webp">
  <p style="font-size:11px;color:#64748b;margin-top:-6px;">PNG/JPG/GIF/WEBP · max 5MB</p>
  <button class="btn2" type="submit">Upload avatar</button>
</form>

<form method="post" style="margin-top:12px;">
  <input type="hidden" name="action" value="update_bio">
  <textarea name="bio" placeholder="Your bio..." maxlength="400"
    oninput="document.getElementById('bioCount').textContent=this.value.length+'/400'">{bio_val}</textarea>
  <p style="font-size:11px;color:#64748b;text-align:right;margin-top:-8px;" id="bioCount">{bio_len}/400</p>
  <button class="btn2" type="submit">Save bio</button>
</form>

<form method="post" style="margin-top:12px;">
  <input type="hidden" name="action" value="update_recovery">
  <input name="recovery" placeholder="Recovery phrase" value="{rec_val}">
  <button class="btn2" type="submit">Save recovery phrase</button>
</form>

<form method="post" style="margin-top:12px;">
  <input type="hidden" name="action" value="change_password">
  <input name="old_pw" type="password" placeholder="Old password" required>
  <input name="new_pw" type="password" placeholder="New password" required>
  <input name="new_pw2" type="password" placeholder="Confirm new password" required>
  <button class="btn2" type="submit">Change password</button>
</form>

<hr style="border-color:#1f2937;margin:18px 0;">
<p style="font-size:13px;font-weight:600;color:#ef4444;">Danger Zone</p>
<p style="font-size:12px;color:#64748b;">This permanently deletes your account, messages and data.</p>
<form method="post" onsubmit="return confirm('Are you absolutely sure? This cannot be undone.');">
  <input type="hidden" name="action" value="delete_account">
  <input name="confirm_delete" placeholder="Type your username to confirm">
  <button class="btn2" type="submit" style="color:#ef4444;border-color:#ef4444;margin-top:6px;">Delete my account</button>
</form>
"""
    return render(content, active="profile", user=user)


@app.route("/uploads/<username>/<filename>")
def serve_upload(username, filename):
    return send_from_directory(user_upload_dir(username), filename)


@app.route("/user/<username>")
def user_profile(username):
    me = current_user()
    if not me:
        return redirect("/login")
    users = load_users()
    info = users.get(username)
    if not info:
        return redirect("/friends")

    bio = html.escape(info.get("bio", ""))
    avatar = info.get("avatar")
    avatar_html = ""
    if avatar:
        avatar_html = f'<img src="/uploads/{username}/{avatar}" class="avatar" alt="avatar">'

    content = f"""
<h1>@{html.escape(username)}</h1>
<p>Public profile.</p>
{avatar_html}
<p style="margin-top:8px;font-size:13px;">{bio or "No bio yet."}</p>
<p style="margin-top:12px;">
  <a href="/friends" class="link">Back to Friends</a>
</p>
"""
    return render(content, active="friends", user=me)

# ---------- FRIENDS & CHAT ----------

@app.route("/friends", methods=["GET", "POST"])
def friends():
    me = current_user()
    if not me:
        return redirect("/login")

    users = load_users()
    info = users.get(me, {})
    # update my last_seen time
    info["last_seen"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    users[me] = info
    save_users(users)

    error = ""
    info_msg = ""

    if request.method == "POST":
        action = request.form.get("action", "add")
        friend_name = request.form.get("friend_username", "").strip()

        if action == "add":
            if not friend_name or friend_name == me:
                error = "Invalid username."
            elif friend_name not in users:
                error = "User not found."
            elif friend_name in info.get("friends", []):
                error = "Already friends."
            elif me in users[friend_name].get("friend_requests", []):
                error = "Request already sent."
            else:
                # send friend request
                other = users.get(friend_name, {})
                reqs = other.get("friend_requests", [])
                if me not in reqs:
                    reqs.append(me)
                other["friend_requests"] = reqs
                users[friend_name] = other
                save_users(users)
                info = users[me]
                info_msg = f"Friend request sent to @{friend_name}."

        elif action == "accept":
            requester = request.form.get("requester", "").strip()
            reqs = info.get("friend_requests", [])
            if requester in reqs:
                reqs.remove(requester)
                info["friend_requests"] = reqs
                my_friends = set(info.get("friends", []))
                my_friends.add(requester)
                info["friends"] = list(my_friends)
                users[me] = info

                other = users.get(requester, {})
                other_friends = set(other.get("friends", []))
                other_friends.add(me)
                other["friends"] = list(other_friends)
                users[requester] = other

                save_users(users)
                info = users[me]
                info_msg = f"You are now friends with @{requester}."

        elif action == "decline":
            requester = request.form.get("requester", "").strip()
            reqs = info.get("friend_requests", [])
            if requester in reqs:
                reqs.remove(requester)
                info["friend_requests"] = reqs
                users[me] = info
                save_users(users)
                info = users[me]
                info_msg = f"Declined request from @{requester}."

        elif action == "remove":
            if friend_name in info.get("friends", []):
                info["friends"] = [f for f in info.get("friends", []) if f != friend_name]
                users[me] = info

                other = users.get(friend_name, {})
                other["friends"] = [f for f in other.get("friends", []) if f != me]
                users[friend_name] = other

                save_users(users)
                info_msg = f"Removed @{friend_name} from friends."

    # --- pending requests ---
    pending = info.get("friend_requests", [])
    requests_html = ""
    if pending:
        requests_html = "<p style='font-weight:600;margin-top:14px;'>Friend Requests</p>"
        for req in pending:
            requests_html += f"""
<div class="friend-card">
  <div><strong>@{html.escape(req)}</strong> wants to be friends</div>
  <div style="display:flex;gap:6px;">
    <form method="post" style="display:inline;">
      <input type="hidden" name="action" value="accept">
      <input type="hidden" name="requester" value="{html.escape(req)}">
      <button class="btn-small" type="submit">Accept</button>
    </form>
    <form method="post" style="display:inline;">
      <input type="hidden" name="action" value="decline">
      <input type="hidden" name="requester" value="{html.escape(req)}">
      <button class="btn-small outline" type="submit">Decline</button>
    </form>
  </div>
</div>
"""

    friends_list = info.get("friends", [])
    friends_html = ""
    if not friends_list:
        friends_html = "<p style='font-size:13px;color:#64748b;'>No friends yet.</p>"
    else:
        for f in sorted(friends_list):
            friend_info = users.get(f, {})
            last_seen = friend_info.get("last_seen")
            online = False
            if last_seen:
                try:
                    ts = datetime.strptime(last_seen, "%Y-%m-%d %H:%M:%S")
                    if datetime.now() - ts < timedelta(seconds=40):
                        online = True
                except Exception:
                    pass

            unread = info.get("unread", {}).get(f, 0)
            badge = f"<small> · {unread} new</small>" if unread else ""
            status_color = "#22c55e" if online else "#4b5563"
            status_label = "online" if online else "offline"
            friends_html += f"""
<div class="friend-card" data-name="{html.escape(f.lower())}">
  <div>
    <span style="display:inline-block;width:8px;height:8px;border-radius:999px;background:{status_color};margin-right:6px;" title="{status_label}"></span>
    <strong>@{html.escape(f)}</strong>{badge}
  </div>
  <div>
    <form method="post" style="display:inline;">
      <input type="hidden" name="action" value="remove">
      <input type="hidden" name="friend_username" value="{html.escape(f)}">
      <button class="btn-small danger" type="submit" onclick="return openConfirm(this.form);">Delete</button>
    </form>
    <form method="get" action="/user/{f}">
      <button class="btn-small outline" type="submit">View</button>
    </form>
    <form method="get" action="/chat/{f}">
      <button class="btn-small" type="submit">Chat</button>
    </form>
  </div>
</div>
"""

    block = ""
    if error:
        block = f'<div class="error">{html.escape(error)}</div>'
    elif info_msg:
        block = f'<div class="info">{html.escape(info_msg)}</div>'

    content = f"""
<h1>Friends</h1>
<p>Your friends list.</p>
{block}
<form method="post">
  <input name="friend_username" placeholder="Add friend by username">
  <button class="btn" type="submit">Send Request</button>
</form>

{requests_html}

<p style="font-weight:600;margin-top:14px;">Your Friends ({len(friends_list)})</p>
<input id="friendSearch" oninput="filterFriends(this.value)" placeholder="Search friends..." style="margin-bottom:8px;">
<div id="friendsList">
{friends_html if friends_html else "<p style='font-size:13px;color:#64748b;'>No friends yet.</p>"}
</div>

<script>
function filterFriends(q){{
  var cards = document.querySelectorAll('#friendsList .friend-card');
  q = q.toLowerCase();
  cards.forEach(function(c){{
    var name = c.getAttribute('data-name') || '';
    c.style.display = name.includes(q) ? '' : 'none';
  }});
}}
</script>
"""
    return render(content, active="friends", user=me)

# ----- chat with friends-------
@app.route("/chat/<friend>", methods=["GET", "POST"])
def chat(friend):
    me = current_user()
    if not me:
        return redirect("/login")

    users = load_users()
    if friend not in users:
        return redirect("/friends")

    my_info = users.get(me, {})
    if friend not in my_info.get("friends", []):
        return redirect("/friends")

    # ---------- POST: actions ----------
    if request.method == "POST":
        action = request.form.get("action", "send")

        # ------------ SEND message ------------
        if action == "send":
            txt = request.form.get("message", "").strip()
            file = request.files.get("file")
            ftype = "text"
            fname = ""
            url = ""

            # optional file upload with random filename
            if file and file.filename:
                ftype = "file"
                original = secure_filename(file.filename)
                updir = user_upload_dir(me)
                os.makedirs(updir, exist_ok=True)
                saved_name = secure_random_filename(original)  # random name
                path = os.path.join(updir, saved_name)
                file.save(path)
                fname = saved_name
                url = f"/uploads/{me}/{saved_name}"

            if txt or ftype == "file":
                chat_data = load_chat(me, friend)
                reply_key = f"reply_to_{friend}"
                reply_index = session.pop(reply_key, None)

                chat_data.append({
                    "from": me,
                    "to": friend,
                    "text": encrypt_text(txt),  # encrypt message text
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "ftype": ftype,
                    "filename": fname,
                    "url": url,
                    "seen": False,
                    "reply_to": reply_index,
                    "reactions": {},
                    "deleted": False,
                })
                save_chat(me, friend, chat_data)

            return redirect(f"/chat/{friend}")

        # ------------ SET / CLEAR REPLY ------------
        if action == "set_reply":
            idx = request.form.get("msg_index")
            try:
                idx_int = int(idx)
            except (TypeError, ValueError):
                idx_int = None

            reply_key = f"reply_to_{friend}"
            if idx_int is None or idx_int < 0:
                session.pop(reply_key, None)
            else:
                session[reply_key] = idx_int

            return redirect(f"/chat/{friend}")

        # ------------ DELETE own message ------------
        if action == "delete":
            idx = request.form.get("msg_index")
            try:
                idx_int = int(idx)
            except (TypeError, ValueError):
                idx_int = -1

            chat_data = load_chat(me, friend)
            if 0 <= idx_int < len(chat_data):
                msg = chat_data[idx_int]
                if msg.get("from") == me:
                    msg["deleted"] = True
                    msg["text"] = "This message was deleted"
                    msg["ftype"] = "text"
                    msg["filename"] = ""
                    msg["url"] = ""
                    msg["reactions"] = {}
                    save_chat(me, friend, chat_data)

            return redirect(f"/chat/{friend}")

        # ------------ REACT / UNREACT ------------
        if action == "react":
            idx = request.form.get("msg_index")
            emoji = request.form.get("emoji", "❤️")
            try:
                idx_int = int(idx)
            except (TypeError, ValueError):
                idx_int = -1

            chat_data = load_chat(me, friend)
            if 0 <= idx_int < len(chat_data):
                msg = chat_data[idx_int]
                reactions = msg.get("reactions", {}) or {}
                if reactions.get(me) == emoji:
                    reactions.pop(me, None)
                else:
                    reactions[me] = emoji
                msg["reactions"] = reactions
                save_chat(me, friend, chat_data)

            return redirect(f"/chat/{friend}")

        # fallback
        return redirect(f"/chat/{friend}")

    # ---------- GET: show chat ----------
    chat_data = load_chat(me, friend)

    # mark as seen
    changed = False
    for msg in chat_data:
        if msg.get("to") == me and not msg.get("seen"):
            msg["seen"] = True
            changed = True
    if changed:
        save_chat(me, friend, chat_data)

    # clear unread count
    unread_map = my_info.get("unread", {})
    if friend in unread_map:
        unread_map[friend] = 0
        my_info["unread"] = unread_map
        users[me] = my_info
        save_users(users)

    # build bubbles
    bubbles = ""
    for i, msg in enumerate(chat_data):
        sender = msg.get("from", "")
        text_raw = decrypt_text(msg.get("text", ""))
        if msg.get("deleted"):
            text_raw = "This message was deleted"
        text = html.escape(text_raw)
        time_html = time_ago(msg.get("time", ""))
        ftype = msg.get("ftype", "text")
        filename = msg.get("filename", "") or ""
        url = msg.get("url", "")

        align = "me" if sender == me else "them"
        author = html.escape(sender)

        # seen ticks
        seen = msg.get("seen", False)
        status_html = ""
        if sender == me:
            symbol = "✓✓" if seen else "✓"
            status_html = f'<span class="msg-time">{symbol}</span>'

        # reply preview inside bubble
        reply_html = ""
        reply_index = msg.get("reply_to")
        if isinstance(reply_index, int) and 0 <= reply_index < len(chat_data):
            rmsg = chat_data[reply_index]
            rtext_raw = decrypt_text(rmsg.get("text") or "") or "[attachment]"
            rtext = html.escape(rtext_raw[:40])
            rauthor = html.escape(rmsg.get("from", ""))
            reply_html = f'''
<div class="reply-preview">
  Replying to @{rauthor}: {rtext}
</div>
'''

        # attachments
        file_html = ""
        if ftype == "file" and url and not msg.get("deleted"):
            ext = ""
            if "." in filename:
                ext = filename.rsplit(".", 1)[1].lower()
            image_exts = ("png", "jpg", "jpeg", "gif", "webp", "bmp")
            audio_exts = ("mp3", "wav", "m4a", "ogg", "oga", "aac")

            if ext in image_exts:
                fn = html.escape(filename or "image")
                file_html = f'''
<div class="image-box">
  <a href="{url}" target="_blank">
    <img src="{url}" alt="{fn}">
  </a>
</div>
'''
            elif ext in audio_exts:
                file_html = f'''
<div class="voice-box">
  <audio controls preload="none">
    <source src="{url}">
  </audio>
</div>
'''
            else:
                fn = html.escape(filename or "file")
                file_html = f'''
<div class="msg-file">
  <a href="{url}" target="_blank">{fn}</a>
</div>
'''

        # reactions row
        reactions = msg.get("reactions", {}) or {}
        reaction_html = ""
        if reactions and not msg.get("deleted"):
            counts = {}
            for em in reactions.values():
                counts[em] = counts.get(em, 0) + 1
            chips = ""
            for em, c in counts.items():
                chips += f'<span class="reaction-chip">{em} {c}</span>'
            reaction_html = f'<div class="reaction-row">{chips}</div>'

        # actions row (reply + delete)
        actions_html = ""
        if not msg.get("deleted"):
            actions_html = f"""
<div class="msg-actions">
  <form method="post" style="display:inline;">
    <input type="hidden" name="action" value="set_reply">
    <input type="hidden" name="msg_index" value="{i}">
    <button class="msg-action-btn" type="submit">Reply</button>
  </form>
"""
            if sender == me:
                actions_html += f"""
  <form method="post" style="display:inline;">
    <input type="hidden" name="action" value="delete">
    <input type="hidden" name="msg_index" value="{i}">
    <button class="msg-action-btn" type="submit">Delete</button>
  </form>
"""
            actions_html += "</div>"

        bubbles += f"""
<div class="msg-row">
  <div class="msg-bubble {align}" data-index="{i}">
    <div class="msg-author">{author}<span class="msg-time">{time_html}</span>{status_html}</div>
    {reply_html}
    <div class="msg-text">{text}</div>
    {file_html}
    {reaction_html}
    {actions_html}
  </div>
</div>
"""

    # reply bar above input
    reply_key = f"reply_to_{friend}"
    reply_info_html = ""
    reply_index = session.get(reply_key)
    if isinstance(reply_index, int) and 0 <= reply_index < len(chat_data):
        rmsg = chat_data[reply_index]
        rtext_raw = decrypt_text(rmsg.get("text") or "") or "[attachment]"
        rtext = html.escape(rtext_raw[:60])
        rauthor = html.escape(rmsg.get("from", ""))
        reply_info_html = f"""
<div class="reply-preview" style="margin-top:10px;">
  Replying to @{rauthor}: {rtext}
  <form method="post" style="display:inline;">
    <input type="hidden" name="action" value="set_reply">
    <input type="hidden" name="msg_index" value="-1">
    <button class="reply-cancel" type="submit">✕ Cancel</button>
  </form>
</div>
"""


    # typing indicator from friend
    friend_info = users.get(friend, {})
    typing_html = ""
    ts_str = friend_info.get("typing_ts")
    typing_to = friend_info.get("typing_to")
    if ts_str and typing_to == me:
        try:
            ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
            if datetime.now() - ts < timedelta(seconds=4):
                typing_html = f"""
<div class="msg-row">
  <div class="msg-bubble them">
    <div class="msg-author">{html.escape(friend)}<span class="msg-time">typing…</span></div>
    <div class="msg-text"><span style="opacity:.7;">typing…</span></div>
  </div>
</div>
"""
        except Exception:
            pass

    if typing_html:
        bubbles += typing_html

    # script: auto-refresh + typing + TAP-TO-REACT
    script = """
<script>
  // Auto-scroll to latest message on load
  var chatBox = document.querySelector('.chat-box');
  if(chatBox) chatBox.scrollTop = chatBox.scrollHeight;

  // Enter key to send
  var msgInput = document.querySelector('input[name="message"]');
  if(msgInput){
    msgInput.addEventListener('keydown', function(e){
      if(e.key === 'Enter' && !e.shiftKey){
        e.preventDefault();
        msgInput.closest('form').submit();
      }
    });
  }

  // Auto-refresh only the chat messages every 2 seconds
  setInterval(function(){
    fetch(window.location.href)
      .then(function(res){ return res.text(); })
      .then(function(html){
        var temp = document.createElement('div');
        temp.innerHTML = html;
        var newBox = temp.querySelector('.chat-box');
        var curBox = document.querySelector('.chat-box');
        if(newBox && curBox){
          curBox.innerHTML = newBox.innerHTML;
        }
      });
  }, 2000);

  document.addEventListener('DOMContentLoaded', function(){
  // ---- Swipe to Reply (Mobile) ----
var touchStartX = 0;
var touchEndX = 0;

document.addEventListener('touchstart', function(e){
  var bubble = e.target.closest('.msg-bubble');
  if (!bubble) return;
  touchStartX = e.changedTouches[0].screenX;
  bubble.classList.add('swipe-target');
}, {passive:true});

document.addEventListener('touchend', function(e){
  var bubble = document.querySelector('.swipe-target');
  if (!bubble) return;

  touchEndX = e.changedTouches[0].screenX;
  bubble.classList.remove('swipe-target');

  var diff = touchEndX - touchStartX;

  // Swipe right threshold
  if (diff > 60){
    var index = bubble.getAttribute('data-index');
    if (!index) return;

    // Auto-submit reply action
    var form = document.createElement('form');
    form.method = 'post';
    form.style.display = 'none';

    var a = document.createElement('input');
    a.name = 'action';
    a.value = 'set_reply';

    var i = document.createElement('input');
    i.name = 'msg_index';
    i.value = index;

    form.appendChild(a);
    form.appendChild(i);
    document.body.appendChild(form);
    form.submit();
  }
}, {passive:true});

    // typing indicator ping
    var msgInput = document.querySelector('input[name="message"]');
    if (msgInput){
      var typingUrl = window.location.pathname.replace('/chat/', '/typing/');
      var typingTimeout = null;
      msgInput.addEventListener('input', function(){
        fetch(typingUrl, {method: 'POST'});
        if (typingTimeout){
          clearTimeout(typingTimeout);
        }
        typingTimeout = setTimeout(function(){
          fetch(typingUrl, {method: 'POST'});
        }, 3000);
      });
    }

    // customize reaction emojis here:
    var reactionEmojis = ['❤️','😂','👍','😮','😢','🔥','😭'];

    var picker = document.getElementById('reactionPicker');
    var rForm  = document.getElementById('reactionForm');
    var rIndex = document.getElementById('reactionIndex');
    var rEmoji = document.getElementById('reactionEmoji');

    function showPickerAtBubble(bubble){
      if (!picker) return;
      var index = bubble.getAttribute('data-index');
      if (index === null) return;

      var html = '';
      reactionEmojis.forEach(function(e){
        html += '<button type="button" data-emoji="' + e + '">' + e + '</button>';
      });
      picker.innerHTML = html;

      var rect = bubble.getBoundingClientRect();
      var x = rect.left + rect.width / 2;
      var y = rect.top;
      picker.style.display = 'block';
      picker.style.left = x + 'px';
      picker.style.top  = (y - 40) + 'px';
      picker.setAttribute('data-index', index);
    }

    function hidePicker(){
      if (picker){
        picker.style.display = 'none';
      }
    }

    // tap bubble -> open picker
    document.addEventListener('click', function(e){
      var bubble = e.target.closest('.msg-bubble');
      if (bubble){
        showPickerAtBubble(bubble);
        return;
      }
      if (picker && picker.style.display === 'block' && !picker.contains(e.target)){
        hidePicker();
      }
    });

    // tap emoji -> submit reaction
    if (picker){
      picker.addEventListener('click', function(e){
        if (e.target.tagName.toLowerCase() === 'button'){
          var emoji = e.target.getAttribute('data-emoji');
          var index = picker.getAttribute('data-index');
          if (rForm && rIndex && rEmoji){
            rIndex.value = index;
            rEmoji.value = emoji;
            rForm.submit();
          }
        }
      });
    }
  });
</script>
"""

    content = f"""
<h1>Chat with @{html.escape(friend)}</h1>
<p>Send messages, voice, images, videos or documents.</p>

<div class="chat-box">
  {bubbles if bubbles else "<p style='font-size:13px;color:#64748b;'>No messages yet.</p>"}
</div>

{reply_info_html}

<form method="post" enctype="multipart/form-data" class="chat-input-row">
  <input type="hidden" name="action" value="send">
  <input name="message" placeholder="Type a message...">
  <div style="margin-top:8px;">
    <input type="file" name="file">
    <div class="helper">Attach image, audio (voice), video or document.</div>
  </div>
  <button class="btn" type="submit" style="margin-top:10px;">Send</button>
</form>

<div class="reaction-picker" id="reactionPicker"></div>

<form id="reactionForm" method="post" style="display:none;">
  <input type="hidden" name="action" value="react">
  <input type="hidden" name="msg_index" id="reactionIndex">
  <input type="hidden" name="emoji" id="reactionEmoji">
</form>
{script}
"""
    return render(content, active="friends", user=me)


@app.route("/typing/<friend>", methods=["POST"])
def typing(friend):
    me = current_user()
    if not me:
        return ("", 401)
    users = load_users()
    info = users.get(me, {})
    info["typing_to"] = friend
    info["typing_ts"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    users[me] = info
    save_users(users)
    return ("", 204)

@app.route("/ping", methods=["POST"])
def ping():
    me = current_user()
    if not me:
        return ("", 401)
    users = load_users()
    info = users.get(me, {})
    info["last_seen"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    users[me] = info
    save_users(users)
    return ("", 204)

@app.route("/stories", methods=["GET", "POST"])
def stories_page():
    me = current_user()
    if not me:
        return redirect("/login")

    users = load_users()
    stories = load_stories()

    # -------- cleanup expired (older than STORY_TTL_HOURS) --------
    now_ts = int(datetime.now().timestamp())
    cutoff = now_ts - STORY_TTL_HOURS * 3600
    changed = False

    for uname, arr in list(stories.items()):
        if not isinstance(arr, list):
            arr = []
        new_arr = []
        for s in arr:
            ts = s.get("created_ts")
            if not isinstance(ts, int):
                continue
            if ts >= cutoff:
                new_arr.append(s)
        if len(new_arr) != len(arr):
            changed = True
        stories[uname] = new_arr

    if changed:
        save_stories(stories)

    error = None

    # -------- POST actions: delete story OR create story --------
    if request.method == "POST":
        action = request.form.get("action", "create")

        # delete an existing story (only own stories)
        if action == "delete_story":
            sid = request.form.get("story_id")
            my_list = stories.get(me, [])
            new_list = []
            for s in my_list:
                if s.get("id") != sid:
                    new_list.append(s)
            stories[me] = new_list
            save_stories(stories)
            return redirect("/stories")

        # create story
        file = request.files.get("file")
        caption = (request.form.get("caption") or "").strip()

        if not file or not file.filename:
            error = "Select an image or video."
        else:
            filename = secure_filename(file.filename)
            updir = user_upload_dir(me)
            os.makedirs(updir, exist_ok=True)

            # random filename for stories
            saved_name = secure_random_filename(filename, prefix="story_")
            path = os.path.join(updir, saved_name)
            file.save(path)
            url = f"/uploads/{me}/{saved_name}"

            ext = ""
            if "." in filename:
                ext = filename.rsplit(".", 1)[1].lower()

            image_exts = ("png", "jpg", "jpeg", "gif", "webp", "bmp")
            video_exts = ("mp4", "webm", "mov", "m4v")

            if ext in image_exts:
                ftype = "image"
            elif ext in video_exts:
                ftype = "video"
            else:
                ftype = "file"

            story_obj = {
                "id": str(int(datetime.now().timestamp() * 1000)),
                "user": me,
                "caption": caption,
                "created_ts": int(datetime.now().timestamp()),
                "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "ftype": ftype,
                "filename": saved_name,
                "url": url,
                "viewers": [],
            }

            stories.setdefault(me, []).append(story_obj)
            save_stories(stories)
            session["story_posted"] = "Story posted successfully!"
            return redirect("/stories")

    # -------- group stories per user & sort by time --------
    user_stories = {}
    for uname, arr in stories.items():
        if not isinstance(arr, list):
            continue
        sorted_arr = sorted(arr, key=lambda s: s.get("created_ts", 0))
        if sorted_arr:
            user_stories[uname] = sorted_arr

    # -------- STORY GRID: one circle per user --------
    story_cards = ""
    for uname, arr in user_stories.items():
        uname_html = html.escape(uname)

        latest = arr[-1]
        thumb_url = latest.get("url", "")

        viewer_set = set()
        for s in arr:
            for v in (s.get("viewers") or []):
                viewer_set.add(v)
        count = len(viewer_set)

        if count:
            names = ", ".join("@" + html.escape(v) for v in list(viewer_set)[:5])
            views_text = f"Views ({count}): {names}"
        else:
            views_text = "Views: 0"

        story_cards += f"""
<div class="story-item">
  <button class="story-circle" onclick="window.location='/stories?user={uname_html}&idx=0&view=1';">
    <div class="story-ring">
      <img src="{thumb_url}" alt="story by @{uname_html}" class="story-thumb">
    </div>
    <div class="story-name">@{uname_html}</div>
  </button>
  <div class="story-views">{views_text}</div>
</div>
"""

    if not story_cards:
        story_cards = "<p style='font-size:13px;color:#64748b;'>No active stories right now.</p>"

    # -------- VIEWER: one story in that user's sequence --------
    owner = request.args.get("user")
    idx_str = request.args.get("idx", "0")
    mark_view = request.args.get("view")
    current_story = None

    next_target = "/stories"
    prev_target = "/stories"

    if owner and owner in user_stories:
        arr = user_stories[owner]
        try:
            idx = int(idx_str)
        except (TypeError, ValueError):
            idx = 0
        if idx < 0:
            idx = 0
        if 0 <= idx < len(arr):
            current_story = arr[idx]

            # NEXT target
            if idx + 1 < len(arr):
                next_target = f"/stories?user={owner}&idx={idx+1}&view=1"
            else:
                next_target = "/stories"

            # PREV target
            if idx - 1 >= 0:
                prev_target = f"/stories?user={owner}&idx={idx-1}&view=1"
            else:
                prev_target = "/stories"

            # mark as viewed
            if mark_view and me != owner:
                sid = current_story.get("id")
                viewers = current_story.get("viewers") or []
                if me not in viewers:
                    viewers.append(me)
                    current_story["viewers"] = viewers

                    arr_all = stories.get(owner, [])
                    for j, s2 in enumerate(arr_all):
                        if s2.get("id") == sid:
                            arr_all[j] = current_story
                            break
                    stories[owner] = arr_all
                    save_stories(stories)

    # -------- viewer HTML (fullscreen overlay + delete) --------
    viewer_html = ""
    if current_story:
        s = current_story
        uname_html = html.escape(s.get("user", ""))
        caption_html = html.escape(s.get("caption", "") or "")
        url = s.get("url", "")
        ftype = s.get("ftype", "image")

        if ftype == "image":
            media_html = f"<img src='{url}' class='story-view-media' alt='story'>"
        elif ftype == "video":
            media_html = f"<video src='{url}' class='story-view-media' controls autoplay></video>"
        else:
            media_html = f"<a href='{url}' target='_blank' class='link'>Open file</a>"

        v_list = s.get("viewers") or []
        if v_list:
            vnames = ", ".join("@" + html.escape(v) for v in v_list)
            viewers_line = f"Seen by ({len(v_list)}): {vnames}"
        else:
            viewers_line = "No views yet."

        created_ts = s.get("created_ts", now_ts)
        try:
            dt = datetime.fromtimestamp(created_ts)
            time_html = html.escape(dt.strftime("%Y-%m-%d %H:%M"))
        except Exception:
            time_html = ""

        # delete button only for owner
        if s.get("user") == me:
            delete_button_html = "<button type='button' class='btn-danger' onclick='openStoryDelete()'>Delete</button>"
        else:
            delete_button_html = ""

        story_id_safe = html.escape(s.get("id", ""))

        viewer_html = f"""
<div class="story-overlay" id="storyOverlay"
     data-next="{html.escape(next_target)}"
     data-prev="{html.escape(prev_target)}"
     data-exit="/stories">
  <div class="story-viewer">
    <div class="story-progress">
      <div id="storyProgressInner" class="story-progress-inner"></div>
    </div>
    <div class="story-view-header" style="display:flex;align-items:center;justify-content:space-between;">
      <div>
        <span class="story-view-user">@{uname_html}</span>
        <span class="story-view-time">{time_html}</span>
      </div>
    </div>
    {media_html}
    {delete_button_html}
    <div class="story-view-caption">{caption_html}</div>
    <div class="story-view-views">{viewers_line}</div>

    <!-- Delete confirmation box -->
    <div id="storyDeleteBox" style="display:none;margin-top:12px;padding:10px 12px;border-radius:12px;border:1px solid #4b5563;background:#020617;">
      <div style="font-size:13px;font-weight:600;margin-bottom:4px;">Delete this story?</div>
      <div style="font-size:12px;color:#9ca3af;margin-bottom:8px;">This action cannot be undone.</div>
      <form method="post" style="display:flex;gap:8px;justify-content:flex-end;margin-top:4px;">
        <input type="hidden" name="action" value="delete_story">
        <input type="hidden" name="story_id" value="{story_id_safe}">
        <button type="button" class="btn2" onclick="closeStoryDelete()">Cancel</button>
        <button type="submit" class="btn-danger">Delete</button>
      </form>
    </div>

  </div>
</div>
"""

    # -------- JS: progress bar + auto-advance + swipe + video + delete modal --------
    script = """
<script>
document.addEventListener('DOMContentLoaded', function(){
  var bar = document.getElementById('storyProgressInner');
  var overlay = document.getElementById('storyOverlay');
  if (!bar || !overlay) return;

  var nextUrl = overlay.getAttribute('data-next') || '/stories';
  var prevUrl = overlay.getAttribute('data-prev') || '/stories';
  var exitUrl = overlay.getAttribute('data-exit') || '/stories';

  var video = overlay.querySelector('video');
  var duration = video ? null : 15000; // video drives its own timing
  var elapsed = 0;
  var last = Date.now();
  var paused = false;
  var finished = false;

  // For video stories: sync progress bar to video duration
  if (video){
    video.addEventListener('loadedmetadata', function(){
      duration = video.duration * 1000;
    });
    video.addEventListener('ended', function(){
      finished = true;
      setTimeout(function(){ window.location.href = nextUrl; }, 300);
    });
    video.addEventListener('pause', function(){ paused = true; });
    video.addEventListener('play',  function(){
      if (!finished){ paused = false; last = Date.now(); }
    });
    video.addEventListener('timeupdate', function(){
      if (!duration || !video.duration) return;
      var t = video.currentTime / video.duration;
      bar.style.width = (t * 100) + '%';
    });
  }

  function step(){
    if (finished || video) return; // video handles its own bar
    if (!paused){
      var now = Date.now();
      elapsed += (now - last);
      last = now;
      var t = elapsed / duration;
      if (t > 1) t = 1;
      bar.style.width = (t * 100) + '%';
      if (t >= 1){
        finished = true;
        setTimeout(function(){ window.location.href = nextUrl; }, 300);
        return;
      }
    }
    requestAnimationFrame(step);
  }
  if (!video) requestAnimationFrame(step);

  function goNext(){ window.location.href = nextUrl; }
  function goPrev(){ window.location.href = prevUrl; }
  function goExit(){ window.location.href = exitUrl; }

  // ---- Swipe support (mobile) ----
  var touchStartX = 0;
  var touchStartY = 0;
  overlay.addEventListener('touchstart', function(e){
    touchStartX = e.changedTouches[0].screenX;
    touchStartY = e.changedTouches[0].screenY;
    paused = true;
  }, {passive:true});

  overlay.addEventListener('touchend', function(e){
    var dx = e.changedTouches[0].screenX - touchStartX;
    var dy = e.changedTouches[0].screenY - touchStartY;
    paused = false;
    last = Date.now();

    if (Math.abs(dx) > Math.abs(dy) && Math.abs(dx) > 40){
      // horizontal swipe
      if (dx < 0) goNext();
      else goPrev();
    }
  }, {passive:true});

  // ---- Tap zones (desktop): left half = prev, right half = next ----
  overlay.addEventListener('click', function(e){
    // don't navigate if tapping delete box or its buttons
    if (e.target.closest('#storyDeleteBox')) return;
    if (e.target.closest('.story-delete-wrap')) return;
    if (!e.target.closest('.story-viewer')){
      goExit();
      return;
    }
    var x = e.clientX;
    var mid = window.innerWidth / 2;
    if (x > mid) goNext();
    else goPrev();
  });

  // ---- Hold to pause (mouse) ----
  function startPause(){ paused = true; }
  function endPause(){ if(!finished){ paused = false; last = Date.now(); } }
  overlay.addEventListener('mousedown', startPause);
  overlay.addEventListener('mouseup',   endPause);
  overlay.addEventListener('mouseleave',endPause);

  overlay.addEventListener('contextmenu', function(e){ e.preventDefault(); });
});

// delete modal helpers
function openStoryDelete(){
  var box = document.getElementById('storyDeleteBox');
  if (box) box.style.display = 'block';
}
function closeStoryDelete(){
  var box = document.getElementById('storyDeleteBox');
  if (box) box.style.display = 'none';
}
</script>
"""

    error_html = ""
    if error:
        error_html = "<p style='color:#f97373;font-size:13px;margin-top:6px;'>" + html.escape(error) + "</p>"

    posted_msg = session.pop("story_posted", "")
    posted_html = f'<div class="info">{html.escape(posted_msg)}</div>' if posted_msg else ""

    content = f"""
<h1>Stories</h1>
<p>Share images or videos that disappear after <strong>16 hours</strong>.</p>
{error_html}
{posted_html}

<h2>Create story</h2>
<form method="post" enctype="multipart/form-data" class="chat-input-row">
  <input name="caption" placeholder="Say something about your story... (optional)">
  <div style="margin-top:8px;">
    <input type="file" name="file" required>
  </div>
  <button class="btn" type="submit" style="margin-top:10px;">Post story</button>
</form>

<h2 style="margin-top:18px;">Stories</h2>
<div class="stories-grid">
  {story_cards}
</div>

{viewer_html}
{script}
"""
    return render(content, active="stories", user=me)


#-----------group----------
@app.route("/group/create", methods=["GET", "POST"])
def create_group():
    me = current_user()
    if not me:
        return redirect("/login")

    users = load_users()
    groups = load_groups()
    error = ""

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        members = request.form.get("members", "").split(",")
        avatar_file = request.files.get("avatar")

        members = [m.strip() for m in members if m.strip() in users]
        if me not in members:
            members.append(me)

        if not name:
            error = "Group name required."
        elif len(members) < 2:
            error = "Add at least 1 other valid user."
        else:
            group_id = str(int(datetime.now().timestamp()))
            avatar_url = ""

            # save avatar if provided
            if avatar_file and avatar_file.filename:
                filename = secure_filename(avatar_file.filename)
                updir = user_upload_dir(me)
                os.makedirs(updir, exist_ok=True)
                saved_name = f"group_{group_id}_{filename}"
                path = os.path.join(updir, saved_name)
                avatar_file.save(path)
                avatar_url = f"/uploads/{me}/{saved_name}"

            groups[group_id] = {
                "name": name,
                "owner": me,
                "members": members,
                "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "avatar": avatar_url,
            }
            save_groups(groups)
            return redirect("/groups")

    block = f'<div class="error">{html.escape(error)}</div>' if error else ""

    content = f"""
<h1>Create Group</h1>
{block}
<form method="post" enctype="multipart/form-data">
  <input name="name" placeholder="Group name" required>
  <input name="members" placeholder="Usernames (comma separated)">
  <div style="margin-top:8px;">
    <span style="font-size:12px;color:#9ca3af;">Group profile photo (optional)</span><br>
    <input type="file" name="avatar">
  </div>
  <button class="btn" type="submit" style="margin-top:10px;">Create Group</button>
</form>
<p><a href="/groups" class="link">Back to Groups</a></p>
"""
    return render(content, active=   "friends", user=me)

@app.route("/groups")
def groups_page():
    me = current_user()
    if not me:
        return redirect("/login")

    groups = load_groups()
    my_groups = []

    for gid, g in groups.items():
        if me in g.get("members", []):
            my_groups.append((gid, g))

    html_blocks = ""
    for gid, g in my_groups:
        avatar = g.get("avatar", "") or ""
        avatar_html = ""
        if avatar:
            avatar_html = f'<img src="{avatar}" class="group-avatar">'

        html_blocks += f"""
<div class="friend-card">
  <div>
    {avatar_html}<strong>{html.escape(g['name'])}</strong>
    <small> · {len(g.get('members', []))} members</small>
  </div>
  <div>
    <form method="get" action="/group/{gid}">
      <button class="btn-small" type="submit">Open</button>
    </form>
  </div>
</div>
"""

    content = f"""
<h1>Groups</h1>
<p>Your group chats.</p>

<form action="/group/create">
  <button class="btn">Create New Group</button>
</form>

{html_blocks if html_blocks else "<p style='color:#64748b;'>No groups yet.</p>"}
"""
    return render(content, active="groups", user=me)

@app.route("/group/<group_id>", methods=["GET", "POST"])
def group_chat(group_id):
    me = current_user()
    if not me:
        return redirect("/login")

    users = load_users()
    groups = load_groups()
    group = groups.get(group_id)
    if not group or me not in group.get("members", []):
        return redirect("/groups")

    is_owner = (group.get("owner") == me)

    # ---------- POST: actions ----------
    if request.method == "POST":
        action = request.form.get("action", "send")

        # SEND message (with optional file + reply)
        if action == "send":
            txt = request.form.get("message", "").strip()
            file = request.files.get("file")
            ftype = "text"
            fname = ""
            url = ""

            if file and file.filename:
                ftype = "file"
                original = secure_filename(file.filename)
                updir = user_upload_dir(me)
                os.makedirs(updir, exist_ok=True)
                saved_name = secure_random_filename(original)
                path = os.path.join(updir, saved_name)
                file.save(path)
                fname = saved_name
                url = f"/uploads/{me}/{saved_name}"

            if txt or ftype == "file":
                chat_data = load_group_chat(group_id)
                reply_key = f"greply_to_{group_id}"
                reply_index = session.pop(reply_key, None)

                chat_data.append({
                    "from": me,
                    "group": group_id,
                    "text": encrypt_text(txt),
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "ftype": ftype,
                    "filename": fname,
                    "url": url,
                    "reply_to": reply_index,
                    "reactions": {},
                    "deleted": False,
                    "seen_by": [me],  # sender has seen their own message
                })
                save_group_chat(group_id, chat_data)

            return redirect(f"/group/{group_id}")

        # SET reply target
        if action == "set_reply":
            idx = request.form.get("msg_index")
            try:
                idx_int = int(idx)
            except (TypeError, ValueError):
                idx_int = None
            reply_key = f"greply_to_{group_id}"
            if idx_int is None or idx_int < 0:
                session.pop(reply_key, None)
            else:
                session[reply_key] = idx_int
            return redirect(f"/group/{group_id}")

        # DELETE message (soft delete, only own)
        if action == "delete":
            idx = request.form.get("msg_index")
            try:
                idx_int = int(idx)
            except (TypeError, ValueError):
                idx_int = -1

            chat_data = load_group_chat(group_id)
            if 0 <= idx_int < len(chat_data):
                msg = chat_data[idx_int]
                if msg.get("from") == me:
                    msg["deleted"] = True
                    msg["text"] = "This message was deleted"
                    msg["ftype"] = "text"
                    msg["filename"] = ""
                    msg["url"] = ""
                    msg["reactions"] = {}
                    save_group_chat(group_id, chat_data)

            return redirect(f"/group/{group_id}")

        # REACT / UNREACT
        if action == "react":
            idx = request.form.get("msg_index")
            emoji = request.form.get("emoji", "❤️")
            try:
                idx_int = int(idx)
            except (TypeError, ValueError):
                idx_int = -1

            chat_data = load_group_chat(group_id)
            if 0 <= idx_int < len(chat_data):
                msg = chat_data[idx_int]
                reactions = msg.get("reactions", {})
                if reactions.get(me) == emoji:
                    reactions.pop(me, None)
                else:
                    reactions[me] = emoji
                msg["reactions"] = reactions
                save_group_chat(group_id, chat_data)

            return redirect(f"/group/{group_id}")

        return redirect(f"/group/{group_id}")

    # ---------- GET: show group chat ----------
    chat_data = load_group_chat(group_id)

    # mark messages as seen by this user
    seen_changed = False
    for msg in chat_data:
        if msg.get("group") != group_id:
            continue
        seen_by = msg.get("seen_by")
        if not isinstance(seen_by, list):
            seen_by = []
        if me not in seen_by:
            seen_by.append(me)
            msg["seen_by"] = seen_by
            seen_changed = True
    if seen_changed:
        save_group_chat(group_id, chat_data)

    bubbles = ""
    for i, msg in enumerate(chat_data):
        sender = msg.get("from", "")
        text_raw = decrypt_text(msg.get("text", ""))
        if msg.get("deleted"):
            text_raw = "This message was deleted"
        text = html.escape(text_raw)
        time_html = time_ago(msg.get("time", ""))
        ftype = msg.get("ftype", "text")
        filename = msg.get("filename", "") or ""
        url = msg.get("url", "")

        align = "me" if sender == me else "them"
        author = html.escape(sender)

        # reply preview inside bubble
        reply_html = ""
        reply_index = msg.get("reply_to")
        if isinstance(reply_index, int) and 0 <= reply_index < len(chat_data):
            rmsg = chat_data[reply_index]
            rtext_raw = decrypt_text(rmsg.get("text") or "") or "[attachment]"
            rtext = html.escape(rtext_raw[:40])
            rauthor = html.escape(rmsg.get("from", ""))
            reply_html = f'''
<div class="reply-preview">
  Replying to @{rauthor}: {rtext}
</div>
'''

        # attachments: image / voice / file
        file_html = ""
        if ftype == "file" and url and not msg.get("deleted"):
            ext = ""
            if "." in filename:
                ext = filename.rsplit(".", 1)[1].lower()
            image_exts = ("png", "jpg", "jpeg", "gif", "webp", "bmp")
            audio_exts = ("mp3", "wav", "m4a", "ogg", "oga", "aac")

            if ext in image_exts:
                fn = html.escape(filename or "image")
                file_html = f'''
<div class="image-box">
  <a href="{url}" target="_blank">
    <img src="{url}" alt="{fn}">
  </a>
</div>
'''
            elif ext in audio_exts:
                file_html = f'''
<div class="voice-box">
  <audio controls preload="none">
    <source src="{url}">
  </audio>
</div>
'''
            else:
                fn = html.escape(filename or "file")
                file_html = f'''
<div class="msg-file">
  <a href="{url}" target="_blank">{fn}</a>
</div>
'''

        # reactions row
        reactions = msg.get("reactions", {}) or {}
        reaction_html = ""
        if reactions and not msg.get("deleted"):
            counts = {}
            for em in reactions.values():
                counts[em] = counts.get(em, 0) + 1
            chips = ""
            for em, c in counts.items():
                chips += f'<span class="reaction-chip">{em} {c}</span>'
            reaction_html = f'<div class="reaction-row">{chips}</div>'

        # seen-by row (only for my messages)
        seen_html = ""
        seen_by = msg.get("seen_by", [])
        if not isinstance(seen_by, list):
            seen_by = []
        if sender == me and not msg.get("deleted"):
            others = [u for u in seen_by if u != me]
            if others:
                if len(others) <= 3:
                    names = ", ".join("@" + html.escape(u) for u in others)
                    label = f"Seen by {names}"
                else:
                    label = f"Seen by {len(others)} members"
                seen_html = f'<div class="seen-row">{label}</div>'

        # actions (reply + delete for own)
        actions_html = ""
        if not msg.get("deleted"):
            actions_html = f"""
<div class="msg-actions">
  <form method="post" style="display:inline;">
    <input type="hidden" name="action" value="set_reply">
    <input type="hidden" name="msg_index" value="{i}">
    <button class="msg-action-btn" type="submit">Reply</button>
  </form>
"""
            if sender == me:
                actions_html += f"""
  <form method="post" style="display:inline;">
    <input type="hidden" name="action" value="delete">
    <input type="hidden" name="msg_index" value="{i}">
    <button class="msg-action-btn" type="submit">Delete</button>
  </form>
"""
            actions_html += "</div>"

        bubbles += f"""
<div class="msg-row">
  <div class="msg-bubble {align}" data-index="{i}">
    <div class="msg-author">{author}<span class="msg-time">{time_html}</span></div>
    {reply_html}
    <div class="msg-text">{text}</div>
    {file_html}
    {reaction_html}
    {seen_html}
    {actions_html}
  </div>
</div>
"""

    # typing indicator
    typing_users = []
    for m in group.get("members", []):
        if m == me:
            continue
        info = users.get(m, {})
        ts_str = info.get("typing_group_ts")
        gid_to = info.get("typing_group")
        if ts_str and gid_to == group_id:
            try:
                ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                if datetime.now() - ts < timedelta(seconds=4):
                    typing_users.append(m)
            except Exception:
                pass

    if typing_users:
        name = html.escape(typing_users[0])
        typing_html = f"""
<div class="msg-row">
  <div class="msg-bubble them">
    <div class="msg-author">{name}<span class="msg-time">typing…</span></div>
    <div class="msg-text"><span style="opacity:.7;">typing…</span></div>
  </div>
</div>
"""
        bubbles += typing_html

    # admin button (owner only)
    admin_button_html = ""
    if is_owner:
        admin_button_html = f"""
<form method="get" action="/group/{group_id}/admin" style="margin-top:8px;">
  <button class="btn2" type="submit">Open group admin panel</button>
</form>
"""

    # reply bar above input
    reply_key = f"greply_to_{group_id}"
    reply_info_html = ""
    reply_index = session.get(reply_key)
    if isinstance(reply_index, int) and 0 <= reply_index < len(chat_data):
        rmsg = chat_data[reply_index]
        rtext_raw = decrypt_text(rmsg.get("text") or "") or "[attachment]"
        rtext = html.escape(rtext_raw[:60])
        rauthor = html.escape(rmsg.get("from", ""))
        reply_info_html = f"""
<div class="reply-preview" style="margin-top:10px;">
  Replying to @{rauthor}: {rtext}
  <form method="post" style="display:inline;">
    <input type="hidden" name="action" value="set_reply">
    <input type="hidden" name="msg_index" value="-1">
    <button class="reply-cancel" type="submit">✕ Cancel</button>
  </form>
</div>
"""

    avatar = group.get("avatar", "") or ""
    avatar_html = ""
    if avatar:
        avatar_html = f'<img src="{avatar}" class="group-avatar-large">'

    # JS just for auto-refresh, typing, tap-to-react, swipe-to-reply
    script = """
<script>
  // Auto-scroll to latest message on load
  var chatBox = document.querySelector('.chat-box');
  if(chatBox) chatBox.scrollTop = chatBox.scrollHeight;

  // Enter key to send
  var msgInput = document.querySelector('input[name="message"]');
  if(msgInput){
    msgInput.addEventListener('keydown', function(e){
      if(e.key === 'Enter' && !e.shiftKey){
        e.preventDefault();
        msgInput.closest('form').submit();
      }
    });
  }

  // Auto-refresh only the chat messages every 2 seconds
  setInterval(function(){
    fetch(window.location.href)
      .then(function(res){ return res.text(); })
      .then(function(html){
        var temp = document.createElement('div');
        temp.innerHTML = html;
        var newBox = temp.querySelector('.chat-box');
        var curBox = document.querySelector('.chat-box');
        if(newBox && curBox){
          curBox.innerHTML = newBox.innerHTML;
        }
      });
  }, 2000);

  document.addEventListener('DOMContentLoaded', function(){
    // typing indicator ping (group)
    var msgInput = document.querySelector('input[name="message"]');
    if (msgInput){
      var typingUrl = window.location.pathname.replace('/group/', '/gtyping/');
      var typingTimeout = null;
      msgInput.addEventListener('input', function(){
        fetch(typingUrl, {method: 'POST'});
        if (typingTimeout){
          clearTimeout(typingTimeout);
        }
        typingTimeout = setTimeout(function(){
          fetch(typingUrl, {method: 'POST'});
        }, 3000);
      });
    }

    // tap-to-react
    var reactionEmojis = ['❤️','😂','👍','😮','😢','🔥'];
    var picker = document.getElementById('reactionPicker');
    var rForm  = document.getElementById('reactionForm');
    var rIndex = document.getElementById('reactionIndex');
    var rEmoji = document.getElementById('reactionEmoji');

    function showPickerAtBubble(bubble){
      if (!picker) return;
      var index = bubble.getAttribute('data-index');
      if (index === null) return;

      var html = '';
      reactionEmojis.forEach(function(e){
        html += '<button type="button" data-emoji="' + e + '">' + e + '</button>';
      });
      picker.innerHTML = html;

      var rect = bubble.getBoundingClientRect();
      picker.style.display = 'block';
      picker.style.left = (rect.left + rect.width / 2) + 'px';
      picker.style.top  = (rect.top - 40) + 'px';
      picker.setAttribute('data-index', index);
    }

    function hidePicker(){
      if (picker){
        picker.style.display = 'none';
      }
    }

    document.addEventListener('click', function(e){
      var bubble = e.target.closest('.msg-bubble');
      if (bubble && bubble.closest('.chat-box')){
        showPickerAtBubble(bubble);
        return;
      }
      if (picker && picker.style.display === 'block' && !picker.contains(e.target)){
        hidePicker();
      }
    });

    if (picker){
      picker.addEventListener('click', function(e){
        if (e.target.tagName.toLowerCase() === 'button'){
          var emoji = e.target.getAttribute('data-emoji');
          var index = picker.getAttribute('data-index');
          if (rForm && rIndex && rEmoji){
            rIndex.value = index;
            rEmoji.value = emoji;
            rForm.submit();
          }
        }
      });
    }

    // Swipe-to-reply (group)
    var startX = 0;
    document.addEventListener('touchstart', function(e){
      var bubble = e.target.closest('.msg-bubble');
      if (!bubble) return;
      startX = e.changedTouches[0].screenX;
      bubble.classList.add('swipe-target');
    }, {passive:true});

    document.addEventListener('touchend', function(e){
      var bubble = document.querySelector('.swipe-target');
      if (!bubble) return;
      var endX = e.changedTouches[0].screenX;
      bubble.classList.remove('swipe-target');

      if ((endX - startX) > 60){
        var index = bubble.getAttribute('data-index');
        if (!index) return;

        var form = document.createElement('form');
        form.method = 'post';
        form.style.display = 'none';

        var a = document.createElement('input');
        a.name = 'action';
        a.value = 'set_reply';

        var i = document.createElement('input');
        i.name = 'msg_index';
        i.value = index;

        form.appendChild(a);
        form.appendChild(i);
        document.body.appendChild(form);
        form.submit();
      }
    }, {passive:true});
  });
</script>
"""

    content = f"""
<h1>{avatar_html}{html.escape(group['name'])}</h1>
<p>Group chat · {len(group.get('members', []))} members</p>
{admin_button_html}

<div class="chat-box">
  {bubbles if bubbles else "<p style='font-size:13px;color:#64748b;'>No messages yet.</p>"}
</div>

{reply_info_html}

<form method="post" enctype="multipart/form-data" class="chat-input-row">
  <input type="hidden" name="action" value="send">
  <input name="message" placeholder="Type a message...">
  <div style="margin-top:8px;">
    <input type="file" name="file">
  </div>
  <button class="btn" type="submit" style="margin-top:10px;">Send</button>
</form>

<div class="reaction-picker" id="reactionPicker"></div>

<form id="reactionForm" method="post" style="display:none;">
  <input type="hidden" name="action" value="react">
  <input type="hidden" name="msg_index" id="reactionIndex">
  <input type="hidden" name="emoji" id="reactionEmoji">
</form>
{script}
"""
    return render(content, active="groups", user=me)

#--------- Admin----------
@app.route("/group/<group_id>/admin", methods=["GET", "POST"])
def group_admin(group_id):
    me = current_user()
    if not me:
        return redirect("/login")

    users = load_users()
    groups = load_groups()
    group = groups.get(group_id)

    if not group or me not in group.get("members", []):
        return redirect("/groups")

    owner = group.get("owner")
    is_owner = (owner == me)

    # only owner can use admin panel
    if not is_owner:
        return redirect(f"/group/{group_id}")

    error = None

    # --------- POST actions ----------
    if request.method == "POST":
        action = request.form.get("action")

        # add member
        if action == "add_member":
            username = (request.form.get("username") or "").strip()
            if not username:
                error = "Enter a username."
            elif username not in users:
                error = f"User @{username} does not exist."
            elif username in group.get("members", []):
                error = f"@{username} is already in the group."
            else:
                group.setdefault("members", []).append(username)
                groups[group_id] = group
                save_groups(groups)
                return redirect(f"/group/{group_id}/admin")

        # remove member
        elif action == "remove_member":
            member = request.form.get("member")
            if member and member != owner and member in group.get("members", []):
                group["members"] = [m for m in group["members"] if m != member]
                groups[group_id] = group
                save_groups(groups)
            return redirect(f"/group/{group_id}/admin")

        # delete entire group
        elif action == "delete_group":
            groups.pop(group_id, None)
            save_groups(groups)
            # optional: if you have a helper to delete chat file, call it here
            # delete_group_chat(group_id)
            return redirect("/groups")

    # ---------- build admin page ----------
    group_name = html.escape(group.get("name", "Group"))
    members = group.get("members", [])

    # members list html
    members_html = ""
    for member in members:
        label = f"@{html.escape(member)}"
        if member == owner:
            label += " (owner)"

        remove_html = ""
        if member != owner:
            # custom remove button – no browser confirm
            remove_html = f"""
<form id="removeForm_{member}" method="post" style="display:inline;">
  <input type="hidden" name="action" value="remove_member">
  <input type="hidden" name="member" value="{member}">
  <button class="btn-danger" type="button" onclick="openRemoveModal('{member}')">
    Remove
  </button>
</form>
"""

        members_html += f"""
<div class="friend-card">
  <div>{label}</div>
  <div>{remove_html}</div>
</div>
"""

    error_html = ""
    if error:
        error_html = f'<p style="color:#f97373;font-size:13px;margin-bottom:8px;">{html.escape(error)}</p>'

    avatar = group.get("avatar", "") or ""
    avatar_html = ""
    if avatar:
        avatar_html = f'<img src="{avatar}" class="group-avatar-large">'

    # JS for remove + delete modals
    script = """
<script>
var currentRemoveUser = null;

function openRemoveModal(username){
  currentRemoveUser = username;
  var text = document.getElementById('removeText');
  if (text){
    text.textContent = 'Remove @' + username + ' from the group?';
  }
  var ov = document.getElementById('removeOverlay');
  if (ov){ ov.style.display = 'flex'; }
}

function closeRemoveModal(){
  var ov = document.getElementById('removeOverlay');
  if (ov){ ov.style.display = 'none'; }
  currentRemoveUser = null;
}

function submitRemove(){
  if (!currentRemoveUser) return;
  var form = document.getElementById('removeForm_' + currentRemoveUser);
  if (form){ form.submit(); }
}

// delete-group modal
function openGroupDeleteModal(){
  var ov = document.getElementById('groupDeleteOverlay');
  if (ov){ ov.style.display = 'flex'; }
}
function closeGroupDeleteModal(){
  var ov = document.getElementById('groupDeleteOverlay');
  if (ov){ ov.style.display = 'none'; }
}
function submitGroupDelete(){
  var form = document.getElementById('deleteGroupForm');
  if (form){ form.submit(); }
}
</script>
"""

    content = f"""
<h1>{avatar_html}{group_name}</h1>
<p>Group admin · manage members and settings for <strong>{group_name}</strong>.</p>

{error_html}

<h2>Add to group</h2>
<form method="post" style="margin-bottom:14px;">
  <input type="hidden" name="action" value="add_member">
  <input name="username" placeholder="Username to add">
  <button class="btn" type="submit" style="margin-top:8px;">Add to group</button>
</form>

<h2>Members</h2>
{members_html}

<h2>Danger zone</h2>
<form id="deleteGroupForm" method="post">
  <input type="hidden" name="action" value="delete_group">
  <button class="btn-danger" type="button" onclick="openGroupDeleteModal()">Delete group</button>
</form>

<p style="margin-top:10px;">
  <a href="/group/{group_id}" class="link">Back to group chat</a>
</p>

<!-- Remove member modal -->
<div class="gconfirm-overlay" id="removeOverlay">
  <div class="gconfirm-box">
    <div class="gconfirm-title">Remove member?</div>
    <div class="gconfirm-text" id="removeText">
      Are you sure you want to remove this member from the group?
    </div>
    <div class="gconfirm-buttons">
      <button type="button" class="btn2" onclick="closeRemoveModal()">Cancel</button>
      <button type="button" class="btn-danger" onclick="submitRemove()">Remove</button>
    </div>
  </div>
</div>

<!-- Delete group modal -->
<div class="gconfirm-overlay" id="groupDeleteOverlay">
  <div class="gconfirm-box">
    <div class="gconfirm-title">Delete group?</div>
    <div class="gconfirm-text">
      Delete this group and all its messages? This action cannot be undone.
    </div>
    <div class="gconfirm-buttons">
      <button type="button" class="btn2" onclick="closeGroupDeleteModal()">Cancel</button>
      <button type="button" class="btn-danger" onclick="submitGroupDelete()">Delete</button>
    </div>
  </div>
</div>
{script}
"""
    return render(content, active="groups", user=me)

# ---------- MAIN ----------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)