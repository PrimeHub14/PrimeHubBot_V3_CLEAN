Prime Hub V3.2 verified incremental patch

Upload the CONTENTS of this folder to the ROOT of the existing GitHub repository.
Do not upload the outer patch folder.

Replaces:
- app/db/models.py
- app/db/repo.py
- app/db/session.py
- app/handlers/admin.py
- app/handlers/user.py
- app/services/delivery.py
- app/services/nowpayments.py
- app/keyboards.py
- requirements.txt

Adds:
- app/utils/qr.py

Features:
- /editproduct PRODUCT_ID
- Quantity selector 1–13
- Quantity totals for all payment methods
- QR codes for Wallet, Binance, UPI and NOWPayments addresses
- Safe orders.quantity migration
- Correct USDT BEP20 mapping to usdtbsc
