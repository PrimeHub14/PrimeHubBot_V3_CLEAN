Prime Hub V3.11 — live stock / no checkout hold

Behavior:
- Opening a product, choosing quantity, or opening a payment page never reserves stock.
- The displayed stock remains the live available quantity.
- Inventory is claimed atomically only after payment is confirmed.
- The first confirmed payment gets the available item(s).
- Unpaid expiry and Cancel Order do not alter inventory.
- Internal-wallet purchases are automatically refunded if stock sells out before confirmation.
- Manual or gateway payments that confirm after sell-out are marked paid_out_of_stock for replacement/refund handling.
- Payment-proof routing and duplicate wallet-credit protections from V3.10 are included.

Upload the included app files to the repository root and commit.
