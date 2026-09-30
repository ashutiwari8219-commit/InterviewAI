import os, json, sqlite3
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database.db")

# (question, keywords a good answer should mention)
QUESTIONS = {
    "Python Developer": [
        ("What is the difference between a list and a tuple?", ["mutable", "immutable", "ordered"]),
        ("What are decorators in Python?", ["function", "wrap", "modify", "@"]),
        ("Explain how Python manages memory.", ["garbage", "reference", "heap"]),
        ("What is the difference between a shallow and a deep copy?", ["nested", "reference", "copy", "independent"]),
    ],
    "Data Analyst": [
        ("What is the difference between INNER JOIN and LEFT JOIN?", ["matching", "all rows", "left", "null"]),
        ("How do you handle missing values in a dataset?", ["remove", "impute", "mean", "median"]),
        ("What is a DAX measure in Power BI?", ["calculation", "aggregate", "context", "formula"]),
        ("What makes a good dashboard?", ["clear", "kpi", "audience", "filter"]),
    ],
    "Web Developer": [
        ("What is the difference between GET and POST?", ["retrieve", "submit", "body", "url"]),
        ("Explain the CSS box model.", ["margin", "padding", "border", "content"]),
        ("What is a REST API?", ["http", "resource", "stateless", "json"]),
        ("What is the difference between session and cookie?", ["server", "browser", "store", "id"]),
    ],
    "HR Round": [
        ("Tell me about yourself.", ["experience", "skills", "project", "goal"]),
        ("What are your strengths and weaknesses?", ["strength", "weakness", "improve", "example"]),
        ("Why should we hire you?", ["skills", "value", "team", "learn"]),
        ("Where do you see yourself in five years?", ["grow", "career", "goal", "learn"]),
    ],
}


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL, password TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS interviews(
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
        role TEXT NOT NULL, score REAL NOT NULL, details TEXT NOT NULL, created_at TEXT NOT NULL);
    """)
    con.commit()
    con.close()


init_db()


def login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if "user_id" not in session:
            flash("Please log in first.")
            return redirect(url_for("login"))
        return f(*a, **kw)
    return wrapper


@app.route("/")
def home():
    return render_template("home.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        pw = request.form["password"]
        if not name or not email or len(pw) < 6:
            flash("Fill all fields. Password needs at least 6 characters.")
            return render_template("register.html")
        con = db()
        try:
            con.execute("INSERT INTO users(name,email,password,created_at) VALUES(?,?,?,?)",
                        (name, email, generate_password_hash(pw), datetime.now().strftime("%d %b %Y")))
            con.commit()
        except sqlite3.IntegrityError:
            flash("That email is already registered. Log in instead.")
            return render_template("register.html")
        finally:
            con.close()
        flash("Account created. Log in to continue.")
        return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        con = db()
        u = con.execute("SELECT * FROM users WHERE email=?", (request.form["email"].strip().lower(),)).fetchone()
        con.close()
        if u and check_password_hash(u["password"], request.form["password"]):
            session["user_id"], session["name"] = u["id"], u["name"]
            return redirect(url_for("dashboard"))
        flash("Wrong email or password.")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/dashboard")
@login_required
def dashboard():
    con = db()
    rows = con.execute("SELECT * FROM interviews WHERE user_id=? ORDER BY id DESC", (session["user_id"],)).fetchall()
    con.close()
    avg = round(sum(r["score"] for r in rows) / len(rows)) if rows else 0
    return render_template("dashboard.html", total=len(rows), avg=avg, recent=rows[:3])


@app.route("/start", methods=["GET", "POST"])
@login_required
def start_interview():
    if request.method == "POST" and request.form.get("role") in QUESTIONS:
        return redirect(url_for("interview", role=request.form["role"]))
    return render_template("start_interview.html", roles=list(QUESTIONS))


@app.route("/interview/<role>", methods=["GET", "POST"])
@login_required
def interview(role):
    if role not in QUESTIONS:
        return redirect(url_for("start_interview"))
    qs = QUESTIONS[role]
    if request.method == "POST":
        details = []
        for i, (q, kws) in enumerate(qs):
            ans = request.form.get(f"a{i}", "").strip()
            hit = [k for k in kws if k.lower() in ans.lower()]
            details.append({"q": q, "answer": ans, "hit": hit,
                            "missed": [k for k in kws if k not in hit],
                            "score": round(100 * len(hit) / len(kws))})
        total = round(sum(d["score"] for d in details) / len(details))
        con = db()
        cur = con.execute("INSERT INTO interviews(user_id,role,score,details,created_at) VALUES(?,?,?,?,?)",
                          (session["user_id"], role, total, json.dumps(details),
                           datetime.now().strftime("%d %b %Y, %H:%M")))
        con.commit()
        rid = cur.lastrowid
        con.close()
        return redirect(url_for("results", rid=rid))
    return render_template("interview.html", role=role, questions=[q for q, _ in qs])


@app.route("/results/<int:rid>")
@login_required
def results(rid):
    con = db()
    r = con.execute("SELECT * FROM interviews WHERE id=? AND user_id=?", (rid, session["user_id"])).fetchone()
    con.close()
    if not r:
        return redirect(url_for("performance"))
    return render_template("results.html", r=r, details=json.loads(r["details"]))


@app.route("/performance")
@login_required
def performance():
    con = db()
    rows = con.execute("SELECT * FROM interviews WHERE user_id=? ORDER BY id DESC", (session["user_id"],)).fetchall()
    con.close()
    best = max((r["score"] for r in rows), default=0)
    return render_template("performance.html", rows=rows, best=round(best))


@app.route("/profile")
@login_required
def profile():
    con = db()
    u = con.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    n = con.execute("SELECT COUNT(*) c FROM interviews WHERE user_id=?", (session["user_id"],)).fetchone()["c"]
    con.close()
    return render_template("profile.html", u=u, n=n)


if __name__ == "__main__":
    app.run(debug=True)
