Prime Hub V5.4.1 Runtime Hotfix

Fixes Railway error:
NameError: name 'cleanup_previous_checkout_ui' is not defined

Why it happened:
The V5.4 quantity handler called cleanup_previous_checkout_ui(), but the helper
definition was not present in the deployed user.py.

This hotfix:
- Adds cleanup_previous_checkout_ui() explicitly.
- Adds remember_checkout_menu() explicitly.
- Ensures cancel_open_checkout_orders_for_user() exists in repo.py.
- Keeps the V5.4 quantity replacement behavior.
- Prevents stale quantity/payment menus and duplicate unpaid checkouts.

Upload both files and redeploy.
