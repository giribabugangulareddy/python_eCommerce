from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from src.schemas.product import ProductResponse


class UserCreate(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=10, max_length=128)
    name: str = Field(min_length=1, max_length=120)


class UserLogin(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class UserResponse(BaseModel):
    id: int
    email: str
    name: str
    role: Literal["customer", "admin"]
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class CartItemInput(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(ge=1, le=1000)


class CartLine(BaseModel):
    product: ProductResponse
    quantity: int
    line_total: Decimal


class CartResponse(BaseModel):
    items: list[CartLine]
    total: Decimal


class CheckoutInput(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    address_line: str = Field(min_length=3, max_length=250)
    city: str = Field(min_length=1, max_length=100)
    postal_code: str = Field(min_length=2, max_length=20)
    country: str = Field(min_length=2, max_length=80)


class OrderStatusUpdate(BaseModel):
    status: Literal["processing", "shipped", "delivered", "cancelled"]


class OrderItemResponse(BaseModel):
    product_id: int
    name: str
    quantity: int
    unit_price: Decimal
    line_total: Decimal


class OrderResponse(BaseModel):
    id: int
    user_id: int
    status: str
    payment_status: str
    items: list[OrderItemResponse]
    total: Decimal
    shipping_address: CheckoutInput
    created_at: datetime
    updated_at: datetime
