Prime Hub V5 Enterprise Premium

Added:
- Premium Telegram home UI
- English, Portuguese, Hindi, Spanish and Arabic
- Product search
- Wishlist
- Product reviews
- Recently viewed
- Rich customer profile
- Rewards / referral / loyalty / VIP center
- Existing coupons, flash sales, CSV stock import, AI assistant, support, restock alerts and reports preserved
- /enterprise or /v5 premium admin dashboard
- Inventory center
- Marketing center
- Segmented broadcasts: all / VIP / buyers / referrers
- Scheduled broadcasts
- Admin audit log

Commands:
Customer:
  /recent
  /review ORDER_ID RATING comment
  /coupon CODE
  /referral
  /loyalty
  /vip
  /language
  /recommend

Admin:
  /enterprise
  /v5
  /broadcast
  /schedulebroadcast YYYY-MM-DD HH:MM AUDIENCE message
  /reports
  /ticketsadmin
  /createcoupon
  /flashsale
  /importstock

Important limitations:
- Telegram cannot provide true custom button colors/fonts like a web app. Premium UI is implemented using structured cards, button grids, icons and dashboards.
- Arabic is included throughout the new V5 navigation layer. Older legacy payment/admin strings remain English and require a separate full localization pass for 100% translation.
- Scheduled broadcast time is UTC.
