Prime Hub V3 — TRC20 Direct Auto-Verify FIX

This package restores the original V3 functions that were overwritten by the first TRC20 patch, then merges TRC20 safely.

Fixed:
- Restored quantity keyboard
- Restored Wallet / Binance / UPI / manual payment buttons
- Restored wallet top-up keyboards
- Restored admin review / manual delivery buttons
- Restored all V3 routers in app/main.py
- Restored V3 config variables
- Direct TRC20 now preserves selected quantity
- Direct TRC20 uses the full order total, not single-item price
- Shows QR + public TRC20 address
- Uses confirmed TRON USDT transactions
- Requires exact unique amount
- Prevents transaction reuse
- Handles delivery failure after a confirmed payment without losing the payment record

Railway variables to add:
TRC20_RECEIVE_ADDRESS=<your public TRC20 address>
TRONGRID_API_KEY=<optional but recommended>
TRC20_PAYMENT_TIMEOUT_MINUTES=10
TRC20_POLL_SECONDS=15

Never add a seed phrase or private key.
