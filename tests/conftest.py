"""Test defaults. A missing DATABASE_URL must not fall through to a real .env."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite://")
