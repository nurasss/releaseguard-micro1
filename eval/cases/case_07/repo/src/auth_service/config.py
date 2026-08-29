"""Configuration for auth service."""

import os

SECRET_KEY = os.getenv("AUTH_SECRET_KEY", "default-insecure-secret")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
