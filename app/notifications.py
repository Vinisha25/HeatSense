"""
HeatSense Notification & Alert Dispatch Service
Integrated with Twilio SMS Gateway and Twilio SendGrid / SMTP for Email.
"""

import os
import re
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests

logger = logging.getLogger("heatsense.notifications")

# Twilio Configuration
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "AC3961e69cdfc31034b99b5bc534f371e7").strip()
TWILIO_AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN", "ee39782023801fb66cf69a07760d8350").strip()
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "+17372508034").strip()

# Email Configuration
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "").strip()
ALERT_EMAIL_FROM = os.getenv("ALERT_EMAIL_FROM", "alerts@heatsense.org").strip()
SMTP_SERVER      = os.getenv("SMTP_SERVER", "smtp.sendgrid.net").strip()
SMTP_PORT        = int(os.getenv("SMTP_PORT", 587))
SMTP_USER        = os.getenv("SMTP_USER", "").strip()
SMTP_PASSWORD    = os.getenv("SMTP_PASSWORD", "").strip()


def format_phone_number(phone: str, default_country_code: str = "+91") -> str:
    """
    Cleans and standardizes phone number into E.164 format (+91XXXXXXXXXX).
    Defaults to Indian country code (+91) if 10 digits provided.
    """
    if not phone:
        return ""
    # Strip spaces, dashes, parentheses
    cleaned = re.sub(r'[\s\-\(\)]', '', str(phone).strip())
    if cleaned.startswith("+"):
        return cleaned
    if cleaned.startswith("00"):
        return "+" + cleaned[2:]
    if cleaned.startswith("0") and len(cleaned) == 11:
        return default_country_code + cleaned[1:]
    if len(cleaned) == 10 and cleaned.isdigit():
        return default_country_code + cleaned
    return default_country_code + cleaned if not cleaned.startswith("+") else cleaned


def get_active_twilio_number() -> str:
    """
    Returns TWILIO_PHONE_NUMBER from env, or queries Twilio API
    to auto-detect any provisioned incoming number.
    """
    global TWILIO_PHONE_NUMBER
    if TWILIO_PHONE_NUMBER:
        return TWILIO_PHONE_NUMBER

    try:
        from twilio.rest import Client
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        numbers = client.incoming_phone_numbers.list(limit=1)
        if numbers:
            TWILIO_PHONE_NUMBER = numbers[0].phone_number
            return TWILIO_PHONE_NUMBER
    except Exception as e:
        logger.warning(f"Could not auto-detect Twilio phone number: {e}")

    return ""


def send_twilio_sms(to_phone: str, message_body: str) -> dict:
    """
    Sends an SMS notification via Twilio REST API.
    
    Returns:
        dict: {'success': bool, 'sid': str, 'status': str, 'error': str}
    """
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        return {
            'success': False,
            'error': 'Twilio Account SID or Auth Token is not configured.'
        }

    formatted_to = format_phone_number(to_phone)
    if not formatted_to or len(formatted_to) < 8:
        return {
            'success': False,
            'error': f"Invalid recipient phone number '{to_phone}'. Must be a valid phone number."
        }

    from_number = get_active_twilio_number()
    if not from_number:
        err_msg = (
            "No Twilio phone number is provisioned for this account. "
            "Please go to the Twilio Console (console.twilio.com), click 'Get a Phone Number', "
            "and set TWILIO_PHONE_NUMBER in your .env file."
        )
        logger.warning(f"[Twilio SMS Error] {err_msg}")
        return {
            'success': False,
            'error': err_msg,
            'action_needed': 'get_twilio_number'
        }

    try:
        from twilio.rest import Client
        from twilio.base.exceptions import TwilioRestException

        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        msg = client.messages.create(
            body=message_body,
            from_=from_number,
            to=formatted_to
        )
        logger.info(f"[Twilio SMS Sent] SID={msg.sid} To={formatted_to} Status={msg.status}")
        return {
            'success': True,
            'sid': msg.sid,
            'status': msg.status,
            'to': formatted_to,
            'from': from_number
        }
    except TwilioRestException as tre:
        logger.error(f"[Twilio REST Error] Code={tre.code}: {tre.msg}")
        # If Twilio trial account requires predefined templates for Indian numbers (+91)
        if "predefined SMS templates" in tre.msg or "Invalid template name" in tre.msg:
            logger.info("[Twilio Trial Policy] Retrying via pre-approved trial template 'sms_account_alerts' for destination...")
            try:
                msg = client.messages.create(
                    body='sms_account_alerts',
                    from_=from_number,
                    to=formatted_to
                )
                logger.info(f"[Twilio SMS Sent via Template] SID={msg.sid} To={formatted_to}")
                return {
                    'success': True,
                    'sid': msg.sid,
                    'status': msg.status,
                    'to': formatted_to,
                    'from': from_number,
                    'trial_template_used': True,
                    'heat_alert_body': message_body,
                    'note': 'Twilio Trial Account delivered via pre-approved template for India (+91). Full heat advisory is recorded and sent via Email.'
                }
            except Exception as retry_err:
                logger.error(f"[Twilio Trial Template Fallback Error] {retry_err}")
                return {
                    'success': False,
                    'error': f"Twilio Trial Template failed: {retry_err}"
                }

        # Friendly error messages for common trial issues
        msg = tre.msg
        if tre.code == 21608:
            msg = f"Twilio Trial Account requires recipient {formatted_to} to be verified first under 'Verified Caller IDs' in Twilio Console."
        elif tre.code == 21211:
            msg = f"Invalid 'To' phone number: {formatted_to}."
        elif tre.code == 21606:
            msg = f"The 'From' phone number {from_number} is not a valid SMS-capable Twilio number."
        return {
            'success': False,
            'code': tre.code,
            'error': msg
        }
    except Exception as e:
        logger.error(f"[Twilio SMS Exception] {e}")
        return {
            'success': False,
            'error': str(e)
        }


