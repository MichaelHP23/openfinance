from app.core.config import Settings, settings


def test_cors_origin_list_splits_and_strips():
    s = Settings(cors_origins=" http://a.test , http://b.test ,")
    assert s.cors_origin_list == ["http://a.test", "http://b.test"]


def test_default_allows_both_vite_dev_ports():
    # Vite falls back to 5174 when 5173 is taken, which is easy to hit locally.
    assert "http://localhost:5173" in settings.cors_origin_list
    assert "http://localhost:5174" in settings.cors_origin_list


def test_cors_is_never_a_wildcard():
    assert "*" not in settings.cors_origin_list
