import app.main


def test_analysis_routes_exist():
    routes = [r.path for r in app.main.app.routes]
    assert "/api/v1/analyses/" in routes
    assert "/api/v1/analyses/{analysis_id}" in routes or any(path.startswith("/api/v1/analyses/") for path in routes)
