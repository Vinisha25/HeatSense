"""
HeatSense Routes Module.
Handles all Flask routes including auth, location selection, GEE data,
analysis endpoints, mitigation, health risk, and reports.
"""

import os
import json
import requests
from flask import Blueprint, render_template, jsonify, request, session, redirect, url_for, Response

from app.database import get_db

main_bp = Blueprint('main', __name__)

import re
from werkzeug.security import generate_password_hash, check_password_hash

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _require_session():
    """Check if user is authenticated in the session."""
    return session.get('user') is not None

def _is_valid_email(email):
    """Validate email format for any valid domain."""
    pattern = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
    return bool(re.match(pattern, email.strip()))

def _is_valid_phone(phone):
    """Validate phone number format (allows digits, spaces, hyphens, optional + prefix)."""
    cleaned = re.sub(r'[\s\-()]', '', phone.strip())
    return bool(re.match(r'^\+?[0-9]{8,15}$', cleaned))

def _get_features_for_request():
    """
    Extract lat/lon from request args and return features + metadata.
    Supports both lat/lon params (new) and district_id (legacy).
    """
    from app.preprocessing import get_location_features, _lat_lon_fallback, _EE_INITIALIZED

    lat = request.args.get('lat', type=float)
    lon = request.args.get('lon', type=float)
    radius = request.args.get('radius', 15, type=float)

    if lat is not None and lon is not None:
        features, source = get_location_features(lat, lon, radius_km=radius)
        return features, lat, lon, source

    # Legacy: district_id fallback
    district_id = request.args.get('district_id', type=int)
    if district_id:
        db = get_db()
        district = db.execute("SELECT * FROM districts WHERE id = ?", (district_id,)).fetchone()
        if district:
            lat = district['latitude']
            lon = district['longitude']
            features, source = get_location_features(lat, lon, radius_km=15)
            return features, lat, lon, source

    return None, None, None, None


def _get_location_name():
    """Get location name from request params."""
    name = request.args.get('name', '')
    if name:
        return name
    district_id = request.args.get('district_id', type=int)
    if district_id:
        db = get_db()
        d = db.execute("SELECT name FROM districts WHERE id = ?", (district_id,)).fetchone()
        if d:
            return d['name']
    return 'Selected Location'


# ──────────────────────────────────────────────────────────────────────────────
# Page Routes
# ──────────────────────────────────────────────────────────────────────────────

@main_bp.route('/')
def root():
    """Entry point — redirect to splash screen."""
    return redirect(url_for('main.splash'))

@main_bp.route('/splash')
def splash():
    """Animated splash screen."""
    return render_template('splash.html')

@main_bp.route('/login')
def login():
    """Login and registration page."""
    if _require_session():
        return redirect(url_for('main.location_page'))
    return render_template('login.html', active_tab=request.args.get('tab', 'login'))

@main_bp.route('/register')
def register():
    """Direct route for registration view."""
    if _require_session():
        return redirect(url_for('main.location_page'))
    return render_template('login.html', active_tab='register')

@main_bp.route('/location')
def location_page():
    """Full-page interactive location selection screen."""
    if not _require_session():
        return redirect(url_for('main.login'))
    return render_template('location.html')

@main_bp.route('/dashboard')
def dashboard():
    """Main GIS analysis dashboard."""
    if not _require_session():
        return redirect(url_for('main.login'))

    # Pass location params from URL query string to template
    lat  = request.args.get('lat', 12.9716, type=float)
    lon  = request.args.get('lon', 77.5946, type=float)
    name = request.args.get('name', 'Bengaluru Urban')
    radius = request.args.get('radius', 15, type=float)
    location_id = request.args.get('location_id', type=int)

    db = get_db()
    districts = db.execute("SELECT * FROM districts").fetchall()
    user = session.get('user') or {'display_name': 'Guest', 'email': '', 'photo_url': ''}

    return render_template(
        'index.html',
        districts=districts,
        location_lat=lat,
        location_lon=lon,
        location_name=name,
        location_radius=radius,
        user=user,
    )

