import os
from datetime import date, timedelta, datetime, timezone
from io import BytesIO
from functools import wraps

import psycopg
from psycopg.rows import dict_row

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    abort,
    send_file,
    jsonify
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

# =========================================================
# GOOGLE GEMINI
# =========================================================

from google import genai
from google.genai import types


# =========================================================
# FLASK
# =========================================================

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "CHANGE_ME"
)

DB = os.environ.get("DATABASE_URL")

if not DB:
    raise RuntimeError(
        "DATABASE_URL environment variable bulunamadı."
    )


# =========================================================
# GEMINI / FAZİLETCODEAI
# =========================================================

GEMINI_API_KEY = os.environ.get(
    "GEMINI_API_KEY"
)

if GEMINI_API_KEY:
    try:
        gemini_client = genai.Client(
            api_key=GEMINI_API_KEY
        )
    except Exception as e:
        print(
            "Gemini client oluşturulamadı:",
            repr(e)
        )
        gemini_client = None
else:
    gemini_client = None


# Render Environment üzerinden istenirse
# model değiştirilebilir.
#
# Örneğin:
#
# FAZILETCODEAI_MODEL=gemini-3.6-flash
#
AI_MODEL = os.environ.get(
    "FAZILETCODEAI_MODEL",
    "gemini-3.6-flash"
)


# =========================================================
# DATABASE
# =========================================================

def db():
    return psycopg.connect(
        DB,
        row_factory=dict_row
    )


# =========================================================
# TÜRKİYE TARİHİ
# =========================================================

def turkey_today():
    """
    Türkiye UTC+3 kullanır.
    Render sunucusunun UTC saatinden Türkiye tarihini hesaplar.
    """

    return (
        datetime.now(timezone.utc)
        + timedelta(hours=3)
    ).date()


# =========================================================
# DATABASE INITIALIZATION
# =========================================================

