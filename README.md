# Prime Hub Bot V3 — Manual + Automatic Payments

Telegram digital-product store with PostgreSQL customer/order storage, product images, manual payment proof review, NOWPayments crypto confirmation, stock/sold tracking, and automatic delivery.

## Payment menu

- 💰 Pay with Wallet — manual proof and admin approval
- 🟡 Pay with Binance — manual proof and admin approval
- ⚪ Pay with USDT (BEP20) — automatic through NOWPayments
- ⚪ Pay with USDT (TRC20) — automatic through NOWPayments
- ⚪ Pay with UPI — manual proof and admin approval

## Manual verification flow

1. Customer chooses Wallet, Binance, or UPI.
2. Bot creates an order and shows the configured payment destination.
3. Customer sends a screenshot, receipt, transaction ID, or UTR.
4. Every configured admin receives the proof with **Approve & Deliver** and **Reject** buttons.
5. Approval delivers the product once and saves the final status.
6. Rejection notifies the customer.

Always verify that the money arrived in the real Wallet, Binance, or PhonePe account before approving.

## Railway variables

Copy all values from `.env.example` into Railway → service → Variables.

`ADMIN_IDS` must contain numeric Telegram user IDs. Multiple IDs may be comma-separated.

For UPI, set `UPI_INR_PER_USD` to the conversion rate used by your store and update it when needed.

## NOWPayments webhook

```text
https://YOUR-DOMAIN.up.railway.app/nowpayments-webhook
```

## Admin commands

```text
/admin
/addproduct
/listproducts
/delproduct PRODUCT_ID
/orders
/stats
```

## Railway start command

```text
python -m app.main
```
