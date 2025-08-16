import os, json, re, secrets, datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session, abort
from werkzeug.utils import secure_filename

# ---------- Config ----------
APP_NAME = "Khamsa Travels"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
POSTS_PATH = os.path.join(BASE_DIR, "posts.json")
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp"}
PER_PAGE = 6

os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-change-me")   # set a strong one in prod
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "change-this")           # set in prod!

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
    # show published; if admin, show all
    visible = posts if is_admin() else [p for p in posts if p.get("published", True)]
    if q:
        visible = [p for p in visible if q in p["title"].lower() or q in p["content"].lower()]
    # newest first
    visible.sort(key=lambda p: p["created_at"], reverse=True)

    # pagination
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

# ---------- Auth (super simple) ----------
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
            "cover_image": cover,  # filename only
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
        # refresh slug from title (ensure uniqueness)
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
    # Run the dev server
    app.run(host='0.0.0.0', port=5000, debug=True)