def init_db():

    with db() as c:

        # =================================================
        # USERS
        # =================================================

        c.execute("""
            CREATE TABLE IF NOT EXISTS users(
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'member',
                profile_photo BYTEA,
                profile_mime TEXT,
                created_at TIMESTAMPTZ
                    DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # =================================================
        # WEEKS
        # =================================================

        c.execute("""
            CREATE TABLE IF NOT EXISTS weeks(
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL
            )
        """)

        # =================================================
        # PROJECTS
        # =================================================

        c.execute("""
            CREATE TABLE IF NOT EXISTS projects(
                id SERIAL PRIMARY KEY,
                user_id INTEGER
                    REFERENCES users(id)
                    ON DELETE CASCADE,
                title TEXT NOT NULL,
                html_code TEXT NOT NULL DEFAULT '',
                python_code TEXT NOT NULL DEFAULT '',
                updated_at TIMESTAMPTZ
                    DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # =================================================
        # ATTENDANCE
        # =================================================

        c.execute("""
            CREATE TABLE IF NOT EXISTS attendance(
                id SERIAL PRIMARY KEY,
                user_id INTEGER
                    REFERENCES users(id)
                    ON DELETE CASCADE,
                day DATE NOT NULL,
                present BOOLEAN NOT NULL DEFAULT FALSE,
                UNIQUE(user_id, day)
            )
        """)

        # =================================================
        # ADMIN
        # =================================================

        admin_username = os.environ.get(
            "ADMIN_USERNAME",
            "İsoLec_Baskan"
        )

        admin_password = os.environ.get(
            "ADMIN_PASSWORD"
        )

        if not admin_password:
            admin_password = "32145178"

        existing_admin = c.execute(
            """
            SELECT 1
            FROM users
            WHERE username=%s
            """,
            (admin_username,)
        ).fetchone()

        if not existing_admin:

            c.execute(
                """
                INSERT INTO users(
                    username,
                    password_hash,
                    role
                )
                VALUES(%s,%s,%s)
                """,
                (
                    admin_username,
                    generate_password_hash(
                        admin_password
                    ),
                    "admin"
                )
            )

        # =================================================
        # DEFAULT WEEKS
        # =================================================

        week_count = c.execute(
            """
            SELECT COUNT(*) AS n
            FROM weeks
            """
        ).fetchone()["n"]

        if week_count == 0:

            c.executemany(
                """
                INSERT INTO weeks(
                    title,
                    description
                )
                VALUES(%s,%s)
                """,
                [
                    (
                        "1. Hafta - Teknolojiye Giriş",
                        "Teknoloji dünyasını tanıyoruz."
                    ),
                    (
                        "2. Hafta - Yazılıma Giriş",
                        "Algoritmalar ve temel programlama."
                    ),
                    (
                        "3. Hafta - Web Tasarım",
                        "HTML ve CSS ile web sayfası oluşturma."
                    ),
                    (
                        "4. Hafta - Arduino",
                        "Arduino ve temel elektronik devreler."
                    )
                ]
            )


# =========================================================
# CURRENT USER
# =========================================================

def user():

    if not session.get("uid"):
        return None

    with db() as c:

        return c.execute(
            """
            SELECT *
            FROM users
            WHERE id=%s
            """,
            (session["uid"],)
        ).fetchone()


# =========================================================
# TEMPLATE CONTEXT
# =========================================================

@app.context_processor
def ctx():

    return {
        "current_user": user(),
        "timedelta": timedelta
    }


# =========================================================
# LOGIN REQUIRED
# =========================================================

def login_req(f):

    @wraps(f)
    def w(*a, **k):

        if not user():
            return redirect(
                url_for("login")
            )

        return f(*a, **k)

    return w


# =========================================================
# ADMIN REQUIRED
# =========================================================

def admin_req(f):

    @wraps(f)
    def w(*a, **k):

        current = user()

        if (
            not current
            or current["role"] != "admin"
        ):
            abort(403)

        return f(*a, **k)

    return w


# =========================================================
# HOME
# =========================================================

@app.route("/")
@login_req
def home():

    u = user()

    today = turkey_today()

    with db() as c:

        weeks = c.execute(
            """
            SELECT *
            FROM weeks
            ORDER BY id
            """
        ).fetchall()

        projects = c.execute(
            """
            SELECT *
            FROM projects
            WHERE user_id=%s
            ORDER BY updated_at DESC
            """,
            (u["id"],)
        ).fetchall()

        members = c.execute(
            """
            SELECT
                id,
                username,
                profile_photo,
                profile_mime
            FROM users
            WHERE role='member'
            ORDER BY username
            """
        ).fetchall()

        attendance = c.execute(
            """
            SELECT
                day,
                present
            FROM attendance
            WHERE user_id=%s
            ORDER BY day DESC
            """,
            (u["id"],)
        ).fetchall()

    return render_template(
        "index.html",
        weeks=weeks,
        projects=projects,
        members=members,
        attendance=attendance,
        today=today
    )


# =========================================================
# LOGIN
# =========================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if request.method == "POST":

        username = request.form.get(
            "username",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        with db() as c:

            u = c.execute(
                """
                SELECT *
                FROM users
                WHERE username=%s
                """,
                (username,)
            ).fetchone()

        if u and check_password_hash(
            u["password_hash"],
            password
        ):

            session.clear()

            session["uid"] = u["id"]

            return redirect(
                url_for("home")
            )

        flash(
            "Kullanıcı adı veya şifre yanlış."
        )

    return render_template(
        "login.html"
    )


# =========================================================
# FAZİLETCODEAI - GEMINI
# =========================================================

@app.route(
    "/api/faziletcodeai",
    methods=["POST"]
)
@login_req
def faziletcodeai_api():

    # -----------------------------------------------------
    # JSON AL
    # -----------------------------------------------------

    data = request.get_json(
        silent=True
    ) or {}

    question = (
        data.get("question")
        or ""
    ).strip()

    code = (
        data.get("code")
        or ""
    )

    # -----------------------------------------------------
    # SORU KONTROLÜ
    # -----------------------------------------------------

    if not question:

        return jsonify({
            "answer": (
                "Sorunu yazarsan yardımcı olabilirim."
            )
        }), 400

    # -----------------------------------------------------
    # GEMINI API KEY KONTROLÜ
    # -----------------------------------------------------

    if not gemini_client:

        return jsonify({
            "answer": (
                "FaziletCodeAI şu anda "
                "yapılandırılmamış. "
                "Render Environment bölümünde "
                "GEMINI_API_KEY değişkenini "
                "kontrol et."
            )
        }), 503

    # -----------------------------------------------------
    # KODU SINIRLA
    # -----------------------------------------------------

    if len(code) > 30000:

        code = code[:30000]

    # -----------------------------------------------------
    # KULLANICI BİLGİSİ
    # -----------------------------------------------------

    current = user()

    username = (
        current["username"]
        if current
        else "Kulüp üyesi"
    )

    # -----------------------------------------------------
    # SYSTEM INSTRUCTIONS
    # -----------------------------------------------------

    instructions = """
Sen FaziletCodeAI'sin.

Sen Endertech Bilişim Atölyesi'nin
kulüp üyelerine yardımcı olan bir
yazılım ve teknoloji asistanısın.

Görevin:

- HTML konusunda yardımcı olmak
- CSS konusunda yardımcı olmak
- JavaScript konusunda yardımcı olmak
- Python konusunda yardımcı olmak
- Kod hatalarını bulmak
- Hataları anlaşılır şekilde açıklamak
- Öğrencinin seviyesine uygun anlatmak
- Kod geliştirme fikirleri vermek
- Proje fikirleri üretmek
- Kodun nasıl çalıştığını açıklamak

Yanıtlarını Türkçe ver.

Kullanıcı bir hata soruyorsa:

1. Hatanın nedenini söyle.
2. Nasıl düzeltileceğini göster.
3. Gerekirse düzeltilmiş kod örneği ver.

Kullanıcı kod gönderirse kodu dikkatlice incele.

Gereksiz yere çok uzun cevap verme.

Ancak kod hatasının çözümü için gereken
kod parçalarını eksiksiz göster.

Tehlikeli, yasa dışı veya zarar verici
işlemler konusunda yardımcı olma.

Senin adın FaziletCodeAI.
"""

    # -----------------------------------------------------
    # USER PROMPT
    # -----------------------------------------------------

    prompt = f"""
Kulüp üyesinin kullanıcı adı:
{username}

Kullanıcının sorusu:
{question}

Kullanıcının üzerinde çalıştığı kod:

---------------- CODE START ----------------

{code}

----------------- CODE END -----------------

Bu soruya yardımcı ol.
Yanıtını Türkçe ver.
"""

    # -----------------------------------------------------
    # GEMINI REQUEST
    # -----------------------------------------------------

    try:

        response = gemini_client.models.generate_content(
            model=AI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=instructions,
                temperature=0.3,
                max_output_tokens=2000
            )
        )

        answer = (
            getattr(response, "text", None)
            or ""
        ).strip()

        if not answer:

            answer = (
                "Üzgünüm, şu anda bir yanıt "
                "oluşturamadım."
            )

        return jsonify({
            "answer": answer
        })

    except Exception as e:

        print(
            "FaziletCodeAI Gemini API ERROR:",
            repr(e)
        )

        return jsonify({
            "answer": (
                "FaziletCodeAI'ye bağlanırken "
                "bir hata oluştu. Biraz sonra "
                "tekrar dene. Sorun devam ederse "
                "Render Logs bölümünü kontrol et."
            )
        }), 500


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("login")
    )


# =========================================================
# PROFILE
# =========================================================

@app.route(
    "/profile",
    methods=["GET", "POST"]
)
@login_req
def profile():

    u = user()

    if request.method == "POST":

        with db() as c:

            action = request.form.get(
                "action",
                ""
            )

            # -------------------------------------------------
            # PROFILE PHOTO
            # -------------------------------------------------

            if action == "photo":

                f = request.files.get(
                    "photo"
                )

                if not f:

                    flash(
                        "Bir fotoğraf seç."
                    )

                elif f.mimetype not in {
                    "image/png",
                    "image/jpeg",
                    "image/webp"
                }:

                    flash(
                        "PNG/JPG/WEBP seç."
                    )

                else:

                    photo_data = f.read()

                    if len(photo_data) > 2 * 1024 * 1024:

                        flash(
                            "Fotoğraf en fazla 2 MB."
                        )

                    else:

                        c.execute(
                            """
                            UPDATE users
                            SET
                                profile_photo=%s,
                                profile_mime=%s
                            WHERE id=%s
                            """,
                            (
                                photo_data,
                                f.mimetype,
                                u["id"]
                            )
                        )

                        flash(
                            "Fotoğraf güncellendi."
                        )

            # -------------------------------------------------
            # PASSWORD
            # -------------------------------------------------

            else:

                full = c.execute(
                    """
                    SELECT password_hash
                    FROM users
                    WHERE id=%s
                    """,
                    (u["id"],)
                ).fetchone()

                old_password = request.form.get(
                    "old",
                    ""
                )

                new_password = request.form.get(
                    "new",
                    ""
                )

                confirm_password = request.form.get(
                    "confirm",
                    ""
                )

                if (
                    u["role"] == "member"
                    and full
                    and check_password_hash(
                        full["password_hash"],
                        old_password
                    )
                    and new_password == confirm_password
                    and len(new_password) >= 4
                ):

                    c.execute(
                        """
                        UPDATE users
                        SET password_hash=%s
                        WHERE id=%s
                        """,
                        (
                            generate_password_hash(
                                new_password
                            ),
                            u["id"]
                        )
                    )

                    flash(
                        "Şifre değiştirildi."
                    )

                else:

                    flash(
                        "Şifre bilgileri hatalı."
                    )

        return redirect(
            url_for("profile")
        )

    return render_template(
        "profile.html",
        u=u
    )


# =========================================================
# PROFILE PHOTO
# =========================================================

@app.route(
    "/photo/<int:uid>"
)
@login_req
def photo(uid):

    with db() as c:

        x = c.execute(
            """
            SELECT
                profile_photo,
                profile_mime
            FROM users
            WHERE id=%s
            """,
            (uid,)
        ).fetchone()

    if not x or not x["profile_photo"]:
        abort(404)

    return send_file(
        BytesIO(
            bytes(x["profile_photo"])
        ),
        mimetype=x["profile_mime"]
    )


# =========================================================
# NEW PROJECT
# =========================================================

@app.route(
    "/projects/new",
    methods=["GET", "POST"]
)
@login_req
def new_project():

    if request.method == "POST":

        # JavaScript JSON gönderebilir.
        data = request.get_json(
            silent=True
        )

        if data:

            title = (
                data.get("title")
                or "Yeni Proje"
            )

            html_code = (
                data.get("html_code")
                or data.get("html")
                or ""
            )

            python_code = (
                data.get("python_code")
                or data.get("python")
                or ""
            )

        else:

            title = (
                request.form.get(
                    "title"
                )
                or "Yeni Proje"
            )

            html_code = (
                request.form.get(
                    "html",
                    ""
                )
            )

            python_code = (
                request.form.get(
                    "python",
                    ""
                )
            )

        with db() as c:

            c.execute(
                """
                INSERT INTO projects(
                    user_id,
                    title,
                    html_code,
                    python_code
                )
                VALUES(%s,%s,%s,%s)
                """,
                (
                    user()["id"],
                    title,
                    html_code,
                    python_code
                )
            )

        return redirect(
            url_for("home")
        )

    # project.html "project" bekliyor.
    new_project_data = {
        "id": None,
        "title": "Yeni Proje",
        "html_code": "",
        "python_code": ""
    }

    return render_template(
        "project.html",
        project=new_project_data
    )


# =========================================================
# EDIT PROJECT
# =========================================================

@app.route(
    "/projects/<int:pid>",
    methods=["GET", "POST"]
)
@login_req
def edit_project(pid):

    with db() as c:

        p = c.execute(
            """
            SELECT *
            FROM projects
            WHERE id=%s
            """,
            (pid,)
        ).fetchone()

    if not p:
        abort(404)

    if p["user_id"] != user()["id"]:
        abort(403)

    # -----------------------------------------------------
    # SAVE
    # -----------------------------------------------------

    if request.method == "POST":

        data = request.get_json(
            silent=True
        )

        if data:

            title = (
                data.get("title")
                or p["title"]
            )

            html_code = (
                data.get("html_code")
                if "html_code" in data
                else data.get(
                    "html",
                    p["html_code"]
                )
            )

            python_code = (
                data.get("python_code")
                if "python_code" in data
                else data.get(
                    "python",
                    p["python_code"]
                )
            )

        else:

            title = (
                request.form.get(
                    "title"
                )
                or p["title"]
            )

            html_code = request.form.get(
                "html",
                p["html_code"]
            )

            python_code = request.form.get(
                "python",
                p["python_code"]
            )

        with db() as c:

            c.execute(
                """
                UPDATE projects
                SET
                    title=%s,
                    html_code=%s,
                    python_code=%s,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=%s
                """,
                (
                    title,
                    html_code,
                    python_code,
                    pid
                )
            )

        # AJAX JSON isteğine JSON döndür.
        if data is not None:

            return jsonify({
                "success": True,
                "message": "Kod kaydedildi."
            })

        return redirect(
            url_for(
                "edit_project",
                pid=pid
            )
        )

    return render_template(
        "project.html",
        project=p
    )


# =========================================================
# PROJECT PREVIEW
# =========================================================

@app.route(
    "/preview/<int:pid>"
)
@login_req
def preview(pid):

    with db() as c:

        p = c.execute(
            """
            SELECT *
            FROM projects
            WHERE id=%s
            """,
            (pid,)
        ).fetchone()

    if not p:
        abort(404)

    current = user()

    if (
        p["user_id"] != current["id"]
        and current["role"] != "admin"
    ):
        abort(403)

    return render_template(
        "preview.html",
        p=p
    )


# =========================================================
# ATTENDANCE
# =========================================================

@app.route(
    "/attendance",
    methods=["POST"]
)
@login_req
def attendance_mark():

    u = user()

    if u["role"] == "admin":

        flash(
            "Admin için yoklama üye panelinden yönetilir."
        )

        return redirect(
            url_for("admin")
        )

    selected = request.form.get(
        "day",
        ""
    )

    try:

        day = date.fromisoformat(
            selected
        )

    except ValueError:

        abort(400)

    today = turkey_today()

    # Sadece bugün işaretlenebilir.
    if day != today:

        flash(
            "Sadece bugünün yoklaması işaretlenebilir."
        )

        return redirect(
            url_for("home")
        )

    with db() as c:

        c.execute(
            """
            INSERT INTO attendance(
                user_id,
                day,
                present
            )
            VALUES(%s,%s,TRUE)

            ON CONFLICT(user_id,day)
            DO UPDATE SET
                present=EXCLUDED.present
            """,
            (
                u["id"],
                day
            )
        )

    flash(
        "Bugünkü yoklaman işaretlendi. "
        "Yarın 00:00'dan sonra yeni gün aktif olacak."
    )

    return redirect(
        url_for("home")
    )


# =========================================================
# ADMIN
# =========================================================

@app.route("/admin")
@admin_req
def admin():

    with db() as c:

        users = c.execute(
            """
            SELECT
                id,
                username,
                created_at
            FROM users
            WHERE role='member'
            ORDER BY username
            """
        ).fetchall()

        weeks = c.execute(
            """
            SELECT *
            FROM weeks
            ORDER BY id
            """
        ).fetchall()

        projects = c.execute(
            """
            SELECT
                p.*,
                u.username AS owner
            FROM projects p
            JOIN users u
                ON u.id=p.user_id
            ORDER BY p.updated_at DESC
            """
        ).fetchall()

        att = c.execute(
            """
            SELECT
                a.*,
                u.username
            FROM attendance a
            JOIN users u
                ON u.id=a.user_id
            ORDER BY day DESC
            """
        ).fetchall()

    return render_template(
        "admin.html",
        users=users,
        weeks=weeks,
        projects=projects,
        att=att
    )


# =========================================================
# ADMIN - CREATE MEMBER
# =========================================================

@app.route(
    "/admin/member",
    methods=["POST"]
)
@admin_req
def member():

    try:

        username = request.form.get(
            "username",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        if not username or not password:

            flash(
                "Kullanıcı adı ve şifre gerekli."
            )

            return redirect(
                url_for("admin")
            )

        with db() as c:

            c.execute(
                """
                INSERT INTO users(
                    username,
                    password_hash,
                    role
                )
                VALUES(%s,%s,'member')
                """,
                (
                    username,
                    generate_password_hash(
                        password
                    )
                )
            )

        flash(
            "Üye oluşturuldu."
        )

    except psycopg.errors.UniqueViolation:

        flash(
            "Bu kullanıcı zaten var."
        )

    return redirect(
        url_for("admin")
    )


# =========================================================
# ADMIN - RESET PASSWORD
# =========================================================

@app.route(
    "/admin/reset/<int:uid>",
    methods=["POST"]
)
@admin_req
def reset(uid):

    password = request.form.get(
        "password",
        ""
    )

    if not password:

        flash(
            "Yeni şifre boş olamaz."
        )

        return redirect(
            url_for("admin")
        )

    with db() as c:

        c.execute(
            """
            UPDATE users
            SET password_hash=%s
            WHERE id=%s
              AND role='member'
            """,
            (
                generate_password_hash(
                    password
                ),
                uid
            )
        )

    flash(
        "Şifre sıfırlandı."
    )

    return redirect(
        url_for("admin")
    )


# =========================================================
# ADMIN - DELETE MEMBER
# =========================================================

@app.route(
    "/admin/delete/<int:uid>",
    methods=["POST"]
)
@admin_req
def delete(uid):

    with db() as c:

        c.execute(
            """
            DELETE FROM users
            WHERE id=%s
              AND role='member'
            """,
            (uid,)
        )

    return redirect(
        url_for("admin")
    )


# =========================================================
# ADMIN - CREATE WEEK
# =========================================================

@app.route(
    "/admin/week",
    methods=["POST"]
)
@admin_req
def week():

    title = request.form.get(
        "title",
        ""
    ).strip()

    description = request.form.get(
        "description",
        ""
    ).strip()

    if not title:

        flash(
            "Hafta başlığı gerekli."
        )

        return redirect(
            url_for("admin")
        )

    with db() as c:

        c.execute(
            """
            INSERT INTO weeks(
                title,
                description
            )
            VALUES(%s,%s)
            """,
            (
                title,
                description
            )
        )

    return redirect(
        url_for("admin")
    )


# =========================================================
# ADMIN - ATTENDANCE
# =========================================================

@app.route(
    "/admin/att",
    methods=["POST"]
)
@admin_req
def att():

    uid = request.form.get(
        "uid"
    )

    selected_day = request.form.get(
        "day"
    )

    present = (
        request.form.get(
            "present"
        ) == "1"
    )

    if not uid or not selected_day:

        abort(400)

    with db() as c:

        c.execute(
            """
            INSERT INTO attendance(
                user_id,
                day,
                present
            )
            VALUES(%s,%s,%s)

            ON CONFLICT(user_id,day)
            DO UPDATE SET
                present=EXCLUDED.present
            """,
            (
                uid,
                selected_day,
                present
            )
        )

    return redirect(
        url_for("admin")
    )


# =========================================================
# STARTUP
# =========================================================

init_db()


# =========================================================
# LOCAL DEVELOPMENT
# =========================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                5000
            )
        ),
        debug=False
    )
        ),
        debug=False
    )
