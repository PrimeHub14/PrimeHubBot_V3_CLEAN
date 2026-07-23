PRIMEHUB DIRECT TRC20 AUTO-VERIFY PATCH

Replace/add these files in your existing PrimeHub Premium V2 GitHub repo.

ADD Railway variables:
TRC20_RECEIVE_ADDRESS=your_public_TRC20_address
TRONGRID_API_KEY=optional_but_recommended
TRC20_PAYMENT_TIMEOUT_MINUTES=20
TRC20_POLL_SECONDS=15

Never add a seed phrase or private key.

The QR contains only the public receiving address. The exact unique USDT amount is shown next to it.

Testing:
1. Deploy patch.
2. Buy a cheap test product.
3. Choose USDT TRC20 — Direct.
4. Bot shows QR + address + exact unique amount.
5. Send that exact USDT amount from a wallet that permits it.
6. Bot polls confirmed TRON TRC20 transfers and auto-delivers after a match.

Important: your sending wallet/exchange may still impose its own withdrawal minimum or network fee even though PrimeHub itself has no payment-gateway invoice minimum.
