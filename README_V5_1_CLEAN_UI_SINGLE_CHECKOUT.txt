Prime Hub V5.1 — Clean UI + Single Checkout

Customer UI:
- Keeps the preferred compact Prime Hub home layout.
- Removes Search, VIP and Recommendations from the home buttons.
- Keeps Reviews as the store-wide review/testimonial button.
- Removes product-level review buttons that showed 0.0/5 when no reviews existed.
- Keeps Wishlist and Restock Alerts.
- Keeps Language + Help in a clean final row.

Checkout:
- One unpaid checkout/order is reused when changing payment method.
- Binance -> UPI -> BEP20 -> TRC20 no longer creates multiple order IDs for the same product/quantity.
- Previous payment QR/details message is deleted when a new payment method is selected.
- Only the latest payment details remain visible.
- The payment timer resets for the newly selected method.
- Direct TRC20/BEP20 keeps its configured longer payment window.
- Wallet checkout also removes a previous QR if wallet payment is selected.

Cancellation / expiry:
- Cancel removes the old payment card.
- Customer sees Shop / Order Again and Home buttons.
- Expired orders also show an Order Again button.
- No inventory is deducted for cancelled/expired unpaid orders.
