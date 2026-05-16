import os, json
import psycopg2
import psycopg2.extras
import psycopg2.pool

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# ---------- CONNECTION POOL (Fix 3.1) ----------
_pool = None

def _get_pool():
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1, maxconn=5, dsn=DATABASE_URL, sslmode="require"
        )
    return _pool

def get_conn():  return _get_pool().getconn()
def put_conn(c): _get_pool().putconn(c)

def query(sql, params=(), one=False):
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        result = [dict(r) for r in cur.fetchall()]
        return result[0] if one and result else (result if not one else None)
    finally:
        put_conn(conn)

def execute(sql, params=()):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        put_conn(conn)

# ---------- SCHEMA + MIGRATIONS ----------
def init_db():
    # Fix 3.5 — JSONB for reactions/seen_by/viewers on new tables.
    stmts = [
        """CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY, password_hash TEXT DEFAULT '',
            bio TEXT DEFAULT '', avatar TEXT DEFAULT '',
            recovery TEXT DEFAULT '', last_seen TIMESTAMP,
            typing_to TEXT DEFAULT '', typing_ts TIMESTAMP,
            typing_group TEXT DEFAULT '', typing_group_ts TIMESTAMP,
            created_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS friends (
            user1 TEXT NOT NULL, user2 TEXT NOT NULL, PRIMARY KEY (user1, user2))""",
        """CREATE TABLE IF NOT EXISTS friend_requests (
            from_user TEXT NOT NULL, to_user TEXT NOT NULL,
            PRIMARY KEY (from_user, to_user))""",
        """CREATE TABLE IF NOT EXISTS unread (
            username TEXT NOT NULL, from_user TEXT NOT NULL,
            count INTEGER DEFAULT 0, PRIMARY KEY (username, from_user))""",
        """CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY, sender TEXT NOT NULL, recipient TEXT NOT NULL,
            text TEXT DEFAULT '', ftype TEXT DEFAULT 'text',
            filename TEXT DEFAULT '', url TEXT DEFAULT '',
            seen BOOLEAN DEFAULT FALSE, reply_to INTEGER,
            reactions JSONB DEFAULT '{}', deleted BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS groups (
            group_id TEXT PRIMARY KEY, name TEXT NOT NULL, owner TEXT NOT NULL,
            avatar TEXT DEFAULT '', created_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS group_members (
            group_id TEXT NOT NULL, username TEXT NOT NULL,
            PRIMARY KEY (group_id, username))""",
        """CREATE TABLE IF NOT EXISTS group_messages (
            id SERIAL PRIMARY KEY, group_id TEXT NOT NULL, sender TEXT NOT NULL,
            text TEXT DEFAULT '', ftype TEXT DEFAULT 'text',
            filename TEXT DEFAULT '', url TEXT DEFAULT '',
            reply_to INTEGER, reactions JSONB DEFAULT '{}',
            deleted BOOLEAN DEFAULT FALSE, seen_by JSONB DEFAULT '[]',
            created_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS notes (
            id SERIAL PRIMARY KEY, username TEXT NOT NULL,
            title TEXT DEFAULT '', body TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS stories (
            id SERIAL PRIMARY KEY, username TEXT NOT NULL,
            url TEXT NOT NULL, ftype TEXT DEFAULT 'image',
            caption TEXT DEFAULT '', viewers JSONB DEFAULT '[]',
            created_at TIMESTAMP DEFAULT NOW())""",
    ]

    # Fix 3.4 — indexes on hot query columns; IF NOT EXISTS is idempotent.
    index_stmts = [
        "CREATE INDEX IF NOT EXISTS idx_messages_convo   ON messages(sender, recipient)",
        "CREATE INDEX IF NOT EXISTS idx_messages_time    ON messages(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_grp_msgs_group   ON group_messages(group_id)",
        "CREATE INDEX IF NOT EXISTS idx_grp_msgs_time    ON group_messages(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_stories_user     ON stories(username)",
        "CREATE INDEX IF NOT EXISTS idx_stories_time     ON stories(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_notes_user       ON notes(username)",
        "CREATE INDEX IF NOT EXISTS idx_unread_username  ON unread(username)",
        "CREATE INDEX IF NOT EXISTS idx_friends_user1    ON friends(user1)",
        "CREATE INDEX IF NOT EXISTS idx_friends_user2    ON friends(user2)",
    ]

    # Fix 3.5 — migrate existing TEXT JSON columns to JSONB on live DB.
    # Each DO block checks data_type first so it's safe to run repeatedly.
    jsonb_migrations = [
        """DO $$ BEGIN
             IF (SELECT data_type FROM information_schema.columns
                 WHERE table_name='messages' AND column_name='reactions') = 'text' THEN
               ALTER TABLE messages ALTER COLUMN reactions TYPE JSONB USING reactions::jsonb;
             END IF; END $$""",
        """DO $$ BEGIN
             IF (SELECT data_type FROM information_schema.columns
                 WHERE table_name='group_messages' AND column_name='reactions') = 'text' THEN
               ALTER TABLE group_messages ALTER COLUMN reactions TYPE JSONB USING reactions::jsonb;
             END IF; END $$""",
        """DO $$ BEGIN
             IF (SELECT data_type FROM information_schema.columns
                 WHERE table_name='group_messages' AND column_name='seen_by') = 'text' THEN
               ALTER TABLE group_messages ALTER COLUMN seen_by TYPE JSONB USING seen_by::jsonb;
             END IF; END $$""",
        """DO $$ BEGIN
             IF (SELECT data_type FROM information_schema.columns
                 WHERE table_name='stories' AND column_name='viewers') = 'text' THEN
               ALTER TABLE stories ALTER COLUMN viewers TYPE JSONB USING viewers::jsonb;
             END IF; END $$""",
    ]

    conn = get_conn()
    try:
        cur = conn.cursor()
        for s in stmts + index_stmts + jsonb_migrations:
            cur.execute(s)
        conn.commit()
        print("DB schema ready")
    except Exception:
        conn.rollback()
        raise
    finally:
        put_conn(conn)

