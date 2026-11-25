from unittest.mock import MagicMock, patch

import pytest

from app import app, settings

APPLICATION_VARIABLES = ('APP_TITLE', 'TEAM_NAME', 'GRADE_THRESHOLD', 'FLEE_MODE',
                         'FLEE_RADIUS', 'ACCENT_COLOR', 'JURY_CODE', 'DB_SSLMODE')


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    for key in APPLICATION_VARIABLES:
        monkeypatch.delenv(key, raising=False)
    for key, value in {'DB_HOST': 'database', 'DB_NAME': 'demo',
                       'DB_USER': 'user', 'DB_PASSWORD': 'secret'}.items():
        monkeypatch.setenv(key, value)
    app.config['SCHEMA_READY'] = True


@pytest.fixture
def database():
    connection = MagicMock()
    with patch('app.psycopg.connect') as connect:
        connect.return_value.__enter__.return_value = connection
        connection.connect = connect
        yield connection


def post_grade(**changes):
    body = {'grade': 18, 'juror': 'Mme Martin', 'comment': 'Bravo', **changes}
    return app.test_client().post('/api/grades', json=body)


def test_health_does_not_require_database():
    assert app.test_client().get('/healthz').json == {'status': 'ok'}


def test_readiness_requires_writable_database(database):
    database.execute.return_value.fetchone.return_value = ('off',)
    assert app.test_client().get('/health').status_code == 200
    database.execute.return_value.fetchone.return_value = ('on',)
    assert app.test_client().get('/health').status_code == 503
    database.execute.assert_called_with('SHOW transaction_read_only')


def test_readiness_reports_missing_database_configuration(monkeypatch):
    monkeypatch.delenv('DB_HOST')
    assert app.test_client().get('/health').status_code == 503


def test_database_uses_platform_configuration(database):
    assert app.test_client().post('/api/visits').status_code == 204
    database.connect.assert_called_once_with(
        host='database', port='5432', dbname='demo',
        user='user', password='secret', connect_timeout=10,
    )


def test_page_applies_variables_without_leaking_the_secret(monkeypatch):
    monkeypatch.setenv('APP_TITLE', 'Grand oral')
    monkeypatch.setenv('GRADE_THRESHOLD', '18')
    monkeypatch.setenv('JURY_CODE', 'very-private-code')
    page = app.test_client().get('/').get_data(as_text=True)
    assert 'Grand oral' in page
    assert 'data-threshold="18"' in page
    assert 'very-private-code' not in page


def test_invalid_variables_fall_back_to_safe_values(monkeypatch):
    monkeypatch.setenv('GRADE_THRESHOLD', 'abc')
    monkeypatch.setenv('FLEE_RADIUS', '9999')
    monkeypatch.setenv('FLEE_MODE', 'teleport')
    monkeypatch.setenv('ACCENT_COLOR', 'red; background: url(x)')
    values = settings()
    assert values['threshold'] == 16
    assert values['flee_radius'] == 300
    assert values['flee_mode'] == 'flee'
    assert values['accent'] == '#6d5efc'


def test_good_grade_is_saved(database, caplog):
    assert post_grade().status_code == 201
    assert 'LOG/ note inscrite : 18/20' in caplog.messages
    assert database.execute.call_args.args[1][:3] == (18, 'Mme Martin', 'Bravo')


def test_low_grade_is_refused_by_the_server(database):
    assert post_grade(grade=4).status_code == 403
    database.connect.assert_not_called()


@pytest.mark.parametrize('changes', [
    {'grade': '18'}, {'grade': 21}, {'grade': True}, {'juror': '  '},
    {'juror': 'a' * 61}, {'comment': 'a' * 281}, {'comment': 'a\x00'},
])
def test_malformed_grade_is_refused(database, changes):
    assert post_grade(**changes).status_code == 400
    database.connect.assert_not_called()


def test_jury_code_is_enforced_when_defined(database, monkeypatch):
    monkeypatch.setenv('JURY_CODE', 'sésame')
    assert post_grade().status_code == 401
    assert post_grade(code='faux').status_code == 401
    database.connect.assert_not_called()
    assert post_grade(code='sésame').status_code == 201


def test_escapes_are_only_counted_for_low_grades(database):
    client = app.test_client()
    assert client.post('/api/escapes', json={'counts': {'3': 2}}).status_code == 204
    for counts in ({'18': 1}, {'3': 0}, {'3': 1001}, {'x': 1}, {}):
        assert client.post('/api/escapes', json={'counts': counts}).status_code == 400
