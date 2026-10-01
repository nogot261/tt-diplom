from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import click
from flask import current_app, g
from werkzeug.security import generate_password_hash

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('employee', 'admin')),
    department TEXT NOT NULL,
    position TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    category TEXT NOT NULL,
    estimated_minutes INTEGER NOT NULL,
    pass_percent INTEGER NOT NULL DEFAULT 80,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS modules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    sort_order INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    option_a TEXT NOT NULL,
    option_b TEXT NOT NULL,
    option_c TEXT NOT NULL,
    option_d TEXT NOT NULL,
    correct_option TEXT NOT NULL CHECK(correct_option IN ('A','B','C','D')),
    explanation TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    assigned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    due_date TEXT,
    status TEXT NOT NULL DEFAULT 'assigned' CHECK(status IN ('assigned','in_progress','completed','overdue')),
    UNIQUE(user_id, course_id)
);

CREATE TABLE IF NOT EXISTS module_progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assignment_id INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
    module_id INTEGER NOT NULL REFERENCES modules(id) ON DELETE CASCADE,
    completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(assignment_id, module_id)
);

CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assignment_id INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    score_percent INTEGER,
    passed INTEGER,
    answers_json TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    details TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE_PATH"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_e=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def seed_data(db: sqlite3.Connection) -> None:
    if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        users = [
            (
                "Тюркина Анастасия Валентиновна",
                "admin@example.ru",
                generate_password_hash("Admin123!"),
                "admin",
                "Отдел охраны труда",
                "Администратор системы",
            ),
            (
                "Иванов Сергей Петрович",
                "employee@example.ru",
                generate_password_hash("Employee123!"),
                "employee",
                "Производственный отдел",
                "Специалист",
            ),
            (
                "Петрова Ольга Андреевна",
                "petrova@example.ru",
                generate_password_hash("Employee123!"),
                "employee",
                "Бухгалтерия",
                "Бухгалтер",
            ),
        ]
        db.executemany(
            "INSERT INTO users(full_name,email,password_hash,role,department,position) VALUES (?,?,?,?,?,?)",
            users,
        )

    if db.execute("SELECT COUNT(*) FROM courses").fetchone()[0] == 0:
        course_rows = [
            (
                "Вводный инструктаж по охране труда",
                "Базовые правила безопасного поведения, порядок действий при опасной ситуации и ответственность работников.",
                "Общий инструктаж",
                35,
                80,
            ),
            (
                "Пожарная безопасность",
                "Действия при обнаружении возгорания, эвакуация и применение первичных средств пожаротушения.",
                "Пожарная безопасность",
                25,
                80,
            ),
            (
                "Первая помощь пострадавшим",
                "Алгоритм первичной оценки состояния пострадавшего и безопасная последовательность оказания первой помощи.",
                "Первая помощь",
                40,
                80,
            ),
        ]
        db.executemany(
            "INSERT INTO courses(title,description,category,estimated_minutes,pass_percent) VALUES (?,?,?,?,?)",
            course_rows,
        )

        courses = {r["title"]: r["id"] for r in db.execute("SELECT id,title FROM courses")}
        modules = [
            (courses["Вводный инструктаж по охране труда"], "Цели и обязанности", "Охрана труда включает систему организационных, правовых и технических мер, направленных на сохранение жизни и здоровья работников. Работник обязан соблюдать установленные требования, применять выданные средства защиты и сообщать руководителю об опасностях и происшествиях.", 1),
            (courses["Вводный инструктаж по охране труда"], "Опасные и вредные факторы", "Перед началом работы необходимо оценить рабочее место, убрать препятствия, проверить исправность оборудования и убедиться в наличии необходимых средств защиты. При возникновении неисправности работу прекращают и сообщают ответственному лицу.", 2),
            (courses["Вводный инструктаж по охране труда"], "Действия при аварии", "При аварийной ситуации необходимо прекратить работу, по возможности безопасно отключить оборудование, предупредить окружающих, покинуть опасную зону и сообщить руководителю либо ответственному специалисту.", 3),
            (courses["Пожарная безопасность"], "Профилактика пожара", "Не допускается загромождать эвакуационные выходы, использовать поврежденные электроприборы и оставлять источники повышенной пожарной опасности без контроля.", 1),
            (courses["Пожарная безопасность"], "Действия при обнаружении пожара", "При обнаружении признаков пожара следует сообщить по номеру 112, оповестить людей, начать эвакуацию и при отсутствии угрозы жизни использовать подходящее первичное средство пожаротушения.", 2),
            (courses["Пожарная безопасность"], "Эвакуация", "Эвакуация проводится по обозначенным маршрутам к безопасному выходу. Лифтом при пожаре не пользуются. После выхода нельзя возвращаться в опасную зону без разрешения ответственных служб.", 3),
            (courses["Первая помощь пострадавшим"], "Безопасность места происшествия", "Перед оказанием помощи оценивают безопасность для себя, пострадавшего и окружающих. Нельзя подвергать себя дополнительному риску.", 1),
            (courses["Первая помощь пострадавшим"], "Оценка состояния", "Проверяют сознание и дыхание, вызывают экстренные службы и при необходимости привлекают помощников. Информация диспетчеру должна быть краткой и точной.", 2),
            (courses["Первая помощь пострадавшим"], "Поддержание жизни до прибытия помощи", "В пределах своей подготовки работник выполняет доступные действия первой помощи, наблюдает за состоянием пострадавшего и выполняет указания диспетчера экстренной службы.", 3),
        ]
        db.executemany(
            "INSERT INTO modules(course_id,title,body,sort_order) VALUES (?,?,?,?)",
            modules,
        )

        q = []
        def add(course_title, text, options, correct, explanation):
            q.append((courses[course_title], text, *options, correct, explanation))

        add("Вводный инструктаж по охране труда", "Что следует сделать при обнаружении неисправности оборудования?", ("Продолжить работу до конца смены", "Самостоятельно разобрать оборудование", "Прекратить работу и сообщить ответственному лицу", "Игнорировать неисправность"), "C", "Неисправное оборудование нельзя продолжать использовать до устранения опасности.")
        add("Вводный инструктаж по охране труда", "Кто обязан соблюдать требования охраны труда на рабочем месте?", ("Только руководитель", "Каждый работник", "Только специалист по охране труда", "Только сотрудники производства"), "B", "Обязанность соблюдать требования относится к каждому работнику.")
        add("Вводный инструктаж по охране труда", "Какой первый принцип поведения при аварийной ситуации?", ("Скрыть происшествие", "Продолжать работу", "Прекратить опасную работу и предупредить людей", "Самостоятельно покинуть территорию, никого не уведомляя"), "C", "Нужно остановить опасное действие, предупредить окружающих и сообщить ответственным лицам.")
        add("Вводный инструктаж по охране труда", "Для чего применяются средства индивидуальной защиты?", ("Для формального соблюдения документации", "Для снижения воздействия опасных факторов", "Для ускорения работы", "Только при проверке"), "B", "СИЗ снижают воздействие опасных и вредных производственных факторов.")
        add("Пожарная безопасность", "Какой номер экстренных служб используется в России?", ("1010", "112", "911", "000"), "B", "Единый номер вызова экстренных оперативных служб - 112.")
        add("Пожарная безопасность", "Можно ли пользоваться лифтом при эвакуации во время пожара?", ("Да, всегда", "Да, если он свободен", "Нет", "Только сотрудникам"), "C", "Во время пожара для эвакуации используют безопасные лестничные пути и выходы.")
        add("Пожарная безопасность", "Что нельзя делать с эвакуационными выходами?", ("Обозначать", "Освещать", "Загромождать", "Проверять"), "C", "Эвакуационные пути и выходы должны оставаться свободными.")
        add("Пожарная безопасность", "Когда допустимо применять огнетушитель?", ("При отсутствии угрозы собственной жизни и при подходящем типе очага", "В любом случае", "Только после полного выгорания помещения", "Никогда"), "A", "Первичное тушение допустимо только при сохранении личной безопасности.")
        add("Первая помощь пострадавшим", "Что проверяют до непосредственного контакта с пострадавшим?", ("Только документы", "Безопасность места происшествия", "Только температуру воздуха", "Рабочий график"), "B", "Помогающий не должен становиться вторым пострадавшим.")
        add("Первая помощь пострадавшим", "Что важно сообщить диспетчеру экстренной службы?", ("Только свою должность", "Место, что произошло и состояние пострадавшего", "Только фамилию руководителя", "Ничего, достаточно звонка"), "B", "Для организации помощи нужны место события, характер происшествия и состояние пострадавшего.")
        add("Первая помощь пострадавшим", "После вызова экстренной помощи следует:", ("Оставить пострадавшего одного", "Продолжать безопасные действия в пределах подготовки и наблюдать за состоянием", "Удалить записи о происшествии", "Переместить пострадавшего без необходимости"), "B", "До прибытия специалистов оказывают доступную помощь и контролируют состояние.")
        add("Первая помощь пострадавшим", "Ключевой принцип первой помощи:", ("Действовать быстро любой ценой", "Не подвергать дополнительному риску себя и пострадавшего", "Всегда перемещать пострадавшего", "Не вызывать экстренные службы"), "B", "Безопасность является первым условием оказания помощи.")
        db.executemany(
            """INSERT INTO questions(course_id,text,option_a,option_b,option_c,option_d,correct_option,explanation)
               VALUES (?,?,?,?,?,?,?,?)""",
            q,
        )

    # assignments are idempotently added after courses/users exist
    user_id = db.execute("SELECT id FROM users WHERE email='employee@example.ru'").fetchone()[0]
    petrova_id = db.execute("SELECT id FROM users WHERE email='petrova@example.ru'").fetchone()[0]
    rows = db.execute("SELECT id,title FROM courses ORDER BY id").fetchall()
    due = (date.today() + timedelta(days=14)).isoformat()
    for row in rows:
        db.execute(
            "INSERT OR IGNORE INTO assignments(user_id,course_id,due_date) VALUES (?,?,?)",
            (user_id, row["id"], due),
        )
    if rows:
        db.execute(
            "INSERT OR IGNORE INTO assignments(user_id,course_id,due_date) VALUES (?,?,?)",
            (petrova_id, rows[0]["id"], (date.today() + timedelta(days=7)).isoformat()),
        )

    # Демонстрационное состояние помогает показать основные сценарии сразу
    # после первого запуска: назначенный, выполняемый, завершенный и просроченный курс.
    if len(rows) >= 3:
        intro_id, fire_id, first_aid_id = rows[0]["id"], rows[1]["id"], rows[2]["id"]
        employee_fire = db.execute(
            "SELECT id FROM assignments WHERE user_id=? AND course_id=?",
            (user_id, fire_id),
        ).fetchone()[0]
        employee_first_aid = db.execute(
            "SELECT id FROM assignments WHERE user_id=? AND course_id=?",
            (user_id, first_aid_id),
        ).fetchone()[0]
        petrova_intro = db.execute(
            "SELECT id FROM assignments WHERE user_id=? AND course_id=?",
            (petrova_id, intro_id),
        ).fetchone()[0]

        first_fire_module = db.execute(
            "SELECT id FROM modules WHERE course_id=? ORDER BY sort_order,id LIMIT 1",
            (fire_id,),
        ).fetchone()[0]
        db.execute(
            "INSERT OR IGNORE INTO module_progress(assignment_id,module_id) VALUES (?,?)",
            (employee_fire, first_fire_module),
        )
        db.execute("UPDATE assignments SET status='in_progress' WHERE id=?", (employee_fire,))

        intro_modules = db.execute(
            "SELECT id FROM modules WHERE course_id=? ORDER BY sort_order,id",
            (intro_id,),
        ).fetchall()
        for module in intro_modules:
            db.execute(
                "INSERT OR IGNORE INTO module_progress(assignment_id,module_id) VALUES (?,?)",
                (petrova_intro, module["id"]),
            )
        if db.execute(
            "SELECT COUNT(*) FROM attempts WHERE assignment_id=?", (petrova_intro,)
        ).fetchone()[0] == 0:
            db.execute(
                """INSERT INTO attempts(assignment_id,finished_at,score_percent,passed,answers_json)
                   VALUES (?,CURRENT_TIMESTAMP,100,1,'[]')""",
                (petrova_intro,),
            )
        db.execute("UPDATE assignments SET status='completed' WHERE id=?", (petrova_intro,))

        db.execute(
            "UPDATE assignments SET due_date=?, status='assigned' WHERE id=?",
            ((date.today() - timedelta(days=2)).isoformat(), employee_first_aid),
        )


def init_db(seed: bool = False) -> None:
    db = get_db()
    db.executescript(SCHEMA)
    if seed:
        seed_data(db)
    db.commit()


@click.command("init-db")
def init_db_command() -> None:
    init_db(seed=True)
    click.echo("База данных инициализирована.")


def init_app(app) -> None:
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
