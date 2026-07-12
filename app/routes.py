from flask import Blueprint, render_template, jsonify, request
from app.database import get_db

# Create blueprint for application routes
main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    """
    Renders the main dashboard interface displaying interactive map container
    and core UHI stats.
    """
    db = get_db()
    districts = db.execute("SELECT * FROM districts").fetchall()
    return render_template('index.html', districts=districts)

@main_bp.route('/alerts')
def alerts():
    """
    Health Risk & Alerts dashboard.
    Renders:
      - All health_alerts from the DB (joined with district names)
      - Live HHRI scores for every district (computed at request time)
      - Summary counts per risk tier for the stat ribbon
    """
    from app.health_risk import get_all_alerts, get_district_hhri, RISK_TIERS

    db = get_db()
    alerts_list = get_all_alerts(db)

    # Build live per-district HHRI cards
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

    # Summary counts per tier
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


@main_bp.route('/api/predict', methods=['GET', 'POST'])
def api_predict():
    """
    ML-powered endpoint that predicts the Composite Heat Index (CHI) for a
    given district using the trained Random Forest model. Returns both
    current-day and future (+1.5°C scenario) predictions.
    """
    district_id = request.args.get('district_id', type=int)
    if not district_id:
        return jsonify({"error": "Missing district_id parameter"}), 400

    db = get_db()
    district = db.execute(
        "SELECT * FROM districts WHERE id = ?", (district_id,)
    ).fetchone()
    if not district:
        return jsonify({"error": "District not found"}), 404

    from app.ml import (
        predict_current_conditions, predict_future_conditions, chi_to_risk_level
    )
    from app.preprocessing import _EE_INITIALIZED

    # Build district-level feature vector
    # Use representative baseline values; augmented by GEE when authenticated
    district_features = _get_district_features(district, _EE_INITIALIZED)

    # Current prediction
    current_chi   = predict_current_conditions(district_features)
    current_risk  = chi_to_risk_level(current_chi)

    # Future scenario: +1.5°C warming, -10% NDVI, +5% NDBI
    future_result = predict_future_conditions(
        district_features, temp_offset=1.5,
        ndvi_offset=-0.10, ndbi_offset=0.05
    )
    future_chi  = future_result['predicted_chi']
    future_risk = chi_to_risk_level(future_chi)

    advisories = {
        'Low':       'Normal conditions. No immediate heat stress expected.',
        'Moderate':  'Monitor conditions. Vulnerable groups should stay hydrated.',
        'High':      'High heat stress. Limit outdoor activity during peak hours.',
        'Very High': 'Extreme heat event. Avoid outdoor exposure. Follow BBMP alerts.'
    }

    return jsonify({
        "district":       district["name"],
        "district_id":    district_id,
        # Current conditions
        "current_chi":          current_chi,
        "current_risk_level":   current_risk,
        "current_advisory":     advisories[current_risk],
        "predicted_lst_celsius": round(district_features.get('lst', 32.0), 1),
        # Future scenario
        "future_chi":         future_chi,
        "future_risk_level":  future_risk,
        "future_advisory":    advisories[future_risk],
        "scenario_label":     "+1.5°C Warming / -10% Green Cover",
        # Legacy field for JS compatibility
        "risk_level": current_risk,
        "advisory":   advisories[current_risk],
        "uhi_index":  round(current_chi * 4, 2)
    })


def _get_district_features(district, use_gee=False):
    """
    Assembles a feature dict for a district.
    Tries GEE extraction when authenticated; falls back to
    climatological defaults scaled by latitude/longitude position.
    """
    import math

    lat = district['latitude']
    lon = district['longitude']

    # Climatological baselines derived from Karnataka lat-band regression
    # Northern Karnataka (Kalaburagi, Belagavi) is hotter and drier
    lat_factor = max(0.0, min(1.0, (lat - 11.5) / 7.0))   # 0=south, 1=north

    if use_gee:
        try:
            from app.preprocessing import (
                process_landsat_data, get_era5_land_daily_climate,
                get_lulc_data, get_lulc_heat_score
            )
            import ee
            point  = ee.Geometry.Point([lon, lat])
            region = point.buffer(15000)
            landsat = process_landsat_data('2024-03-01', '2024-05-31')
            climate = get_era5_land_daily_climate('2024-03-01', '2024-05-31')
            lulc    = get_lulc_data()
            lulc_h  = get_lulc_heat_score(lulc)

            stacked = (landsat.select('LST').rename('lst')
                       .addBands(landsat.select('NDVI').rename('ndvi'))
                       .addBands(landsat.select('NDBI').rename('ndbi'))
                       .addBands(climate.select('air_temperature').rename('air_temp'))
                       .addBands(climate.select('relative_humidity').rename('relative_humidity'))
                       .addBands(climate.select('wind_speed').rename('wind_speed'))
                       .addBands(lulc_h.rename('lulc_heat')))

            vals = stacked.reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=region, scale=1000, maxPixels=1e8
            ).getInfo()

            return {
                'lst':                float(vals.get('lst') or 33.0),
                'ndvi':               float(vals.get('ndvi') or 0.35),
                'ndbi':               float(vals.get('ndbi') or 0.05),
                'air_temp':           float(vals.get('air_temp') or 30.0),
                'relative_humidity':  float(vals.get('relative_humidity') or 55.0),
                'wind_speed':         float(vals.get('wind_speed') or 2.5),
                'lulc_heat':          float(vals.get('lulc_heat') or 0.5),
            }
        except Exception as e:
            print(f"[Routes] GEE feature extraction failed: {e}. Using climatological defaults.")

    # Climatological fallback
    return {
        'lst':               28.0 + lat_factor * 14.0,
        'ndvi':              0.55 - lat_factor * 0.30,
        'ndbi':              0.05 + lat_factor * 0.15,
        'air_temp':          26.0 + lat_factor * 12.0,
        'relative_humidity': 70.0 - lat_factor * 30.0,
        'wind_speed':         2.0 + lat_factor * 2.0,
        'lulc_heat':          0.3 + lat_factor * 0.4,
    }