@main_bp.route('/alerts')
def alerts():
    """Health Risk & Alerts dashboard."""
    from app.health_risk import get_all_alerts, get_district_hhri, RISK_TIERS

    db = get_db()
    alerts_list = get_all_alerts(db)

    districts = db.execute('SELECT * FROM districts').fetchall()
    district_risk_cards = []
    for d in districts:
        try:
            hhri_result = get_district_hhri(dict(d))
            district_risk_cards.append({
                'name':         d['name'],
                'hhri':         hhri_result['hhri'],
                'risk_level':   hhri_result['risk_level'],
                'risk_icon':    hhri_result['risk_icon'],
                'colour_class': hhri_result['colour_class'],
                'badge_bg':     hhri_result['badge_bg'],
                'action':       hhri_result['action'],
                'advisory':     hhri_result['advisory'],
            })
        except Exception as e:
            print(f"[Alerts] HHRI calc failed for {d['name']}: {e}")

    tier_counts = {'Low': 0, 'Moderate': 0, 'High': 0, 'Very High': 0}
    for card in district_risk_cards:
        tier_counts[card['risk_level']] = tier_counts.get(card['risk_level'], 0) + 1

    return render_template(
        'alerts.html',
        alerts=alerts_list,
        district_risk_cards=district_risk_cards,
        tier_counts=tier_counts,
        risk_tiers=RISK_TIERS,
    )

@main_bp.route('/logout')
def logout():
    """Clear session and redirect to splash."""
    session.clear()
    return redirect(url_for('main.splash'))


# ──────────────────────────────────────────────────────────────────────────────
# Auth API
# ──────────────────────────────────────────────────────────────────────────────

@main_bp.route('/api/auth/register', methods=['POST'])
def api_auth_register():
    """
    Registers a new user into the SQLite database.
    Validates name, email (any domain), phone, password, and confirmation.
    Stores securely hashed passwords.
    """
    body = request.get_json() or {}
    full_name = (body.get('full_name') or '').strip()
    email = (body.get('email') or '').strip().lower()
    phone = (body.get('phone_number') or '').strip()
    password = body.get('password') or ''
    confirm_password = body.get('confirm_password') or ''

    # 1. Validation: Required fields
    if not full_name:
        return jsonify({'success': False, 'message': 'Please enter your full name.'}), 400
    if len(full_name) < 2:
        return jsonify({'success': False, 'message': 'Full name must be at least 2 characters.'}), 400

    if not email:
        return jsonify({'success': False, 'message': 'Please enter your email address.'}), 400
    if not _is_valid_email(email):
        return jsonify({'success': False, 'message': 'Please enter a valid email address (e.g. name@domain.com).'}), 400

    if not phone:
        return jsonify({'success': False, 'message': 'Please enter your phone number.'}), 400
    if not _is_valid_phone(phone):
        return jsonify({'success': False, 'message': 'Please enter a valid phone number (10 to 15 digits).'}), 400

    if not password:
        return jsonify({'success': False, 'message': 'Please enter a password.'}), 400
    if len(password) < 6:
        return jsonify({'success': False, 'message': 'Password must be at least 6 characters long.'}), 400

    if password != confirm_password:
        return jsonify({'success': False, 'message': 'Passwords do not match. Please retype and confirm.'}), 400

    db = get_db()

    # 2. Check if email already exists
    existing = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        return jsonify({'success': False, 'message': 'An account with this email address already exists. Please sign in.'}), 409

    # 3. Hash password securely & insert user
    password_hash = generate_password_hash(password, method='pbkdf2:sha256')
    try:
        db.execute(
            "INSERT INTO users (full_name, email, phone_number, password_hash) VALUES (?, ?, ?, ?)",
            (full_name, email, phone, password_hash)
        )
        db.commit()
        return jsonify({
            'success': True,
            'message': 'Registration successful! You can now sign in with your email and password.'
        }), 201
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'message': f'Registration failed: {str(e)}'}), 500


