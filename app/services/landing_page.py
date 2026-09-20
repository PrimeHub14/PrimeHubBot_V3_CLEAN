from __future__ import annotations
import html
import re
import time
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
    cache_buster = int(time.time())
    effective_bot = bot_username or settings.TELEGRAM_BOT_USERNAME or "PrimeHubUs_Bot"
    effective_pixel = pixel_id or settings.META_PIXEL_ID or "2035067993878515"

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
      content_name: 'Gemini AI Pro 18 Months + 5TB Special',
      content_category: 'AI Subscription',
      value: 199.00,
      currency: 'INR'
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
    window.fbq = function() { console.log('[Meta Pixel]', arguments); };
    </script>
        """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>🎁 GEMINI AI PRO + 5TB + ANTIGRAVITY — 18 Months (Just ₹199)</title>
  <meta name="description" content="Single-click activation on your own Google email. Get 18 Months of Gemini Advanced, 5TB Google Cloud Storage, Antigravity, Veo 3 and 1-month warranty for only ₹199!">
  <meta property="og:title" content="GEMINI AI PRO + 5TB + ANTIGRAVITY — 18 Months (Just ₹199)">
  <meta property="og:description" content="Single-click activation on your personal email. 5TB Storage + Gemini Advanced. Instant Telegram Delivery!">
  <meta property="og:image" content="https://primehubbotv3clean-production.up.railway.app/gemini-poster.jpg">
  <meta property="og:type" content="product">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:image" content="https://primehubbotv3clean-production.up.railway.app/gemini-poster.jpg">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
  {pixel_code}
  <style>
    :root {{
      --bg: #070a12;
      --card-bg: rgba(17, 24, 43, 0.75);
      --card-border: rgba(66, 133, 244, 0.28);
      --primary: #2979ff;
      --primary-hover: #1c68e3;
      --accent: #a855f7;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --highlight: #00e676;
      --warning: #f59e0b;
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
      padding: 14px 14px 100px;
      overflow-x: hidden;
    }}
    .container {{
      max-width: 500px;
      width: 100%;
      margin: 0 auto;
    }}

    /* Brand Header */
    .brand-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 8px 12px;
      background: rgba(15, 23, 42, 0.7);
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 999px;
      margin-bottom: 16px;
      backdrop-filter: blur(10px);
    }}
    .brand-logo-wrap {{
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .brand-icon {{
      width: 24px;
      height: 24px;
      border-radius: 6px;
      background: linear-gradient(135deg, #a855f7 0%, #2979ff 100%);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 13px;
      font-weight: 900;
      color: #fff;
    }}
    .brand-name {{
      font-size: 13px;
      font-weight: 800;
      letter-spacing: 0.4px;
      color: #ffffff;
    }}
    .brand-name span {{
      color: #93c5fd;
    }}
    .brand-verified {{
      display: inline-flex;
      align-items: center;
      gap: 4px;
      font-size: 11px;
      font-weight: 700;
      color: #69f0ae;
      background: rgba(0, 230, 118, 0.12);
      border: 1px solid rgba(0, 230, 118, 0.35);
      padding: 3px 10px;
      border-radius: 999px;
    }}

    .badge {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: rgba(41, 121, 255, 0.15);
      border: 1px solid rgba(41, 121, 255, 0.45);
      color: #93c5fd;
      padding: 6px 14px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.6px;
      margin-bottom: 10px;
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
      font-size: 25px;
      font-weight: 900;
      line-height: 1.25;
      margin-bottom: 6px;
      background: linear-gradient(135deg, #ffffff 25%, #93c5fd 65%, #c084fc 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      text-align: center;
    }}
    .subtitle {{
      color: var(--text-muted);
      font-size: 13px;
      line-height: 1.5;
      margin-bottom: 16px;
      text-align: center;
    }}

    /* Hero Poster Showcase (Full 1:1 Creative) */
    .hero-poster-card {{
      position: relative;
      border-radius: 20px;
      overflow: hidden;
      margin-bottom: 16px;
      border: 2px solid rgba(168, 85, 247, 0.45);
      box-shadow: 0 16px 40px rgba(0, 0, 0, 0.7), 0 0 35px rgba(168, 85, 247, 0.25);
      background: #090d16;
    }}
    .hero-poster-img {{
      width: 100%;
      height: auto;
      aspect-ratio: 1 / 1;
      display: block;
      border-top-left-radius: 18px;
      border-top-right-radius: 18px;
    }}
    .poster-footer-bar {{
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      background: linear-gradient(90deg, rgba(15, 23, 42, 0.98), rgba(30, 27, 75, 0.98));
      border-top: 1px solid rgba(255, 255, 255, 0.08);
      padding: 10px 14px;
      font-size: 11.5px;
      font-weight: 700;
      color: #93c5fd;
      text-align: center;
    }}
    .poster-footer-bar span.hl {{
      color: #00e676;
    }}

    .deal-card {{
      background: var(--card-bg);
      backdrop-filter: blur(14px);
      -webkit-backdrop-filter: blur(14px);
      border: 1px solid var(--card-border);
      border-radius: 20px;
      padding: 18px;
      margin-bottom: 18px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.5);
    }}
    .timer-bar {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      background: rgba(245, 158, 11, 0.12);
      border: 1px dashed rgba(245, 158, 11, 0.45);
      padding: 9px 14px;
      border-radius: 12px;
      font-size: 12px;
      color: #fbbf24;
      margin-bottom: 12px;
      font-weight: 700;
    }}
    .countdown {{
      font-weight: 900;
      color: #f59e0b;
      font-variant-numeric: tabular-nums;
      font-size: 14px;
    }}

    .stock-progress-wrap {{
      background: rgba(15, 23, 42, 0.8);
      border-radius: 10px;
      padding: 8px 12px;
      margin-bottom: 14px;
      border: 1px solid rgba(255, 255, 255, 0.06);
    }}
    .stock-header {{
      display: flex;
      justify-content: space-between;
      font-size: 11px;
      font-weight: 700;
      color: #cbd5e1;
      margin-bottom: 6px;
    }}
    .stock-highlight {{
      color: #f87171;
    }}
    .stock-track {{
      height: 7px;
      background: rgba(255, 255, 255, 0.1);
      border-radius: 999px;
      overflow: hidden;
    }}
    .stock-fill {{
      height: 100%;
      width: 86%;
      background: linear-gradient(90deg, #f59e0b, #ef4444);
      border-radius: 999px;
    }}

    /* Price Anchor */
    .price-box {{
      background: linear-gradient(135deg, rgba(41, 121, 255, 0.15) 0%, rgba(168, 85, 247, 0.15) 100%);
      border: 1px solid rgba(41, 121, 255, 0.4);
      border-radius: 16px;
      padding: 16px;
      margin-bottom: 16px;
      text-align: center;
    }}
    .price-original {{
      font-size: 13px;
      color: #94a3b8;
      text-decoration: line-through;
    }}
    .price-highlight {{
      font-size: 30px;
      font-weight: 900;
      color: var(--highlight);
      margin: 4px 0;
      letter-spacing: -0.5px;
    }}
    .price-tagline {{
      font-size: 12px;
      color: #93c5fd;
      font-weight: 700;
    }}

    .features {{
      list-style: none;
      display: flex;
      flex-direction: column;
      gap: 11px;
      margin-bottom: 18px;
    }}
    .feature-item {{
      display: flex;
      align-items: flex-start;
      gap: 12px;
      font-size: 13px;
      line-height: 1.4;
    }}
    .feature-icon {{
      display: flex;
      align-items: center;
      justify-content: center;
      width: 28px;
      height: 28px;
      min-width: 28px;
      background: rgba(41, 121, 255, 0.2);
      border-radius: 8px;
      color: #60a5fa;
      font-size: 15px;
    }}
    .feature-item strong {{
      color: #ffffff;
    }}

    .cta-btn {{
      display: block;
      width: 100%;
      background: linear-gradient(135deg, #0088cc 0%, #2979ff 55%, #7c3aed 100%);
      color: #ffffff;
      text-decoration: none;
      padding: 16px 20px;
      border-radius: 16px;
      font-weight: 900;
      font-size: 16px;
      text-align: center;
      box-shadow: 0 8px 25px rgba(0, 136, 204, 0.45);
      transition: transform 0.2s ease, box-shadow 0.2s ease;
      cursor: pointer;
      border: none;
      outline: none;
    }}
    .cta-btn:active {{
      transform: scale(0.98);
    }}
    .cta-subtext {{
      display: block;
      font-size: 11px;
      font-weight: 600;
      opacity: 0.9;
      margin-top: 4px;
      color: #e0f2fe;
    }}
    .guarantees {{
      display: flex;
      justify-content: space-around;
      margin-top: 14px;
      color: var(--text-muted);
      font-size: 11px;
      font-weight: 700;
    }}
    .guarantee-item {{
      display: flex;
      align-items: center;
      gap: 4px;
    }}

    /* Steps Card */
    .steps-card {{
      background: rgba(15, 23, 42, 0.65);
      border: 1px solid rgba(255,255,255,0.08);
      border-radius: 16px;
      padding: 16px;
      margin-bottom: 18px;
    }}
    .step-line {{
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 12.5px;
      margin-bottom: 8px;
      color: #cbd5e1;
    }}
    .step-num {{
      display: flex;
      align-items: center;
      justify-content: center;
      width: 22px;
      height: 22px;
      min-width: 22px;
      background: rgba(245, 158, 11, 0.2);
      border: 1px solid rgba(245, 158, 11, 0.5);
      border-radius: 50%;
      color: #fbbf24;
      font-size: 11px;
      font-weight: 800;
    }}

    /* Comparison Table */
    .comp-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
      margin: 12px 0 18px;
      background: rgba(15, 23, 42, 0.65);
      border-radius: 14px;
      overflow: hidden;
      border: 1px solid rgba(255,255,255,0.08);
    }}
    .comp-table th, .comp-table td {{
      padding: 10px 12px;
      text-align: left;
      border-bottom: 1px solid rgba(255,255,255,0.06);
    }}
    .comp-table th {{
      background: rgba(30, 41, 59, 0.8);
      color: #94a3b8;
      font-weight: 700;
      font-size: 11px;
      text-transform: uppercase;
    }}
    .comp-table .winner {{
      color: #00e676;
      font-weight: 800;
      background: rgba(0, 230, 118, 0.06);
    }}
    .comp-table .loser {{
      color: #94a3b8;
    }}

    .section-title {{
      font-size: 15px;
      font-weight: 800;
      margin: 22px 0 12px;
      color: #e2e8f0;
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .reviews-card {{
      background: rgba(15, 23, 42, 0.6);
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: 16px;
      padding: 14px;
      margin-bottom: 10px;
    }}
    .review-header {{
      display: flex;
      justify-content: space-between;
      margin-bottom: 6px;
      font-size: 12px;
    }}
    .reviewer {{
      font-weight: 700;
      color: #e2e8f0;
    }}
    .stars {{
      color: #fbbf24;
    }}
    .review-text {{
      font-size: 12px;
      color: var(--text-muted);
      line-height: 1.45;
    }}

    /* FAQ */
    .faq-item {{
      background: rgba(15, 23, 42, 0.6);
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: 14px;
      margin-bottom: 8px;
      overflow: hidden;
    }}
    .faq-q {{
      padding: 12px 14px;
      font-size: 12.5px;
      font-weight: 700;
      cursor: pointer;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }}
    .faq-a {{
      padding: 0 14px 12px;
      font-size: 12px;
      color: var(--text-muted);
      line-height: 1.45;
      display: none;
    }}
    .faq-item.active .faq-a {{
      display: block;
    }}
    .faq-item.active .faq-toggle {{
      transform: rotate(45deg);
    }}
    .faq-toggle {{
      font-size: 16px;
      transition: transform 0.2s;
    }}

    /* Sticky Bottom Mobile Bar */
    .sticky-bar {{
      position: fixed;
      bottom: 0;
      left: 0;
      right: 0;
      background: rgba(7, 10, 18, 0.94);
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      padding: 10px 14px;
      border-top: 1px solid rgba(66, 133, 244, 0.3);
      display: flex;
      justify-content: center;
      z-index: 999;
      transform: translateY(120%);
      transition: transform 0.3s ease;
    }}
    .sticky-bar.visible {{
      transform: translateY(0);
    }}
    .sticky-content {{
      max-width: 480px;
      width: 100%;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }}
    .sticky-price-wrap {{
      display: flex;
      flex-direction: column;
    }}
    .sticky-price {{
      font-size: 20px;
      font-weight: 900;
      color: var(--highlight);
      line-height: 1;
    }}
    .sticky-strike {{
      font-size: 11px;
      color: #64748b;
      text-decoration: line-through;
    }}
    .sticky-sub {{
      font-size: 10px;
      color: #93c5fd;
      font-weight: 700;
    }}
    .sticky-cta-btn {{
      background: linear-gradient(135deg, #0088cc 0%, #2979ff 100%);
      color: #ffffff;
      border: none;
      padding: 12px 20px;
      border-radius: 12px;
      font-size: 14px;
      font-weight: 800;
      cursor: pointer;
      box-shadow: 0 4px 15px rgba(0, 136, 204, 0.4);
    }}

    /* Live Buyer Toast */
    .buyer-toast {{
      position: fixed;
      bottom: 78px;
      left: 14px;
      background: rgba(15, 23, 42, 0.92);
      border: 1px solid rgba(0, 230, 118, 0.35);
      border-radius: 12px;
      padding: 8px 12px;
      display: flex;
      align-items: center;
      gap: 8px;
      z-index: 998;
      box-shadow: 0 8px 20px rgba(0,0,0,0.4);
      opacity: 0;
      transform: translateY(15px);
      transition: opacity 0.4s ease, transform 0.4s ease;
      pointer-events: none;
      max-width: 320px;
    }}
    .buyer-toast.show {{
      opacity: 1;
      transform: translateY(0);
    }}
    .toast-dot {{
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #00e676;
      box-shadow: 0 0 8px #00e676;
    }}
    .toast-text {{
      font-size: 11px;
      color: #e2e8f0;
      line-height: 1.3;
    }}
    .toast-time {{
      color: #94a3b8;
      font-size: 10px;
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
    
    <!-- Verified Store Header -->
    <div class="brand-header">
      <div class="brand-logo-wrap">
        <div class="brand-icon">P</div>
        <div class="brand-name">PRIME <span>HUB</span></div>
      </div>
      <div class="brand-verified">
        ✓ Verified Store
      </div>
    </div>

    <!-- Top Badge & Heading -->
    <div style="text-align: center;">
      <div class="badge">
        <span class="pulse-dot"></span>
        MEGA PRICE DROP &bull; LIMITED REDEEM CODES
      </div>
      <h1 class="title">GEMINI AI PRO + 5TB + ANTIGRAVITY</h1>
      <p class="subtitle">
        18 Months Uninterrupted Access On Your Personal Email &bull; Single-Click Activation
      </p>
    </div>

    <!-- Hero Poster Showcase (Full 1:1 Creative) -->
    <div class="hero-poster-card">
      <img src="/gemini-poster.jpg?v={cache_buster}" alt="Gemini AI Pro 18 Months VIP Offer - Prime Hub" class="hero-poster-img">
      <div class="poster-footer-bar">
        <span>🔒 <span class="hl">100% Matching Ad Deal:</span> Instant Redeem On Personal Email &bull; ₹199 Only</span>
      </div>
    </div>

    <!-- Primary Immediate CTA Button -->
    <button id="cta-button-top" class="cta-btn" onclick="openTelegramBot(event)">
      👉 Claim 18-Month Plan for ₹199
      <span class="cta-subtext">Instant Automated Delivery via @PrimeHubUs_Bot</span>
    </button>

    <!-- Main Offer Card -->
    <div class="deal-card" id="mainOffer">
      <!-- Countdown & Scarcity -->
      <div class="timer-bar">
        <span>🔥 Promo Link Discount Ends In:</span>
        <span class="countdown" id="timer">14:59</span>
      </div>

      <div class="stock-progress-wrap">
        <div class="stock-header">
          <span>Batch Status: <strong style="color: #60a5fa;">Selling Fast ⚡</strong></span>
          <span class="stock-highlight">🔥 Only <span id="dynamicStock">289</span> Codes Remaining</span>
        </div>
        <div class="stock-track">
          <div class="stock-fill" id="stockFillBar" style="width: 72%;"></div>
        </div>
      </div>

      <!-- Price Anchor Box -->
      <div class="price-box">
        <div class="price-original">Original: ₹35,999 &bull; Regular Store: ₹799</div>
        <div class="price-highlight">JUST ₹199 ONLY!</div>
        <div class="price-tagline">⚡ One-Time Payment &bull; Direct On Personal Email &bull; No Passwords Needed</div>
      </div>

      <div style="font-size: 13px; font-weight: 800; color: #e2e8f0; margin-bottom: 12px; letter-spacing: 0.3px;">
        🎁 YOUR 18-MONTH PREMIUM PACKAGE INCLUDES:
      </div>

      <ul class="features">
        <li class="feature-item">
          <span class="feature-icon">💾</span>
          <div><strong>5TB Premium Cloud Storage:</strong> Full space for Google Drive + Gmail + Google Photos.</div>
        </li>
        <li class="feature-item">
          <span class="feature-icon">🧠</span>
          <div><strong>Gemini Advanced AI:</strong> Gemini 1.5 Pro multimodal reasoning & 2,000,000 token context.</div>
        </li>
        <li class="feature-item">
          <span class="feature-icon">🍌</span>
          <div><strong>Nano Banana Pro & Veo 3:</strong> Next-generation AI video creation & cinema image tools.</div>
        </li>
        <li class="feature-item">
          <span class="feature-icon">🌊</span>
          <div><strong>Google Flow & Whisk:</strong> 1,000 generation credits refreshed every single month.</div>
        </li>
        <li class="feature-item">
          <span class="feature-icon">🚀</span>
          <div><strong>Antigravity Access & NotebookLM:</strong> Deep Research tools, source synthesis & audio podcasts.</div>
        </li>
        <li class="feature-item">
          <span class="feature-icon">💻</span>
          <div><strong>Gemini Code Assist & CLI:</strong> Enterprise terminal CLI, deep refactoring & coding engine.</div>
        </li>
        <li class="feature-item">
          <span class="feature-icon">👨‍👩‍👧‍👦</span>
          <div><strong>Add Up to 5 Family Members:</strong> Share your 5TB plan with loved ones at zero extra cost.</div>
        </li>
        <li class="feature-item">
          <span class="feature-icon">🛡️</span>
          <div><strong>1-Month Replacement Warranty:</strong> Full 1-month replacement guarantee & 24/7 dedicated support.</div>
        </li>
      </ul>

      <!-- 4 Simple Steps -->
      <div class="steps-card">
        <div style="font-size: 13px; font-weight: 800; color: #f59e0b; margin-bottom: 10px;">⚡ 4 Simple Activation Steps:</div>
        <div class="step-line">
          <span class="step-num">1</span>
          <span>Tap <strong>"Claim on Telegram"</strong> to launch @PrimeHubUs_Bot</span>
        </div>
        <div class="step-line">
          <span class="step-num">2</span>
          <span>Select 18-Month Plan & complete instant UPI payment (₹199)</span>
        </div>
        <div class="step-line">
          <span class="step-num">3</span>
          <span>Bot sends your official Google Redeem Code link automatically</span>
        </div>
        <div class="step-line">
          <span class="step-num">4</span>
          <span>Open link in Chrome, select your personal Gmail & click <strong>"Activate Plan"</strong> &mdash; Done!</span>
        </div>
      </div>

      <button id="cta-button" class="cta-btn" onclick="openTelegramBot(event)">
        👉 Click Here to Open Bot & Claim (₹199)
        <span class="cta-subtext">Instant Auto-Delivery &bull; UPI / Crypto / Binance Accepted</span>
      </button>

      <div class="guarantees">
        <div class="guarantee-item">⚡ 1-Click Redeem</div>
        <div class="guarantee-item">🛡️ 1-Month Warranty</div>
        <div class="guarantee-item">🔒 100% Private Email</div>
      </div>
    </div>

    <!-- Comparison Table -->
    <div class="section-title">📊 Why Choose Our Exclusive ₹199 Deal?</div>
    <table class="comp-table">
      <thead>
        <tr>
          <th>Plan Feature</th>
          <th>Official Google</th>
          <th>Prime Hub VIP</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><strong>Cost (18 Months)</strong></td>
          <td class="loser">₹35,999</td>
          <td class="winner">₹199 (Save 99%)</td>
        </tr>
        <tr>
          <td><strong>Cloud Storage</strong></td>
          <td class="loser">2 TB</td>
          <td class="winner">5 TB Storage</td>
        </tr>
        <tr>
          <td><strong>Activation</strong></td>
          <td class="loser">Auto-Debit Credit Card</td>
          <td class="winner">Single Click on Email</td>
        </tr>
        <tr>
          <td><strong>Family Sharing / Access</strong></td>
          <td class="loser">Individual Only</td>
          <td class="winner">Individual + Add 5 Family Members</td>
        </tr>
        <tr>
          <td><strong>Warranty & Support</strong></td>
          <td class="loser">Standard FAQ</td>
          <td class="winner">1-Month Full Warranty</td>
        </tr>
      </tbody>
    </table>

    <!-- Verified Customer Reviews -->
    <div class="section-title">💬 Verified Customer Feedback</div>
    
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

    <div class="reviews-card">
      <div class="review-header">
        <span class="reviewer">Karan V. • Full-Stack Developer</span>
        <span class="stars">★★★★★</span>
      </div>
      <p class="review-text">
        "The 2M context and Gemini Code Assist are a lifesaver. Plus 5TB Drive for all my client backups."
      </p>
    </div>

    <!-- FAQ Accordion -->
    <div class="section-title">❓ Frequently Asked Questions</div>

    <div class="faq-item" onclick="toggleFaq(this)">
      <div class="faq-q">
        <span>Is this activated on my own email or a shared login?</span>
        <span class="faq-toggle">+</span>
      </div>
      <div class="faq-a">
        It is activated directly on YOUR personal Google email account. You receive an official Google Redeem Code link, open it in Chrome, and activate it yourself. No passwords, no credentials, and no shared logins.
      </div>
    </div>

    <div class="faq-item" onclick="toggleFaq(this)">
      <div class="faq-q">
        <span>Do I need to share my Google password?</span>
        <span class="faq-toggle">+</span>
      </div>
      <div class="faq-a">
        Never! We strictly maintain a Zero-Password Policy. You activate the subscription yourself on Google's official page with a single click.
      </div>
    </div>

    <div class="faq-item" onclick="toggleFaq(this)">
      <div class="faq-q">
        <span>What is your replacement warranty?</span>
        <span class="faq-toggle">+</span>
      </div>
      <div class="faq-a">
        We provide a 1-Month Full Replacement Warranty. If you face any issues within 30 days of purchase, our 24/7 Telegram support team will resolve it or provide a replacement link immediately.
      </div>
    </div>

    <div class="faq-item" onclick="toggleFaq(this)">
      <div class="faq-q">
        <span>Which payment methods are accepted?</span>
        <span class="faq-toggle">+</span>
      </div>
      <div class="faq-a">
        Our bot supports instant automated verification for UPI (PhonePe, Google Pay, Paytm, BHIM, QR scan), Binance Pay, USDT (BEP20 / TRC20), and Store Wallet balance.
      </div>
    </div>

    <div class="faq-item" onclick="toggleFaq(this)">
      <div class="faq-q">
        <span>How long does delivery take?</span>
        <span class="faq-toggle">+</span>
      </div>
      <div class="faq-a">
        Delivery is 100% automated by our Telegram bot (@PrimeHubUs_Bot). As soon as your UPI or Crypto payment is verified, your redeem link is delivered within 30 to 60 seconds.
      </div>
    </div>

    <!-- Footer -->
    <div class="footer">
      <p>&copy; {settings.STORE_NAME}. All rights reserved.</p>
      <p>Official automated delivery powered by Team Prime Hub on Telegram.</p>
    </div>

  </div>

  <!-- Sticky Bottom Bar on Mobile -->
  <div class="sticky-bar" id="stickyBar">
    <div class="sticky-content">
      <div class="sticky-price-wrap">
        <div>
          <span class="sticky-price">₹199</span>
          <span class="sticky-strike">₹35,999</span>
        </div>
        <span class="sticky-sub">18M &bull; 5TB on Your Email</span>
      </div>
      <button class="sticky-cta-btn" onclick="openTelegramBot(event)">
        Claim on Telegram ⚡
      </button>
    </div>
  </div>

  <!-- Live Buyer Notification Toast -->
  <div class="buyer-toast" id="buyerToast">
    <div class="toast-dot"></div>
    <div class="toast-text">
      <strong id="toastName">Rahul S. from Bangalore</strong><br>
      <span>Activated 18M Gemini + 5TB &bull; <span class="toast-time" id="toastTime">2m ago</span></span>
    </div>
  </div>

  <script>
    // Dynamic random stock counter: always 150+ codes remaining (e.g. 165 to 295)
    (function() {{
      const minCodes = 165;
      const maxCodes = 295;
      const randomCodes = Math.floor(Math.random() * (maxCodes - minCodes + 1)) + minCodes;
      const stockEl = document.getElementById('dynamicStock');
      const barEl = document.getElementById('stockFillBar');
      if (stockEl) stockEl.textContent = randomCodes;
      if (barEl) {{
        const pct = Math.min(88, Math.max(50, Math.round(((500 - randomCodes) / 500) * 100)));
        barEl.style.width = pct + '%';
      }}
    }})();

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

    // Sticky Bottom Bar scroll listener
    const stickyBar = document.getElementById('stickyBar');
    const mainOffer = document.getElementById('mainOffer');
    window.addEventListener('scroll', function() {{
      if (mainOffer) {{
        const rect = mainOffer.getBoundingClientRect();
        if (rect.bottom < 100) {{
          stickyBar.classList.add('visible');
        }} else {{
          stickyBar.classList.remove('visible');
        }}
      }}
    }});

    // Live Social Proof Notification Popups
    const buyers = [
      {{ name: "Rahul S. from Bangalore", time: "2m ago" }},
      {{ name: "Priya M. from Mumbai", time: "4m ago" }},
      {{ name: "Vikram R. from Delhi NCR", time: "7m ago" }},
      {{ name: "Ananya K. from Hyderabad", time: "9m ago" }},
      {{ name: "Sameer T. from Pune", time: "11m ago" }},
      {{ name: "Aditya P. from Chennai", time: "14m ago" }},
      {{ name: "Kavita D. from Kolkata", time: "18m ago" }}
    ];
    let toastIndex = 0;
    const toast = document.getElementById('buyerToast');
    const toastName = document.getElementById('toastName');
    const toastTime = document.getElementById('toastTime');

    function showNextToast() {{
      if (!toast) return;
      const b = buyers[toastIndex % buyers.length];
      toastName.textContent = b.name;
      toastTime.textContent = b.time;
      toast.classList.add('show');

      setTimeout(function() {{
        toast.classList.remove('show');
      }}, 4000);

      toastIndex++;
    }}
    setTimeout(function() {{
      showNextToast();
      setInterval(showNextToast, 9000);
    }}, 2500);

    // Telegram Bot Deep-Link Redirector with Pixel Tracking
    function openTelegramBot(e) {{
      if (e && e.preventDefault) e.preventDefault();

      try {{
        if (typeof fbq === 'function') {{
          fbq('track', 'Lead', {{
            content_name: 'Gemini AI Pro 18 Months + 5TB',
            content_category: 'AI Subscription',
            value: 199.00,
            currency: 'INR'
          }});
          fbq('track', 'InitiateCheckout', {{
            content_name: 'Gemini AI Pro 18 Months + 5TB',
            value: 199.00,
            currency: 'INR'
          }});
        }}
      }} catch(err) {{
        console.warn('Pixel track error', err);
      }}

      const deepLink = "{deep_link}";
      const webFallback = "{web_fallback}";

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