@main_bp.route('/api/mitigation', methods=['POST'])
def api_mitigation():
    """
    Module 6: Mitigation Simulation endpoint.

    Accepts JSON body:
        district_id   (int)  : Target district.
        scenario_type (str)  : Strategy key — one of:
                               vegetation_expansion | green_roofs |
                               reduce_buildup | increase_parks
                               (legacy 'greenery' and 'albedo' also accepted)

    Returns a full before/after simulation payload with:
        - before_chi, after_chi, chi_reduction, pct_improvement
        - before_lst, after_lst, lst_reduction
        - factor_changes list
        - Plotly chart JSONs: chi_bar_json, lst_bar_json,
                              delta_bar_json, indicator_json
    """
    body        = request.get_json() or {}
    district_id = body.get('district_id')
    strategy    = body.get('scenario_type', 'vegetation_expansion')

    if not district_id:
        return jsonify({'error': 'Missing district_id'}), 400

    db       = get_db()
    district = db.execute(
        'SELECT * FROM districts WHERE id = ?', (district_id,)
    ).fetchone()
    if not district:
        return jsonify({'error': 'District not found'}), 404

    from app.mitigation import run_mitigation_simulation
    from app.preprocessing import _EE_INITIALIZED

    district_features = _get_district_features(district, _EE_INITIALIZED)

    try:
        result = run_mitigation_simulation(district_features, strategy)
        return jsonify(result)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': f'Simulation failed: {e}'}), 500


@main_bp.route('/api/map-layers')
def api_map_layers():
    """
    Renders and serves the interactive Geemap/Folium HTML composite.
    Accepts optional start_date and end_date queries.
    """
    start_date = request.args.get('start_date', '2024-03-01')
    end_date = request.args.get('end_date', '2024-05-31')
    
    from app.visualization import generate_geemap_html
    html_content = generate_geemap_html(start_date, end_date)
    return html_content

@main_bp.route('/api/history')
def api_history():
    """
    Retrieves the historical decadal temperature/CHI trends for a specific district
    and returns the interactive Plotly JSON graph schema.
    """
    district_id = request.args.get('district_id', type=int)
    if not district_id:
        return jsonify({"error": "Missing district_id parameter"}), 400
        
    from app.preprocessing import get_district_historical_trend
    from app.visualization import generate_plotly_temperature_trends
    
    historical_data = get_district_historical_trend(district_id)
    plotly_json = generate_plotly_temperature_trends(historical_data)
    
    return plotly_json, 200, {'Content-Type': 'application/json'}


@main_bp.route('/api/factor-analysis')
def api_factor_analysis():
    """
    Module 5: Factor Analysis endpoint.

    Uses the trained Random Forest model to extract feature importances
    and returns three Plotly chart JSON payloads:
        - bar_chart_json   : horizontal importance bar chart
        - pie_chart_json   : donut percentage contribution chart
        - table_chart_json : ranked factor table
    Also returns a ranked_factors list with label, importance, and percentage.
    """
    from app.ml import get_feature_analysis
    try:
        result = get_feature_analysis()
        return jsonify(result)
    except Exception as e:
        # Return fallback physics-based importances if model fails
        return jsonify({'error': str(e)}), 500


