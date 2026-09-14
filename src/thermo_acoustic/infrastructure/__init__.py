"""Explicit adapter factories for simulated and retained hardware backends."""

from .simulated import build_simulated_application

__all__ = ["build_simulated_application"]


def build_real_application():
    """Import real-driver adapters only after explicit real-mode selection."""
    from .real import build_real_application as build
    return build()


__all__.append("build_real_application")
