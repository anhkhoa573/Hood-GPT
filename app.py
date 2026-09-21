from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import os
import sqlite3
import hashlib
from datetime import datetime, timedelta
from functools import wraps
from google import genai

app = Flask(__name__)
app.secret_key = "hood-gpt-secret-key-2026"
app.permanent_session_lifetime = timedelta(days=7)

DB_PATH = "hood.db"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "PASTE_KEY_CUA_BAN_VAO_DAY")

MODE_CONFIG = {
    "basic": {
        "model": "gemini-3.6-flash",
        "system": "Ban la tro ly AI than thien. Tra loi ngan gon, de hieu.",
        "max_tokens": 1000
    },
    "pro": {
        "model": "gemini-3.6-flash",
        "system": "Ban la chuyen gia AI. Tra loi chi tiet, co phan tich, vi du cu the.",
        "max_tokens": 2000
    },
    "max": {
        "model": "gemini-3.6-flash",
        "system": "Ban la AI thong minh nhat. Suy luan sau, tra loi day du moi goc do.",
        "max_tokens": 4000
    }
}


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, mode TEXT DEFAULT 'basic', created_at TEXT NOT NULL, msg_count INTEGER DEFAULT 0)")
    conn.execute("CREATE TABLE IF NOT EXISTS chats (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL)")
    conn.commit()
    conn.close()


def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()


def login_required(f):
    @wraps(f)
    def deco(*a, **kw):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*a, **kw)
    return deco


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        d = request.get_json()
        u = d.get("username", "").strip()
        p = d.get("password", "")
        action = d.get("action", "login")

        if not u or not p:
            return jsonify({"ok": False, "error": "Nhap day du thong tin!"})

        init_db()
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row

        if action == "register":
            if len(u) < 3 or len(u) > 20:
                conn.close()
                return jsonify({"ok": False, "error": "Ten 3-20 ky tu!"})
            if len(p) < 6:
                conn.close()
                return jsonify({"ok": False, "error": "Mat khau it nhat 6 ky tu!"})
            try:
                conn.execute("INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                             (u, hash_pw(p), datetime.utcnow().isoformat()))
                conn.commit()
                row = conn.execute("SELECT * FROM users WHERE username = ?", (u,)).fetchone()
                session["user_id"] = row["id"]
                session["username"] = row["username"]
                session.permanent = True
                conn.close()
                return jsonify({"ok": True, "message": "Dang ky thanh cong!"})
            except sqlite3.IntegrityError:
                conn.close()
                return jsonify({"ok": False, "error": "Ten da ton tai!"})

        row = conn.execute("SELECT * FROM users WHERE username = ? AND password_hash = ?",
                           (u, hash_pw(p))).fetchone()
        conn.close()
        if not row:
            return jsonify({"ok": False, "error": "Sai ten hoac mat khau!"})
        session["user_id"] = row["id"]
        session["username"] = row["username"]
        session.permanent = True
        return jsonify({"ok": True, "message": "Dang nhap thanh cong!"})

    if "user_id" in session:
        return redirect(url_for("index"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    return render_template("index.html", username=session.get("username"))


@app.route("/api/chat", methods=["POST"])
@login_required
def api_chat():
    try:
        d = request.get_json()
        msg = d.get("message", "").strip()
        mode = d.get("mode", "basic")

        if not msg:
            return jsonify({"ok": False, "error": "Nhap tin nhan!"})
        if mode not in MODE_CONFIG:
            mode = "basic"

        uid = session["user_id"]
        cfg = MODE_CONFIG[mode]

        init_db()
        conn = sqlite3.connect(DB_PATH)
        conn.execute("INSERT INTO chats (user_id, role, content, created_at) VALUES (?, 'user', ?, ?)",
                     (uid, msg, datetime.utcnow().isoformat()))
        conn.commit()

        rows = conn.execute(
            "SELECT role, content FROM chats WHERE user_id = ? ORDER BY id DESC LIMIT 6",
            (uid,)
        ).fetchall()
        conn.close()

        history = list(reversed(rows))

        history_text = ""
        for role, content in history[:-1]:
            if role == "user":
                history_text += "User: " + content + chr(10)
            else:
                history_text += "Assistant: " + content + chr(10)

        full_prompt = history_text + "User: " + msg + chr(10) + "Assistant:"

        client = genai.Client(api_key=GEMINI_API_KEY)

        response = client.models.generate_content(
            model=cfg["model"],
            contents=full_prompt,
            config={
                "system_instruction": cfg["system"],
                "max_output_tokens": cfg["max_tokens"],
                "temperature": 0.9 if mode == "max" else 0.7
            }
        )

        reply = response.text if response.text else ""

        if not reply:
            return jsonify({"ok": False, "error": "AI khong tra loi. Thu lai."})

        conn = sqlite3.connect(DB_PATH)
        conn.execute("INSERT INTO chats (user_id, role, content, created_at) VALUES (?, 'assistant', ?, ?)",
                     (uid, reply, datetime.utcnow().isoformat()))
        conn.execute("UPDATE users SET msg_count = msg_count + 1 WHERE id = ?", (uid,))
        conn.commit()
        conn.close()

        return jsonify({"ok": True, "reply": reply, "mode": mode})

    except Exception as e:
        return jsonify({"ok": False, "error": "Loi: " + str(e)})


@app.route("/api/history")
@login_required
def api_history():
    uid = session["user_id"]
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT role, content, created_at FROM chats WHERE user_id = ? ORDER BY id ASC LIMIT 30",
        (uid,)
    ).fetchall()
    conn.close()
    return jsonify({"ok": True, "history": [dict(r) for r in rows]})


@app.route("/api/clear", methods=["POST"])
@login_required
def api_clear():
    uid = session["user_id"]
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM chats WHERE user_id = ?", (uid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)