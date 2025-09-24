from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Tuple

from pymongo import ASCENDING, DESCENDING
from pymongo.errors import PyMongoError, OperationFailure

# runtime deps wired via app bootstrap
from app.extensions import get_mongo


def log(obj: Dict[str, Any]) -> None:
    print(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))


IndexSpec = Tuple[List[Tuple[str, int]], Dict[str, Any]]


def specs() -> Dict[str, List[IndexSpec]]:
    return {
        # --- Core domain ---
        "users": [
            ([("email", ASCENDING)], {"name": "email_1", "background": True}),
            ([("phone", ASCENDING)], {"name": "phone_1", "background": True}),
            ([("name", ASCENDING)], {"name": "name_1", "background": True}),
        ],
        "studio": [
            ([("is_active", ASCENDING)], {"name": "is_active_1", "background": True}),
        ],
        "services": [
            ([("is_active", ASCENDING), ("order", ASCENDING)], {"name": "is_active_1_order_1", "background": True}),
        ],
        "works": [
            (
                [("author_type", ASCENDING), ("is_visible", ASCENDING), ("order", ASCENDING)],
                {"name": "author_type_1_is_visible_1_order_1", "background": True},
            ),
        ],
        "availability": [],
        "bookings": [
            (
                [("service_id", ASCENDING), ("start_at", ASCENDING)],
                {"name": "service_id_1_start_at_1", "unique": True, "background": True},
            ),
            ([("code", ASCENDING)], {"name": "code_1", "background": True}),
            (
                [("customer_id", ASCENDING), ("start_at", DESCENDING)],
                {"name": "customer_id_1_start_at_-1", "background": True},
            ),
            ([("status", ASCENDING)], {"name": "status_1", "background": True}),
            ([("created_at", DESCENDING)], {"name": "created_at_-1", "background": True}),
        ],
        "reviews": [
            ([("booking_id", ASCENDING)], {"name": "booking_id_1", "unique": True, "background": True}),
            ([("status", ASCENDING), ("created_at", DESCENDING)], {"name": "status_1_created_at_-1", "background": True}),
        ],
        "goods": [
            ([("status", ASCENDING)], {"name": "status_1", "background": True}),
            ([("name_i18n.ko", ASCENDING)], {"name": "name_i18n.ko_1", "background": True}),
        ],
        "orders": [
            ([("code", ASCENDING)], {"name": "code_1", "unique": True, "background": True}),
            (
                [("status", ASCENDING), ("expires_at", ASCENDING)],
                {"name": "status_1_expires_at_1", "background": True},
            ),
            (
                [("customer_id", ASCENDING), ("created_at", DESCENDING)],
                {"name": "customer_id_1_created_at_-1", "background": True},
            ),
        ],
        "audit_logs": [
            ([("at", DESCENDING)], {"name": "at_-1", "background": True}),
            ([("admin_id", ASCENDING)], {"name": "admin_id_1", "background": True}),
        ],
        "notifications_logs": [
            ([("at", DESCENDING)], {"name": "at_-1", "background": True}),
            ([("status", ASCENDING)], {"name": "status_1", "background": True}),
            ([("channel", ASCENDING)], {"name": "channel_1", "background": True}),
            ([("to", ASCENDING)], {"name": "to_1", "background": True}),
        ],
        "metrics_rollups": [
            ([("bucket", ASCENDING)], {"name": "bucket_1", "background": True}),
            ([("type", ASCENDING), ("bucket", ASCENDING)], {"name": "type_1_bucket_1", "background": True}),
        ],
        "job_locks": [
            ([("job_key", ASCENDING)], {"name": "job_key_1", "unique": True, "background": True}),
            ([("expires_at", ASCENDING)], {"name": "expires_at_1_ttl", "expireAfterSeconds": 0, "background": True}),
        ],
        # --- Infra helpers used by rate limit middleware ---
        "rate_limits": [
            ([("expireAt", ASCENDING)], {"name": "expireAt_1_ttl", "expireAfterSeconds": 0, "background": True}),
            ([("key", ASCENDING), ("bucket", ASCENDING)], {"name": "key_1_bucket_1", "unique": True, "background": True}),
        ],
    }


def ensure_indexes(apply: bool = False) -> bool:
    client = get_mongo()
    db = client.get_database()
    ok_all = True
    for coll_name, idx_list in specs().items():
        coll = db.get_collection(coll_name)
        for keys, opts in idx_list:
            spec = {"collection": coll_name, "keys": keys, "options": opts}
            if not apply:
                log({"action": "dry-run", **spec, "ok": True})
                continue
            try:
                name = coll.create_index(keys, **opts)
                log({"action": "create_index", "collection": coll_name, "name": name, "ok": True})
            except OperationFailure as e:
                msg = str(e)
                if "already exists with different options" in msg or "Index options conflict" in msg:
                    ok_all = False
                    log(
                        {
                            "action": "create_index",
                            "collection": coll_name,
                            "ok": False,
                            "error": "INDEX_CONFLICT",
                            "message": msg,
                            "keys": keys,
                            "options": opts,
                        }
                    )
                else:
                    ok_all = False
                    log(
                        {
                            "action": "create_index",
                            "collection": coll_name,
                            "ok": False,
                            "error": "OPERATION_FAILURE",
                            "message": msg,
                            "keys": keys,
                            "options": opts,
                        }
                    )
            except PyMongoError as e:
                ok_all = False
                log(
                    {
                        "action": "create_index",
                        "collection": coll_name,
                        "ok": False,
                        "error": "PYMONGO_ERROR",
                        "message": str(e),
                        "keys": keys,
                        "options": opts,
                    }
                )
    return ok_all


def main() -> int:
    parser = argparse.ArgumentParser(description="Create/verify MongoDB indexes for Pen Art.")
    parser.add_argument("--apply", action="store_true", help="Apply changes (create indexes).")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be created without applying.")
    args = parser.parse_args()

    apply = bool(args.apply and not args.dry_run)
    mode = "apply" if apply else "dry-run"
    log({"action": "start", "mode": mode})

    try:
        ok = ensure_indexes(apply=apply)
    except Exception as e:
        log({"action": "fatal", "ok": False, "error": "UNCAUGHT", "message": str(e)})
        return 1

    log({"action": "done", "ok": ok, "mode": mode})
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