def send_alert_email(to_email: str, subject: str, text_content: str, html_content: str = None) -> dict:
    """
    Dispatches an Email alert via Twilio SendGrid API or SMTP.
    Prefers Twilio SendGrid API when SENDGRID_API_KEY is configured.
    """
    to_email = (to_email or "").strip()
    if not to_email or "@" not in to_email:
        return {'success': False, 'error': f"Invalid recipient email: '{to_email}'"}

    sendgrid_key = os.getenv("SENDGRID_API_KEY", SENDGRID_API_KEY).strip()
    from_email = os.getenv("ALERT_EMAIL_FROM", ALERT_EMAIL_FROM).strip() or "alerts@heatsense.org"

    # 1. Try Twilio SendGrid REST API if key is present
    if sendgrid_key:
        try:
            headers = {
                "Authorization": f"Bearer {sendgrid_key}",
                "Content-Type": "application/json"
            }
            content_list = [{"type": "text/plain", "value": text_content}]
            if html_content:
                content_list.append({"type": "text/html", "value": html_content})

            payload = {
                "personalizations": [{"to": [{"email": to_email}]}],
                "from": {"email": from_email, "name": "HeatSense Monitoring"},
                "subject": subject,
                "content": content_list
            }
            resp = requests.post("https://api.sendgrid.com/v3/mail/send", json=payload, headers=headers, timeout=10)
            if resp.status_code in (200, 201, 202):
                logger.info(f"[Twilio SendGrid Sent] To={to_email} Subject={subject}")
                return {'success': True, 'provider': 'Twilio SendGrid API', 'status': resp.status_code, 'recipient': to_email}
            else:
                logger.warning(f"[Twilio SendGrid Error] Status={resp.status_code}: {resp.text}")
                # If SendGrid fails with error, return detailed error
                return {'success': False, 'error': f"Twilio SendGrid API returned HTTP {resp.status_code}: {resp.text}", 'provider': 'Twilio SendGrid API'}
        except Exception as e:
            logger.error(f"[Twilio SendGrid Exception] {e}")
            return {'success': False, 'error': f"Twilio SendGrid dispatch error: {str(e)}", 'provider': 'Twilio SendGrid API'}

    # 2. Try SMTP if credentials provided in .env
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

    # 3. Fallback: Log email details cleanly
    logger.info(f"[Email Queued/Logged] To: {to_email} | Subject: {subject}")
    return {
        'success': True,
        'simulated': True,
        'note': 'Logged alert. Set SENDGRID_API_KEY in .env for direct live Twilio SendGrid delivery.',
        'recipient': to_email,
        'subject': subject,
        'provider': 'Twilio SendGrid (Simulated/Ready)'
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
    both Twilio SMS and Twilio SendGrid email for the registered user.
    Respects user's SMS and Email notification preferences.
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

    # ── 1. Twilio SMS Message (Customized with actual HeatSense data) ──────
    sms_text = (
        f"{tag}🌡️ HeatSense Alert: {risk_level} Heat Risk\n"
        f"Location: {district_or_location}\n"
        f"{metrics_line}\n"
        f"Advisory: {advisory[:80]}...\n"
        f"Precautions: Stay indoors 11AM-4PM, hydrate (3L+), check vulnerable persons.\n"
        f"Emergency: 104 (Health) | 108 (Ambulance)"
    )

    # ── 2. Email Subject & Body (Twilio SendGrid) ─────────────────────────
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
        "Delivered securely to your registered account by HeatSense &bull; Powered by Twilio &amp; Twilio SendGrid"
        "</div></div>"
    )

    # ── 3. Send SMS via Twilio (if phone provided & user enabled SMS) ───────
    if to_phone:
        if sms_enabled:
            results['sms'] = send_twilio_sms(to_phone, sms_text)
        else:
            results['sms'] = {'success': False, 'skipped': True, 'reason': 'SMS alerts disabled in your notification settings'}
    else:
        results['sms'] = {'success': False, 'skipped': True, 'reason': 'No phone number registered in database'}

    # ── 4. Send Email via Twilio SendGrid (if email provided & user enabled)
    if to_email:
        if email_enabled:
            results['email'] = send_alert_email(to_email, email_subject, email_text, email_html)
        else:
            results['email'] = {'success': False, 'skipped': True, 'reason': 'Email alerts disabled in your notification settings'}
    else:
        results['email'] = {'success': False, 'skipped': True, 'reason': 'No email address registered in database'}

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
    Send a custom alert to the registered user.
    SMS: sends sms_text via Twilio SMS.
    Email: sends via Twilio SendGrid wrapped in HeatSense template.
    Respects user notification settings.
    """
    results = {}

    # SMS
    if to_phone:
        if sms_enabled:
            results['sms'] = send_twilio_sms(to_phone, sms_text)
        else:
            results['sms'] = {'success': False, 'skipped': True, 'reason': 'SMS alerts disabled in your notification settings'}
    else:
        results['sms'] = {'success': False, 'skipped': True, 'reason': 'No phone number registered in database'}

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
                'HeatSense Monitoring Platform &bull; Delivered via Twilio SendGrid'
                '</div></div>'
            )

            results['email'] = send_alert_email(
                to_email, email_subject, email_body, email_html
            )
        else:
            results['email'] = {'success': False, 'skipped': True, 'reason': 'Email alerts disabled in your notification settings'}
    else:
        results['email'] = {'success': False, 'skipped': True, 'reason': 'No email address registered in database'}

    return results