@main_bp.route('/api/auth/login', methods=['POST'])
def api_auth_login():
    """
    Authenticates a user against the SQLite database using email and password.
    Creates a secure session on success.
    """
    body = request.get_json() or {}
    email = (body.get('email') or '').strip().lower()
    password = body.get('password') or ''

    if not email or not password:
        return jsonify({'success': False, 'message': 'Please provide both email address and password.'}), 400

    if not _is_valid_email(email):
        return jsonify({'success': False, 'message': 'Please enter a valid email address.'}), 400

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

    if not user or not check_password_hash(user['password_hash'], password):
        return jsonify({'success': False, 'message': 'Invalid email address or password. Please try again.'}), 401

    # Establish session
    session.clear()
    session['user'] = {
        'id':           user['id'],
        'display_name': user['full_name'],
        'email':        user['email'],
        'phone_number': user['phone_number'],
    }
    session.permanent = True

    return jsonify({
        'success': True,
        'message': f'Welcome back, {user["full_name"]}!',
        'redirect': '/location'
    }), 200


# ──────────────────────────────────────────────────────────────────────────────
# Location & Geocoding API
# ──────────────────────────────────────────────────────────────────────────────

@main_bp.route('/api/geocode')
def api_geocode():
    """
    Reverse geocodes a lat/lon to a place name using Nominatim (OpenStreetMap).
    Returns specific area names (Urwa, Surathkal, etc.) not just city names.
    """
    lat  = request.args.get('lat', type=float)
    lon  = request.args.get('lon', type=float)
    full = request.args.get('full', '0')

    if lat is None or lon is None:
        return jsonify({'error': 'Missing lat/lon'}), 400

    try:
        resp = requests.get(
            'https://nominatim.openstreetmap.org/reverse',
            params={
                'lat': lat, 'lon': lon,
                'format': 'json',
                'zoom': 16,  # High zoom = specific place names
                'addressdetails': 1,
            },
            headers={'User-Agent': 'HeatSense-Karnataka/2.0 (academic project)'},
            timeout=8
        )
        data = resp.json()
        addr = data.get('address', {})

        # Build specific name (most detailed available)
        name = (
            addr.get('neighbourhood') or
            addr.get('suburb') or
            addr.get('village') or
            addr.get('town') or
            addr.get('city_district') or
            addr.get('city') or
            addr.get('county') or
            data.get('display_name', f"{lat:.4f},{lon:.4f}")
        )

        district = (
            addr.get('county') or
            addr.get('city') or
            addr.get('state_district') or '—'
        )
        state   = addr.get('state', 'Karnataka')
        p_type  = data.get('type', 'place').capitalize()
        level   = data.get('addresstype', 'Location').capitalize()

        if full == '1':
            return jsonify({
                'name':         name,
                'district':     district,
                'state':        state,
                'type':         p_type,
                'level':        level,
                'display_name': data.get('display_name', ''),
                'lat':          lat,
                'lon':          lon,
            })

        return jsonify({'display_name': name})

    except Exception as e:
        print(f"[Geocode] Nominatim failed: {e}")
        return jsonify({'display_name': f"{lat:.4f}, {lon:.4f}"})


@main_bp.route('/api/search-location')
def api_search_location():
    """
    Searches for locations in Karnataka by text using Nominatim.
    Returns up to 10 matching results with lat/lon.
    """
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])

    try:
        resp = requests.get(
            'https://nominatim.openstreetmap.org/search',
            params={
                'q':              f"{q}, Karnataka, India",
                'format':         'json',
                'addressdetails': 1,
                'limit':          10,
                'countrycodes':   'in',
            },
            headers={'User-Agent': 'HeatSense-Karnataka/2.0 (academic project)'},
            timeout=8
        )
        results = resp.json()
        out = []
        for r in results:
            addr = r.get('address', {})
            # Filter to Karnataka
            if 'Karnataka' not in r.get('display_name', ''):
                continue
            name = (
                addr.get('neighbourhood') or
                addr.get('suburb') or
                addr.get('village') or
                addr.get('town') or
                addr.get('city') or
                r.get('name', r.get('display_name', ''))
            )
            out.append({
                'name':         name,
                'display_name': r.get('display_name', ''),
                'lat':          float(r['lat']),
                'lon':          float(r['lon']),
                'type':         r.get('type', 'place'),
            })
        return jsonify(out)

    except Exception as e:
        print(f"[Search] Nominatim search failed: {e}")
        return jsonify([])


