# Real-time eCommerce API

FastAPI and MongoDB backend with customer authentication, product/catalog and inventory management, carts, mock checkout, order management, and authenticated WebSocket events.

## Run locally

Install dependencies and start MongoDB, then run:

```powershell
python -m pip install -r requirements.txt
$env:MONGODB_URI = "mongodb://127.0.0.1:27017"
$env:MONGODB_DATABASE = "ecommerce_local"
$env:JWT_SECRET = "replace-with-a-long-random-secret"
$env:ADMIN_EMAIL = "admin@example.com"
$env:ADMIN_PASSWORD = "replace-with-a-password-of-at-least-10-characters"
python -m uvicorn src.main:app --host 127.0.0.1 --port 8000
```

The configured administrator account is created on first startup. Set a unique secret and admin credentials before exposing the service beyond a local development environment. The fallback JWT secret is for local development only.

For Docker Compose, set `JWT_SECRET`, `ADMIN_EMAIL`, and `ADMIN_PASSWORD` in the environment before running `docker compose up --build`.

Interactive API reference: `http://127.0.0.1:8000/docs`

## API

All REST routes are under `/api/v1`.

| Method | Route | Access | Purpose |
|---|---|---|---|
| POST | `/auth/register` | Public | Register a customer |
| POST | `/auth/login` | Public | Login; returns a bearer JWT |
| GET | `/auth/me` | Customer/Admin | Read the signed-in user's profile |
| GET | `/products` | Public | List/search products (`search`, `offset`, `limit`) |
| GET | `/products/{product_id}` | Public | Get a product |
| POST | `/products` | Admin | Create a product |
| PATCH | `/products/{product_id}` | Admin | Edit product or inventory |
| DELETE | `/products/{product_id}` | Admin | Archive a product not in an active order |
| GET | `/cart` | Customer | View cart and current totals |
| POST | `/cart/items` | Customer | Add a quantity to a cart |
| PUT | `/cart/items/{product_id}` | Customer | Set an item's quantity |
| DELETE | `/cart/items/{product_id}` | Customer | Remove a cart item |
| DELETE | `/cart` | Customer | Clear the cart |
| POST | `/orders/checkout` | Customer | Reserve stock and place a mock-paid order |
| GET | `/orders` | Customer | List the signed-in customer's orders |
| GET | `/orders/{order_id}` | Customer/Admin | Read an order (customers can read only their own) |
| POST | `/orders/{order_id}/cancel` | Customer | Cancel an order still processing |
| GET | `/admin/orders` | Admin | List all orders |
| PATCH | `/admin/orders/{order_id}/status` | Admin | Advance order status |
| WS | `/ws?token={JWT}` | Authenticated | Receive live product, inventory, and order events |

Pass REST credentials using `Authorization: Bearer <JWT>`. Connect to the WebSocket with the JWT returned from login. It sends `connection.ready`, `product.created`, `product.updated`, `product.deleted`, `inventory.updated`, and order lifecycle events. Order events are sent to the order owner and administrators; product and inventory events go to all connected authenticated users.

Checkout is a mock flow and does not charge a payment method. MongoDB stock changes use conditional updates to avoid selling more stock than is available. Use a replica set and transactions before extending this to workflows that require multi-document ACID guarantees.
