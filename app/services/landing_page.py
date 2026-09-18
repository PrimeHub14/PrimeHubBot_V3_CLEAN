from __future__ import annotations
import html
import re
from app.config import settings

def sanitize_slug(text: str) -> str:
    cleaned = re.sub(r'[^a-zA-Z0-9_]', '_', text.strip())
    return cleaned[:40]

def render_gemini_bridge_html(
    bot_username: str,
    utm_source: str = "meta",
    utm_campaign: str = "gemini18",
    pixel_id: str | None = None,
) -> str:
    effective_bot = bot_username or settings.TELEGRAM_BOT_USERNAME or "PrimeHubStoreBot"
    effective_pixel = pixel_id or settings.META_PIXEL_ID or ""

    # Generate deep-link payload e.g. meta_fb_gemini18
    raw_payload = f"meta_{utm_source}_{utm_campaign}".strip("_")
    payload = sanitize_slug(raw_payload) or "gemini18"

    deep_link = f"tg://resolve?domain={html.escape(effective_bot)}&start={html.escape(payload)}"
    web_fallback = f"https://t.me/{html.escape(effective_bot)}?start={html.escape(payload)}"

    pixel_code = ""
    if effective_pixel:
        pixel_code = f"""
    <!-- Meta Pixel Code -->
    <script>
    !function(f,b,e,v,n,t,s)
    {{if(f.fbq)return;n=f.fbq=function(){{n.callMethod?
    n.callMethod.apply(n,arguments):n.queue.push(arguments)}};
    if(!f._fbq)f._fbq=n;n.push=n;n.loaded=!0;n.version='2.0';
    n.queue=[];t=b.createElement(e);t.async=!0;
    t.src=v;s=b.getElementsByTagName(e)[0];
    s.parentNode.insertBefore(t,s)}}(window, document,'script',
    'https://connect.facebook.net/en_US/fbevents.js');
    fbq('init', '{html.escape(effective_pixel)}');
    fbq('track', 'PageView');
    fbq('track', 'ViewContent', {{
      content_name: 'Gemini AI Pro 18 Months Special',
      content_category: 'AI Subscription'
    }});
    </script>
    <noscript><img height="1" width="1" style="display:none"
    src="https://www.facebook.com/tr?id={html.escape(effective_pixel)}&ev=PageView&noscript=1"
    /></noscript>
    <!-- End Meta Pixel Code -->
        """
    else:
        pixel_code = """
    <script>
    // Meta Pixel placeholder (Add META_PIXEL_ID to Railway variables)
    window.fbq = function() { console.log('[Meta Pixel]', arguments); };
    </script>
        """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>Gemini AI Pro 18 Months — Exclusive Telegram Special</title>
  <meta name="description" content="Unlock 18 Months of uninterrupted Gemini AI Pro access with 2M token context, advanced reasoning, and multimodal capabilities. Instant bot delivery.">
  <meta property="og:title" content="Gemini AI Pro 18 Months — Exclusive Special">
  <meta property="og:description" content="Instant Telegram Bot Delivery with 24/7 warranty and verified payment methods.">
  <meta property="og:type" content="product">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  {pixel_code}
  <style>
    :root {{
      --bg: #090d16;
      --card-bg: rgba(20, 27, 45, 0.7);
      --card-border: rgba(66, 133, 244, 0.25);
      --primary: #2979ff;
      --primary-hover: #1c68e3;
      --accent: #9c27b0;
      --text: #f0f4f9;
      --text-muted: #94a3b8;
      --highlight: #00e676;
      --warning: #ff9100;
    }}
    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
      font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
      -webkit-tap-highlight-color: transparent;
    }}
    body {{
      background: radial-gradient(circle at 50% 0%, #172554 0%, #090d16 65%, #05070c 100%);
      color: var(--text);
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: 16px 16px 40px;
    }}
    .container {{
      max-width: 480px;
      width: 100%;
      margin: 0 auto;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: rgba(41, 121, 255, 0.15);
      border: 1px solid rgba(41, 121, 255, 0.4);
      color: #93c5fd;
      padding: 6px 14px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      margin-bottom: 12px;
    }}
    .pulse-dot {{
      width: 8px;
      height: 8px;
      background: var(--highlight);
      border-radius: 50%;
      box-shadow: 0 0 10px var(--highlight);
      animation: pulse 1.8s infinite;
    }}
    @keyframes pulse {{
      0% {{ transform: scale(0.9); opacity: 0.8; }}
      50% {{ transform: scale(1.3); opacity: 1; }}
      100% {{ transform: scale(0.9); opacity: 0.8; }}
    }}
    .title {{
      font-size: 28px;
      font-weight: 800;
      line-height: 1.25;
      margin-bottom: 10px;
      background: linear-gradient(135deg, #ffffff 30%, #93c5fd 70%, #d8b4fe 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }}
    .subtitle {{
      color: var(--text-muted);
      font-size: 14px;
      line-height: 1.5;
      margin-bottom: 18px;
    }}
    .deal-card {{
      background: var(--card-bg);
      backdrop-filter: blur(14px);
      -webkit-backdrop-filter: blur(14px);
      border: 1px solid var(--card-border);
      border-radius: 20px;
      padding: 20px;
      margin-bottom: 20px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.5);
    }}
    .timer-bar {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      background: rgba(255, 145, 0, 0.1);
      border: 1px dashed rgba(255, 145, 0, 0.4);
      padding: 8px 14px;
      border-radius: 12px;
      font-size: 13px;
      color: #ffb74d;
      margin-bottom: 16px;
      font-weight: 600;
    }}
    .countdown {{
      font-weight: 800;
      color: #ffa726;
      font-variant-numeric: tabular-nums;
    }}
    .features {{
      list-style: none;
      display: flex;
      flex-direction: column;
      gap: 12px;
      margin-bottom: 20px;
    }}
    .feature-item {{
      display: flex;
      align-items: flex-start;
      gap: 12px;
      font-size: 14px;
      line-height: 1.4;
    }}
    .feature-icon {{
      display: flex;
      align-items: center;
      justify-content: center;
      width: 26px;
      height: 26px;
      min-width: 26px;
      background: rgba(41, 121, 255, 0.2);
      border-radius: 8px;
      color: #60a5fa;
      font-size: 14px;
    }}
    .feature-item strong {{
      color: #ffffff;
    }}
    .cta-btn {{
      display: block;
      width: 100%;
      background: linear-gradient(135deg, #0088cc 0%, #2979ff 100%);
      color: #ffffff;
      text-decoration: none;
      padding: 16px 20px;
      border-radius: 16px;
      font-weight: 800;
      font-size: 16px;
      text-align: center;
      box-shadow: 0 8px 25px rgba(0, 136, 204, 0.4);
      transition: transform 0.2s ease, box-shadow 0.2s ease;
      cursor: pointer;
      border: none;
      outline: none;
    }}
    .cta-btn:active {{
      transform: scale(0.98);
      box-shadow: 0 4px 15px rgba(0, 136, 204, 0.3);
    }}
    .cta-subtext {{
      display: block;
      font-size: 12px;
      font-weight: 500;
      opacity: 0.85;
      margin-top: 4px;
    }}
    .guarantees {{
      display: flex;
      justify-content: space-around;
      margin-top: 14px;
      color: var(--text-muted);
      font-size: 11px;
      font-weight: 600;
    }}
    .guarantee-item {{
      display: flex;
      align-items: center;
      gap: 4px;
    }}
    .section-title {{
      font-size: 16px;
      font-weight: 700;
      margin: 24px 0 12px;
      color: #e2e8f0;
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .reviews-card {{
      background: rgba(15, 23, 42, 0.6);
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: 16px;
      padding: 16px;
      margin-bottom: 12px;
    }}
    .review-header {{
      display: flex;
      justify-content: space-between;
      margin-bottom: 6px;
      font-size: 13px;
    }}
    .reviewer {{
      font-weight: 700;
      color: #e2e8f0;
    }}
    .stars {{
      color: #fbbf24;
    }}
    .review-text {{
      font-size: 13px;
      color: var(--text-muted);
      line-height: 1.4;
    }}
    .faq-item {{
      background: rgba(15, 23, 42, 0.6);
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: 14px;
      margin-bottom: 8px;
      overflow: hidden;
    }}
    .faq-q {{
      padding: 14px 16px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }}
    .faq-a {{
      padding: 0 16px 14px;
      font-size: 13px;
      color: var(--text-muted);
      line-height: 1.4;
      display: none;
    }}
    .faq-item.active .faq-a {{
      display: block;
    }}
    .faq-item.active .faq-toggle {{
      transform: rotate(45deg);
    }}
    .faq-toggle {{
      font-size: 18px;
      transition: transform 0.2s;
    }}
    .footer {{
      margin-top: 30px;
      text-align: center;
      font-size: 11px;
      color: #64748b;
      line-height: 1.6;
    }}
  </style>
</head>
<body>
  <div class="container">
    
    <!-- Top Badge -->
    <div style="text-align: center;">
      <div class="badge">
        <span class="pulse-dot"></span>
        MEGA PRICE DROP ALERT • LIMITED TIME
      </div>
      <h1 class="title">GEMINI AI PRO + 5TB + ANTIGRAVITY</h1>
      <p class="subtitle">
        18 Months Uninterrupted Access On Your Personal Email • Quick Single-Click Activation
      </p>
    </div>

    <!-- Main Offer Card -->
    <div class="deal-card">
      <div class="timer-bar">
        <span>🔥 Limited Redeem Codes Available</span>
        <span class="countdown" id="timer">14:59</span>
      </div>

      <!-- Price Anchor Box -->
      <div style="background: rgba(41, 121, 255, 0.12); border: 1px solid rgba(41, 121, 255, 0.4); border-radius: 14px; padding: 14px; margin-bottom: 18px; text-align: center;">
        <div style="font-size: 13px; color: #94a3b8; text-decoration: line-through;">Original Price: ₹35,999 &bull; Regular: ₹799</div>
        <div style="font-size: 26px; font-weight: 800; color: #00e676; margin: 4px 0;">JUST ₹199 ONLY!</div>
        <div style="font-size: 12px; color: #93c5fd; font-weight: 600;">⚡ Direct on Your Email &bull; No Shared Logins &bull; No Family Invites</div>
      </div>

      <div style="font-size: 14px; font-weight: 700; color: #e2e8f0; margin-bottom: 12px;">🎁 18-MONTH PREMIUM PACKAGE INCLUDES:</div>
      <ul class="features">
        <li class="feature-item">
          <span class="feature-icon">💾</span>
          <div><strong>5TB Premium Storage:</strong> For Google Drive + Gmail + Google Photos.</div>
        </li>
        <li class="feature-item">
          <span class="feature-icon">🧠</span>
          <div><strong>Gemini Advanced AI:</strong> Advanced AI, deep reasoning & full coding features.</div>
        </li>
        <li class="feature-item">
          <span class="feature-icon">🍌</span>
          <div><strong>Nano Banana Pro & Veo 3:</strong> State-of-the-art video & multimodal generation.</div>
        </li>
        <li class="feature-item">
          <span class="feature-icon">🌊</span>
          <div><strong>Google Flow & Whisk:</strong> 1,000 credits refreshed every month.</div>
        </li>
        <li class="feature-item">
          <span class="feature-icon">🚀</span>
          <div><strong>Antigravity Access & NotebookLM:</strong> Premium NotebookLM & Deep Research tools.</div>
        </li>
        <li class="feature-item">
          <span class="feature-icon">💻</span>
          <div><strong>Gemini Code Assist & CLI:</strong> Enterprise-grade coding assistant & Health Premium.</div>
        </li>
        <li class="feature-item">
          <span class="feature-icon">👨‍👩‍👧‍👦</span>
          <div><strong>Add Up to 5 Family Members:</strong> Share your 5TB plan with your loved ones.</div>
        </li>
        <li class="feature-item">
          <span class="feature-icon">🛡️</span>
          <div><strong>1 Month Warranty:</strong> Full replacement warranty and setup assistance included.</div>
        </li>
      </ul>

      <!-- Activation Steps -->
      <div style="background: rgba(15, 23, 42, 0.7); border: 1px solid rgba(255,255,255,0.08); border-radius: 14px; padding: 14px; margin-bottom: 18px;">
        <div style="font-size: 13px; font-weight: 700; color: #f59e0b; margin-bottom: 8px;">⚡ 4 Simple Activation Steps:</div>
        <div style="font-size: 12px; color: #cbd5e1; line-height: 1.6;">
          1️⃣ Copy the redeem code / activation link sent by our bot<br>
          2️⃣ Paste it in your Chrome browser<br>
          3️⃣ Choose your own Google account<br>
          4️⃣ Click "Activate Plan" — Done!
        </div>
      </div>

      <button id="cta-button" class="cta-btn" onclick="openTelegramBot(event)">
        👉 Claim 18-Month Plan for ₹199
        <span class="cta-subtext">Instant Bot Redeem Link • UPI & Crypto Accepted</span>
      </button>

      <div class="guarantees">
        <div class="guarantee-item">⚡ 1-Click Setup</div>
        <div class="guarantee-item">🛡️ 1-Month Warranty</div>
        <div class="guarantee-item">⭐ 4.9/5 Rating</div>
      </div>
    </div>

    <!-- Social Proof -->
    <div class="section-title">💬 Verified Customer Reviews</div>
    
    <div class="reviews-card">
      <div class="review-header">
        <span class="reviewer">Rohit S. • Data Scientist</span>
        <span class="stars">★★★★★</span>
      </div>
      <p class="review-text">
        "Activated directly on my own Google email in 15 seconds. 5TB Google Drive storage plus Gemini Advanced for ₹199 is an unbeatable deal."
      </p>
    </div>

    <div class="reviews-card">
      <div class="review-header">
        <span class="reviewer">Ananya P. • Content Creator</span>
        <span class="stars">★★★★★</span>
      </div>
      <p class="review-text">
        "Paid via UPI and received the redeem link immediately from the bot. No shared passwords, 100% private."
      </p>
    </div>

    <!-- FAQ Accordion -->
    <div class="section-title">❓ Frequently Asked Questions</div>

    <div class="faq-item" onclick="toggleFaq(this)">
      <div class="faq-q">
        <span>Is this activated on my own email?</span>
        <span class="faq-toggle">+</span>
      </div>
      <div class="faq-a">
        Yes! You will receive a direct Redeem Code link. You open it in Chrome and activate it on your personal Google account. No shared passwords, no family invite requests.
      </div>
    </div>

    <div class="faq-item" onclick="toggleFaq(this)">
      <div class="faq-q">
        <span>What warranty do you provide?</span>
        <span class="faq-toggle">+</span>
      </div>
      <div class="faq-a">
        We provide a 1-Month Full Replacement Warranty and dedicated customer support for your purchase.
      </div>
    </div>

    <div class="faq-item" onclick="toggleFaq(this)">
      <div class="faq-q">
        <span>What payment methods are supported?</span>
        <span class="faq-toggle">+</span>
      </div>
      <div class="faq-a">
        We support instant auto-verification for UPI (PhonePe, GPay, Paytm), Binance Pay, USDT (BEP20 / TRC20), and Store Wallet.
      </div>
    </div>

    <!-- Footer -->
    <div class="footer">
      <p>© {settings.STORE_NAME}. All rights reserved.</p>
      <p>Secure automated delivery powered by Team Prime Hub on Telegram.</p>
    </div>

  </div>

  <script>
    // 15-minute countdown urgency timer
    let minutes = 14;
    let seconds = 59;
    setInterval(function() {{
      if (seconds === 0) {{
        if (minutes === 0) {{
          minutes = 14;
          seconds = 59;
        }} else {{
          minutes--;
          seconds = 59;
        }}
      }} else {{
        seconds--;
      }}
      const minStr = String(minutes).padStart(2, '0');
      const secStr = String(seconds).padStart(2, '0');
      const el = document.getElementById('timer');
      if (el) el.textContent = minStr + ':' + secStr;
    }}, 1000);

    // FAQ Accordion toggle
    function toggleFaq(el) {{
      el.classList.toggle('active');
    }}

    // Telegram Bot Deep-Link Redirector
    function openTelegramBot(e) {{
      if (e && e.preventDefault) e.preventDefault();

      // Track Meta Pixel Lead event
      try {{
        if (typeof fbq === 'function') {{
          fbq('track', 'Lead', {{
            content_name: 'Gemini AI Pro 18 Months',
            content_category: 'AI Subscription',
            value: 1.00,
            currency: 'USD'
          }});
          fbq('track', 'InitiateCheckout');
        }}
      }} catch(err) {{
        console.warn('Pixel track error', err);
      }}

      const deepLink = "{deep_link}";
      const webFallback = "{web_fallback}";

      // Attempt native app protocol first, fallback to web
      let fallbackTimer = setTimeout(function() {{
        window.location.href = webFallback;
      }}, 500);

      window.addEventListener('blur', function() {{
        clearTimeout(fallbackTimer);
      }});

      window.location.href = deepLink;
    }}
  </script>
</body>
</html>
"""