@main_bp.route('/api/analyze-location', methods=['POST'])
def api_analyze_location():
    """
    Accepts a selected lat/lon, stores it (or finds existing),
    and returns a location_id for dashboard use.
    """
    body = request.get_json() or {}
    lat  = body.get('lat')
    lon  = body.get('lon')
    name = body.get('name', 'Unknown Location')
    radius_km = body.get('radius_km', 15)

    if lat is None or lon is None:
        return jsonify({'error': 'Missing lat/lon'}), 400

    db = get_db()

    # Try to find existing location within ~5km
    existing = db.execute(
        "SELECT id FROM locations WHERE ABS(latitude - ?) < 0.05 AND ABS(longitude - ?) < 0.05",
        (lat, lon)
    ).fetchone()

    if existing:
        return jsonify({'location_id': existing['id'], 'name': name})

    # Insert new location
    cursor = db.execute(
        "INSERT INTO locations (name, latitude, longitude, radius_km) VALUES (?, ?, ?, ?)",
        (name, lat, lon, radius_km)
    )
    db.commit()
    return jsonify({'location_id': cursor.lastrowid, 'name': name})


# ──────────────────────────────────────────────────────────────────────────────
# GEE Status
# ──────────────────────────────────────────────────────────────────────────────

@main_bp.route('/api/gee-status')
def api_gee_status():
    """
    Returns actual GEE connection status. Never hardcodes 'Active' if disconnected.
    """
    from app.preprocessing import get_gee_status
    return jsonify(get_gee_status())


# ──────────────────────────────────────────────────────────────────────────────
# Map Layers
# ──────────────────────────────────────────────────────────────────────────────

@main_bp.route('/api/map-layers')
def api_map_layers():
    """
    Renders and serves the interactive map HTML.
    Accepts lat/lon for any location, falls back to Karnataka center.
    """
    start_date = request.args.get('start_date', '2024-03-01')
    end_date   = request.args.get('end_date', '2024-05-31')
    lat        = request.args.get('lat', 14.5, type=float)
    lon        = request.args.get('lon', 75.7, type=float)
    radius_km  = request.args.get('radius', 15, type=float)

    from app.visualization import generate_geemap_html
    html_content = generate_geemap_html(start_date, end_date, lat, lon, radius_km)
    return html_content


# ──────────────────────────────────────────────────────────────────────────────
# Analysis APIs
# ──────────────────────────────────────────────────────────────────────────────

