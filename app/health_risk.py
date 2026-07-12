"""
HeatSense Health Risk & Alerts Module — Module 7.

Computes district-level Heat Health Risk Index (HHRI) by combining:
  - Composite Heat Index (CHI) from the RF model
  - Air temperature and humidity
  - Population vulnerability (proxy by district)
  - Time-of-day peak risk factor

Also manages:
  - Generating and persisting health alerts to SQLite
  - Loading active/resolved alerts for the dashboard
  - Public advisory message generation per risk tier
"""

from datetime import date, datetime

# ──────────────────────────────────────────────────────────────────────────────
# Risk tier definitions
# ──────────────────────────────────────────────────────────────────────────────

RISK_TIERS = {
    'Low': {
        'level': 1,
        'colour_class': 'success',
        'badge_bg': '#27ae60',
        'icon': '🟢',
        'advisory': (
            'Conditions are normal. Stay hydrated and avoid prolonged sun exposure '
            'during afternoon hours. No special precautions needed.'
        ),
        'action': 'Monitor',
    },
    'Moderate': {
        'level': 2,
        'colour_class': 'warning',
        'badge_bg': '#f39c12',
        'icon': '🟡',
        'advisory': (
            'Moderate heat stress expected. Vulnerable groups (elderly, children, '
            'outdoor workers) should limit exposure between 11 AM – 4 PM. '
            'Keep water intake above 3 litres/day.'
        ),
        'action': 'Caution',
    },
    'High': {
        'level': 3,
        'colour_class': 'orange',
        'badge_bg': '#e67e22',
        'icon': '🟠',
        'advisory': (
            'High heat stress alert. Avoid outdoor physical activity during peak hours. '
            'Open cooling centres in public buildings. Distribute ORS packets '
            'in high-density neighbourhoods. Farmers should irrigate at night.'
        ),
        'action': 'Alert',
    },
    'Very High': {
        'level': 4,
        'colour_class': 'danger',
        'badge_bg': '#e74c3c',
        'icon': '🔴',
        'advisory': (
            'EXTREME HEAT EVENT. Activate district heat action plan immediately. '
            'Open all cooling shelters. Issue public emergency SMS alerts. '
            'Restrict outdoor construction work. Deploy ASHA workers for door-to-door '
            'health checks in slum areas. Contact BBMP Heat Helpline: 080-22221188.'
        ),
        'action': 'Emergency',
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# HHRI Calculation
# ──────────────────────────────────────────────────────────────────────────────

def calculate_hhri(chi: float, air_temp: float, humidity: float,
                   vulnerability_index: float = 0.5) -> dict:
    """
    Computes the Heat Health Risk Index (HHRI) as a weighted composite of:
      - CHI         (40%) — already encodes multi-factor heat
      - Air temp    (25%) — direct thermal stress on the human body
      - Humidity    (20%) — reduces body cooling efficiency
      - Vulnerability (15%) — elderly / outdoor worker population fraction

    All inputs are normalised to [0, 1] before weighting.

    Args:
        chi               (float): Composite Heat Index, [0, 1].
        air_temp          (float): Air temperature in °C.
        humidity          (float): Relative humidity, %.
        vulnerability_index (float): District vulnerability proxy [0, 1].
    Returns:
        dict: hhri score, risk_level, tier metadata.
    """
    import numpy as np

    # Normalise
    air_n  = float(np.clip((air_temp  - 15.0) / 30.0, 0, 1))
    rh_n   = float(np.clip((humidity  - 20.0) / 80.0, 0, 1))
    vuln_n = float(np.clip(vulnerability_index, 0, 1))

    hhri = (chi * 0.40 + air_n * 0.25 + rh_n * 0.20 + vuln_n * 0.15)
    hhri = round(float(np.clip(hhri, 0, 1)), 4)

    # Map score to risk tier
    if hhri < 0.30:
        level = 'Low'
    elif hhri < 0.52:
        level = 'Moderate'
    elif hhri < 0.72:
        level = 'High'
    else:
        level = 'Very High'

    tier = RISK_TIERS[level]
    return {
        'hhri':             hhri,
        'risk_level':       level,
        'risk_icon':        tier['icon'],
        'colour_class':     tier['colour_class'],
        'badge_bg':         tier['badge_bg'],
        'action':           tier['action'],
        'advisory':         tier['advisory'],
        'components': {
            'chi':           round(chi, 4),
            'air_temp_norm': round(air_n, 4),
            'humidity_norm': round(rh_n, 4),
            'vulnerability': round(vuln_n, 4),
        },
    }


# ──────────────────────────────────────────────────────────────────────────────
# Alert Management
# ──────────────────────────────────────────────────────────────────────────────

def generate_alerts_for_all_districts(app):
    """
    Iterates over all districts, computes their HHRI from climatological
    feature defaults, and inserts today's alerts into the health_alerts table.
    Only generates alerts for risk level Moderate and above.
    Skips districts that already have an active alert for today.

    Args:
        app: Flask application instance (for DB access).
    Returns:
        list[dict]: All alerts generated this run.
    """
    import sqlite3
    from app.database import get_db
    from app.ml import predict_current_conditions

    today = date.today().isoformat()
    generated = []

    # Vulnerability proxies per district (based on % elderly + outdoor workers)
    VULNERABILITY = {
        'Bengaluru Urban': 0.55,
        'Mysuru':          0.45,
        'Hubli-Dharwad':   0.60,
        'Mangaluru':       0.40,
        'Belagavi':        0.65,
        'Kalaburagi':      0.72,   # hottest, most vulnerable
    }

    with app.app_context():
        db = get_db()
        districts = db.execute('SELECT * FROM districts').fetchall()

        for d in districts:
            lat = d['latitude']
            lat_factor = max(0.0, min(1.0, (lat - 11.5) / 7.0))

            features = {
                'lst':               28.0 + lat_factor * 14.0,
                'ndvi':              0.55 - lat_factor * 0.30,
                'ndbi':              0.05 + lat_factor * 0.15,
                'air_temp':          26.0 + lat_factor * 12.0,
                'relative_humidity': 70.0 - lat_factor * 30.0,
                'wind_speed':         2.0 + lat_factor * 2.0,
                'lulc_heat':          0.3 + lat_factor * 0.4,
            }

            chi = predict_current_conditions(features)
            vuln = VULNERABILITY.get(d['name'], 0.5)
            result = calculate_hhri(
                chi=chi,
                air_temp=features['air_temp'],
                humidity=features['relative_humidity'],
                vulnerability_index=vuln,
            )

            # Only persist Moderate+ alerts
            if result['risk_level'] == 'Low':
                continue

            # Avoid duplicate alerts for today
            existing = db.execute(
                'SELECT id FROM health_alerts WHERE district_id=? AND alert_date=?',
                (d['id'], today)
            ).fetchone()
            if existing:
                continue

            db.execute(
                '''INSERT INTO health_alerts
                   (district_id, alert_date, risk_level, advisory_message, status)
                   VALUES (?, ?, ?, ?, ?)''',
                (d['id'], today,
                 result['risk_level'],
                 result['advisory'],
                 'active')
            )
            db.commit()

            # Dispatch mock SMS/Email notifications
            dispatch_alerts(d['name'], result['risk_level'], result['advisory'])

            generated.append({
                'district': d['name'],
                **result,
                'alert_date': today,
            })
            print(f"[Alerts] {result['risk_icon']} Alert saved — "
                  f"{d['name']}: {result['risk_level']} (HHRI={result['hhri']})")

    return generated


def dispatch_alerts(district_name: str, risk_level: str, advisory: str):
    """
    Placeholder for dispatching UHI heat alerts via email and SMS gateways.
    Simulates sending alerts to registered health workers and residents.
    """
    import logging
    logger = logging.getLogger("heatsense.alerts")
    # SMS dispatch placeholder
    sms_msg = f"[SMS ALERT] HeatSense WARNING: {district_name} is under {risk_level} heat hazard! {advisory[:80]}..."
    print(sms_msg)
    logger.warning(sms_msg)
    
    # Email dispatch placeholder
    email_msg = (
        f"[EMAIL ALERT] HeatSense Advisory\n"
        f"To: karnataka-health-officers@gov.in\n"
        f"Subject: Emergency Heat Stress Alert - {district_name} ({risk_level})\n\n"
        f"Dear Officer,\n\n"
        f"A {risk_level} heat risk warning has been issued for {district_name}.\n"
        f"Precautionary Guidelines: {advisory}\n\n"
        f"Sincerely,\nHeatSense Monitoring System"
    )
    print(email_msg)
    logger.warning(email_msg)



def get_all_alerts(db) -> list:
    """
    Fetches all health_alerts joined with district names, ordered by date desc.
    Returns a list of dict-like sqlite3.Row objects.
    """
    rows = db.execute("""
        SELECT a.*, d.name as district_name
        FROM health_alerts a
        JOIN districts d ON a.district_id = d.id
        ORDER BY a.created_at DESC
    """).fetchall()
    return rows


def get_district_hhri(district: dict) -> dict:
    """
    Computes a real-time HHRI for a specific district dict
    (as returned from the DB) using climatological feature defaults.

    Returns:
        dict: Full HHRI result from calculate_hhri().
    """
    from app.ml import predict_current_conditions

    lat = district['latitude']
    lat_factor = max(0.0, min(1.0, (lat - 11.5) / 7.0))

    features = {
        'lst':               28.0 + lat_factor * 14.0,
        'ndvi':              0.55 - lat_factor * 0.30,
        'ndbi':              0.05 + lat_factor * 0.15,
        'air_temp':          26.0 + lat_factor * 12.0,
        'relative_humidity': 70.0 - lat_factor * 30.0,
        'wind_speed':         2.0 + lat_factor * 2.0,
        'lulc_heat':          0.3 + lat_factor * 0.4,
    }
    chi = predict_current_conditions(features)

    VULNERABILITY = {
        'Bengaluru Urban': 0.55, 'Mysuru': 0.45,
        'Hubli-Dharwad': 0.60,  'Mangaluru': 0.40,
        'Belagavi': 0.65,        'Kalaburagi': 0.72,
    }
    vuln = VULNERABILITY.get(district['name'], 0.5)

    return calculate_hhri(chi, features['air_temp'],
                          features['relative_humidity'], vuln)
