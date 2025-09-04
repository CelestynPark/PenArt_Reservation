from __future__ import annotations

import math
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from flask import current_app, request
from urllib.parse import urlencode

try:
    from pymongo.collation import Collation # type: ignore
except Exception:   # pragma: no cover
    Collection = Any    # type: ignore

