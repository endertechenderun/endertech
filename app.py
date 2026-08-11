import os
from io import BytesIO
from functools import wraps
import psycopg
from psycopg.rows import dict_row
from flask import Flask,render_template,request,redirect,url_for,session,flash,abort,send_file
from werkzeug.security import generate_password_hash,check_password_hash

app=Flask(__name__)
app.secret_key=os.environ.get("SECRET_KEY","CHANGE_ME")
DB=os.environ["DATABASE_URL"]

def db(): return psycopg.connect(DB,row_factory=dict_row)

def init_db():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS users(
        id SERIAL PRIMARY KEY,username TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'member',profile_photo BYTEA,profile_mime TEXT,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP)""")
        c.execute("""CREATE TABLE IF NOT EXISTS weeks(
        id SERIAL PRIMARY KEY,title TEXT NOT NULL,description TEXT NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS projects(
        id SERIAL PRIMARY KEY,user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
        title TEXT NOT NULL,html_code TEXT NOT NULL DEFAULT '',
        python_code TEXT NOT NULL DEFAULT '',updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP)""")
        c.execute("""CREATE TABLE IF NOT EXISTS attendance(
        id SERIAL PRIMARY KEY,user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
        day DATE NOT NULL,present BOOLEAN NOT NULL DEFAULT FALSE,
        UNIQUE(user_id,day))""")
        if not c.execute("SELECT 1 FROM users WHERE username=%s",("İsoLec_Baskan",)).fetchone():
            c.execute("INSERT INTO users(username,password_hash,role) VALUES(%s,%s,%s)",
                      ("İsoLec_Baskan",generate_password_hash("32145178"),"admin"))
        if c.execute("SELECT COUNT(*) n FROM weeks").fetchone()["n"]==0:
            c.executemany("INSERT INTO weeks(title,description) VALUES(%s,%s)",[
                ("1. Hafta - Teknolojiye Giriş","Teknoloji dünyasını tanıyoruz."),
                ("2. Hafta - Yazılıma Giriş","Algoritmalar ve temel programlama."),
                ("3. Hafta - Web Tasarım","HTML ve CSS ile web sayfası oluşturma."),
                ("4. Hafta - Arduino","Arduino ve temel elektronik devreler.")])

def user():
    if not session.get("uid"): return None
    with db() as c:return c.execute("SELECT * FROM users WHERE id=%s",(session["uid"],)).fetchone()

@app.context_processor
def ctx(): return {"current_user":user()}

def login_req(f):
    @wraps(f)
    def w(*a,**k):
        if not user(): return redirect(url_for("login"))
        return f(*a,**k)
    return w

def admin_req(f):
    @wraps(f)
    def w(*a,**k):
        if not user() or user()["role"]!="admin": abort(403)
        return f(*a,**k)
    return w

@app.route("/")
@login_req
def home():
    u=user()
    with db() as c:
        weeks=c.execute("SELECT * FROM weeks ORDER BY id").fetchall()
        projects=c.execute("SELECT * FROM projects WHERE user_id=%s ORDER BY updated_at DESC",(u["id"],)).fetchall()
    return render_template("index.html",weeks=weeks,projects=projects)

@app.route("/login",methods=["GET","POST"])
def login():
    if request.method=="POST":
        with db() as c:u=c.execute("SELECT * FROM users WHERE username=%s",(request.form["username"].strip(),)).fetchone()
        if u and check_password_hash(u["password_hash"],request.form["password"]):
            session.clear();session["uid"]=u["id"];return redirect(url_for("home"))
        flash("Kullanıcı adı veya şifre yanlış.")
    return render_template("login.html")

@app.route("/logout")
def logout():session.clear();return redirect(url_for("login"))

@app.route("/profile",methods=["GET","POST"])
@login_req
def profile():
    u=user()
    if request.method=="POST":
        with db() as c:
            if request.form["action"]=="photo":
                f=request.files.get("photo")
                if not f or f.mimetype not in {"image/png","image/jpeg","image/webp"}: flash("PNG/JPG/WEBP seç.")
                elif len(f.read())>2*1024*1024: flash("Fotoğraf en fazla 2 MB.")
                else:
                    f.stream.seek(0);c.execute("UPDATE users SET profile_photo=%s,profile_mime=%s WHERE id=%s",(f.read(),f.mimetype,u["id"]));flash("Fotoğraf güncellendi.")
            else:
                full=c.execute("SELECT password_hash FROM users WHERE id=%s",(u["id"],)).fetchone()
                if u["role"]=="member" and check_password_hash(full["password_hash"],request.form["old"]) and request.form["new"]==request.form["confirm"] and len(request.form["new"])>=4:
                    c.execute("UPDATE users SET password_hash=%s WHERE id=%s",(generate_password_hash(request.form["new"]),u["id"]));flash("Şifre değiştirildi.")
                else: flash("Şifre bilgileri hatalı.")
        return redirect(url_for("profile"))
    return render_template("profile.html",u=u)

@app.route("/photo/<int:uid>")
@login_req
def photo(uid):
    with db() as c:x=c.execute("SELECT profile_photo,profile_mime FROM users WHERE id=%s",(uid,)).fetchone()
    if not x or not x["profile_photo"]: abort(404)
    return send_file(BytesIO(bytes(x["profile_photo"])),mimetype=x["profile_mime"])

@app.route("/projects/new",methods=["GET","POST"])
@login_req
def new_project():
    if request.method=="POST":
        with db() as c:c.execute("INSERT INTO projects(user_id,title,html_code,python_code) VALUES(%s,%s,%s,%s)",(user()["id"],request.form["title"],request.form["html"],request.form["python"]))
        return redirect(url_for("home"))
    return render_template("project.html",p=None)

@app.route("/projects/<int:pid>",methods=["GET","POST"])
@login_req
def edit_project(pid):
    with db() as c:p=c.execute("SELECT * FROM projects WHERE id=%s",(pid,)).fetchone()
    if not p or p["user_id"]!=user()["id"]:abort(403)
    if request.method=="POST":
        with db() as c:c.execute("UPDATE projects SET title=%s,html_code=%s,python_code=%s,updated_at=CURRENT_TIMESTAMP WHERE id=%s",(request.form["title"],request.form["html"],request.form["python"],pid))
        return redirect(url_for("home"))
    return render_template("project.html",p=p)

@app.route("/preview/<int:pid>")
@login_req
def preview(pid):
    with db() as c:p=c.execute("SELECT * FROM projects WHERE id=%s",(pid,)).fetchone()
    if not p or (p["user_id"]!=user()["id"] and user()["role"]!="admin"):abort(403)
    return render_template("preview.html",p=p)

@app.route("/admin")
@admin_req
def admin():
    with db() as c:
        users=c.execute("SELECT id,username,created_at FROM users WHERE role='member' ORDER BY username").fetchall()
        weeks=c.execute("SELECT * FROM weeks ORDER BY id").fetchall()
        projects=c.execute("SELECT p.*,u.username owner FROM projects p JOIN users u ON u.id=p.user_id ORDER BY p.updated_at DESC").fetchall()
        att=c.execute("SELECT a.*,u.username FROM attendance a JOIN users u ON u.id=a.user_id ORDER BY day DESC").fetchall()
    return render_template("admin.html",users=users,weeks=weeks,projects=projects,att=att)

@app.route("/admin/member",methods=["POST"])
@admin_req
def member():
    try:
        with db() as c:c.execute("INSERT INTO users(username,password_hash,role) VALUES(%s,%s,'member')",(request.form["username"].strip(),generate_password_hash(request.form["password"])))
        flash("Üye oluşturuldu.")
    except psycopg.errors.UniqueViolation:flash("Bu kullanıcı zaten var.")
    return redirect(url_for("admin"))

@app.route("/admin/reset/<int:uid>",methods=["POST"])
@admin_req
def reset(uid):
    with db() as c:c.execute("UPDATE users SET password_hash=%s WHERE id=%s AND role='member'",(generate_password_hash(request.form["password"]),uid))
    flash("Şifre sıfırlandı.")
    return redirect(url_for("admin"))

@app.route("/admin/delete/<int:uid>",methods=["POST"])
@admin_req
def delete(uid):
    with db() as c:c.execute("DELETE FROM users WHERE id=%s AND role='member'",(uid,))
    return redirect(url_for("admin"))

@app.route("/admin/week",methods=["POST"])
@admin_req
def week():
    with db() as c:c.execute("INSERT INTO weeks(title,description) VALUES(%s,%s)",(request.form["title"],request.form["description"]))
    return redirect(url_for("admin"))

@app.route("/admin/att",methods=["POST"])
@admin_req
def att():
    with db() as c:c.execute("""INSERT INTO attendance(user_id,day,present) VALUES(%s,%s,%s)
    ON CONFLICT(user_id,day) DO UPDATE SET present=EXCLUDED.present""",(request.form["uid"],request.form["day"],request.form["present"]=="1"))
    return redirect(url_for("admin"))

init_db()
