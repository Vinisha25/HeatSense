"""
HeatSense Health Risk & Alerts Module — Module 7.

Computes location-level Heat Health Risk Index (HHRI) by combining:
  - Composite Heat Index (CHI) from the RF model
  - Air temperature and humidity
  - Population vulnerability (proxy by location type)
  - Time-of-day peak risk factor

Also manages:
  - Generating and persisting health alerts to SQLite
  - Loading active/resolved alerts for the dashboard
  - Public advisory message generation per risk tier
  - Age-specific precautionary guidance
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
            'outdoor workers) should limit exposure between 11 AM - 4 PM. '
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
            'health checks in slum areas. Contact Arogya Sahayavani: 104.'
        ),
        'action': 'Emergency',
    },
}

# ──────────────────────────────────────────────────────────────────────────────
# Age-specific precautions
# ──────────────────────────────────────────────────────────────────────────────

AGE_PRECAUTIONS = {
    'Low': {
        'children':       ['Drink water every 30 minutes during outdoor play', 'Wear light clothing', 'Use sunscreen SPF 30+'],
        'adults':         ['Stay hydrated throughout the day', 'Avoid prolonged sun exposure 12–3 PM', 'Wear breathable fabrics'],
        'elderly':        ['Rest indoors during afternoon hours', 'Keep water and ORS at hand', 'Monitor blood pressure'],
        'workers':        ['Take regular shade breaks', 'Drink at least 250ml water every hour', 'Work during cooler morning hours'],
        'pregnant':       ['Avoid outdoor exposure during peak hours', 'Stay hydrated', 'Monitor for dizziness'],
        'general':        ['Stay indoors or in shade during 12–3 PM', 'Keep drinking water accessible', 'Check on elderly neighbors'],
    },
    'Moderate': {
        'children':       ['Limit outdoor play to before 10 AM and after 5 PM', 'Drink water every 20 min', 'Wear hats and light clothes', 'Watch for signs of heat exhaustion (pale skin, dizziness)'],
        'adults':         ['Avoid strenuous outdoor activity 11 AM–4 PM', 'Drink 3+ litres of water daily', 'Wear loose, light-coloured clothing', 'Use fans/coolers indoors'],
        'elderly':        ['STAY INDOORS during 10 AM–5 PM', 'Drink ORS or electrolyte drinks', 'Have someone check on you twice daily', 'Keep room ventilated'],
        'workers':        ['Mandatory 15-min shade break every hour', 'Drink water before feeling thirsty', 'Watch co-workers for heat illness signs', 'Reschedule strenuous tasks to morning/evening'],
        'pregnant':       ['Stay in cool, ventilated rooms', 'Drink at least 2.5 L water daily', 'Avoid direct sun', 'Report persistent headache or swelling to doctor'],
        'general':        ['Stay cool indoors', 'Wet cloth on neck/wrists to cool down', 'Check on children and elderly frequently', 'Avoid cooking during peak heat hours'],
    },
    'High': {
        'children':       ['NO outdoor activity 9 AM–6 PM', 'Supervise for heat exhaustion (heavy sweating, weakness, rapid pulse)', 'Cool baths if overheated', 'Increase fluid intake immediately'],
        'adults':         ['Avoid all outdoor exertion during peak hours', 'Use air conditioning or visit cooling centres', 'Eat light, cool foods — avoid heavy meals', 'Watch for heat cramps or exhaustion'],
        'elderly':        ['CRITICAL: Ensure elderly persons are in cool, ventilated spaces', 'Provide chilled water and ORS at regular intervals', 'Immediate medical attention for confusion or weakness', 'Daily health check from ASHA/community health worker'],
        'workers':        ['Mandatory engineering controls (shading, ventilation at worksite)', 'Stop work if body temperature feels dangerously high', 'Buddy system — no worker should be alone', 'Access to first aid for heat-related emergencies on-site'],
        'pregnant':       ['Complete bed rest in cool environment', 'Notify healthcare provider about heat exposure', 'Avoid any outdoor activity', 'Monitor fetal movements; seek care if reduced'],
        'general':        ['Visit nearest public cooling centre', 'Do not leave anyone (especially children or elderly) in parked vehicles', 'Stay connected with family/neighbors', 'Call Arogya Sahayavani 104 for heat-illness symptoms'],
    },
    'Very High': {
        'children':       ['EMERGENCY: Keep children in air-conditioned spaces', 'Call 108 (Ambulance) immediately for any unconsciousness or seizure', 'Apply cool, wet cloths to skin; do not give cold water rapidly', 'Rush to nearest hospital for severe heat stroke'],
        'adults':         ['EVACUATE to cooling centre immediately', 'Treat heat stroke as medical emergency — call 108', 'Strip excess clothing; apply ice packs to neck, armpits, groin', 'Do not leave home without someone accompanying'],
        'elderly':        ['HIGHEST RISK: Activate all emergency protocols', 'Move to air-conditioned facility immediately', 'Continuous monitoring for confusion, slurred speech, unconsciousness', 'Call 108 without delay for any deterioration'],
        'workers':        ['HALT all outdoor construction and field work IMMEDIATELY', 'All workers must be moved to shaded/cooled areas', 'Emergency heat response protocol must be activated', 'Report all heat-related illness cases to district health officer'],
        'pregnant':       ['Hospital-level monitoring required', 'Do NOT expose to outdoor heat under any circumstances', 'Immediate obstetric consultation for any heat-stress symptoms', 'Call 108 for emergency transport if needed'],
        'general':        ['DISTRICT HEAT EMERGENCY DECLARED', 'Avoid all outdoor activity', 'Check on all vulnerable neighbors — elderly, children, sick', 'Arogya Sahayavani: 104 | Ambulance: 108 | BBMP Heat Helpline: 080-22221188'],
    },
}

AGE_GROUP_META = {
    'children':   {'label': 'Children (0–12 years)', 'icon': '👶', 'color': '#3b82f6'},
    'adults':     {'label': 'Adults (13–60 years)', 'icon': '🧑', 'color': '#f97316'},
    'elderly':    {'label': 'Senior Citizens (60+ years)', 'icon': '👴', 'color': '#ef4444'},
    'workers':    {'label': 'Outdoor Workers', 'icon': '👷', 'color': '#eab308'},
    'pregnant':   {'label': 'Pregnant Women', 'icon': '🤰', 'color': '#8b5cf6'},
    'general':    {'label': 'General Public', 'icon': '👥', 'color': '#10b981'},
}

def get_age_specific_precautions(risk_level: str) -> list:
    """
    Returns age-group-specific precautionary guidance for a given risk level.

    Args:
        risk_level (str): One of 'Low', 'Moderate', 'High', 'Very High'.
    Returns:
        list[dict]: Each entry contains group metadata + precaution list.
    """
    if risk_level not in AGE_PRECAUTIONS:
        risk_level = 'Moderate'

    precautions = AGE_PRECAUTIONS[risk_level]
    result = []
    for group_key, meta in AGE_GROUP_META.items():
        result.append({
            'key':          group_key,
            'label':        meta['label'],
            'icon':         meta['icon'],
            'color':        meta['color'],
            'precautions':  precautions.get(group_key, []),
            'risk_level':   risk_level,
        })
    return result

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
    """
    import numpy as np

    air_n  = float(np.clip((air_temp  - 15.0) / 30.0, 0, 1))
    rh_n   = float(np.clip((humidity  - 20.0) / 80.0, 0, 1))
    vuln_n = float(np.clip(vulnerability_index, 0, 1))

    hhri = (chi * 0.40 + air_n * 0.25 + rh_n * 0.20 + vuln_n * 0.15)
    hhri = round(float(np.clip(hhri, 0, 1)), 4)

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

