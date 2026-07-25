Prime Hub V5.4 — Quantity / Checkout Replacement Fix

Fixes:
- Quantity 2 -> Continue to Payment -> then changing to Quantity 3 removes the old Quantity 2 payment menu.
- Continue to Payment replaces the quantity card instead of adding another payment-menu message.
- If an older checkout had a QR/payment-detail card, it is deleted when a new quantity selection starts.
- Previous unpaid checkout orders are silently cancelled so they do not later produce duplicate expiry/cancellation messages.
- Only the final quantity/payment choice remains visible.
- Inventory is still not deducted until payment is confirmed.
