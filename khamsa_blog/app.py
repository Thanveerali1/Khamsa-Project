import os, json, re, secrets, datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session, abort, g
from werkzeug.utils import secure_filename

# ---------- Config ----------
APP_NAME = "Khamsa Travels"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
POSTS_PATH = os.path.join(BASE_DIR, "posts.json")
STATIC_DIR = os.path.join(BASE_DIR, "static")
UPLOAD_DIR = os.path.join(STATIC_DIR, "uploads")
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp"}
PER_PAGE = 6

# MySQL config (set these in your environment)
MYSQL_HOST = os.environ.get("MYSQL_HOST", "127.0.0.1")
MYSQL_USER = os.environ.get("MYSQL_USER", "root")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "")
MYSQL_DB = os.environ.get("MYSQL_DB", "khamsa_blog")

os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-change-me")   # set a strong one in prod
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "change-this")           # set in prod!

# ---------- DB (MySQL) ----------
#   pip install mysql-connector-python
import mysql.connector

def get_db():
    """Get a request-scoped MySQL connection."""
    if "db" not in g:
        g.db = mysql.connector.connect(
            host=MYSQL_HOST,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DB,
            autocommit=False,
        )
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
    """Create feedbacks table if not exists."""
    db = get_db()
    cur = db.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS feedbacks (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            email VARCHAR(120) NULL,
            rating TINYINT NULL,
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
    )
    db.commit()
    cur.close()

