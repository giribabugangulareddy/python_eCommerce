from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pymongo.collection import Collection

from src.api.v1.endpoints.auth import CurrentUser
from src.core.database import get_carts, get_db
from src.models.product import Product
from src.schemas.commerce import CartItemInput, CartLine, CartResponse

router = APIRouter(prefix="/cart", tags=["cart"])
Products = Annotated[Collection, Depends(get_db)]
Carts = Annotated[Collection, Depends(get_carts)]


def _read_cart(
    user: dict[str, Any], carts: Collection, products: Collection
) -> CartResponse:
    cart = carts.find_one({"user_id": user["id"]}) or {"items": []}
    lines: list[CartLine] = []
    total = Decimal("0.00")
    for item in cart["items"]:
        document = products.find_one(
            {"id": item["product_id"], "active": {"$ne": False}}
        )
        if document is None:
            raise HTTPException(
                status_code=409,
                detail=f"Product {item['product_id']} was removed; remove it from your cart",
            )
        product = Product.from_document(document)
        line_total = product.price * item["quantity"]
        total += line_total
        lines.append(
            CartLine(
                product=product,
                quantity=item["quantity"],
                line_total=line_total,
            )
        )
    return CartResponse(items=lines, total=total)


@router.get("", response_model=CartResponse)
def get_cart(user: CurrentUser, carts: Carts, products: Products) -> CartResponse:
    return _read_cart(user, carts, products)


@router.post("/items", response_model=CartResponse)
def add_cart_item(
    payload: CartItemInput, user: CurrentUser, carts: Carts, products: Products
) -> CartResponse:
    if products.find_one(
        {"id": payload.product_id, "active": {"$ne": False}}
    ) is None:
        raise HTTPException(status_code=404, detail="Product not found")
    cart = carts.find_one({"user_id": user["id"]}) or {"items": []}
    quantities = {item["product_id"]: item["quantity"] for item in cart["items"]}
    new_quantity = quantities.get(payload.product_id, 0) + payload.quantity
    if new_quantity > 1000:
        raise HTTPException(status_code=422, detail="Cart quantity cannot exceed 1000")
    quantities[payload.product_id] = new_quantity
    carts.update_one(
        {"user_id": user["id"]},
        {
            "$set": {
                "items": [
                    {"product_id": key, "quantity": value}
                    for key, value in quantities.items()
                ]
            }
        },
        upsert=True,
    )
    return _read_cart(user, carts, products)


@router.put("/items/{product_id}", response_model=CartResponse)
def set_cart_item(
    product_id: int,
    payload: CartItemInput,
    user: CurrentUser,
    carts: Carts,
    products: Products,
) -> CartResponse:
    if product_id != payload.product_id:
        raise HTTPException(status_code=422, detail="Path and body product IDs must match")
    if products.find_one({"id": product_id, "active": {"$ne": False}}) is None:
        raise HTTPException(status_code=404, detail="Product not found")
    cart = carts.find_one({"user_id": user["id"]}) or {"items": []}
    quantities = {item["product_id"]: item["quantity"] for item in cart["items"]}
    quantities[product_id] = payload.quantity
    carts.update_one(
        {"user_id": user["id"]},
        {
            "$set": {
                "items": [
                    {"product_id": key, "quantity": value}
                    for key, value in quantities.items()
                ]
            }
        },
        upsert=True,
    )
    return _read_cart(user, carts, products)


@router.delete("/items/{product_id}", response_model=CartResponse)
def remove_cart_item(
    product_id: int, user: CurrentUser, carts: Carts, products: Products
) -> CartResponse:
    carts.update_one(
        {"user_id": user["id"]},
        {"$pull": {"items": {"product_id": product_id}}},
    )
    return _read_cart(user, carts, products)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def clear_cart(user: CurrentUser, carts: Carts) -> Response:
    carts.delete_one({"user_id": user["id"]})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
