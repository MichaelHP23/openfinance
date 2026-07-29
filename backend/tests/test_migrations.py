"""The suite builds its schema with Base.metadata.create_all, so nothing else here ever
executes a migration. This test does, on a throwaway database, and it is the reason the
enum handling in a1b2c3d4e5f6 is caught before a deploy is.

ponytail: one round trip on the whole chain, not per-revision assertions. It fails on the
mistakes migrations actually make — bad ordering, a type created twice, an object the
downgrade forgets to drop — and costs one container.
"""

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from testcontainers.postgres import PostgresContainer


def _alembic_config(url: str) -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def test_migrations_upgrade_downgrade_and_upgrade_again():
    with PostgresContainer("postgres:17", driver="psycopg") as pg:
        url = pg.get_connection_url()
        cfg = _alembic_config(url)
        command.upgrade(cfg, "head")

        # Never downgrade until the container is proven to be what got migrated. env.py used
        # to overwrite the URL with settings.database_url, which pointed this test at the
        # real database and dropped every table in it. If that regresses, this fails here
        # with the container still empty, before anything destructive runs.
        with create_engine(url).connect() as conn:
            assert "trades" in inspect(conn).get_table_names(), (
                "alembic did not migrate the test container — refusing to downgrade"
            )

        # The second upgrade is the point: anything the downgrade leaves behind (a Postgres
        # enum outlives its table) blows up here rather than on someone's database.
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
