"""Explicit macOS Input Monitoring request for a process that needs it."""

import ctypes


def request_input_monitoring():
    """Request access once on explicit user command; never install an event tap."""
    try:
        framework = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        request = framework.CGRequestListenEventAccess
        request.argtypes = []
        request.restype = ctypes.c_bool
        return bool(request())
    except (OSError, AttributeError):
        return False
