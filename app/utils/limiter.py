import os

from dotenv import load_dotenv
from slowapi import Limiter
from slowapi.util import get_remote_address

load_dotenv()

DEBUG_VALUES = {"1", "true", "yes", "on"}
is_debug = os.getenv("DEBUG", "false").strip().lower() in DEBUG_VALUES

limiter = Limiter(key_func=get_remote_address, enabled=not is_debug)
