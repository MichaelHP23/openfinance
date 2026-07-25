import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from testcontainers.postgres import PostgresContainer
from app.models.base import Base
import app.models  # noqa: F401  ensure all models imported/registered


@pytest.fixture(scope="session")
def pg_engine():
    with PostgresContainer("postgres:17", driver="psycopg") as pg:
        engine = create_engine(pg.get_connection_url())
        Base.metadata.create_all(engine)
        yield engine


@pytest.fixture
def db(pg_engine):
    conn = pg_engine.connect()
    txn = conn.begin()
    session = sessionmaker(bind=conn, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        txn.rollback()
        conn.close()
