from __future__ import annotations

import csv
import io
import json
import secrets
from functools import wraps
from urllib.parse import urlparse

from flask import (
    Blueprint,
    Response,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash

from .db import get_db

bp = Blueprint("main", __name__)


def log_event(event_type: str, details: str) -> None:
    db = get_db()
    db.execute(
        "INSERT INTO audit_log(user_id,event_type,details) VALUES (?,?,?)",
        (session.get("user_id"), event_type, details),
    )
    db.commit()


def refresh_overdue_statuses() -> None:
    db = get_db()
    db.execute(
        """UPDATE assignments
           SET status='overdue'
           WHERE status!='completed'
             AND due_date IS NOT NULL
             AND due_date < date('now')"""
    )
    db.commit()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("main.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("main.login", next=request.path))
        if g.user["role"] != "admin":
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def safe_next(target: str | None) -> str | None:
    if not target:
        return None
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc or not target.startswith("/"):
        return None
    return target


@bp.before_app_request
def load_logged_in_user() -> None:
    user_id = session.get("user_id")
    if user_id is None:
        g.user = None
        return
    g.user = get_db().execute(
        "SELECT * FROM users WHERE id=? AND is_active=1", (user_id,)
    ).fetchone()
    if g.user is None:
        session.clear()


@bp.app_context_processor
def inject_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(24)
    return {"csrf_token": session["csrf_token"]}


@bp.before_app_request
def verify_csrf() -> None:
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        expected = session.get("csrf_token")
        actual = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        if not expected or not actual or not secrets.compare_digest(expected, actual):
            abort(400, description="Некорректный CSRF-токен")


@bp.route("/")
def index():
    if g.user:
        return redirect(url_for("main.dashboard"))
    return render_template("index.html")


@bp.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute(
            "SELECT * FROM users WHERE lower(email)=? AND is_active=1", (email,)
        ).fetchone()
        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Неверный адрес электронной почты или пароль.", "error")
        else:
            session.clear()
            session["user_id"] = user["id"]
            session["csrf_token"] = secrets.token_urlsafe(24)
            log_event("login", f"Вход пользователя {user['email']}")
            return redirect(safe_next(request.args.get("next")) or url_for("main.dashboard"))
    return render_template("login.html")


@bp.route("/logout", methods=("POST",))
@login_required
def logout():
    log_event("logout", "Выход из системы")
    session.clear()
    return redirect(url_for("main.index"))


@bp.route("/dashboard")
@login_required
def dashboard():
    if g.user["role"] == "admin":
        return redirect(url_for("main.admin_dashboard"))

    refresh_overdue_statuses()
    assignments = get_db().execute(
        """
        SELECT a.*, c.title, c.description, c.category, c.estimated_minutes, c.pass_percent,
               (SELECT COUNT(*) FROM modules m WHERE m.course_id=c.id) AS modules_total,
               (SELECT COUNT(*) FROM module_progress mp WHERE mp.assignment_id=a.id) AS modules_done,
               (SELECT MAX(score_percent) FROM attempts t WHERE t.assignment_id=a.id AND t.finished_at IS NOT NULL) AS best_score
        FROM assignments a JOIN courses c ON c.id=a.course_id
        WHERE a.user_id=? AND c.is_active=1
        ORDER BY CASE a.status WHEN 'in_progress' THEN 0 WHEN 'assigned' THEN 1 WHEN 'overdue' THEN 2 ELSE 3 END,
                 a.due_date, c.title
        """,
        (g.user["id"],),
    ).fetchall()
    return render_template("dashboard.html", assignments=assignments)


def get_assignment_or_404(assignment_id: int):
    row = get_db().execute(
        """SELECT a.*, c.title, c.description, c.pass_percent, c.estimated_minutes
           FROM assignments a JOIN courses c ON c.id=a.course_id
           WHERE a.id=?""",
        (assignment_id,),
    ).fetchone()
    if row is None:
        abort(404)
    if g.user["role"] != "admin" and row["user_id"] != g.user["id"]:
        abort(403)
    return row


@bp.route("/training/<int:assignment_id>")
@login_required
def training(assignment_id: int):
    refresh_overdue_statuses()
    assignment = get_assignment_or_404(assignment_id)
    db = get_db()
    modules = db.execute(
        """
        SELECT m.*, CASE WHEN mp.id IS NULL THEN 0 ELSE 1 END AS completed
        FROM modules m
        LEFT JOIN module_progress mp ON mp.module_id=m.id AND mp.assignment_id=?
        WHERE m.course_id=?
        ORDER BY m.sort_order, m.id
        """,
        (assignment_id, assignment["course_id"]),
    ).fetchall()
    attempts = db.execute(
        "SELECT * FROM attempts WHERE assignment_id=? AND finished_at IS NOT NULL ORDER BY id DESC LIMIT 5",
        (assignment_id,),
    ).fetchall()
    return render_template("training.html", assignment=assignment, modules=modules, attempts=attempts)


@bp.route("/training/<int:assignment_id>/module/<int:module_id>/complete", methods=("POST",))
@login_required
def complete_module(assignment_id: int, module_id: int):
    assignment = get_assignment_or_404(assignment_id)
    db = get_db()
    module = db.execute(
        "SELECT id FROM modules WHERE id=? AND course_id=?",
        (module_id, assignment["course_id"]),
    ).fetchone()
    if module is None:
        abort(404)
    db.execute(
        "INSERT OR IGNORE INTO module_progress(assignment_id,module_id) VALUES (?,?)",
        (assignment_id, module_id),
    )
    db.execute(
        """UPDATE assignments
           SET status=CASE WHEN status IN ('completed','overdue') THEN status ELSE 'in_progress' END
           WHERE id=?""",
        (assignment_id,),
    )
    db.commit()
    log_event("module_completed", f"assignment={assignment_id}; module={module_id}")
    flash("Раздел отмечен как изученный.", "success")
    return redirect(url_for("main.training", assignment_id=assignment_id) + f"#module-{module_id}")


@bp.route("/test/<int:assignment_id>", methods=("GET", "POST"))
@login_required
def take_test(assignment_id: int):
    refresh_overdue_statuses()
    assignment = get_assignment_or_404(assignment_id)
    db = get_db()
    module_counts = db.execute(
        """SELECT (SELECT COUNT(*) FROM modules WHERE course_id=?) AS total,
                  (SELECT COUNT(*) FROM module_progress WHERE assignment_id=?) AS done""",
        (assignment["course_id"], assignment_id),
    ).fetchone()
    if module_counts["done"] < module_counts["total"]:
        flash("Перед итоговым тестированием необходимо изучить все разделы курса.", "error")
        return redirect(url_for("main.training", assignment_id=assignment_id))

    questions = db.execute(
        "SELECT * FROM questions WHERE course_id=? ORDER BY id",
        (assignment["course_id"],),
    ).fetchall()
    if not questions:
        abort(400, description="Для курса не настроены вопросы")

    if request.method == "GET":
        return render_template("test.html", assignment=assignment, questions=questions)

    correct = 0
    detailed = []
    for question in questions:
        answer = request.form.get(f"q_{question['id']}")
        is_correct = answer == question["correct_option"]
        correct += int(is_correct)
        detailed.append(
            {
                "question_id": question["id"],
                "answer": answer,
                "correct": question["correct_option"],
                "is_correct": is_correct,
            }
        )

    score = round(correct * 100 / len(questions))
    passed = score >= assignment["pass_percent"]
    db.execute(
        """INSERT INTO attempts(assignment_id,finished_at,score_percent,passed,answers_json)
           VALUES (?,CURRENT_TIMESTAMP,?,?,?)""",
        (assignment_id, score, int(passed), json.dumps(detailed, ensure_ascii=False)),
    )
    if passed:
        db.execute("UPDATE assignments SET status='completed' WHERE id=?", (assignment_id,))
    else:
        db.execute("UPDATE assignments SET status='in_progress' WHERE id=?", (assignment_id,))
    db.commit()
    refresh_overdue_statuses()
    log_event("test_finished", f"assignment={assignment_id}; score={score}; passed={passed}")
    return render_template(
        "test_result.html",
        assignment=assignment,
        score=score,
        passed=passed,
        questions=questions,
        detailed=detailed,
    )


@bp.route("/admin")
@admin_required
def admin_dashboard():
    refresh_overdue_statuses()
    db = get_db()
    stats = db.execute(
        """
        SELECT
          (SELECT COUNT(*) FROM users WHERE role='employee' AND is_active=1) AS employees,
          (SELECT COUNT(*) FROM assignments) AS assignments,
          (SELECT COUNT(*) FROM assignments WHERE status='completed') AS completed,
          (SELECT COUNT(*) FROM assignments WHERE status='overdue') AS overdue
        """
    ).fetchone()
    latest = db.execute(
        """SELECT a.id, u.full_name, c.title, a.status, a.due_date,
                  (SELECT MAX(score_percent) FROM attempts t WHERE t.assignment_id=a.id) AS best_score
           FROM assignments a
           JOIN users u ON u.id=a.user_id
           JOIN courses c ON c.id=a.course_id
           ORDER BY a.id DESC LIMIT 12"""
    ).fetchall()
    return render_template("admin_dashboard.html", stats=stats, latest=latest)


@bp.route("/admin/assignments", methods=("GET", "POST"))
@admin_required
def admin_assignments():
    refresh_overdue_statuses()
    db = get_db()
    if request.method == "POST":
        user_id = request.form.get("user_id", type=int)
        course_id = request.form.get("course_id", type=int)
        due_date = request.form.get("due_date") or None
        if not user_id or not course_id:
            flash("Выберите сотрудника и курс.", "error")
        else:
            try:
                db.execute(
                    "INSERT INTO assignments(user_id,course_id,due_date) VALUES (?,?,?)",
                    (user_id, course_id, due_date),
                )
                db.commit()
                log_event("assignment_created", f"user={user_id}; course={course_id}; due={due_date}")
                flash("Обучение назначено сотруднику.", "success")
            except Exception as exc:
                if "UNIQUE constraint failed" in str(exc):
                    flash("Этот курс уже назначен выбранному сотруднику.", "error")
                else:
                    raise

    employees = db.execute(
        "SELECT * FROM users WHERE role='employee' AND is_active=1 ORDER BY full_name"
    ).fetchall()
    courses = db.execute("SELECT * FROM courses WHERE is_active=1 ORDER BY title").fetchall()
    assignments = db.execute(
        """SELECT a.*,u.full_name,u.department,c.title,
                  (SELECT MAX(score_percent) FROM attempts t WHERE t.assignment_id=a.id) AS best_score
           FROM assignments a
           JOIN users u ON u.id=a.user_id
           JOIN courses c ON c.id=a.course_id
           ORDER BY a.id DESC"""
    ).fetchall()
    return render_template(
        "admin_assignments.html",
        employees=employees,
        courses=courses,
        assignments=assignments,
    )


@bp.route("/admin/report")
@admin_required
def admin_report():
    refresh_overdue_statuses()
    rows = get_db().execute(
        """SELECT u.full_name,u.department,u.position,c.title,a.status,a.due_date,
                  (SELECT MAX(score_percent) FROM attempts t WHERE t.assignment_id=a.id) AS best_score,
                  (SELECT COUNT(*) FROM attempts t WHERE t.assignment_id=a.id AND t.finished_at IS NOT NULL) AS attempts
           FROM assignments a
           JOIN users u ON u.id=a.user_id
           JOIN courses c ON c.id=a.course_id
           ORDER BY u.full_name,c.title"""
    ).fetchall()
    return render_template("admin_report.html", rows=rows)


@bp.route("/admin/report.csv")
@admin_required
def admin_report_csv():
    refresh_overdue_statuses()
    rows = get_db().execute(
        """SELECT u.full_name,u.department,u.position,c.title,a.status,a.due_date,
                  (SELECT MAX(score_percent) FROM attempts t WHERE t.assignment_id=a.id) AS best_score,
                  (SELECT COUNT(*) FROM attempts t WHERE t.assignment_id=a.id AND t.finished_at IS NOT NULL) AS attempts
           FROM assignments a
           JOIN users u ON u.id=a.user_id
           JOIN courses c ON c.id=a.course_id
           ORDER BY u.full_name,c.title"""
    ).fetchall()
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(
        [
            "Сотрудник",
            "Подразделение",
            "Должность",
            "Курс",
            "Статус",
            "Срок",
            "Лучший результат, %",
            "Попыток",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row["full_name"],
                row["department"],
                row["position"],
                row["title"],
                row["status"],
                row["due_date"] or "",
                row["best_score"] if row["best_score"] is not None else "",
                row["attempts"],
            ]
        )
    data = "\ufeff" + output.getvalue()
    return Response(
        data,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=training_report.csv"},
    )


@bp.route("/about")
def about():
    return render_template("about.html")


@bp.app_errorhandler(403)
def forbidden(_e):
    return render_template(
        "error.html", code=403, message="Недостаточно прав для просмотра раздела."
    ), 403


@bp.app_errorhandler(404)
def not_found(_e):
    return render_template(
        "error.html", code=404, message="Запрашиваемая страница не найдена."
    ), 404


@bp.app_errorhandler(400)
def bad_request(e):
    return render_template(
        "error.html",
        code=400,
        message=getattr(e, "description", "Некорректный запрос."),
    ), 400
