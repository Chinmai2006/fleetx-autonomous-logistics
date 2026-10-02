"""
Shared pytest configuration.

Clears API role tokens for the test environment so that
require_operator_if_configured() returns 'local-development' instead of
enforcing auth — matching the behaviour when .env has no tokens set.

This is necessary because the live .env may have tokens configured for the
demo environment. Tests that exercise the full task-creation path do not
supply bearer tokens, so they would all get HTTP 401 without this override.
"""
import pytest


@pytest.fixture(autouse=True)
def clear_api_tokens(monkeypatch):
    """Override both token settings to empty strings for every test."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "API_OPERATOR_TOKEN", "")
    monkeypatch.setattr(settings, "API_ADMIN_TOKEN", "")
