Prime Hub V3.9

Fixes:
- prices remain visible for out-of-stock products
- /stock lists every product with available and held quantities
- manual delivery mode per product
- /setmanualstock and /deliverorder
- payment orders reserve stock for 10 minutes only
- abandoned unpaid orders expire automatically and release stock
- payment messages show the 10-minute deadline

Commands:
/stock
/deliverymode PRODUCT_ID instant|manual
/setmanualstock PRODUCT_ID QTY
/deliverorder ORDER_ID