# ---------- Utilities ----------
def load_posts():
    if not os.path.exists(POSTS_PATH):
        with open(POSTS_PATH, "w", encoding="utf-8") as f:
            json.dump([], f)
    with open(POSTS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_posts(posts):
    with open(POSTS_PATH, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)

def next_id(posts):
    return (max([p["id"] for p in posts]) + 1) if posts else 1

def slugify(text):
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or secrets.token_hex(4)

def unique_slug(posts, base_slug, ignore_id=None):
    slug = base_slug
    i = 2
    existing = {p["slug"]: p["id"] for p in posts}
    while slug in existing and existing[slug] != ignore_id:
        slug = f"{base_slug}-{i}"
        i += 1
    return slug

def is_admin():
    return session.get("admin", False)

def save_image(file):
    if not file or file.filename == "":
        return ""
    filename = secure_filename(file.filename)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXT:
        flash("Only JPG/PNG/WEBP images are allowed.", "warning")
        return ""
    newname = f"{secrets.token_hex(8)}{ext}"
    path = os.path.join(UPLOAD_DIR, newname)
    file.save(path)
    return newname

# ---------- Routes (Public) ----------
@app.route("/")
def index():
    q = request.args.get("q", "").strip().lower()
    page = max(int(request.args.get("page", 1)), 1)

    posts = load_posts()
    visible = posts if is_admin() else [p for p in posts if p.get("published", True)]
    if q:
        visible = [p for p in visible if q in p["title"].lower() or q in p["content"].lower()]
    visible.sort(key=lambda p: p["created_at"], reverse=True)

    total = len(visible)
    start, end = (page - 1) * PER_PAGE, page * PER_PAGE
    page_items = visible[start:end]
    last_page = (total + PER_PAGE - 1) // PER_PAGE

    return render_template(
        "index.html",
        app_name=APP_NAME,
        posts=page_items,
        q=q,
        page=page,
        last_page=last_page,
        total=total
    )

@app.route("/post/<slug>")
def view_post(slug):
    posts = load_posts()
    post = next((p for p in posts if p["slug"] == slug), None)
    if not post or (not post.get("published", True) and not is_admin()):
        abort(404)
    return render_template("view_post.html", app_name=APP_NAME, post=post)

# ---------- Feedback (Public) ----------
@app.route("/feedback", methods=["GET", "POST"])
def feedback():
    init_db()  # ensure table exists
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        rating = request.form.get("rating", "").strip()
        message = request.form.get("message", "").strip()

        if not name or not message or len(message) < 3:
            flash("Please provide your name and a valid message.", "warning")
            return redirect(url_for("feedback"))

        try:
            rating_val = int(rating) if rating else None
            if rating_val is not None and (rating_val < 1 or rating_val > 5):
                rating_val = None
        except ValueError:
            rating_val = None

        db = get_db()
        cur = db.cursor()
        cur.execute(
            "INSERT INTO feedbacks (name, email, rating, message) VALUES (%s, %s, %s, %s)",
            (name, email or None, rating_val, message)
        )
        db.commit()
        cur.close()
        flash("Thanks for your feedback!", "success")
        return redirect(url_for("index"))

    return render_template("feedback.html", app_name=APP_NAME)

# ---------- Auth ----------
@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["admin"] = True
            flash("Logged in.", "success")
            return redirect(url_for("dashboard"))
        flash("Wrong password.", "danger")
    return render_template("login.html", app_name=APP_NAME)

@app.route("/logout")
def logout():
    session.pop("admin", None)
    flash("Logged out.", "info")
    return redirect(url_for("index"))

# ---------- Admin ----------
@app.route("/admin")
def dashboard():
    if not is_admin(): return redirect(url_for("login"))
    posts = load_posts()
    posts.sort(key=lambda p: p["created_at"], reverse=True)
    return render_template("edit_post.html", app_name=APP_NAME, mode="list", posts=posts)

@app.route("/admin/feedbacks")
def view_feedbacks():
    if not is_admin(): return redirect(url_for("login"))
    init_db()
    page = max(int(request.args.get("page", 1)), 1)
    per_page = 12
    offset = (page - 1) * per_page

    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT COUNT(*) AS c FROM feedbacks")
    total = cur.fetchone()["c"]

    cur.execute(
        "SELECT id, name, email, rating, message, created_at FROM feedbacks "
        "ORDER BY created_at DESC LIMIT %s OFFSET %s",
        (per_page, offset)
    )
    items = cur.fetchall()
    cur.close()

    last_page = (total + per_page - 1) // per_page
    return render_template(
        "feedbacks.html",
        app_name=APP_NAME,
        feedbacks=items,
        page=page,
        last_page=last_page,
        total=total
    )

@app.route("/admin/feedbacks/delete/<int:fid>", methods=["POST"])
def delete_feedback(fid):
    if not is_admin(): return redirect(url_for("login"))
    db = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM feedbacks WHERE id=%s", (fid,))
    db.commit()
    cur.close()
    flash("Feedback deleted.", "info")
    return redirect(url_for("view_feedbacks"))

@app.route("/admin/new", methods=["GET","POST"])
def new_post():
    if not is_admin(): return redirect(url_for("login"))
    if request.method == "POST":
        posts = load_posts()
        title = request.form.get("title","").strip()
        content = request.form.get("content","").strip()
        published = True if request.form.get("published") == "on" else False
        cover = save_image(request.files.get("cover"))

        if not title or len(content) < 10:
            flash("Title and content are required (content ≥ 10 chars).", "warning")
            return redirect(url_for("new_post"))

        base = slugify(title)
        slug = unique_slug(posts, base)
        post = {
            "id": next_id(posts),
            "title": title,
            "slug": slug,
            "content": content,
            "cover_image": cover,
            "published": published,
            "created_at": datetime.datetime.utcnow().isoformat()
        }
        posts.append(post)
        save_posts(posts)
        flash("Post created.", "success")
        return redirect(url_for("dashboard"))

    return render_template("edit_post.html", app_name=APP_NAME, mode="new")

@app.route("/admin/edit/<int:pid>", methods=["GET","POST"])
def edit_post(pid):
    if not is_admin(): return redirect(url_for("login"))
    posts = load_posts()
    post = next((p for p in posts if p["id"] == pid), None)
    if not post: abort(404)

    if request.method == "POST":
        title = request.form.get("title","").strip()
        content = request.form.get("content","").strip()
        published = True if request.form.get("published") == "on" else False
        new_cover = request.files.get("cover")
        if new_cover and new_cover.filename:
            saved = save_image(new_cover)
            if saved: post["cover_image"] = saved

        if not title or len(content) < 10:
            flash("Title and content are required.", "warning")
            return redirect(url_for("edit_post", pid=pid))

        post["title"] = title
        post["content"] = content
        post["published"] = published
        base = slugify(title)
        post["slug"] = unique_slug(posts, base, ignore_id=pid)

        save_posts(posts)
        flash("Post updated.", "success")
        return redirect(url_for("dashboard"))

    return render_template("edit_post.html", app_name=APP_NAME, mode="edit", post=post)

@app.route("/admin/delete/<int:pid>", methods=["POST"])
def delete_post(pid):
    if not is_admin(): return redirect(url_for("login"))
    posts = load_posts()
    new_posts = [p for p in posts if p["id"] != pid]
    if len(new_posts) == len(posts):
        abort(404)
    save_posts(new_posts)
    flash("Post deleted.", "info")
    return redirect(url_for("dashboard"))

if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)
