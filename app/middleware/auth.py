from __future__ import annotations

from typing import Any, Dict

from flask import Blueprint, g, request, session

from app.core.constants import ERR_INVALID_PAYLOAD, ERR_UNAUTHORIZED
from app.services import auth