def get_location_hhri(lat: float, lon: float, features: dict) -> dict:
    """
    Computes HHRI for any lat/lon location using extracted features.

    Args:
        lat (float): Latitude.
        lon (float): Longitude.
        features (dict): Environmental features from get_location_features().
    Returns:
        dict: Full HHRI result including age-specific precautions.
    """
    from app.ml import predict_current_conditions

    chi = predict_current_conditions(features)

    # Vulnerability proxy based on geographic context
    # Northern Karnataka (Kalaburagi, Bidar, Raichur) = higher vulnerability
    lat_factor = max(0.0, min(1.0, (lat - 11.5) / 7.0))
    base_vuln = 0.40 + lat_factor * 0.32

    hhri_result = calculate_hhri(
        chi=chi,
        air_temp=features.get('air_temp', 30.0),
        humidity=features.get('relative_humidity', 55.0),
        vulnerability_index=base_vuln,
    )
    hhri_result['age_precautions'] = get_age_specific_precautions(hhri_result['risk_level'])
    return hhri_result

# ──────────────────────────────────────────────────────────────────────────────
# Alert Management
# ──────────────────────────────────────────────────────────────────────────────

def generate_alerts_for_all_districts(app):
    """
    Iterates over all districts, computes their HHRI from climatological
    feature defaults, and inserts today's alerts into the health_alerts table.
    """
    import sqlite3
    from app.database import get_db
    from app.ml import predict_current_conditions
    from app.preprocessing import _lat_lon_fallback

    today = date.today().isoformat()
    generated = []

    VULNERABILITY = {
        'Bengaluru Urban': 0.55,
        'Mysuru':          0.45,
        'Hubli-Dharwad':   0.60,
        'Mangaluru':       0.40,
        'Belagavi':        0.65,
        'Kalaburagi':      0.72,
    }

    with app.app_context():
        db = get_db()
        districts = db.execute('SELECT * FROM districts').fetchall()

        for d in districts:
            lat = d['latitude']
            lon = d['longitude']

            features = _lat_lon_fallback(lat, lon)
            chi = predict_current_conditions(features)
            vuln = VULNERABILITY.get(d['name'], 0.5)
            result = calculate_hhri(
                chi=chi,
                air_temp=features['air_temp'],
                humidity=features['relative_humidity'],
                vulnerability_index=vuln,
            )

            if result['risk_level'] == 'Low':
                continue

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

            dispatch_alerts(d['name'], result['risk_level'], result['advisory'])

            generated.append({
                'district': d['name'],
                **result,
                'alert_date': today,
            })
            print(f"[Alerts] Alert saved - "
                  f"{d['name']}: {result['risk_level']} (HHRI={result['hhri']})")

    return generated


def dispatch_alerts(district_name: str, risk_level: str, advisory: str):
    """
    Placeholder for dispatching UHI heat alerts via email and SMS gateways.
    """
    import logging
    logger = logging.getLogger("heatsense.alerts")
    sms_msg = f"[SMS ALERT] HeatSense WARNING: {district_name} is under {risk_level} heat hazard! {advisory[:80]}..."
    print(sms_msg)
    logger.warning(sms_msg)

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
    Computes a real-time HHRI for a specific district dict using climatological features.
    """
    from app.ml import predict_current_conditions
    from app.preprocessing import _lat_lon_fallback

    lat = district['latitude']
    lon = district['longitude']
    features = _lat_lon_fallback(lat, lon)
    chi = predict_current_conditions(features)

    VULNERABILITY = {
        'Bengaluru Urban': 0.55, 'Mysuru': 0.45,
        'Hubli-Dharwad': 0.60,  'Mangaluru': 0.40,
        'Belagavi': 0.65,        'Kalaburagi': 0.72,
    }
    vuln = VULNERABILITY.get(district['name'], 0.5)

    return calculate_hhri(chi, features['air_temp'], features['relative_humidity'], vuln)
