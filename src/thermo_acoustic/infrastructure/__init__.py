"""Explicit adapter factories for simulated and retained hardware backends."""

from .simulated import build_simulated_application

__all__ = ["build_simulated_application"]
