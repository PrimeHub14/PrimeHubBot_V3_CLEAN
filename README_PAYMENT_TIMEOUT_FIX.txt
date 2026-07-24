Prime Hub V3 Payment Timeout Fix

Behavior after this patch:

- USDT TRC20 direct orders: 30 minute payment window.
- USDT BEP20 direct orders: 30 minute payment window.
- Binance manual payment orders: 10 minute payment window.
- UPI manual payment orders: 10 minute payment window.
- Other pending/manual payment orders: 10 minute payment window.
- Prime Hub internal wallet purchases are instant. They do not create a
  waiting order; if the wallet balance is insufficient, payment does not start.

When a waiting order expires:
1. Database status becomes `expired`.
2. No inventory is deducted.
3. The payment QR/message is edited to show EXPIRED.
4. Payment buttons are removed.
5. The customer receives an expiry notification.
6. A new order can be created normally.

The worker checks approximately every 10 seconds, so expiry can appear a few
seconds after the exact deadline.