@main_bp.route('/api/predict', methods=['GET', 'POST'])
def api_predict():
    """
    ML-powered endpoint — predicts CHI for any location (lat/lon or district_id).
    Returns current-day and future (+1.5°C scenario) predictions.
    """
    from app.ml import predict_current_conditions, predict_future_conditions, chi_to_risk_level
    from app.preprocessing import get_location_features

    features, lat, lon, source = _get_features_for_request()
    location_name = _get_location_name()

    if features is None:
        # Defaults to Bengaluru if nothing specified
        lat, lon = 12.9716, 77.5946
        from app.preprocessing import _lat_lon_fallback
        features = _lat_lon_fallback(lat, lon)
        source = 'climatological'
        location_name = 'Bengaluru Urban'

    current_chi  = predict_current_conditions(features)
    current_risk = chi_to_risk_level(current_chi)

    future_result = predict_future_conditions(features, temp_offset=1.5, ndvi_offset=-0.10, ndbi_offset=0.05)
    future_chi    = future_result['predicted_chi']
    future_risk   = chi_to_risk_level(future_chi)

    advisories = {
        'Low':       'Normal conditions. No immediate heat stress expected.',
        'Moderate':  'Monitor conditions. Vulnerable groups should stay hydrated.',
        'High':      'High heat stress. Limit outdoor activity during peak hours.',
        'Very High': 'Extreme heat event. Avoid outdoor exposure. Follow district alerts.'
    }

    return jsonify({
        'location':             location_name,
        'lat':                  lat,
        'lon':                  lon,
        'data_source':          source,
        # Current conditions
        'current_chi':          current_chi,
        'current_risk_level':   current_risk,
        'current_advisory':     advisories[current_risk],
        'predicted_lst_celsius': round(features.get('lst', 32.0), 1),
        # Environmental factors
        'features':             {k: round(v, 3) for k, v in features.items()},
        # Future scenario
        'future_chi':           future_chi,
        'future_risk_level':    future_risk,
        'future_advisory':      advisories[future_risk],
        'scenario_label':       '+1.5°C Warming / -10% Green Cover',
        # Legacy fields
        'risk_level':           current_risk,
        'advisory':             advisories[current_risk],
        'uhi_index':            round(current_chi * 4, 2),
    })


@main_bp.route('/api/history')
def api_history():
    """
    Retrieves historical heat trends for any location (lat/lon or district_id).
    """
    from app.preprocessing import get_location_historical_trend

    lat = request.args.get('lat', type=float)
    lon = request.args.get('lon', type=float)
    name = request.args.get('name', 'Selected Location')
    start_year = request.args.get('start_year', 2015, type=int)
    end_year   = request.args.get('end_year', 2025, type=int)

    if lat is None or lon is None:
        # Legacy district_id
        district_id = request.args.get('district_id', type=int)
        if district_id:
            db = get_db()
            d = db.execute("SELECT * FROM districts WHERE id = ?", (district_id,)).fetchone()
            if d:
                lat, lon, name = d['latitude'], d['longitude'], d['name']
        if lat is None:
            lat, lon = 12.9716, 77.5946
            name = 'Bengaluru Urban'

    historical_data = get_location_historical_trend(lat, lon, name, start_year, end_year)

    from app.visualization import generate_plotly_temperature_trends
    plotly_json = generate_plotly_temperature_trends(historical_data, location_name=name)

    # Also return raw data for client-side use
    result = json.loads(plotly_json)
    return jsonify({
        'chart': result,
        'data': historical_data,
        'location': name,
        'lat': lat, 'lon': lon,
    })


@main_bp.route('/api/factor-analysis')
def api_factor_analysis():
    """
    Factor Analysis endpoint — returns radar chart + bar/pie/table charts.
    Uses actual processed feature values for the selected location.
    """
    from app.ml import get_feature_analysis
    from app.visualization import generate_radar_chart

    features, lat, lon, source = _get_features_for_request()
    location_name = _get_location_name()

    if features is None:
        from app.preprocessing import _lat_lon_fallback
        lat, lon = 12.9716, 77.5946
        features = _lat_lon_fallback(lat, lon)
        location_name = 'Bengaluru Urban'
        source = 'climatological'

    # Radar chart from actual feature values
    radar_json = generate_radar_chart(features, location_name=location_name)

    # Bar/pie/table from RF model feature importances
    try:
        ml_analysis = get_feature_analysis()
    except Exception as e:
        ml_analysis = {'ranked_factors': [], 'bar_chart_json': '{}', 'pie_chart_json': '{}', 'table_chart_json': '{}'}

    # Build factor scores for display
    factor_scores = _build_factor_scores(features)

    return jsonify({
        **ml_analysis,
        'radar_chart_json': radar_json,
        'factor_scores':    factor_scores,
        'features':         {k: round(v, 3) for k, v in features.items()},
        'data_source':      source,
        'location':         location_name,
        'lat':              lat,
        'lon':              lon,
    })


