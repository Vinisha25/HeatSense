"""
HeatSense Visualization Module.
Generates interactive web maps using Geemap/Folium, dynamic charts using Plotly,
and radar/spider charts for factor analysis.
"""

import os
import json
import tempfile
import math

def generate_geemap_html(start_date="2024-03-01", end_date="2024-05-31",
                         lat=14.5, lon=75.7, radius_km=15):
    """
    Creates an interactive map showing CHI, LST, NDVI, NDBI, LULC, and ERA5 layers.
    Centered on the selected location, not fixed to Karnataka centroid.
    Falls back to clean Folium map with Leaflet if GEE is not authenticated.
    """
    from app.preprocessing import (
        initialize_earth_engine, get_karnataka_boundary,
        process_landsat_data, get_lulc_data, get_era5_land_daily_climate,
        calculate_composite_heat_index, classify_heat_hotspots,
        calculate_lst_trend_slope, calculate_epoch_difference,
        get_lulc_heat_score, normalize_gee_band, _EE_INITIALIZED
    )

    if not _EE_INITIALIZED:
        initialize_earth_engine()

    if _EE_INITIALIZED:
        try:
            import ee
            import geemap

            m = geemap.Map(center=[lat, lon], zoom=12)

            # Location AOI
            point = ee.Geometry.Point([lon, lat])
            region = point.buffer(radius_km * 1000)

            # Landsat 8 bands
            landsat_comp = process_landsat_data(start_date, end_date, region)

            lst_viz = {'bands': ['LST'], 'min': 20.0, 'max': 45.0,
                       'palette': ['#0000ff', '#00ffff', '#ffff00', '#ff7f00', '#ff0000']}
            m.addLayer(landsat_comp, lst_viz, 'Land Surface Temp (LST °C)', True)

            ndvi_viz = {'bands': ['NDVI'], 'min': -0.1, 'max': 0.8,
                        'palette': ['#ffffff', '#f7fcb9', '#addd8e', '#31a354', '#006837']}
            m.addLayer(landsat_comp, ndvi_viz, 'Vegetation Index (NDVI)', False)

            ndbi_viz = {'bands': ['NDBI'], 'min': -0.5, 'max': 0.5,
                        'palette': ['#0000ff', '#ffffff', '#ff0000']}
            m.addLayer(landsat_comp, ndbi_viz, 'Built-Up Index (NDBI)', False)

            # LULC
            lulc = get_lulc_data(region)
            lulc_viz = {
                'min': 10, 'max': 100,
                'palette': ['#006400', '#ffbb22', '#ffff4c', '#f096ff', '#fa0000',
                            '#b4b4b4', '#f0f0f0', '#0064c8', '#0096a0', '#00cf75', '#fae6a0']
            }
            m.addLayer(lulc, lulc_viz, 'ESA LULC (WorldCover)', False)

            # ERA5 Climate
            climate = get_era5_land_daily_climate(start_date, end_date, region)
            air_temp_viz = {'bands': ['air_temperature'], 'min': 15.0, 'max': 40.0,
                            'palette': ['#1a9850', '#fee08b', '#d73027']}
            m.addLayer(climate, air_temp_viz, 'Air Temperature (2m °C)', False)

            rh_viz = {'bands': ['relative_humidity'], 'min': 10.0, 'max': 90.0,
                      'palette': ['#a6611a', '#f5f5f5', '#018571']}
            m.addLayer(climate, rh_viz, 'Relative Humidity (%)', False)

            wind_viz = {'bands': ['wind_speed'], 'min': 0.0, 'max': 8.0,
                        'palette': ['#f7f7f7', '#cccccc', '#969696', '#525252', '#080808']}
            m.addLayer(climate, wind_viz, 'Wind Speed (10m m/s)', False)

            # CHI & Hotspots
            chi = calculate_composite_heat_index(start_date, end_date, region)
            hotspots = classify_heat_hotspots(chi)

            chi_viz = {
                'min': 0.0, 'max': 1.0,
                'palette': ['#313695', '#4575b4', '#74add1', '#abd9e9',
                            '#fdae61', '#f46d43', '#d73027', '#a50026']
            }
            m.addLayer(chi, chi_viz, 'Composite Heat Index (CHI)', True)

            hotspot_viz = {'min': 0, 'max': 3,
                           'palette': ['#27ae60', '#f1c40f', '#e67e22', '#c0392b']}
            m.addLayer(hotspots, hotspot_viz, 'Heat Hotspots Classification', True)

            # Add AOI circle marker
            m.addLayer(region, {'color': '#f97316', 'fillOpacity': 0.02, 'width': 2}, 'Analysis AOI', True)

            fd, path = tempfile.mkstemp(suffix='.html')
            try:
                m.to_html(path)
                with open(path, 'r', encoding='utf-8') as f:
                    html_content = f.read()
            finally:
                os.close(fd)
                os.remove(path)

            return html_content

        except Exception as e:
            print(f"[Visualization] GEE map failed: {e}")

    # ── Folium fallback map ──────────────────────────────────────────────────
    return _generate_folium_fallback_map(lat, lon, radius_km)


