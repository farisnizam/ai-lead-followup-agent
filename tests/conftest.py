import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.agent.client import get_agent_client
from app.config import settings
from app.db import Base, get_db
from app.main import app
from tests.fakes import always_fails

TEST_DB_NAME = "leadagent_test"


def _admin_url() -> str:
    # psycopg.connect() takes a libpq conninfo string, not a SQLAlchemy URL -
    # strip the "+psycopg" driver suffix SQLAlchemy needs but libpq rejects.
    base = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    return base.rsplit("/", 1)[0] + "/postgres"


def _test_db_url() -> str:
    return settings.database_url.rsplit("/", 1)[0] + f"/{TEST_DB_NAME}"


@pytest.fixture(scope="session", autouse=True)
def _create_test_database():
    """Create a dedicated test database on the same Postgres instance used
    for dev, so tests run against real Postgres (JSONB, etc.) rather than a
    stand-in like SQLite."""
    admin_conn = psycopg.connect(_admin_url(), autocommit=True)
    try:
        with admin_conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB_NAME,))
            if cur.fetchone() is None:
                cur.execute(f"CREATE DATABASE {TEST_DB_NAME}")
    finally:
        admin_conn.close()

    engine = create_engine(_test_db_url())
    Base.metadata.create_all(bind=engine)
    yield
    engine.dispose()


@pytest.fixture()
def db_session():
    """One outer transaction per test, rolled back at teardown. The app code
    under test calls session.commit() as normal, so a plain outer transaction
    would get committed for real by the first request; nesting it inside a
    SAVEPOINT (restarted after every commit) keeps commits scoped to the
    SAVEPOINT while the outer transaction stays open for the final rollback.
    See: SQLAlchemy docs, "Joining a Session into an External Transaction"."""
    engine = create_engine(_test_db_url())
    connection = engine.connect()
    outer_transaction = connection.begin()
    TestSession = sessionmaker(bind=connection)
    session = TestSession()

    nested = connection.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(session, transaction):
        nonlocal nested
        if not nested.is_active:
            nested = connection.begin_nested()

    yield session

    session.close()
    outer_transaction.rollback()
    connection.close()
    engine.dispose()


class _AgentClientHolder:
    """Mutable holder so a test can swap the fake agent client's behavior
    after the `client` fixture is already built, e.g.
    `fake_agent_client.current = FakeAgentClient(tool_name=...)`."""

    def __init__(self):
        self.current = always_fails()


@pytest.fixture()
def fake_agent_client():
    return _AgentClientHolder()


@pytest.fixture()
def client(db_session, fake_agent_client):
    def override_get_db():
        yield db_session

    def override_get_agent_client():
        return fake_agent_client.current

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_agent_client] = override_get_agent_client
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
