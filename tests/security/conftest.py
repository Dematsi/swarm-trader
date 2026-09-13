"""Fixtures for security regression tests.

The FastAPI app is imported against a throwaway SQLite engine so the tests never
create or touch app/backend/hedge_fund.db, and lifespan/startup events (Ollama
probe) are never run because TestClient is not used as a context manager.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _sqlite_engine(path):
    return create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})


@pytest.fixture(scope="session")
def backend_app(tmp_path_factory):
    import app.backend.database.connection as connection

    # app.backend.main runs Base.metadata.create_all(bind=engine) at import time.
    connection.engine = _sqlite_engine(tmp_path_factory.mktemp("db") / "import.db")
    from app.backend.main import app

    return app


@pytest.fixture
def client(backend_app, tmp_path):
    from fastapi.testclient import TestClient

    from app.backend.database import get_db
    from app.backend.database.models import Base

    engine = _sqlite_engine(tmp_path / "test.db")
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def _get_test_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    backend_app.dependency_overrides[get_db] = _get_test_db
    try:
        # The backend only trusts localhost host headers; "testserver" is rejected.
        yield TestClient(backend_app, base_url="http://localhost")
    finally:
        backend_app.dependency_overrides.pop(get_db, None)
        engine.dispose()
