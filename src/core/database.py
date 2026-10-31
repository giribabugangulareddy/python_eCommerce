import os
from collections.abc import Iterator
from datetime import datetime, timezone

from pymongo import MongoClient, ReturnDocument
from pymongo.collection import Collection
from pymongo.database import Database

from src.core.security import hash_password

_client: MongoClient | None = None
_database: Database | None = None


def initialize_database() -> None:
    global _client, _database
    _client = MongoClient(
        os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27017"),
        tz_aware=True,
        serverSelectionTimeoutMS=5000,
    )
    _client.admin.command("ping")
    _database = _client[os.getenv("MONGODB_DATABASE", "ecommerce_local")]
    _database.products.create_index("id", unique=True)
    _database.users.create_index("id", unique=True)
    _database.users.create_index("email", unique=True)
    _database.carts.create_index("user_id", unique=True)
    _database.orders.create_index("id", unique=True)
    _database.orders.create_index([("user_id", 1), ("created_at", -1)])
    _seed_admin(_database)


def _seed_admin(database: Database) -> None:
    email = os.getenv("ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("ADMIN_PASSWORD", "")
    if not email and not password:
        return
    if not email or len(password) < 10:
        raise ValueError("Set both ADMIN_EMAIL and an ADMIN_PASSWORD of at least 10 characters")
    if database.users.find_one({"email": email}, {"_id": 1}) is not None:
        return
    database.users.update_one(
        {"email": email},
        {
            "$setOnInsert": {
                "id": get_next_id("users"),
                "email": email,
                "name": "Store Administrator",
                "password_hash": hash_password(password),
                "role": "admin",
                "active": True,
                "created_at": datetime.now(timezone.utc),
            }
        },
        upsert=True,
    )


def close_database() -> None:
    global _client, _database
    if _client is not None:
        _client.close()
    _client = None
    _database = None


def get_db() -> Iterator[Collection]:
    if _database is None:
        raise RuntimeError("Database is not initialized")
    yield _database.products


def get_collection(name: str) -> Collection:
    if _database is None:
        raise RuntimeError("Database is not initialized")
    return _database[name]


def get_users() -> Collection:
    return get_collection("users")


def get_carts() -> Collection:
    return get_collection("carts")


def get_orders() -> Collection:
    return get_collection("orders")


def get_next_id(collection: str) -> int:
    if _database is None:
        raise RuntimeError("Database is not initialized")
    counter = _database.counters.find_one_and_update(
        {"_id": collection},
        {"$inc": {"sequence_value": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return counter["sequence_value"]


def get_next_product_id() -> int:
    return get_next_id("products")
