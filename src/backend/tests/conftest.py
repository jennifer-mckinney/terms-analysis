from __future__ import annotations

import os

# #133: the suite runs as the local developer setup (DEPLOY_ENV=local, loopback bind,
# no key) so the existing endpoint tests keep exercising behaviour, not auth. This
# must happen before ``app`` is imported: Settings reads the environment at import
# and fails closed when DEPLOY_ENV is unset and API_KEY is empty. Rate limits are
# overridden through the same environment variables the app reads, high enough
# that no existing test trips them; test_auth_ratelimit.py sets its own per test.
os.environ["DEPLOY_ENV"] = "local"
os.environ["BACKEND_HOST"] = "127.0.0.1"
os.environ["API_KEY"] = ""
for _var in (
    "FORWARDED_ALLOW_IPS",
    "RATE_LIMIT_TRUSTED_PROXY_CIDRS",
    "RATE_LIMIT_CLIENT_IP_HEADER",
):
    os.environ.pop(_var, None)
for _var in (
    "RATE_LIMIT_PRE_AUTH",
    "RATE_LIMIT_PER_CLIENT",
    "RATE_LIMIT_PER_KEY",
    "RATE_LIMIT_HEALTH",
):
    os.environ[_var] = "100000/minute"

# The local opt-in only exempts loopback peers (ruling 2), so test clients present
# a loopback address instead of Starlette's default "testclient".
LOOPBACK_PEER = ("127.0.0.1", 50000)

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import pytest  # noqa: E402

from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def app_client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, client=LOOPBACK_PEER) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def sample_privacy_policy_text():
    return (
        "We provide the right to access your personal data.\n"
        "You may request deletion of your account data.\n"
        "We retain records as long as necessary for legal compliance."
    )
