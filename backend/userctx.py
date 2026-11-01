"""Which household member the current request acts for. Single-user installs always resolve to user 1."""

from flask import g, has_app_context

DEFAULT_USER_ID = 1


def current_user_id() -> int:
    return int(g.get("user_id", DEFAULT_USER_ID)) if has_app_context() else DEFAULT_USER_ID
