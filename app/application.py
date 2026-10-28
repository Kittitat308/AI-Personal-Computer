"""Backward-compatible import facade for the desktop application."""

from app.application_composed import DesktopApplication, ThreadBridge

__all__ = ["DesktopApplication", "ThreadBridge"]
