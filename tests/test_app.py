from pathlib import Path

import pytest

from app import create_app
from app.db import get_db


@pytest.fixture()
def app(tmp_path: Path):
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test-secret",
        "DATABASE_PATH": str(tmp_path / "test.db"),
    })
    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


def csrf_from_session(client):
    with client.session_transaction() as sess:
        return sess["csrf_token"]


def login(client, email, password):
    client.get("/login")
    return client.post("/login", data={"email": email, "password": password, "csrf_token": csrf_from_session(client)}, follow_redirects=True)


def test_employee_can_log_in_and_see_assignments(client):
    response = login(client, "employee@example.ru", "Employee123!")
    assert response.status_code == 200
    assert "Мое обучение" in response.get_data(as_text=True)
    assert "Вводный инструктаж" in response.get_data(as_text=True)


def test_employee_cannot_open_admin(client):
    login(client, "employee@example.ru", "Employee123!")
    response = client.get("/admin")
    assert response.status_code == 403


def test_test_is_locked_before_modules_completed(client, app):
    login(client, "employee@example.ru", "Employee123!")
    with app.app_context():
        aid = get_db().execute("SELECT id FROM assignments ORDER BY id LIMIT 1").fetchone()[0]
    response = client.get(f"/test/{aid}", follow_redirects=True)
    assert "необходимо изучить все разделы" in response.get_data(as_text=True)


def test_employee_can_complete_training_and_pass(client, app):
    login(client, "employee@example.ru", "Employee123!")
    with app.app_context():
        db = get_db()
        assignment = db.execute("SELECT * FROM assignments ORDER BY id LIMIT 1").fetchone()
        modules = db.execute("SELECT id FROM modules WHERE course_id=?", (assignment["course_id"],)).fetchall()
        questions = db.execute("SELECT * FROM questions WHERE course_id=?", (assignment["course_id"],)).fetchall()
    for module in modules:
        client.post(f"/training/{assignment['id']}/module/{module['id']}/complete", data={"csrf_token": csrf_from_session(client)}, follow_redirects=True)
    answers = {f"q_{q['id']}": q["correct_option"] for q in questions}
    answers["csrf_token"] = csrf_from_session(client)
    response = client.post(f"/test/{assignment['id']}", data=answers, follow_redirects=True)
    text = response.get_data(as_text=True)
    assert "100%" in text
    assert "Тестирование пройдено" in text
    with app.app_context():
        status = get_db().execute("SELECT status FROM assignments WHERE id=?", (assignment["id"],)).fetchone()[0]
        assert status == "completed"


def test_admin_can_export_report(client):
    login(client, "admin@example.ru", "Admin123!")
    response = client.get("/admin/report.csv")
    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("text/csv")
    assert "Сотрудник" in response.get_data(as_text=True)
