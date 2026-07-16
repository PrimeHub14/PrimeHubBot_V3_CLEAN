Prime Hub V4.0.3

Fixes the /orders command handler, which was still using the older compact format.

After this patch, /orders shows:
- Product name
- Quantity
- Status
- Total
- Date and time

Also ensures /shop uses the category stock totals added in V4.0.2.
