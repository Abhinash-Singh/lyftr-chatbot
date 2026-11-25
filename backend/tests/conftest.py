import os
import sys
import tempfile

import pytest

os.environ.setdefault("LLM_API_KEYS", "test-key-1,test-key-2")
os.environ.setdefault("LLM_MODEL", "gemini/gemini-2.0-flash")
os.environ.setdefault("ENABLE_FAILURE_SIMULATION", "true")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost:3000")

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
