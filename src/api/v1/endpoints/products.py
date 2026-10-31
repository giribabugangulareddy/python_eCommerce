import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pymongo.collection import Collection

from src.api.v1.endpoints.auth import AdminUser
from src.core.database import get_db, get_next_product_id, get_orders
from src.core.realtime import manager
from src.models.product import Product
from src.schemas.product import ProductCreate, ProductResponse, ProductUpdate

router = APIRouter(prefix="/products", tags=["products"])
Database = Annotated[Collection, Depends(get_db)]


def _price_to_cents(price: Decimal) -> int:
    return int(price * 100)


def _event_product(product: Product) -> dict[str, Any]:
    return {
        "id": product.id,
        "name": product.name,
        "description": product.description,
        "price": str(product.price),
        "stock": product.stock,
        "created_at": product.created_at.isoformat(),
        "updated_at": product.updated_at.isoformat(),
    }


@router.post(
    "",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_product(
    payload: ProductCreate, db: Database, _: AdminUser
) -> Product:
    now = datetime.now(timezone.utc)
    document = {
        "id": get_next_product_id(),
        "name": payload.name,
        "description": payload.description,
        "price_cents": _price_to_cents(payload.price),
        "stock": payload.stock,
        "active": True,
        "created_at": now,
        "updated_at": now,
    }
    db.insert_one(document)
    product = Product.from_document(document)
    await manager.publish({"type": "product.created", "data": _event_product(product)})
    return product


@router.get("", response_model=list[ProductResponse])
def list_products(
    db: Database,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    search: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
) -> list[Product]:
    if search is None:
        cursor = (
            db.find({"active": {"$ne": False}})
            .sort("id", 1)
            .skip(offset)
            .limit(limit)
        )
    else:
        pattern = re.escape(search)
        cursor = (
            db.find(
                {
                    "active": {"$ne": False},
                    "$or": [
                        {"name": {"$regex": pattern, "$options": "i"}},
                        {"description": {"$regex": pattern, "$options": "i"}},
                    ],
                }
            )
            .sort("id", 1)
            .skip(offset)
            .limit(limit)
        )
    return [Product.from_document(document) for document in cursor]


@router.get("/{product_id}", response_model=ProductResponse)
def get_product(product_id: int, db: Database) -> Product:
    document = db.find_one({"id": product_id, "active": {"$ne": False}})
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return Product.from_document(document)


@router.patch("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: int,
    payload: ProductUpdate,
    db: Database,
    _: AdminUser,
) -> Product:
    changes = payload.model_dump(exclude_unset=True)
    if "price" in changes and changes["price"] is not None:
        changes["price_cents"] = _price_to_cents(changes.pop("price"))

    if changes:
        changes["updated_at"] = datetime.now(timezone.utc)
        result = db.update_one(
            {"id": product_id, "active": {"$ne": False}}, {"$set": changes}
        )
        if result.matched_count == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
            )

    document = db.find_one({"id": product_id, "active": {"$ne": False}})
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    product = Product.from_document(document)
    event_type = "inventory.updated" if "stock" in changes else "product.updated"
    await manager.publish({"type": event_type, "data": _event_product(product)})
    return product


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: int, db: Database, _: AdminUser
) -> Response:
    orders = get_orders()
    active_order = orders.find_one(
        {
            "items.product_id": product_id,
            "status": {"$in": ["processing", "shipped"]},
        },
        {"_id": 1},
    )
    if active_order is not None:
        raise HTTPException(
            status_code=409,
            detail="Product belongs to an active order and cannot be deleted",
        )
    result = db.update_one(
        {"id": product_id, "active": {"$ne": False}},
        {"$set": {"active": False, "updated_at": datetime.now(timezone.utc)}},
    )
    if result.matched_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
        )
    await manager.publish({"type": "product.deleted", "data": {"id": product_id}})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