# ---------- USERS ----------
def get_user(u): return query("SELECT * FROM users WHERE username=%s",(u,),one=True)
def user_exists(u): return bool(query("SELECT 1 FROM users WHERE username=%s",(u,),one=True))

def get_users_bulk(usernames):
    """Fix 3.2 — fetch multiple users in one query. Returns {username: user_dict}."""
    if not usernames: return {}
    rows = query("SELECT * FROM users WHERE username = ANY(%s)", (list(usernames),))
    return {r["username"]: r for r in rows}

def create_user(username, password_hash, bio="", avatar="", recovery="",
                email="", google_id="", auth_provider="local"):
    """Create a new user. Works for both local and Google auth."""
    execute("""
        INSERT INTO users
          (username, password_hash, bio, avatar, recovery,
           email, google_id, auth_provider, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT(username) DO NOTHING
    """, (username, password_hash or "", bio, avatar, recovery,
          email, google_id, auth_provider))

def get_user_by_email(email):
    """Look up a user by email address (used by Google OAuth flow)."""
    return query("SELECT * FROM users WHERE email=%s", (email,), one=True)

def update_user(username, **kwargs):
    ALLOWED = {"password_hash","bio","avatar","recovery","last_seen",
               "typing_to","typing_ts","typing_group","typing_group_ts"}
    pairs = [(k, v) for k, v in kwargs.items() if k in ALLOWED]
    if not pairs: return
    set_clause = ", ".join(f"{k} = %s" for k, _ in pairs)
    values = [v for _, v in pairs] + [username]
    execute(f"UPDATE users SET {set_clause} WHERE username = %s", values)

def delete_user(username):
    two = lambda sql: execute(sql, (username, username))
    one = lambda sql: execute(sql, (username,))
    two("DELETE FROM messages WHERE sender=%s OR recipient=%s")
    one("DELETE FROM group_messages WHERE sender=%s")
    two("DELETE FROM friend_requests WHERE from_user=%s OR to_user=%s")
    two("DELETE FROM friends WHERE user1=%s OR user2=%s")
    two("DELETE FROM unread WHERE username=%s OR from_user=%s")
    one("DELETE FROM notes WHERE username=%s")
    one("DELETE FROM stories WHERE username=%s")
    one("DELETE FROM group_members WHERE username=%s")
    one("DELETE FROM users WHERE username=%s")

