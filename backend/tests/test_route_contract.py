import re

import pytest

from app import create_app

_app = create_app({"DATABASE_URL": "sqlite://", "ACCESS_TOKEN": "s3cret", "TESTING": True})
ROUTES = sorted(
    (r.rule, m)
    for r in _app.url_map.iter_rules()
    if r.rule.startswith("/api/") and r.rule not in ("/api/health", "/api/ready")
    for m in r.methods - {"HEAD", "OPTIONS"}
)


@pytest.mark.parametrize(("rule", "method"), ROUTES)
def test_every_api_route_requires_auth(authed_app, rule, method):
    path = re.sub(r"<[^>]+>", "1", rule)
    r = authed_app.test_client().open(path, method=method)
    assert r.status_code == 401
