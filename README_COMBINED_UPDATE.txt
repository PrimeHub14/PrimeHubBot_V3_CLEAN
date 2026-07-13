Prime Hub Combined Update — Stock + Delivery Notes

This update was built from the latest PrimeHubBot_V3_CLEAN repository.
It preserves the same Railway project, PostgreSQL database, bot token, products, users, orders, and variables.

Included features:
- Existing quantity selector and QR payment flows
- Existing product editing
- Unique per-unit stock records
- /addstock PRODUCT_ID
- /stock PRODUCT_ID
- /removestock PRODUCT_ID QUANTITY
- /disablestock PRODUCT_ID
- Automatic stock availability checks before order creation
- Automatic allocation after successful payment/admin approval
- Automatic reduction only after successful delivery
- Stock release when Telegram delivery fails
- Out-of-stock protection
- Stock count shown on product pages and admin product list
- Product-specific reusable delivery notes
- /editnote PRODUCT_ID
- /viewnote PRODUCT_ID
- Delivery Note button in /editproduct
- Placeholders: {product_name}, {quantity}, {order_id}, {support_username}
- Safe PostgreSQL schema migration; existing data is not deleted

After deployment, test in this order:
1. /stock 1
2. /addstock 1
3. Paste one unique item per line
4. /editnote 1
5. Buy one unit using a manual test payment and approve it
6. Confirm one stock item is delivered and /stock 1 decreases by one