# ---------- FRIENDS ----------
def get_friends(username):
    rows = query("SELECT CASE WHEN user1=%s THEN user2 ELSE user1 END AS friend "
                 "FROM friends WHERE user1=%s OR user2=%s",(username,username,username))
    return [r["friend"] for r in rows]

def are_friends(u1,u2):
    return bool(query("SELECT 1 FROM friends WHERE (user1=%s AND user2=%s) OR (user1=%s AND user2=%s)",
                      (u1,u2,u2,u1),one=True))

def add_friend(u1,u2):
    a,b=sorted([u1,u2])
    execute("INSERT INTO friends(user1,user2) VALUES(%s,%s) ON CONFLICT DO NOTHING",(a,b))

def remove_friend(u1,u2):
    a,b=sorted([u1,u2])
    execute("DELETE FROM friends WHERE user1=%s AND user2=%s",(a,b))

def send_request(f,t): execute("INSERT INTO friend_requests(from_user,to_user) VALUES(%s,%s) ON CONFLICT DO NOTHING",(f,t))
def cancel_request(f,t): execute("DELETE FROM friend_requests WHERE from_user=%s AND to_user=%s",(f,t))
def get_pending_in(u): return [r["from_user"] for r in query("SELECT from_user FROM friend_requests WHERE to_user=%s",(u,))]
def accept_request(f,t): cancel_request(f,t); add_friend(f,t)
def reject_request(f,t): cancel_request(f,t)
def already_requested(f,t): return bool(query("SELECT 1 FROM friend_requests WHERE from_user=%s AND to_user=%s",(f,t),one=True))

# ---------- UNREAD ----------
def count_unread(u):
    r=query("SELECT COALESCE(SUM(count),0) AS total FROM unread WHERE username=%s",(u,),one=True)
    return int(r["total"]) if r else 0
def get_unread_senders(u): return [r["from_user"] for r in query("SELECT from_user FROM unread WHERE username=%s AND count>0",(u,))]
def get_unread_dict(u): return {r["from_user"]:r["count"] for r in query("SELECT from_user,count FROM unread WHERE username=%s",(u,))}
def increment_unread(u,f): execute("INSERT INTO unread(username,from_user,count) VALUES(%s,%s,1) ON CONFLICT(username,from_user) DO UPDATE SET count=unread.count+1",(u,f))
def reset_unread(u,f): execute("UPDATE unread SET count=0 WHERE username=%s AND from_user=%s",(u,f))

# ---------- DM MESSAGES ----------
def load_chat(u1, u2, limit=100):
    # Fix 4.7 — paginate: return only the most recent `limit` messages.
    return query("""
        SELECT * FROM (
            SELECT * FROM messages
            WHERE (sender=%s AND recipient=%s) OR (sender=%s AND recipient=%s)
            ORDER BY created_at DESC LIMIT %s
        ) sub ORDER BY created_at ASC
    """, (u1, u2, u2, u1, limit))

def send_message(sender, recipient, text="", ftype="text", filename="", url="", reply_to=None):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO messages(sender,recipient,text,ftype,filename,url,reply_to) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                    (sender,recipient,text,ftype,filename,url,reply_to))
        mid = cur.fetchone()[0]; conn.commit(); return mid
    except Exception:
        conn.rollback(); raise
    finally:
        put_conn(conn)

def mark_seen(sender,recipient): execute("UPDATE messages SET seen=TRUE WHERE sender=%s AND recipient=%s AND seen=FALSE",(sender,recipient))
def soft_delete_message(mid): execute("UPDATE messages SET deleted=TRUE,text='This message was deleted',ftype='text',filename='',url='',reactions='{}' WHERE id=%s",(mid,))
def get_message_by_id(mid): return query("SELECT * FROM messages WHERE id=%s",(mid,),one=True)

