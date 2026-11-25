"""soutenance-app — grades that only let the jury pick the good ones."""
import hmac
import logging
import os
import re
import socket
from datetime import datetime, timezone

import psycopg
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)
app.logger.setLevel(logging.INFO)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024

GRADE_MAX = 20
FLEE_MODES = ('flee', 'vanish', 'shrink', 'chaos')
INSTANCE = socket.gethostname()
STARTED_AT = datetime.now(timezone.utc)

SCHEMA = (
    'CREATE TABLE IF NOT EXISTS visits '
    '(id BIGSERIAL PRIMARY KEY, '
    'created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP)',
    'CREATE TABLE IF NOT EXISTS grades '
    '(id BIGSERIAL PRIMARY KEY, '
    f'grade SMALLINT NOT NULL CHECK (grade BETWEEN 0 AND {GRADE_MAX}), '
    'juror TEXT NOT NULL, comment TEXT NOT NULL, instance TEXT NOT NULL, '
    'created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)',
    'CREATE TABLE IF NOT EXISTS escapes '
    '(grade SMALLINT PRIMARY KEY, total BIGINT NOT NULL)',
)


def integer_setting(name, default, minimum, maximum):
    """Read an integer variable; fall back to the default and stay in bounds."""
    try:
        value = int(os.environ.get(name, '').strip())
    except ValueError:
        return default
    return min(max(value, minimum), maximum)


def settings():
    """Application variables. None of them is required."""
    mode = os.environ.get('FLEE_MODE', '').strip().lower()
    color = os.environ.get('ACCENT_COLOR', '').strip()
    return {
        'title': os.environ.get('APP_TITLE', '').strip() or 'Soutenance SIGL',
        'team': os.environ.get('TEAM_NAME', '').strip() or 'Notre équipe',
        'threshold': integer_setting('GRADE_THRESHOLD', 16, 0, GRADE_MAX),
        'flee_mode': mode if mode in FLEE_MODES else 'flee',
        'flee_radius': integer_setting('FLEE_RADIUS', 130, 60, 300),
        'accent': color if re.fullmatch(r'#[0-9a-fA-F]{6}', color) else '#6d5efc',
    }


def jury_code():
    """Secret: only ever compared, never sent to the browser."""
    return os.environ.get('JURY_CODE', '')


def db_connect(timeout=10):
    options = {}
    if os.environ.get('DB_SSLMODE'):
        options['sslmode'] = os.environ['DB_SSLMODE']
    return psycopg.connect(
        host=os.environ['DB_HOST'], port=os.environ.get('DB_PORT', '5432'),
        dbname=os.environ['DB_NAME'], user=os.environ['DB_USER'],
        password=os.environ['DB_PASSWORD'], connect_timeout=timeout,
        **options,
    )


def ensure_schema(connection):
    if app.config.get('SCHEMA_READY'):
        return
    # Several replicas can start together: only one creates the tables at a time.
    connection.execute("SELECT pg_advisory_xact_lock(hashtext('soutenance-app'))")
    for statement in SCHEMA:
        connection.execute(statement)
    connection.commit()
    app.config['SCHEMA_READY'] = True


def error(message, status):
    return jsonify(error=message), status


@app.errorhandler(psycopg.Error)
def database_error(exception):
    app.logger.error('database error: %s', type(exception).__name__)
    return error('Base de données indisponible.', 503)


@app.get('/healthz')
def health():
    return jsonify(status='ok')


@app.get('/health')
def readiness():
    """Require a writable PostgreSQL primary for private cloud readiness."""
    required = ('DB_HOST', 'DB_NAME', 'DB_USER', 'DB_PASSWORD')
    if any(not os.environ.get(name, '').strip() for name in required):
        return jsonify(status='unavailable',
                       reason='database configuration missing'), 503
    try:
        with db_connect(timeout=3) as connection:
            writable = (connection.execute('SHOW transaction_read_only')
                        .fetchone()[0] == 'off')
    except (psycopg.Error, ValueError):
        return jsonify(status='unavailable',
                       reason='database connection failed'), 503
    if not writable:
        return jsonify(status='unavailable',
                       reason='database is read-only'), 503
    return jsonify(status='ok')


