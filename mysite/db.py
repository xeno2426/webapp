import os, json
import psycopg2
import psycopg2.extras
from urllib.parse import urlparse

DATABASE_URL = os.environ.get("DATABASE_URL", "")

def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

def query(sql, params=(), one=False):
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        result = cur.fetchall()
        result = [dict(r) for r in result]
        return result[0] if one and result else (result if not one else None)
    finally:
        conn.close()

def execute(sql, params=()):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
    finally:
        conn.close()

def init_db():
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
            reactions TEXT DEFAULT '{}', deleted BOOLEAN DEFAULT FALSE,
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
            reply_to INTEGER, reactions TEXT DEFAULT '{}',
            deleted BOOLEAN DEFAULT FALSE, seen_by TEXT DEFAULT '[]',
            created_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS notes (
            id SERIAL PRIMARY KEY, username TEXT NOT NULL,
            title TEXT DEFAULT '', body TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS stories (
            id SERIAL PRIMARY KEY, username TEXT NOT NULL,
            url TEXT NOT NULL, ftype TEXT DEFAULT 'image',
            caption TEXT DEFAULT '', viewers TEXT DEFAULT '[]',
            created_at TIMESTAMP DEFAULT NOW())""",
    ]
    conn = get_conn()
    try:
        cur = conn.cursor()
        for s in stmts:
            cur.execute(s)
        conn.commit()
        print("DB schema ready")
    finally:
        conn.close()

# USERS
def get_user(u): return query("SELECT * FROM users WHERE username=%s",(u,),one=True)
def user_exists(u): return bool(query("SELECT 1 FROM users WHERE username=%s",(u,),one=True))
def create_user(username,password_hash,bio="",avatar="",recovery=""):
    execute("INSERT INTO users(username,password_hash,bio,avatar,recovery) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(username) DO NOTHING",(username,password_hash,bio,avatar,recovery))
def update_user(username,**kwargs):
    allowed={"password_hash","bio","avatar","recovery","last_seen","typing_to","typing_ts","typing_group","typing_group_ts"}
    conn=get_conn()
    try:
        cur=conn.cursor()
        for k,v in kwargs.items():
            if k in allowed:
                cur.execute(f"UPDATE users SET {k}=%s WHERE username=%s",(v,username))
        conn.commit()
    finally: conn.close()
def delete_user(username):
    for sql in ["DELETE FROM friend_requests WHERE from_user=%s OR to_user=%s",
                "DELETE FROM friends WHERE user1=%s OR user2=%s",
                "DELETE FROM unread WHERE username=%s OR from_user=%s",
                "DELETE FROM notes WHERE username=%s","DELETE FROM stories WHERE username=%s",
                "DELETE FROM group_members WHERE username=%s","DELETE FROM users WHERE username=%s"]:
        if sql.count('%s') == 2:
            execute(sql,(username,username))
        else:
            execute(sql,(username,))

# FRIENDS
def get_friends(username):
    rows=query("SELECT CASE WHEN user1=%s THEN user2 ELSE user1 END AS friend FROM friends WHERE user1=%s OR user2=%s",(username,username,username))
    return [r["friend"] for r in rows]
def are_friends(u1,u2): return bool(query("SELECT 1 FROM friends WHERE (user1=%s AND user2=%s) OR (user1=%s AND user2=%s)",(u1,u2,u2,u1),one=True))
def add_friend(u1,u2):
    a,b=sorted([u1,u2]); execute("INSERT INTO friends(user1,user2) VALUES(%s,%s) ON CONFLICT DO NOTHING",(a,b))
def remove_friend(u1,u2):
    a,b=sorted([u1,u2]); execute("DELETE FROM friends WHERE user1=%s AND user2=%s",(a,b))
def send_request(f,t): execute("INSERT INTO friend_requests(from_user,to_user) VALUES(%s,%s) ON CONFLICT DO NOTHING",(f,t))
def cancel_request(f,t): execute("DELETE FROM friend_requests WHERE from_user=%s AND to_user=%s",(f,t))
def get_pending_in(u): return [r["from_user"] for r in query("SELECT from_user FROM friend_requests WHERE to_user=%s",(u,))]
def accept_request(f,t): cancel_request(f,t); add_friend(f,t)
def reject_request(f,t): cancel_request(f,t)
def already_requested(f,t): return bool(query("SELECT 1 FROM friend_requests WHERE from_user=%s AND to_user=%s",(f,t),one=True))

# UNREAD
def count_unread(u):
    r=query("SELECT COALESCE(SUM(count),0) AS total FROM unread WHERE username=%s",(u,),one=True)
    return int(r["total"]) if r else 0
def get_unread_senders(u): return [r["from_user"] for r in query("SELECT from_user FROM unread WHERE username=%s AND count>0",(u,))]
def get_unread_dict(u): return {r["from_user"]:r["count"] for r in query("SELECT from_user,count FROM unread WHERE username=%s",(u,))}
def increment_unread(u,f): execute("INSERT INTO unread(username,from_user,count) VALUES(%s,%s,1) ON CONFLICT(username,from_user) DO UPDATE SET count=unread.count+1",(u,f))
def reset_unread(u,f): execute("UPDATE unread SET count=0 WHERE username=%s AND from_user=%s",(u,f))

# DM MESSAGES
def load_chat(u1,u2):
    rows=query("SELECT * FROM messages WHERE (sender=%s AND recipient=%s) OR (sender=%s AND recipient=%s) ORDER BY created_at ASC",(u1,u2,u2,u1))
    for r in rows:
        if isinstance(r.get("reactions"),str): r["reactions"]=json.loads(r["reactions"])
    return rows
def send_message(sender,recipient,text="",ftype="text",filename="",url="",reply_to=None):
    conn=get_conn()
    try:
        cur=conn.cursor()
        cur.execute("INSERT INTO messages(sender,recipient,text,ftype,filename,url,reply_to) VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                    (sender,recipient,text,ftype,filename,url,reply_to))
        mid=cur.fetchone()[0]; conn.commit(); return mid
    finally: conn.close()
def mark_seen(sender,recipient): execute("UPDATE messages SET seen=TRUE WHERE sender=%s AND recipient=%s AND seen=FALSE",(sender,recipient))
def soft_delete_message(mid): execute("UPDATE messages SET deleted=TRUE,text='This message was deleted',ftype='text',filename='',url='',reactions='{}' WHERE id=%s",(mid,))
def get_message_by_id(mid):
    r=query("SELECT * FROM messages WHERE id=%s",(mid,),one=True)
    if r and isinstance(r.get("reactions"),str): r["reactions"]=json.loads(r["reactions"])
    return r
def react_message(mid,username,emoji):
    msg=get_message_by_id(mid)
    if not msg: return
    r=msg.get("reactions",{}) or {}
    if r.get(username)==emoji: r.pop(username)
    else: r[username]=emoji
    execute("UPDATE messages SET reactions=%s WHERE id=%s",(json.dumps(r),mid))

# GROUPS
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
    rows=query("SELECT g.* FROM groups g JOIN group_members gm ON g.group_id=gm.group_id WHERE gm.username=%s ORDER BY g.created_at",(username,))
    out=[]
    for g in rows:
        d=dict(g); d["members"]=get_group_members(g["group_id"]); out.append(d)
    return out

# GROUP MESSAGES
def load_group_chat(gid):
    rows=query("SELECT * FROM group_messages WHERE group_id=%s ORDER BY created_at ASC",(gid,))
    for r in rows:
        if isinstance(r.get("reactions"),str): r["reactions"]=json.loads(r["reactions"])
        if isinstance(r.get("seen_by"),str):   r["seen_by"]=json.loads(r["seen_by"])
    return rows
def send_group_message(gid,sender,text="",ftype="text",filename="",url="",reply_to=None):
    conn=get_conn()
    try:
        cur=conn.cursor()
        cur.execute("INSERT INTO group_messages(group_id,sender,text,ftype,filename,url,reply_to,seen_by) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                    (gid,sender,text,ftype,filename,url,reply_to,json.dumps([sender])))
        mid=cur.fetchone()[0]; conn.commit(); return mid
    finally: conn.close()
def mark_group_seen(gid,username):
    rows=query("SELECT id,seen_by FROM group_messages WHERE group_id=%s",(gid,))
    for row in rows:
        seen=json.loads(row["seen_by"]) if isinstance(row["seen_by"],str) else (row["seen_by"] or [])
        if username not in seen:
            seen.append(username)
            execute("UPDATE group_messages SET seen_by=%s WHERE id=%s",(json.dumps(seen),row["id"]))
def soft_delete_group_message(mid): execute("UPDATE group_messages SET deleted=TRUE,text='This message was deleted',ftype='text',filename='',url='',reactions='{}' WHERE id=%s",(mid,))
def get_group_message_by_id(mid):
    r=query("SELECT * FROM group_messages WHERE id=%s",(mid,),one=True)
    if r and isinstance(r.get("reactions"),str): r["reactions"]=json.loads(r["reactions"])
    return r
def react_group_message(mid,username,emoji):
    msg=get_group_message_by_id(mid)
    if not msg: return
    r=msg.get("reactions",{}) or {}
    if r.get(username)==emoji: r.pop(username)
    else: r[username]=emoji
    execute("UPDATE group_messages SET reactions=%s WHERE id=%s",(json.dumps(r),mid))

# NOTES
def load_notes(username,sort="newest"):
    order="DESC" if sort=="newest" else "ASC"
    return query(f"SELECT * FROM notes WHERE username=%s ORDER BY created_at {order}",(username,))
def add_note(username,title,body): execute("INSERT INTO notes(username,title,body) VALUES(%s,%s,%s)",(username,title,body))
def update_note(note_id,username,title,body): execute("UPDATE notes SET title=%s,body=%s WHERE id=%s AND username=%s",(title,body,note_id,username))
def delete_note(note_id,username): execute("DELETE FROM notes WHERE id=%s AND username=%s",(note_id,username))

# STORIES
def load_stories():
    out={}
    rows=query("SELECT * FROM stories WHERE created_at > NOW() - INTERVAL '16 hours' ORDER BY username,created_at ASC")
    for r in rows:
        d=dict(r)
        if isinstance(d.get("viewers"),str): d["viewers"]=json.loads(d["viewers"])
        out.setdefault(d["username"],[]).append(d)
    return out
def add_story(username,url,ftype="image",caption=""): execute("INSERT INTO stories(username,url,ftype,caption,viewers) VALUES(%s,%s,%s,%s,%s)",(username,url,ftype,caption,"[]"))
def delete_story(story_id,username): execute("DELETE FROM stories WHERE id=%s AND username=%s",(story_id,username))
def add_story_viewer(story_id,viewer):
    r=query("SELECT viewers FROM stories WHERE id=%s",(story_id,),one=True)
    if not r: return
    viewers=json.loads(r["viewers"]) if isinstance(r["viewers"],str) else (r["viewers"] or [])
    if viewer not in viewers:
        viewers.append(viewer)
        execute("UPDATE stories SET viewers=%s WHERE id=%s",(json.dumps(viewers),story_id))