def react_message(mid, username, emoji):
    msg = get_message_by_id(mid)
    if not msg: return
    r = msg.get("reactions") or {}
    if r.get(username)==emoji: r.pop(username)
    else: r[username]=emoji
    execute("UPDATE messages SET reactions=%s WHERE id=%s",(json.dumps(r),mid))

# ---------- GROUPS ----------
def get_group(gid):
    g=query("SELECT * FROM groups WHERE group_id=%s",(gid,),one=True)
    if not g: return None
    g=dict(g); g["members"]=get_group_members(gid); return g

def create_group(gid,name,owner,avatar=""):
    execute("INSERT INTO groups(group_id,name,owner,avatar) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING",(gid,name,owner,avatar))
    add_group_member(gid,owner)

def delete_group(gid):
    execute("DELETE FROM group_members WHERE group_id=%s",(gid,))
    execute("DELETE FROM group_messages WHERE group_id=%s",(gid,))
    execute("DELETE FROM groups WHERE group_id=%s",(gid,))

def get_group_members(gid): return [r["username"] for r in query("SELECT username FROM group_members WHERE group_id=%s",(gid,))]
def add_group_member(gid,u): execute("INSERT INTO group_members(group_id,username) VALUES(%s,%s) ON CONFLICT DO NOTHING",(gid,u))
def remove_group_member(gid,u): execute("DELETE FROM group_members WHERE group_id=%s AND username=%s",(gid,u))

def user_groups(username):
    # Fix 3.2 — batch-fetch all members in one extra query instead of N+1.
    rows = query("SELECT g.* FROM groups g JOIN group_members gm ON g.group_id=gm.group_id "
                 "WHERE gm.username=%s ORDER BY g.created_at",(username,))
    if not rows: return []
    gids = [g["group_id"] for g in rows]
    member_rows = query("SELECT group_id,username FROM group_members WHERE group_id=ANY(%s)",(gids,))
    members_map = {}
    for m in member_rows:
        members_map.setdefault(m["group_id"],[]).append(m["username"])
    return [{**dict(g),"members":members_map.get(g["group_id"],[])} for g in rows]

# ---------- GROUP MESSAGES ----------
def load_group_chat(gid, limit=100):
    # Fix 4.7 — paginate to last `limit` messages.
    return query("""
        SELECT * FROM (
            SELECT * FROM group_messages
            WHERE group_id=%s
            ORDER BY created_at DESC LIMIT %s
        ) sub ORDER BY created_at ASC
    """, (gid, limit))

def send_group_message(gid, sender, text="", ftype="text", filename="", url="", reply_to=None):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO group_messages(group_id,sender,text,ftype,filename,url,reply_to,seen_by) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb) RETURNING id",
                    (gid,sender,text,ftype,filename,url,reply_to,json.dumps([sender])))
        mid = cur.fetchone()[0]; conn.commit(); return mid
    except Exception:
        conn.rollback(); raise
    finally:
        put_conn(conn)

def mark_group_seen(gid, username):
    # Fix 3.3 — single UPDATE using JSONB operators; was N individual UPDATE round-trips.
    execute("""
        UPDATE group_messages
        SET seen_by = seen_by || jsonb_build_array(%s::text)
        WHERE group_id = %s
          AND NOT (seen_by @> jsonb_build_array(%s::text))
    """, (username, gid, username))

def soft_delete_group_message(mid): execute("UPDATE group_messages SET deleted=TRUE,text='This message was deleted',ftype='text',filename='',url='',reactions='{}' WHERE id=%s",(mid,))
def get_group_message_by_id(mid): return query("SELECT * FROM group_messages WHERE id=%s",(mid,),one=True)

def react_group_message(mid, username, emoji):
    msg = get_group_message_by_id(mid)
    if not msg: return
    r = msg.get("reactions") or {}
    if r.get(username)==emoji: r.pop(username)
    else: r[username]=emoji
    execute("UPDATE group_messages SET reactions=%s WHERE id=%s",(json.dumps(r),mid))