def _build_factor_scores(features: dict) -> list:
    """Build 0–100 normalized factor scores for display cards."""
    lst  = features.get('lst', 30)
    ndvi = features.get('ndvi', 0.4)
    ndbi = features.get('ndbi', 0.1)
    air  = features.get('air_temp', 28)
    rh   = features.get('relative_humidity', 60)
    wind = features.get('wind_speed', 3)
    lulc = features.get('lulc_heat', 0.5)

    return [
        {'key': 'lst',   'label': 'Land Surface Temp',   'unit': '°C',  'value': round(lst,1),  'score': round(max(0,min(100,(lst-20)/30*100)),1),  'direction': 'heat',    'icon': '🌡️',  'color': '#ef4444'},
        {'key': 'air',   'label': 'Air Temperature',      'unit': '°C',  'value': round(air,1),  'score': round(max(0,min(100,(air-15)/30*100)),1),  'direction': 'heat',    'icon': '🌬️', 'color': '#f97316'},
        {'key': 'ndbi',  'label': 'Built-Up (NDBI)',      'unit': '',    'value': round(ndbi,3), 'score': round(max(0,min(100,(ndbi+0.5)/1.0*100)),1), 'direction': 'heat',  'icon': '🏙️', 'color': '#c0392b'},
        {'key': 'lulc',  'label': 'LULC Heat Score',      'unit': '',    'value': round(lulc,3), 'score': round(max(0,min(100,lulc*100)),1),          'direction': 'heat',    'icon': '🗺️',  'color': '#e67e22'},
        {'key': 'rh',    'label': 'Humidity',              'unit': '%',   'value': round(rh,1),   'score': round(max(0,min(100,(rh-10)/90*100)),1),    'direction': 'heat',    'icon': '💧',  'color': '#2980b9'},
        {'key': 'ndvi',  'label': 'Vegetation (NDVI)',     'unit': '',    'value': round(ndvi,3), 'score': round(max(0,min(100,(1-(ndvi+0.1)/0.9)*100)),1), 'direction': 'cool', 'icon': '🌿', 'color': '#27ae60'},
        {'key': 'wind',  'label': 'Wind Speed',            'unit': 'm/s', 'value': round(wind,1), 'score': round(max(0,min(100,(1-wind/10)*100)),1),   'direction': 'cool',    'icon': '💨',  'color': '#8e44ad'},
    ]


@main_bp.route('/api/health-risk')
def api_health_risk():
    """
    Health Risk endpoint — returns HHRI, risk level, and age-specific precautions.
    Works for any lat/lon.
    """
    from app.health_risk import get_location_hhri, get_age_specific_precautions
    from app.ml import predict_current_conditions

    features, lat, lon, source = _get_features_for_request()
    location_name = _get_location_name()

    if features is None:
        from app.preprocessing import _lat_lon_fallback
        lat, lon = 12.9716, 77.5946
        features = _lat_lon_fallback(lat, lon)
        location_name = 'Bengaluru Urban'

    hhri_result = get_location_hhri(lat, lon, features)
    chi = predict_current_conditions(features)

    return jsonify({
        'location':         location_name,
        'lat':              lat,
        'lon':              lon,
        'data_source':      source,
        'chi':              chi,
        'hhri':             hhri_result['hhri'],
        'risk_level':       hhri_result['risk_level'],
        'risk_icon':        hhri_result['risk_icon'],
        'badge_bg':         hhri_result['badge_bg'],
        'advisory':         hhri_result['advisory'],
        'action':           hhri_result['action'],
        'components':       hhri_result['components'],
        'age_precautions':  hhri_result['age_precautions'],
        'emergency_contacts': [
            {'label': 'Arogya Sahayavani', 'number': '104'},
            {'label': 'Ambulance',          'number': '108'},
            {'label': 'Police',             'number': '100'},
            {'label': 'BBMP Heat Helpline', 'number': '080-22221188'},
        ],
    })


