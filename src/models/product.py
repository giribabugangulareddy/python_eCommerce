from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class Product:
    id: int
    name: str
    description: str | None
    price: Decimal
    stock: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> "Product":
        return cls(
            id=document["id"],
            name=document["name"],
            description=document.get("description"),
            price=(Decimal(document["price_cents"]) / Decimal("100")).quantize(
                Decimal("0.01")
            ),
            stock=document["stock"],
            created_at=document["created_at"],
            updated_at=document["updated_at"],
        )
