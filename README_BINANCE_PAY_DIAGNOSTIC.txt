Prime Hub — Binance Pay Read-Only Diagnostic

Purpose:
Confirm whether the user's ordinary Binance account API key can access:
GET /sapi/v1/pay/transactions

Railway variables required:
BINANCE_API_KEY
BINANCE_API_SECRET

Existing:
BINANCE_PAY_ID

Security:
- Keep Binance API permissions read-only.
- Do NOT enable withdrawals.
- Do NOT enable trading.
- Do NOT enable transfers.
- Never paste API credentials into Telegram/chat.

Test:
1. Deploy this patch.
2. In Telegram, from the admin account, send:
   /binancetest
3. The command requests up to 10 Binance Pay records from the last 7 days.
4. If Binance accepts the request, the bot confirms API access.
5. If records exist, it displays a sanitized preview.

This patch DOES NOT auto-deliver Binance orders yet.
That should only be enabled after confirming the endpoint works on this account.