@main_bp.route('/api/mitigation', methods=['POST'])
def api_mitigation():
    """
    Mitigation Simulation endpoint.
    Accepts: lat, lon (or district_id), scenario_type
    Returns: full before/after simulation payload.
    """
    body        = request.get_json() or {}
    strategy    = body.get('scenario_type', 'vegetation_expansion')
    lat         = body.get('lat')
    lon         = body.get('lon')
    radius      = body.get('radius', 15)
    name        = body.get('name', 'Selected Location')
    district_id = body.get('district_id')

    from app.preprocessing import get_location_features, _lat_lon_fallback, _EE_INITIALIZED
    from app.mitigation import run_mitigation_simulation

    if lat is not None and lon is not None:
        features, source = get_location_features(lat, lon, radius_km=radius)
    elif district_id:
        db = get_db()
        district = db.execute('SELECT * FROM districts WHERE id = ?', (district_id,)).fetchone()
        if not district:
            return jsonify({'error': 'District not found'}), 404
        lat = district['latitude']
        lon = district['longitude']
        name = district['name']
        features, source = get_location_features(lat, lon, radius_km=15)
    else:
        return jsonify({'error': 'Missing lat/lon or district_id'}), 400

    try:
        result = run_mitigation_simulation(features, strategy)
        result['location'] = name
        result['lat'] = lat
        result['lon'] = lon
        result['data_source'] = source
        return jsonify(result)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': f'Simulation failed: {e}'}), 500


@main_bp.route('/api/before-after-maps')
def api_before_after_maps():
    """
    Generates before and after mitigation Folium maps.
    Returns JSON with before_html and after_html.
    """
    from app.mitigation import run_mitigation_simulation, apply_strategy_offsets
    from app.preprocessing import get_location_features, _lat_lon_fallback

    lat      = request.args.get('lat', type=float)
    lon      = request.args.get('lon', type=float)
    strategy = request.args.get('strategy', 'vegetation_expansion')
    radius   = request.args.get('radius', 15, type=float)

    if lat is None or lon is None:
        lat, lon = 12.9716, 77.5946

    features, source = get_location_features(lat, lon, radius_km=radius)
    after_features = apply_strategy_offsets(features, strategy)

    from app.visualization import generate_before_after_maps
    before_html, after_html = generate_before_after_maps(
        lat, lon, radius, strategy, features, after_features
    )

    # Return as JSON with HTML embedded
    return jsonify({
        'before_html': before_html,
        'after_html':  after_html,
        'data_source': source,
    })


@main_bp.route('/api/alerts')
def api_alerts_json():
    """JSON API endpoint to fetch seeded health alerts from the database."""
    from app.health_risk import get_all_alerts
    db = get_db()
    alerts_list = get_all_alerts(db)
    result = [{
        "id":               a["id"],
        "alert_date":       a["alert_date"],
        "risk_level":       a["risk_level"],
        "advisory_message": a["advisory_message"],
        "status":           a["status"],
        "district_name":    a["district_name"],
    } for a in alerts_list]
    return jsonify(result)


# ──────────────────────────────────────────────────────────────────────────────
# Reports
# ──────────────────────────────────────────────────────────────────────────────

