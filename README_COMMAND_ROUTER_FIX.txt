Prime Hub V3.6.4 command router fix

The previous command-handler patch added app/handlers/navigation.py,
but the running bot did not register that router in app/main.py.

This patch:
- adds navigation.py
- registers navigation.router before all other routers
- makes /start, /menu, /shop, /wallet, /orders, /profile and /help work
  even while another FSM flow is active

Upload only:
app/main.py
app/handlers/navigation.py
