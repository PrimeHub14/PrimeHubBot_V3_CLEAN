Prime Hub V3 — Manual Order Cancellation

Adds a visible "Cancel Order" button to direct USDT TRC20 and BEP20 payment QR cards.

Current behavior:
- TRC20/BEP20: customer can cancel manually before payment confirmation.
- UPI/Binance manual orders: already include Cancel Order.
- Internal wallet purchases: instant; no waiting order exists to cancel.
- Automatic expiry continues to work as a backup.

A confirmed/delivered order cannot be cancelled.
Cancelling an unpaid order does not deduct stock.
