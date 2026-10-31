from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pymongo import ReturnDocument
from pymongo.collection import Collection

from src.api.v1.endpoints.auth import AdminUser, CurrentUser
from src.core.database import get_carts, get_db, get_next_id, get_orders
from src.core.realtime import manager
from src.schemas.commerce import (
    CheckoutInput,
    OrderResponse,
    OrderStatusUpdate,
)

router = APIRouter(tags=["orders"])
Products = Annotated[Collection, Depends(get_db)]
Carts = Annotated[Collection, Depends(get_carts)]
Orders = Annotated[Collection, Depends(get_orders)]


def _price(cents: int) -> Decimal:
    return (Decimal(cents) / Decimal(100)).quantize(Decimal("0.01"))


def _response(order: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": order["id"],
        "user_id": order["user_id"],
        "status": order["status"],
        "payment_status": order["payment_status"],
        "items": [
            {
                "product_id": item["product_id"],
                "name": item["name"],
                "quantity": item["quantity"],
                "unit_price": _price(item["unit_price_cents"]),
                "line_total": _price(item["unit_price_cents"] * item["quantity"]),
            }
            for item in order["items"]
        ],
        "total": _price(order["total_cents"]),
        "shipping_address": order["shipping_address"],
        "created_at": order["created_at"],
        "updated_at": order["updated_at"],
    }


@router.post(
    "/orders/checkout",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def checkout(
    payload: CheckoutInput,
    user: CurrentUser,
    carts: Carts,
    products: Products,
    orders: Orders,
) -> dict[str, Any]:
    cart = carts.find_one({"user_id": user["id"]})
    if cart is None or not cart.get("items"):
        raise HTTPException(status_code=400, detail="Your cart is empty")

    reserved: list[tuple[int, int]] = []
    order_items: list[dict[str, Any]] = []
    total_cents = 0
    try:
        for item in cart["items"]:
            product_id = item["product_id"]
            quantity = item["quantity"]
            product = products.find_one(
                {"id": product_id, "active": {"$ne": False}}
            )
            if product is None:
                raise HTTPException(
                    status_code=409,
                    detail=f"Product {product_id} is no longer available",
                )
            reservation = products.update_one(
                {
                    "id": product_id,
                    "active": {"$ne": False},
                    "stock": {"$gte": quantity},
                },
                {
                    "$inc": {"stock": -quantity},
                    "$set": {"updated_at": datetime.now(timezone.utc)},
                },
            )
            if reservation.matched_count == 0:
                raise HTTPException(
                    status_code=409,
                    detail=f"Insufficient stock for {product['name']}",
                )
            reserved.append((product_id, quantity))
            unit_price_cents = product["price_cents"]
            total_cents += unit_price_cents * quantity
            order_items.append(
                {
                    "product_id": product_id,
                    "name": product["name"],
                    "quantity": quantity,
                    "unit_price_cents": unit_price_cents,
                }
            )

        now = datetime.now(timezone.utc)
        order = {
            "id": get_next_id("orders"),
            "user_id": user["id"],
            "status": "processing",
            "payment_status": "mock_paid",
            "items": order_items,
            "total_cents": total_cents,
            "shipping_address": payload.model_dump(),
            "created_at": now,
            "updated_at": now,
        }
        orders.insert_one(order)
    except Exception:
        for product_id, quantity in reserved:
            products.update_one({"id": product_id}, {"$inc": {"stock": quantity}})
        raise

    carts.delete_one({"user_id": user["id"]})
    event = {"type": "order.created", "data": _response(order)}
    await manager.publish(event, audience=f"user:{user['id']}")
    await manager.publish(event, audience="admins")
    for product_id, quantity in reserved:
        product = products.find_one({"id": product_id}, {"stock": 1})
        await manager.publish(
            {
                "type": "inventory.updated",
                "data": {
                    "product_id": product_id,
                    "stock": product["stock"],
                    "quantity_sold": quantity,
                },
            }
        )
    return _response(order)


@router.get("/orders", response_model=list[OrderResponse])
def list_my_orders(user: CurrentUser, orders: Orders) -> list[dict[str, Any]]:
    return [
        _response(order)
        for order in orders.find({"user_id": user["id"]}).sort("created_at", -1)
    ]


@router.get("/orders/{order_id}", response_model=OrderResponse)
def get_order(order_id: int, user: CurrentUser, orders: Orders) -> dict[str, Any]:
    query: dict[str, Any] = {"id": order_id}
    if user["role"] != "admin":
        query["user_id"] = user["id"]
    order = orders.find_one(query)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return _response(order)


def _change_order_status(
    order: dict[str, Any],
    new_status: str,
    orders: Collection,
    products: Collection,
) -> dict[str, Any]:
    old_status = order["status"]
    allowed = {
        "processing": {"shipped", "cancelled"},
        "shipped": {"delivered"},
        "delivered": set(),
        "cancelled": set(),
    }
    if new_status not in allowed[old_status]:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot change an order from {old_status} to {new_status}",
        )
    updated = orders.find_one_and_update(
        {"id": order["id"], "status": old_status},
        {"$set": {"status": new_status, "updated_at": datetime.now(timezone.utc)}},
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise HTTPException(
            status_code=409, detail="Order was updated by another request"
        )
    if new_status == "cancelled":
        for item in order["items"]:
            result = products.update_one(
                {"id": item["product_id"]},
                {
                    "$inc": {"stock": item["quantity"]},
                    "$set": {"updated_at": datetime.now(timezone.utc)},
                },
            )
            if result.matched_count == 0:
                raise RuntimeError(f"Cannot restore stock for product {item['product_id']}")
    return updated


@router.post("/orders/{order_id}/cancel", response_model=OrderResponse)
async def cancel_order(
    order_id: int, user: CurrentUser, orders: Orders, products: Products
) -> dict[str, Any]:
    order = orders.find_one({"id": order_id, "user_id": user["id"]})
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    updated = _change_order_status(order, "cancelled", orders, products)
    await manager.publish(
        {"type": "order.cancelled", "data": _response(updated)},
        audience=f"user:{user['id']}",
    )
    await manager.publish(
        {"type": "order.cancelled", "data": _response(updated)}, audience="admins"
    )
    return _response(updated)


@router.get("/admin/orders", response_model=list[OrderResponse])
def list_all_orders(_: AdminUser, orders: Orders) -> list[dict[str, Any]]:
    return [_response(order) for order in orders.find().sort("created_at", -1)]


@router.patch("/admin/orders/{order_id}/status", response_model=OrderResponse)
async def update_order_status(
    order_id: int,
    payload: OrderStatusUpdate,
    _: AdminUser,
    orders: Orders,
    products: Products,
) -> dict[str, Any]:
    order = orders.find_one({"id": order_id})
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    updated = _change_order_status(order, payload.status, orders, products)
    event_type = f"order.{payload.status}"
    await manager.publish(
        {"type": event_type, "data": _response(updated)},
        audience=f"user:{order['user_id']}",
    )
    await manager.publish(
        {"type": event_type, "data": _response(updated)}, audience="admins"
    )
    return _response(updated)
