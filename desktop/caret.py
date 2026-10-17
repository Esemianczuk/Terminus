"""Retired compatibility shim for the former accessibility caret observer.

Terminus deliberately does not open text accessibility interfaces, traverse
accessibility trees, or run an AT-SPI helper. Window bounds provide a coarse
inspection target. Existing imports can close this inert observer safely.
"""


class LocalCaretObserver:
    def __init__(self, **_):
        self.process = self.reader = None

    def start(self):
        return False

    def snapshot(self):
        return {"rect": None, "secure": None, "available": False,
                "fresh": False, "backend": "unavailable", "precision": None,
                "reason": "geometry_observer_retired"}

    def close(self):
        return None
