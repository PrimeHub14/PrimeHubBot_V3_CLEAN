Prime Hub V3.8 strict stock and quantity fix

Fixes:
- Every product is stock-controlled.
- Existing products with zero stock are immediately shown as OUT OF STOCK.
- Checkout/payment is blocked when stock is zero or requested quantity exceeds stock.
- One unique StockItem is reserved for every purchased quantity.
- A quantity of 13 delivers 13 different stock items, never one reusable link.
- Stock is reserved before payment to prevent overselling.
- Reserved stock is released when payment setup fails, admin rejects, wallet debit fails, or provider reports failed/expired/refunded.
- New products start at stock 0 and cannot be purchased until /addstock PRODUCT_ID is used.

After deployment, add one unique line per sellable unit with /addstock PRODUCT_ID.
