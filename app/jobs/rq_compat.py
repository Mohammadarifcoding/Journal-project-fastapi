import multiprocessing
import sys

_patched = False


def apply_windows_rq_patch() -> None:
    global _patched
    if _patched or sys.platform != "win32":
        return

    original_get_context = multiprocessing.get_context

    def _patched_get_context(method: str | None = None):
        if method == "fork":
            method = "spawn"
        return original_get_context(method)

    multiprocessing.get_context = _patched_get_context
    _patched = True
