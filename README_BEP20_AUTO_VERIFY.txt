PrimeHub V3 — Direct USDT BEP20 Auto Verification

This update preserves the existing V3 features and the working TRC20 system.

New checkout flow:
1. Customer chooses USDT BEP20.
2. Bot creates an order-specific exact amount.
3. Bot shows a QR code and your BEP20 receiving address.
4. Railway checks confirmed Binance-Peg USDT Transfer logs using BSC_RPC_URL.
5. It verifies the official token contract, receiver, exact amount, confirmations,
   and prevents the same transaction hash from being reused.
6. After confirmation, the existing PrimeHub delivery service runs automatically.

Required Railway variables:
BEP20_RECEIVE_ADDRESS=<your public BEP20 address>
BSC_RPC_URL=<your NodeReal BSC Mainnet HTTPS endpoint>

Optional variables (defaults are already built in):
BEP20_PAYMENT_TIMEOUT_MINUTES=30
BEP20_POLL_SECONDS=10
BEP20_CONFIRMATIONS=3
BEP20_BACKFILL_BLOCKS=10000

Security:
- Never add a seed phrase/private key to Railway.
- BSC_RPC_URL contains your NodeReal credential and must stay secret.
- The bot only needs your public receiving address and read-only RPC access.
