"""Registry behavior — register / get / list and clear errors."""

import pytest

from agent_core import RegistrationError, Registry, UnknownReferenceError


def test_register_get_list():
    r: Registry[int] = Registry("thing")
    r.register("a", 1)
    r.register("b", 2)
    assert r.get("a") == 1
    assert r.list() == ["a", "b"]
    assert "a" in r
    assert len(r) == 2


def test_duplicate_registration_raises():
    r: Registry[int] = Registry("thing")
    r.register("a", 1)
    with pytest.raises(RegistrationError):
        r.register("a", 2)


def test_overwrite_allows_replacement():
    r: Registry[int] = Registry("thing")
    r.register("a", 1)
    r.register("a", 2, overwrite=True)
    assert r.get("a") == 2


def test_empty_key_rejected():
    r: Registry[int] = Registry("thing")
    with pytest.raises(RegistrationError):
        r.register("", 1)


def test_unknown_get_raises_with_helpful_message():
    r: Registry[int] = Registry("tool")
    r.register("echo", 1)
    with pytest.raises(UnknownReferenceError) as exc:
        r.get("missing")
    msg = str(exc.value)
    assert "missing" in msg
    assert "echo" in msg  # lists what *is* registered
