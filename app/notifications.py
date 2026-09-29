"""
HeatSense Notification & Alert Dispatch Service
Integrated with SMTP for Email and Telegram for instant messaging.
"""

import os
import re
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests

logger = logging.getLogger("heatsense.notifications")

# Email Configuration (SMTP)
ALERT_EMAIL_FROM = os.getenv("ALERT_EMAIL_FROM", "alerts@heatsense.org").strip()
SMTP_SERVER      = os.getenv("SMTP_SERVER", "").strip()
SMTP_PORT        = int(os.getenv("SMTP_PORT", 587))
SMTP_USER        = os.getenv("SMTP_USER", "").strip()
SMTP_PASSWORD    = os.getenv("SMTP_PASSWORD", "").strip()

# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "").strip()


def send_telegram_message(message: str, chat_id: str = None, parse_mode: str = "HTML") -> dict:
    """
    Sends a Telegram message via the HeatSense Bot (@HeatSense_HealthBot).

    Returns:
        dict: {'success': bool, 'message_id': int, 'error': str}
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN).strip()
    target_chat = (chat_id or os.getenv("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID)).strip()

    if not token:
        return {'success': False, 'error': 'TELEGRAM_BOT_TOKEN is not configured in .env'}
    if not target_chat:
        return {'success': False, 'error': 'TELEGRAM_CHAT_ID is not configured in .env'}

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": target_chat,
        "text": message,
        "parse_mode": parse_mode,
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        data = resp.json()
        if data.get("ok"):
            msg_id = data["result"]["message_id"]
            logger.info(f"[Telegram Sent] message_id={msg_id} chat_id={target_chat}")
            return {'success': True, 'message_id': msg_id, 'chat_id': target_chat}
        else:
            err = data.get("description", "Unknown Telegram API error")
            logger.error(f"[Telegram Error] {err}")
            return {'success': False, 'error': err}
    except Exception as e:
        logger.error(f"[Telegram Exception] {e}")
        return {'success': False, 'error': str(e)}


def send_alert_email(to_email: str, subject: str, text_content: str, html_content: str = None) -> dict:
    """
    Dispatches an Email alert via SMTP if credentials are configured in .env.
    """
    to_email = (to_email or "").strip()
    if not to_email or "@" not in to_email:
        return {'success': False, 'error': f"Invalid recipient email: '{to_email}'"}

    from_email = os.getenv("ALERT_EMAIL_FROM", ALERT_EMAIL_FROM).strip() or "alerts@heatsense.org"
    smtp_server = os.getenv("SMTP_SERVER", "").strip()
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_password = os.getenv("SMTP_PASSWORD", "").strip()
    smtp_port = int(os.getenv("SMTP_PORT", 587))

    if smtp_server and smtp_user and smtp_password:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = from_email
            msg["To"] = to_email

            part1 = MIMEText(text_content, "plain")
            msg.attach(part1)
            if html_content:
                part2 = MIMEText(html_content, "html")
                msg.attach(part2)

            with smtplib.SMTP(smtp_server, smtp_port, timeout=10) as server:
                server.starttls()
                server.login(smtp_user, smtp_password)
                server.sendmail(from_email, to_email, msg.as_string())

            logger.info(f"[SMTP Email Sent] To={to_email} Subject={subject}")
            return {'success': True, 'provider': 'SMTP', 'server': smtp_server, 'recipient': to_email}
        except Exception as e:
            logger.error(f"[SMTP Error] {e}")
            return {'success': False, 'error': f"SMTP dispatch failed: {str(e)}"}

    return {
        'success': False,
        'skipped': True,
        'reason': 'No SMTP email service configured'
    }


def dispatch_heat_alert(
    district_or_location: str,
    risk_level: str,
    advisory: str,
    hhri: float = None,
    chi: float = None,
    temperature: float = None,
    precautions: list = None,
    to_phone: str = None,
    to_email: str = None,
    sms_enabled: bool = True,
    email_enabled: bool = True,
    is_test: bool = False,
) -> dict:
    """
    Formats and dispatches customized HeatSense health risk alerts across
    Telegram and Email for the registered user.
    """
    results = {}

    # Build metric summary strings from actual HeatSense data
    metrics_parts = []
    if temperature is not None:
        metrics_parts.append(f"Temp: {temperature:.1f}°C")
    if chi is not None:
        metrics_parts.append(f"CHI: {chi:.3f}")
    if hhri is not None:
        metrics_parts.append(f"HHRI: {hhri:.3f}")
    metrics_line = " | ".join(metrics_parts) if metrics_parts else "Elevated Thermal Index"

    # Default recommended precautions if none provided
    if not precautions:
        if risk_level in ('Very High', 'Severe'):
            precautions = [
                "HALT all strenuous outdoor activity between 10 AM and 5 PM",
                "Move to air-conditioned or well-ventilated cooling spaces immediately",
                "Hydrate continuously with 3+ litres of water or ORS electrolyte fluids",
                "Check immediately on senior citizens, infants, and outdoor workers",
                "Call 108 (Ambulance) or 104 (Health Helpline) for dizziness, cramps or vomiting"
            ]
        elif risk_level == 'High':
            precautions = [
                "Stay indoors during peak solar hours (11 AM to 4 PM)",
                "Drink at least 3 litres of water or lemon water/ORS daily",
                "Wear light, loose cotton clothing and protect head/eyes with hats/umbrellas",
                "Take scheduled cooling breaks in shaded areas if working outdoors",
                "Contact Arogya Sahayavani 104 for heat-related symptoms or guidance"
            ]
        else:
            precautions = [
                "Drink plenty of water before feeling thirsty",
                "Avoid prolonged direct sun exposure during midday",
                "Keep living spaces ventilated and shaded"
            ]

    precautions_bullets = "\n".join(f"• {p}" for p in precautions[:4])
    precautions_html = "".join(f"<li>{p}</li>" for p in precautions)

    tag = "[TEST NOTIFICATION] " if is_test else ""
    risk_color = '#ef4444' if risk_level in ('Very High', 'Severe') else ('#f97316' if risk_level == 'High' else '#f59e0b')

    # ── 1. Alert Text ─────────────────────────────────────────────────────
    sms_text = (
        f"HeatSense High-Heat Alert: High heat conditions are reported in {district_or_location}. "
        f"Please stay hydrated, avoid strenuous outdoor activity during peak heat, and follow local advisories."
    )

    # ── 2. Email Subject & Body ───────────────────────────────────────────
    email_subject = (
        f"{tag}🌡️ HeatSense Alert: {risk_level} Heat-Health Risk in {district_or_location}"
        f" ({metrics_line})"
    )

    email_text = (
        f"{tag}HEATSENSE HEAT-HEALTH RISK ALERT\n"
        f"==================================================\n"
        f"Target Location : {district_or_location}\n"
        f"Risk Severity   : {risk_level}\n"
        f"Heat Indicators : {metrics_line}\n\n"
        f"Health Advisory:\n{advisory}\n\n"
        f"Recommended Precautionary Measures:\n{precautions_bullets}\n\n"
        f"Emergency Helplines (Karnataka):\n"
        f"• Health Advisory (Arogya Sahayavani): 104\n"
        f"• Ambulance Emergency Services        : 108\n"
        f"• State Disaster Control Center       : 1070\n"
        f"• BBMP Heat Helpline (Bengaluru)     : 080-22221188\n\n"
        f"– HeatSense Automated Environmental Health Monitoring Platform\n"
    )

    email_html = (
        "<div style=\"font-family:'Segoe UI',Helvetica,Arial,sans-serif;max-width:620px;"
        "margin:0 auto;background:#111827;color:#f3f4f6;border-radius:14px;"
        "overflow:hidden;border:1px solid #374151;box-shadow:0 10px 25px rgba(0,0,0,0.5);\">"
        "<div style=\"background:linear-gradient(135deg,#f97316 0%,#dc2626 100%);padding:26px;text-align:center;\">"
        f"<h1 style=\"margin:0;color:white;font-size:22px;font-weight:800;letter-spacing:-0.5px;\">"
        f"{'🧪 TEST NOTIFICATION: ' if is_test else ''}🌡️ Heat-Health Risk Alert</h1>"
        "<p style=\"margin:8px 0 0;color:rgba(255,255,255,0.92);font-size:13px;\">"
        "HeatSense Automated Early Warning &amp; Mitigation Platform</p>"
        "</div><div style=\"padding:24px;\">"
        f"<div style=\"background:#1f2937;padding:18px;border-radius:10px;"
        f"border-left:5px solid {risk_color};margin-bottom:20px;\">"
        f"<div style=\"font-size:12px;color:#9ca3af;text-transform:uppercase;letter-spacing:1px;font-weight:600;\">Monitored Location</div>"
        f"<h2 style=\"margin:4px 0 10px;color:#f97316;font-size:20px;\">📍 {district_or_location}</h2>"
        f"<div style=\"display:flex;gap:12px;flex-wrap:wrap;font-size:14px;color:#e5e7eb;\">"
        f"<span>Risk Level: <strong style=\"color:{risk_color};\">{risk_level}</strong></span> &bull; "
        f"<span><strong>{metrics_line}</strong></span>"
        f"</div></div>"
        "<h3 style=\"color:#f3f4f6;font-size:15px;margin:0 0 8px;font-weight:700;\">"
        "⚠️ Clinical Health Advisory</h3>"
        f"<p style=\"color:#d1d5db;line-height:1.65;font-size:14px;"
        f"background:#1e293b;padding:14px;border-radius:8px;margin:0 0 20px;\">{advisory}</p>"
        "<h3 style=\"color:#f3f4f6;font-size:15px;margin:0 0 10px;font-weight:700;\">"
        "🛡️ Recommended Precautions</h3>"
        f"<ul style=\"color:#d1d5db;font-size:13.5px;line-height:1.85;padding-left:22px;margin:0 0 22px;\">"
        f"{precautions_html}"
        "</ul>"
        "<div style=\"padding:16px;background:#1f2937;border-radius:10px;border:1px solid rgba(249,115,22,0.25);\">"
        "<h4 style=\"margin:0 0 10px;color:#f97316;font-size:13.5px;font-weight:700;\">"
        "🚨 Karnataka Emergency Health Helplines</h4>"
        "<p style=\"margin:3px 0;font-size:13px;color:#cbd5e1;\">"
        "• Arogya Sahayavani (Health Advice): <strong style=\"color:white;\">104</strong></p>"
        "<p style=\"margin:3px 0;font-size:13px;color:#cbd5e1;\">"
        "• Emergency Medical Services (Ambulance): <strong style=\"color:white;\">108</strong></p>"
        "<p style=\"margin:3px 0;font-size:13px;color:#cbd5e1;\">"
        "• State Disaster Management Control: <strong style=\"color:white;\">1070</strong></p>"
        "<p style=\"margin:3px 0;font-size:13px;color:#cbd5e1;\">"
        "• BBMP Heat Helpline (Bengaluru): <strong style=\"color:white;\">080-22221188</strong></p>"
        "</div></div>"
        "<div style=\"background:#0f172a;padding:14px;text-align:center;"
        "font-size:11.5px;color:#64748b;border-top:1px solid rgba(255,255,255,0.06);\">"
        "Delivered securely to your registered account by HeatSense Automated Monitoring Platform"
        "</div></div>"
    )

    # ── 3. Send Email (if email provided & user enabled)
    if to_email:
        if email_enabled:
            results['email'] = send_alert_email(to_email, email_subject, email_text, email_html)
        else:
            results['email'] = {'success': False, 'skipped': True, 'reason': 'Email alerts disabled in your notification settings'}
    else:
        results['email'] = {'success': False, 'skipped': True, 'reason': 'No email address registered in database'}

    # ── 5. Send Telegram message via @HeatSense_HealthBot ─────────────────
    risk_emoji = '🔴' if risk_level in ('Very High', 'Severe') else ('🟠' if risk_level == 'High' else '🟡')
    test_tag   = '🧪 <b>[TEST]</b>\n' if is_test else ''
    tg_message = (
        f"{test_tag}"
        f"{risk_emoji} <b>HeatSense Heat-Health Alert</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📍 <b>Location:</b> {district_or_location}\n"
        f"⚠️ <b>Risk Level:</b> {risk_level}\n"
        f"🌡️ <b>Metrics:</b> {metrics_line}\n\n"
        f"📋 <b>Advisory:</b>\n{advisory}\n\n"
        f"🛡️ <b>Stay Safe:</b>\n"
        + "\n".join(f"• {p}" for p in (precautions or [])[:3]) +
        f"\n\n🚨 <b>Emergency:</b> Ambulance 108 | Health 104 | Disaster 1070"
    )
    results['telegram'] = send_telegram_message(tg_message)

    return results


def send_custom_alert(
    sms_text: str,
    email_subject: str,
    email_body: str,
    to_phone: str = None,
    to_email: str = None,
    sms_enabled: bool = True,
    email_enabled: bool = True,
) -> dict:
    """
    Send a custom alert to the registered user via Telegram.
    Respects user notification settings.
    """
    results = {}

    # Email
    if to_email:
        if email_enabled:
            import html as html_mod
            body_html_safe = html_mod.escape(email_body).replace('\n', '<br>')

            email_html = (
                '<div style="font-family:\'Segoe UI\',Helvetica,Arial,sans-serif;'
                'max-width:600px;margin:0 auto;background:#111827;color:#f3f4f6;'
                'border-radius:12px;overflow:hidden;border:1px solid #374151;">'
                '<div style="background:linear-gradient(135deg,#f97316,#ea580c);'
                'padding:24px;text-align:center;">'
                '<h1 style="margin:0;color:white;font-size:22px;font-weight:800;">'
                '🌡️ HeatSense Alert</h1>'
                '<p style="margin:6px 0 0;color:rgba(255,255,255,0.9);font-size:13px;">'
                'Urban Heat Island &amp; Health Warning System</p></div>'
                '<div style="padding:24px;">'
                f'<div style="color:#e5e7eb;line-height:1.7;font-size:14px;">'
                f'{body_html_safe}</div></div>'
                '<div style="background:#0f172a;padding:14px;text-align:center;'
                'font-size:11px;color:#64748b;">'
                'HeatSense Monitoring Platform'
                '</div></div>'
            )

            results['email'] = send_alert_email(
                to_email, email_subject, email_body, email_html
            )
        else:
            results['email'] = {'success': False, 'skipped': True, 'reason': 'Email alerts disabled in your notification settings'}
    else:
        results['email'] = {'success': False, 'skipped': True, 'reason': 'No email address registered in database'}

    # Telegram
    tg_body = (sms_text or email_body or '').strip()
    results['telegram'] = send_telegram_message(
        f"🌡️ <b>HeatSense Alert</b>\n\n{tg_body}"
    )

    return results
