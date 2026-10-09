from app.main import app

def test_routes_exist():
    paths = {r.path for r in app.routes}
    assert "/health" in paths
    assert "/music/search" in paths
    assert "/music/stream/{video_id}" in paths
    assert "/lyrics" in paths

    assert "/music/import-playlist" in paths
