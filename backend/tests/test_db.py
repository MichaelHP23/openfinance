from sqlalchemy import text


def test_db_connects(db):
    assert db.execute(text("SELECT 1")).scalar() == 1
