import os

from slowapi import Limiter
from slowapi.util import get_remote_address


DEBUG_VALUES = {"1", "true", "yes", "on"}
is_debug = os.getenv("DEBUG", "false").strip().lower() in DEBUG_VALUES

limiter = Limiter(key_func=get_remote_address, enabled=not is_debug)