# ---------- NOTES ----------
def load_notes(username,sort="newest"):
    order="DESC" if sort=="newest" else "ASC"
    return query(f"SELECT * FROM notes WHERE username=%s ORDER BY created_at {order}",(username,))
def search_notes(username, q, sort="newest"):
    # Fix 5.5 — server-side ILIKE search; parameterised so safe from injection.
    order   = "DESC" if sort == "newest" else "ASC"
    pattern = f"%{q}%"
    return query(f"SELECT * FROM notes WHERE username=%s AND (title ILIKE %s OR body ILIKE %s) "
                 f"ORDER BY created_at {order}", (username, pattern, pattern))
def add_note(username,title,body): execute("INSERT INTO notes(username,title,body) VALUES(%s,%s,%s)",(username,title,body))
def update_note(note_id,username,title,body): execute("UPDATE notes SET title=%s,body=%s WHERE id=%s AND username=%s",(title,body,note_id,username))
def delete_note(note_id,username): execute("DELETE FROM notes WHERE id=%s AND username=%s",(note_id,username))

# ---------- STORIES ----------
def load_stories():
    out={}
    rows=query("SELECT * FROM stories WHERE created_at > NOW() - INTERVAL '16 hours' ORDER BY username,created_at ASC")
    for r in rows:
        d=dict(r)
        if d.get("viewers") is None: d["viewers"]=[]  # JSONB returns list directly
        out.setdefault(d["username"],[]).append(d)
    return out

def add_story(username,url,ftype="image",caption=""):
    execute("INSERT INTO stories(username,url,ftype,caption,viewers) VALUES(%s,%s,%s,%s,'[]'::jsonb)",(username,url,ftype,caption))

def delete_story(story_id,username): execute("DELETE FROM stories WHERE id=%s AND username=%s",(story_id,username))

def add_story_viewer(story_id, viewer):
    # Fix 3.5 — atomic JSONB append; no read-modify-write race condition.
    execute("""
        UPDATE stories
        SET viewers = viewers || jsonb_build_array(%s::text)
        WHERE id = %s AND NOT (viewers @> jsonb_build_array(%s::text))
    """, (viewer, story_id, viewer))

# ---------- B4: CLEAR / BLOCK / REPORT / ONLINE ----------

def is_online(username):
    """True if user was active within the last 90 seconds."""
    row = query("SELECT last_seen FROM users WHERE username=%s", (username,), one=True)
    if not row or not row.get("last_seen"): return False
    from datetime import datetime, timedelta, timezone
    ts = row["last_seen"]
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts) < timedelta(seconds=90)

def clear_chat(user_a, user_b):
    """Soft-delete all DMs between two users by marking them deleted."""
    execute(
        """UPDATE messages
           SET deleted = TRUE
           WHERE (sender=%s AND receiver=%s)
              OR (sender=%s AND receiver=%s)""",
        (user_a, user_b, user_b, user_a)
    )

def block_user(blocker, blocked):
    """
    Remove friendship and record block.
    Uses IF NOT EXISTS so calling twice is safe.
    Requires a blocks table — schema below (auto-created if absent).
    """
    execute("""
        CREATE TABLE IF NOT EXISTS blocks (
            id         SERIAL PRIMARY KEY,
            blocker    TEXT NOT NULL,
            blocked    TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(blocker, blocked)
        )
    """)
    execute(
        "INSERT INTO blocks(blocker,blocked) VALUES(%s,%s) ON CONFLICT DO NOTHING",
        (blocker, blocked)
    )
    # Also remove the friend relationship
    execute(
        "DELETE FROM friends WHERE (user_a=%s AND user_b=%s) OR (user_a=%s AND user_b=%s)",
        (blocker, blocked, blocked, blocker)
    )

def file_report(reporter, reported, reason=""):
    """
    Record a user report.
    Requires a reports table — auto-created if absent.
    """
    execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id         SERIAL PRIMARY KEY,
            reporter   TEXT NOT NULL,
            reported   TEXT NOT NULL,
            reason     TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    execute(
        "INSERT INTO reports(reporter,reported,reason) VALUES(%s,%s,%s)",
        (reporter, reported, reason)
    )