@main_bp.route('/api/download-report')
def api_download_report():
    """
    Generates and returns a downloadable text/markdown report summarizing the UHI
    predictions, trend analysis, factor importance, and mitigation recommendations.
    """
    from datetime import datetime
    district_id = request.args.get('district_id', type=int)

    if not district_id:
        return jsonify({"error": "Missing district_id parameter"}), 400

    db = get_db()
    district = db.execute("SELECT * FROM districts WHERE id = ?", (district_id,)).fetchone()
    if not district:
        return jsonify({"error": "District not found"}), 404

    from app.ml import predict_current_conditions, predict_future_conditions, chi_to_risk_level
    from app.preprocessing import _EE_INITIALIZED, get_district_historical_trend
    from app.routes import _get_district_features
    from app.health_risk import get_district_hhri

    # Fetch features and predictions
    features = _get_district_features(district, _EE_INITIALIZED)
    current_chi = predict_current_conditions(features)
    current_risk = chi_to_risk_level(current_chi)
    hhri_result = get_district_hhri(dict(district))

    # Future prediction
    future_result = predict_future_conditions(features)
    future_chi = future_result['predicted_chi']
    future_risk = chi_to_risk_level(future_chi)

    # Historical trend
    trend = get_district_historical_trend(district_id)
    trend_slope = trend[-1]['lst_slope'] if trend else 0.18

    # Generate markdown content
    report = f"""# HEATSENSE UHI ANALYSIS & HEALTH ASSESSMENT REPORT
Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Study Area: {district['name']}, Karnataka, India
District Coordinates: Lat {district['latitude']}, Lon {district['longitude']}

=========================================

1. CURRENT ENVIRONMENTAL PROFILE
--------------------------------
- Land Surface Temperature (LST): {features['lst']:.1f} °C
- Air Temperature (2m): {features['air_temp']:.1f} °C
- Normalized Difference Vegetation (NDVI): {features['ndvi']:.3f}
- Built-up Index (NDBI): {features['ndbi']:.3f}
- Relative Humidity: {features['relative_humidity']:.1f}%
- Wind Speed: {features['wind_speed']:.1f} m/s
- Land Use/Cover Heat Rating: {features['lulc_heat']:.2f}

2. MACHINE LEARNING UHI INDEX & PREDICTIONS
------------------------------------------
- Current Composite Heat Index (CHI): {current_chi:.3f}
- Heat Vulnerability Risk Rating: {current_risk}
- Heat Health Risk Index (HHRI): {hhri_result['hhri']:.3f}

Forecasted Future Climate Scenario (+1.5°C Global Temp Increase & -10% Green Space):
- Projected Future CHI: {future_chi:.3f}
- Projected Risk Level: {future_risk}
- Primary Health Advisory: {hhri_result['advisory']}

3. HISTORICAL WARMING SLOPE
---------------------------
- Decadal Temperature Warming Trend (2015-2025): +{trend_slope:.3f} °C / year
- Epoch Temperature Delta (2022-2025 vs 2015-2018): +{trend_slope * 7:.1f} °C

4. HEALTH INTERVENTION & MITIGATION RECOMMENDATIONS
--------------------------------------------------
* Vegetation Expansion (Cooling potential: -1.8°C LST)
* Green Roof Retrofitting (Cooling potential: -1.2°C LST)
* Built-up Density Control (Cooling potential: -2.0°C LST)
* Urban Parks Development (Cooling potential: -2.2°C LST)

=========================================
Emergency Contacts:
- Arogya Sahayavani: 104
- Ambulance: 108
- BBMP Heat Helpline: 080-22221188
"""
    from flask import Response
    return Response(
        report,
        mimetype="text/markdown",
        headers={"Content-disposition": f"attachment; filename=HeatSense_{district['name'].replace(' ', '_')}_Report.md"}
    )


@main_bp.route('/api/alerts')
def api_alerts_json():
    """
    JSON API endpoint to fetch seeded health alerts from the database.
    """
    from app.health_risk import get_all_alerts
    db = get_db()
    alerts_list = get_all_alerts(db)
    
    result = []
    for a in alerts_list:
        result.append({
            "id": a["id"],
            "alert_date": a["alert_date"],
            "risk_level": a["risk_level"],
            "advisory_message": a["advisory_message"],
            "status": a["status"],
            "district_name": a["district_name"]

        })
    return jsonify(result)


@main_bp.route('/api/download-pdf')
def api_download_pdf():
    """
    Renders a print-ready HTML page summarizing the UHI predictions and indices.
    Triggers browser printing to PDF via window.print().
    """
    from datetime import datetime
    district_id = request.args.get('district_id', type=int)
    if not district_id:
        return jsonify({"error": "Missing district_id"}), 400

    db = get_db()
    district = db.execute("SELECT * FROM districts WHERE id = ?", (district_id,)).fetchone()
    if not district:
        return jsonify({"error": "District not found"}), 404

    from app.ml import predict_current_conditions, predict_future_conditions, chi_to_risk_level
    from app.preprocessing import _EE_INITIALIZED
    from app.routes import _get_district_features
    from app.health_risk import get_district_hhri

    features = _get_district_features(district, _EE_INITIALIZED)
    current_chi = predict_current_conditions(features)
    current_risk = chi_to_risk_level(current_chi)
    hhri_result = get_district_hhri(dict(district))

    future_result = predict_future_conditions(features)
    future_chi = future_result['predicted_chi']
    future_risk = chi_to_risk_level(future_chi)

    return render_template(
        'pdf_report.html',
        district=district,
        date_now=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        features=features,
        current_chi=current_chi,
        current_risk=current_risk,
        hhri=hhri_result,
        future_chi=future_chi,
        future_risk=future_risk
    )



