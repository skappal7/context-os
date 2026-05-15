from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from contextos.proxy.app import create_app  # noqa: F401


def __getattr__(name: str):  # lazy export — avoids circular import via payload module
    if name == "create_app":
        from contextos.proxy.app import create_app as _ca
        return _ca
    raise AttributeError(name)
