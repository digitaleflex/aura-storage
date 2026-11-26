from api.app_factory import create_app
from api.main import app


def test_create_app_returns_fastapi_and_main_app_compatible():
    fresh = create_app()
    assert fresh.title == "AURA Management API"
    assert app.title == "AURA Management API"
    assert app.version == fresh.version
