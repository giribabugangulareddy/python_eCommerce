from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from jwt import InvalidTokenError

from src.api.v1.endpoints.auth import router as auth_router
from src.api.v1.endpoints.cart import router as cart_router
from src.api.v1.endpoints.orders import router as orders_router
from src.api.v1.endpoints.products import router as products_router
from src.core.database import close_database, get_users, initialize_database
from src.core.realtime import manager
from src.core.security import decode_access_token


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    initialize_database()
    try:
        yield
    finally:
        close_database()


app = FastAPI(title="Real-time eCommerce API", version="1.0.0", lifespan=lifespan)
app.include_router(auth_router, prefix="/api/v1")
app.include_router(products_router, prefix="/api/v1")
app.include_router(cart_router, prefix="/api/v1")
app.include_router(orders_router, prefix="/api/v1")


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/api/v1/ws")
async def websocket_events(websocket: WebSocket, token: str) -> None:
    try:
        claims = decode_access_token(token)
        user_id = int(claims["sub"])
        user = get_users().find_one({"id": user_id, "active": True})
        if user is None or user["role"] != claims.get("role"):
            raise InvalidTokenError("User is inactive or token role is invalid")
    except (InvalidTokenError, KeyError, TypeError, ValueError):
        await websocket.close(code=4401, reason="Invalid or expired access token")
        return

    await manager.connect(user_id, user["role"], websocket)
    try:
        await websocket.send_json(
            {"type": "connection.ready", "data": {"user_id": user_id}}
        )
        while True:
            message = await websocket.receive_text()
            if message == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(user_id, websocket)