@main_bp.route('/api/download-report')
def api_download_report():
    """Generates and returns a downloadable text report."""
    from datetime import datetime
    from app.ml import predict_current_conditions, predict_future_conditions, chi_to_risk_level
    from app.health_risk import get_location_hhri
    from app.preprocessing import get_location_historical_trend

    features, lat, lon, source = _get_features_for_request()
    location_name = _get_location_name()

    if features is None:
        from app.preprocessing import _lat_lon_fallback
        lat, lon = 12.9716, 77.5946
        features = _lat_lon_fallback(lat, lon)
        location_name = 'Bengaluru Urban'

    current_chi  = predict_current_conditions(features)
    current_risk = chi_to_risk_level(current_chi)
    hhri_result  = get_location_hhri(lat, lon, features)
    future_result = predict_future_conditions(features)
    future_chi   = future_result['predicted_chi']
    future_risk  = chi_to_risk_level(future_chi)
    trend        = get_location_historical_trend(lat, lon, location_name)
    trend_slope  = trend[-1]['lst_slope'] if trend else 0.18

    report = f"""# HEATSENSE UHI ANALYSIS & HEALTH ASSESSMENT REPORT
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Study Area: {location_name}, Karnataka, India
Coordinates: Lat {lat:.5f}, Lon {lon:.5f}
Data Source: {source}

=========================================

1. CURRENT ENVIRONMENTAL PROFILE
---------------------------------
- Land Surface Temperature (LST): {features['lst']:.1f} °C
- Air Temperature (2m): {features['air_temp']:.1f} °C
- Normalized Difference Vegetation (NDVI): {features['ndvi']:.3f}
- Built-up Index (NDBI): {features['ndbi']:.3f}
- Relative Humidity: {features['relative_humidity']:.1f}%
- Wind Speed: {features['wind_speed']:.1f} m/s
- Land Use/Cover Heat Rating: {features['lulc_heat']:.2f}

2. COMPOSITE HEAT INDEX (CHI) & PREDICTIONS
-------------------------------------------
- Current Composite Heat Index (CHI): {current_chi:.3f}
- Heat Risk Rating: {current_risk}
- Heat Health Risk Index (HHRI): {hhri_result['hhri']:.3f}

Forecasted Climate Scenario (+1.5°C warming, -10% Green Space):
- Projected Future CHI: {future_chi:.3f}
- Projected Risk Level: {future_risk}
- Primary Health Advisory: {hhri_result['advisory']}

3. HISTORICAL WARMING TREND
----------------------------
- Decadal Warming Slope: +{trend_slope:.3f}°C/year

4. MITIGATION RECOMMENDATIONS
-------------------------------
* Vegetation Expansion — Cooling potential: -1.8°C LST
* Green Roof Retrofit  — Cooling potential: -1.2°C LST
* Reduce Built-Up Area — Cooling potential: -2.0°C LST
* Urban Parks          — Cooling potential: -2.2°C LST

=========================================
EMERGENCY CONTACTS (Karnataka):
- Arogya Sahayavani: 104
- Ambulance: 108
- Police: 100
- BBMP Heat Helpline: 080-22221188
"""

    safe_name = location_name.replace(' ', '_').replace('/', '_')
    return Response(
        report,
        mimetype="text/markdown",
        headers={"Content-disposition": f"attachment; filename=HeatSense_{safe_name}_Report.md"}
    )


@main_bp.route('/api/download-pdf')
def api_download_pdf():
    """Renders a print-ready HTML page for PDF download."""
    from datetime import datetime
    from app.ml import predict_current_conditions, predict_future_conditions, chi_to_risk_level
    from app.health_risk import get_location_hhri

    features, lat, lon, source = _get_features_for_request()
    location_name = _get_location_name()

    if features is None:
        from app.preprocessing import _lat_lon_fallback
        lat, lon = 12.9716, 77.5946
        features = _lat_lon_fallback(lat, lon)
        location_name = 'Bengaluru Urban'

    current_chi  = predict_current_conditions(features)
    current_risk = chi_to_risk_level(current_chi)
    hhri_result  = get_location_hhri(lat, lon, features)
    future_result = predict_future_conditions(features)
    future_chi   = future_result['predicted_chi']
    future_risk  = chi_to_risk_level(future_chi)

    # Create a minimal district-like dict for template compatibility
    location_dict = {'name': location_name, 'latitude': lat, 'longitude': lon}

    return render_template(
        'pdf_report.html',
        district=location_dict,
        date_now=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        features=features,
        current_chi=current_chi,
        current_risk=current_risk,
        hhri=hhri_result,
        future_chi=future_chi,
        future_risk=future_risk,
    )