@app.get('/')
def index():
    # The page renders without the database, so the grades can always flee.
    return render_template('index.html', config=settings(), grade_max=GRADE_MAX,
                           code_required=bool(jury_code()))


@app.post('/api/visits')
def record_visit():
    with db_connect() as connection:
        ensure_schema(connection)
        connection.execute('INSERT INTO visits DEFAULT VALUES')
    return '', 204


@app.get('/api/state')
def state():
    with db_connect() as connection:
        ensure_schema(connection)
        visits = connection.execute('SELECT COUNT(*) FROM visits').fetchone()[0]
        total, average, before_start, first = connection.execute(
            'SELECT COUNT(*), AVG(grade), '
            'COUNT(*) FILTER (WHERE created_at < %s), MIN(created_at) '
            'FROM grades', (STARTED_AT,)
        ).fetchone()
        history = connection.execute(
            'SELECT id, grade, juror, comment, instance, created_at '
            'FROM grades ORDER BY id DESC LIMIT 20'
        ).fetchall()
        escapes = connection.execute(
            'SELECT grade, total FROM escapes ORDER BY total DESC, grade'
        ).fetchall()
    return jsonify(
        visits=visits,
        grades={
            'total': total,
            'average': None if average is None else round(float(average), 2),
            'before_start': before_start,
            'first_at': None if first is None else first.isoformat(),
            'history': [
                {'id': row[0], 'grade': row[1], 'juror': row[2], 'comment': row[3],
                 'instance': row[4], 'created_at': row[5].isoformat()}
                for row in history
            ],
        },
        escapes=[{'grade': grade, 'total': count} for grade, count in escapes],
        instance={'name': INSTANCE, 'started_at': STARTED_AT.isoformat()},
    )


@app.post('/api/grades')
def add_grade():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return error('Requête JSON attendue.', 400)
    grade = body.get('grade')
    juror = body.get('juror')
    comment = body.get('comment', '')
    code = body.get('code', '')
    if type(grade) is not int or not 0 <= grade <= GRADE_MAX:
        return error('Note invalide.', 400)
    if not all(isinstance(value, str) and '\x00' not in value
               for value in (juror, comment, code)):
        return error('Champs invalides.', 400)
    juror, comment = juror.strip(), comment.strip()
    if not 1 <= len(juror) <= 60 or len(comment) > 280:
        return error('Nom requis (60 caractères max), commentaire de 280 max.', 400)
    # Enforced here too: calling the API directly does not get around the buttons.
    if grade < settings()['threshold']:
        return error('Bien essayé, mais cette note est intouchable.', 403)
    expected = jury_code()
    if expected and not hmac.compare_digest(code.encode('utf-8', 'replace'),
                                            expected.encode('utf-8', 'replace')):
        return error('Code jury incorrect.', 401)
    with db_connect() as connection:
        ensure_schema(connection)
        connection.execute(
            'INSERT INTO grades (grade, juror, comment, instance) '
            'VALUES (%s, %s, %s, %s)', (grade, juror, comment, INSTANCE)
        )
    # Logged once the transaction is committed. No name or comment in the logs.
    app.logger.info('LOG/ note inscrite : %d/%d', grade, GRADE_MAX)
    return jsonify(status='saved'), 201


@app.post('/api/escapes')
def add_escapes():
    body = request.get_json(silent=True)
    counts = body.get('counts') if isinstance(body, dict) else None
    if not isinstance(counts, dict) or not 1 <= len(counts) <= GRADE_MAX + 1:
        return error('Compteurs invalides.', 400)
    threshold = settings()['threshold']
    allowed = {str(grade): grade for grade in range(threshold)}
    if any(key not in allowed or type(count) is not int or not 1 <= count <= 1000
           for key, count in counts.items()):
        return error('Compteurs invalides.', 400)
    with db_connect() as connection:
        ensure_schema(connection)
        # Sorted so concurrent requests lock the rows in the same order.
        for grade, count in sorted((allowed[key], n) for key, n in counts.items()):
            connection.execute(
                'INSERT INTO escapes (grade, total) VALUES (%s, %s) '
                'ON CONFLICT (grade) DO UPDATE '
                'SET total = escapes.total + EXCLUDED.total', (grade, count)
            )
    return '', 204


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '8080')))
