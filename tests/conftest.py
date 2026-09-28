import os
from contextlib import contextmanager

import psycopg
import pytest
from django.db import connection


@contextmanager
def _connect_as(role: str, password_env: str):
    """A separate autocommit connection to the test database as a runtime role.

    It logs in as that role, so the role's own settings (timeouts) apply exactly as in
    production, which SET ROLE would not do.
    """
    s = connection.settings_dict
    conn = psycopg.connect(
        host=s["HOST"],
        port=s["PORT"] or 5432,
        dbname=s["NAME"],
        user=role,
        password=os.environ[password_env],
        autocommit=True,
    )
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def as_api(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock(), _connect_as("grs_api", "GRS_API_PASSWORD") as conn:
        yield conn


@pytest.fixture
def as_worker(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock(), _connect_as("grs_worker", "GRS_WORKER_PASSWORD") as conn:
        yield conn


@pytest.fixture
def connect_as(django_db_setup, django_db_blocker):
    """Factory for extra connections, e.g. to race two sessions against each other."""

    def factory(role="grs_api", password_env="GRS_API_PASSWORD"):
        return _connect_as(role, password_env)

    with django_db_blocker.unblock():
        yield factory