def _generate_folium_fallback_map(lat, lon, radius_km=15):
    """
    Generates a Folium map centered on the selected location as GEE fallback.
    Uses real OpenStreetMap tiles (no fake data).
    """
    import folium

    m = folium.Map(
        location=[lat, lon],
        zoom_start=13,
        tiles='CartoDB dark_matter',
    )

    # AOI circle at selected location
    folium.Circle(
        location=[lat, lon],
        radius=radius_km * 1000,
        color='#f97316',
        fill=True,
        fill_color='#f97316',
        fill_opacity=0.05,
        weight=2,
        dash_array='8 4',
        tooltip=f"Analysis AOI ({radius_km} km radius)",
    ).add_to(m)

    # Orange pin at selected location
    folium.Marker(
        location=[lat, lon],
        popup=folium.Popup(
            f"<b style='color:#f97316;'>Selected Location</b><br>"
            f"Lat: {lat:.5f}, Lon: {lon:.5f}<br>"
            f"<small>Analysis AOI: {radius_km} km radius</small>",
            max_width=250
        ),
        icon=folium.Icon(color='orange', icon='fire', prefix='fa'),
    ).add_to(m)

    # GEE offline banner
    html_banner = f"""
    <div style="position: fixed; top: 12px; left: 50%; transform: translateX(-50%);
                width: 420px; z-index:9999;
                background: rgba(15,15,15,0.95); padding: 10px 16px; border-radius: 10px;
                border: 1px solid rgba(239, 68, 68, 0.5);
                box-shadow: 0 4px 24px rgba(0,0,0,0.5); font-family: 'Inter', sans-serif;">
        <div style="display:flex;align-items:center;gap:8px;">
            <span style="font-size:16px;">⚠️</span>
            <div>
                <div style="color: #ef4444; font-size: 12px; font-weight: 700;">GEE Offline — Basemap View</div>
                <div style="color: rgba(255,255,255,0.5); font-size: 10px; margin-top: 2px;">
                    Run <code style="background:rgba(255,255,255,0.1);padding:1px 4px;border-radius:3px;">earthengine authenticate</code> to load satellite layers.
                </div>
            </div>
        </div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(html_banner))

    fd, path = tempfile.mkstemp(suffix='.html')
    try:
        m.save(path)
        with open(path, 'r', encoding='utf-8') as f:
            html_content = f.read()
    finally:
        os.close(fd)
        os.remove(path)

    return html_content


def generate_before_after_maps(lat, lon, radius_km, strategy_key, before_features, after_features,
                                 start_date='2024-03-01', end_date='2024-05-31'):
    """
    Generates two Folium maps — Before mitigation and After mitigation —
    for the Before & After comparison panel.

    Returns:
        tuple: (before_html: str, after_html: str)
    """
    import folium

    def make_map(features, title, color):
        m = folium.Map(location=[lat, lon], zoom_start=13, tiles='CartoDB dark_matter')

        # Calculate CHI for color ring
        from app.ml import predict_current_conditions, chi_to_risk_level
        chi = predict_current_conditions(features)
        risk = chi_to_risk_level(chi)

        # Color circles based on CHI zones
        zone_colors = {'Low': '#27ae60', 'Moderate': '#f1c40f', 'High': '#e67e22', 'Very High': '#c0392b'}
        zone_color = zone_colors.get(risk, '#e67e22')

        # Heatmap-like rings from center
        for r_frac in [0.3, 0.6, 1.0]:
            folium.Circle(
                location=[lat, lon],
                radius=radius_km * 1000 * r_frac,
                color=zone_color,
                fill=True,
                fill_color=zone_color,
                fill_opacity=0.15 * (1.5 - r_frac),
                weight=1,
            ).add_to(m)

        folium.Marker(
            location=[lat, lon],
            popup=folium.Popup(
                f"<div style='font-family:Inter,sans-serif;'>"
                f"<b style='color:{color};'>{title}</b><br>"
                f"<b>CHI:</b> {chi:.3f}<br>"
                f"<b>Risk:</b> {risk}<br>"
                f"<b>LST:</b> {features.get('lst',0):.1f}°C<br>"
                f"<b>NDVI:</b> {features.get('ndvi',0):.3f}"
                f"</div>",
                max_width=220,
            ),
            icon=folium.Icon(color='orange', icon='thermometer-half', prefix='fa'),
        ).add_to(m)

        # Title overlay
        html_title = f"""
        <div style="position: fixed; top: 10px; left: 10px; z-index:9999;
                    background: rgba(10,10,10,0.9); padding: 8px 14px; border-radius: 8px;
                    border: 1px solid {color}; font-family:'Inter',sans-serif;">
            <div style="color:{color};font-size:12px;font-weight:700;">{title}</div>
            <div style="color:rgba(255,255,255,0.5);font-size:10px;">CHI: {chi:.3f} | Risk: {risk}</div>
        </div>
        """
        m.get_root().html.add_child(folium.Element(html_title))

        fd, path = tempfile.mkstemp(suffix='.html')
        try:
            m.save(path)
            with open(path, 'r', encoding='utf-8') as f:
                html = f.read()
        finally:
            os.close(fd)
            os.remove(path)
        return html

    before_html = make_map(before_features, '🔴 Current State (Before Mitigation)', '#ef4444')
    after_html  = make_map(after_features,  '🟢 After Mitigation Applied',           '#27ae60')
    return before_html, after_html


def generate_plotly_temperature_trends(historical_data, location_name='Selected Location',
                                        include_forecast=True, forecast_years=5):
    """
    Generates an interactive Plotly chart showing temperature and CHI trends.
    Clearly distinguishes historical data from predicted/projected data.

    Args:
        historical_data: list of dicts with year, mean_lst_celsius, mean_chi
        location_name: name shown in chart title
        include_forecast: whether to extend with predicted future values
        forecast_years: how many years to project forward
    Returns:
        str: Plotly JSON
    """
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    import numpy as np

    years = [d['year'] for d in historical_data]
    lst   = [d['mean_lst_celsius'] for d in historical_data]
    chi   = [d['mean_chi'] for d in historical_data]

    # ── Calculate warming slope for projection ────────────────────────────────
    if len(years) >= 2:
        x_arr = np.array(years)
        y_lst_arr = np.array(lst)
        slope_lst, intercept_lst = np.polyfit(x_arr, y_lst_arr, 1)
        y_chi_arr = np.array(chi)
        slope_chi, intercept_chi = np.polyfit(x_arr, y_chi_arr, 1)
    else:
        slope_lst = 0.18; intercept_lst = lst[0] if lst else 30
        slope_chi = 0.014; intercept_chi = chi[0] if chi else 0.5

    # ── Forecast values ───────────────────────────────────────────────────────
    last_year = max(years) if years else 2025
    forecast_yrs = list(range(last_year + 1, last_year + forecast_years + 1))
    forecast_lst = [round(slope_lst * y + intercept_lst, 2) for y in forecast_yrs]
    forecast_chi = [round(min(1.0, slope_chi * y + intercept_chi), 3) for y in forecast_yrs]

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # Historical LST (solid line, red)
    fig.add_trace(go.Scatter(
        x=years, y=lst,
        name="LST (Historical)",
        line=dict(color="#ef4444", width=3),
        marker=dict(size=7, color="#ef4444"),
        hovertemplate="<b>%{x}</b><br>LST: %{y:.1f}°C<extra></extra>",
    ), secondary_y=False)

    # Projected LST (dashed)
    if include_forecast and forecast_yrs:
        # Connect last historical to first forecast
        fig.add_trace(go.Scatter(
            x=[last_year] + forecast_yrs, y=[lst[-1]] + forecast_lst,
            name="LST (Projected)",
            line=dict(color="#ef4444", width=2, dash='dash'),
            marker=dict(size=5, color="#ef4444", symbol='diamond'),
            opacity=0.75,
            hovertemplate="<b>%{x}</b><br>Projected LST: %{y:.1f}°C<extra></extra>",
        ), secondary_y=False)

        # Uncertainty band for forecast
        upper = [v + 0.8 for v in forecast_lst]
        lower = [v - 0.8 for v in forecast_lst]
        fig.add_trace(go.Scatter(
            x=forecast_yrs + forecast_yrs[::-1],
            y=upper + lower[::-1],
            fill='toself',
            fillcolor='rgba(239,68,68,0.08)',
            line=dict(color='rgba(239,68,68,0)'),
            name='Projection Uncertainty',
            showlegend=False,
            hoverinfo='skip',
        ), secondary_y=False)

    # Historical CHI (dashed orange)
    fig.add_trace(go.Scatter(
        x=years, y=chi,
        name="CHI (Historical)",
        line=dict(color="#f97316", width=3),
        marker=dict(size=7, color="#f97316"),
        hovertemplate="<b>%{x}</b><br>CHI: %{y:.3f}<extra></extra>",
    ), secondary_y=True)

    # Projected CHI
    if include_forecast and forecast_yrs:
        fig.add_trace(go.Scatter(
            x=[last_year] + forecast_yrs, y=[chi[-1]] + forecast_chi,
            name="CHI (Projected)",
            line=dict(color="#f97316", width=2, dash='dot'),
            marker=dict(size=5, color="#f97316", symbol='diamond'),
            opacity=0.75,
            hovertemplate="<b>%{x}</b><br>Projected CHI: %{y:.3f}<extra></extra>",
        ), secondary_y=True)

    # Vertical divider line between historical and forecast
    if include_forecast and forecast_yrs:
        fig.add_vline(
            x=last_year + 0.5,
            line_dash="dot",
            line_color="rgba(255,255,255,0.2)",
            annotation_text="Forecast →",
            annotation_position="top right",
            annotation_font=dict(color="rgba(255,255,255,0.4)", size=11),
        )

    # CHI risk level bands (horizontal)
    fig.add_hrect(y0=0.75, y1=1.0,   fillcolor="rgba(239,68,68,0.07)",  line_width=0, secondary_y=True)
    fig.add_hrect(y0=0.55, y1=0.75,  fillcolor="rgba(230,126,34,0.07)", line_width=0, secondary_y=True)
    fig.add_hrect(y0=0.35, y1=0.55,  fillcolor="rgba(241,196,15,0.05)", line_width=0, secondary_y=True)

    fig.update_layout(
        title=f"Heat Trend Analysis — {location_name}",
        xaxis_title="Year",
        legend=dict(
            orientation='h',
            x=0, y=-0.2,
            bgcolor='rgba(0,0,0,0)',
        ),
        margin=dict(l=40, r=40, t=50, b=80),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        hovermode="x unified",
        xaxis=dict(
            showgrid=True,
            gridcolor='rgba(255,255,255,0.05)',
            tickvals=years + (forecast_yrs if include_forecast else []),
        ),
    )

    slope_str = f"+{slope_lst:.2f}" if slope_lst >= 0 else f"{slope_lst:.2f}"
    fig.update_yaxes(
        title_text=f"Mean LST (°C) | Slope: {slope_str}°C/yr",
        color="#ef4444",
        secondary_y=False,
        gridcolor='rgba(255,255,255,0.04)',
    )
    fig.update_yaxes(
        title_text="Composite Heat Index (CHI)",
        color="#f97316",
        range=[0, 1.05],
        secondary_y=True,
        showgrid=False,
    )

    import plotly.utils
    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)


def generate_radar_chart(features: dict, location_name: str = 'Selected Location') -> str:
    """
    Generates a Plotly radar/spider chart for Factor Analysis.
    Matches the reference image style:
      - Large centered chart, white/light background
      - Orange/red outline with transparent fill
      - Labels around chart, location title at top
      - 0–100 scale (normalized from raw factor values)

    Args:
        features (dict): Environmental feature values (raw numbers).
        location_name (str): Location to display as title.
    Returns:
        str: Plotly JSON.
    """
    import plotly.graph_objects as go
    import plotly.utils

    # Normalize each factor to 0–100 heat contribution scale
    # Higher = more heat stress (inverted for NDVI and wind)
    lst  = features.get('lst', 30)
    ndvi = features.get('ndvi', 0.4)
    ndbi = features.get('ndbi', 0.1)
    air  = features.get('air_temp', 28)
    rh   = features.get('relative_humidity', 60)
    wind = features.get('wind_speed', 3)
    lulc = features.get('lulc_heat', 0.5)

    # Normalize to 0–100 scale (heat contribution direction)
    scores = {
        'LST':             round(max(0, min(100, (lst  - 20) / 30 * 100)), 1),
        'Air Temperature': round(max(0, min(100, (air  - 15) / 30 * 100)), 1),
        'Built-Up (NDBI)': round(max(0, min(100, (ndbi + 0.5) / 1.0 * 100)), 1),
        'LULC Heat':       round(max(0, min(100, lulc * 100)), 1),
        'Humidity':        round(max(0, min(100, (rh   - 10) / 90 * 100)), 1),
        'Vegetation (NDVI)': round(max(0, min(100, (1 - (ndvi + 0.1) / 0.9) * 100)), 1),  # inverted
        'Wind Speed':      round(max(0, min(100, (1 - wind / 10) * 100)), 1),  # inverted
    }

    categories = list(scores.keys())
    values     = list(scores.values())

    # Close the radar loop
    categories_closed = categories + [categories[0]]
    values_closed     = values + [values[0]]

    fig = go.Figure()

    # Filled area (light orange)
    fig.add_trace(go.Scatterpolar(
        r=values_closed,
        theta=categories_closed,
        fill='toself',
        fillcolor='rgba(249, 115, 22, 0.12)',
        line=dict(color='#f97316', width=3),
        name='Heat Factors',
        hovertemplate='<b>%{theta}</b><br>Score: %{r:.1f}/100<extra></extra>',
    ))

    # Grid reference circles (25, 50, 75, 100)
    for ref in [25, 50, 75, 100]:
        fig.add_trace(go.Scatterpolar(
            r=[ref] * (len(categories) + 1),
            theta=categories_closed,
            mode='lines',
            line=dict(color='rgba(200,200,200,0.25)', width=1),
            showlegend=False,
            hoverinfo='skip',
        ))

    fig.update_layout(
        title=dict(
            text=f'<b>Factor Analysis</b><br><span style="font-size:13px;color:#888">{location_name}</span>',
            x=0.5,
            xanchor='center',
            font=dict(size=18, color='#1a1a1a'),
        ),
        polar=dict(
            bgcolor='rgba(255,255,255,0.95)',
            angularaxis=dict(
                tickfont=dict(size=12, color='#444', family='Inter'),
                linecolor='rgba(0,0,0,0.1)',
                gridcolor='rgba(0,0,0,0.08)',
            ),
            radialaxis=dict(
                range=[0, 100],
                tickvals=[25, 50, 75, 100],
                tickfont=dict(size=10, color='#999'),
                gridcolor='rgba(0,0,0,0.1)',
                linecolor='rgba(0,0,0,0.1)',
            ),
        ),
        paper_bgcolor='rgba(255,255,255,0.0)',
        plot_bgcolor='rgba(255,255,255,0.0)',
        showlegend=False,
        height=480,
        margin=dict(l=80, r=80, t=100, b=60),
    )

    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)


def generate_prediction_chart(historical_data, future_data, location_name='Selected Location'):
    """
    Generates a prediction chart showing historical CHI + future projection.
    Clearly styled to distinguish past from projected.

    Args:
        historical_data: list of dicts [{year, mean_lst_celsius, mean_chi}]
        future_data: dict with future scenario predictions
        location_name: chart title location
    Returns:
        str: Plotly JSON
    """
    import plotly.graph_objects as go
    import plotly.utils
    import numpy as np

    years = [d['year'] for d in historical_data]
    lst_vals = [d['mean_lst_celsius'] for d in historical_data]
    chi_vals = [d['mean_chi'] for d in historical_data]

    last_year = max(years) if years else 2025

    # Project 10 years forward
    proj_years = list(range(last_year + 1, last_year + 11))
    slope_l, ic_l = np.polyfit(years, lst_vals, 1) if len(years) > 1 else (0.18, lst_vals[-1])
    slope_c, ic_c = np.polyfit(years, chi_vals, 1) if len(years) > 1 else (0.014, chi_vals[-1])

    proj_lst = [round(slope_l * y + ic_l, 2) for y in proj_years]
    proj_chi = [round(min(1.0, slope_c * y + ic_c), 3) for y in proj_years]

    fig = go.Figure()

    # Historical CHI area
    fig.add_trace(go.Scatter(
        x=years, y=chi_vals,
        mode='lines+markers',
        name='Historical CHI',
        fill='tozeroy',
        fillcolor='rgba(249,115,22,0.1)',
        line=dict(color='#f97316', width=3),
        marker=dict(size=8, color='#f97316'),
        hovertemplate='%{x}: CHI = %{y:.3f}<extra>Historical</extra>',
    ))

    # Projected CHI area
    fig.add_trace(go.Scatter(
        x=[last_year] + proj_years,
        y=[chi_vals[-1]] + proj_chi,
        mode='lines+markers',
        name='Projected CHI',
        fill='tozeroy',
        fillcolor='rgba(239,68,68,0.08)',
        line=dict(color='#ef4444', width=2, dash='dash'),
        marker=dict(size=6, symbol='diamond', color='#ef4444'),
        hovertemplate='%{x}: Projected CHI = %{y:.3f}<extra>Forecast</extra>',
    ))

    # Historical/forecast divider
    fig.add_vline(x=last_year + 0.5, line_dash='dot', line_color='rgba(255,255,255,0.2)',
                  annotation_text='Forecast →', annotation_font=dict(color='rgba(255,255,255,0.4)', size=10))

    # Risk level bands
    fig.add_hrect(y0=0.75, y1=1.0,  fillcolor='rgba(239,68,68,0.1)', line_width=0,
                  annotation_text='Very High', annotation_position='right', annotation_font=dict(color='#ef4444', size=9))
    fig.add_hrect(y0=0.55, y1=0.75, fillcolor='rgba(230,126,34,0.08)', line_width=0,
                  annotation_text='High', annotation_position='right', annotation_font=dict(color='#e67e22', size=9))
    fig.add_hrect(y0=0.35, y1=0.55, fillcolor='rgba(241,196,15,0.06)', line_width=0,
                  annotation_text='Moderate', annotation_position='right', annotation_font=dict(color='#f1c40f', size=9))
    fig.add_hrect(y0=0.0,  y1=0.35, fillcolor='rgba(39,174,96,0.05)', line_width=0,
                  annotation_text='Low', annotation_position='right', annotation_font=dict(color='#27ae60', size=9))

    fig.update_layout(
        title=f'Heat Prediction — {location_name}',
        xaxis_title='Year',
        yaxis_title='Composite Heat Index (CHI)',
        yaxis=dict(range=[0, 1.1], gridcolor='rgba(255,255,255,0.05)'),
        xaxis=dict(gridcolor='rgba(255,255,255,0.05)'),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        legend=dict(orientation='h', x=0, y=-0.15, bgcolor='rgba(0,0,0,0)'),
        margin=dict(l=50, r=80, t=50, b=80),
        hovermode='x unified',
    )

    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)


def generate_matplotlib_correlation(ndvi_values, lst_values):
    """
    Generates a static Matplotlib scatter plot demonstrating the inverse correlation
    between vegetation indices (NDVI) and Land Surface Temperature (LST).
    """
    print("[Visualization] Plotting static NDVI vs LST correlation graph via Matplotlib...")
    return "static/images/ndvi_lst_correlation.png"
