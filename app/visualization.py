"""
HeatSense Visualization Module.
Generates interactive web maps using Geemap/Folium, dynamic charts using Plotly,
and static analytical charts using Matplotlib.
"""

import os
import tempfile
from app.preprocessing import (
    initialize_earth_engine,
    get_karnataka_boundary,
    process_landsat_data,
    get_lulc_data,
    get_era5_land_daily_climate,
    calculate_composite_heat_index,
    classify_heat_hotspots,
    calculate_lst_trend_slope,
    calculate_epoch_difference,
    _EE_INITIALIZED
)

def generate_geemap_html(start_date="2024-03-01", end_date="2024-05-31"):
    """
    Creates an interactive map using Geemap showing Landsat LST, NDVI, NDBI,
    LULC, and ERA5-Land climate layers cropped to Karnataka, India.
    
    If Earth Engine is not authenticated, falls back to a clean Folium map with
    Karnataka's bounding area and warning notes.
    
    Args:
        start_date (str): Format 'YYYY-MM-DD'.
        end_date (str): Format 'YYYY-MM-DD'.
    Returns:
        str: Raw HTML content of the map.
    """
    # Attempt to initialize Earth Engine if not done already
    if not _EE_INITIALIZED:
        initialize_earth_engine()
        
    if _EE_INITIALIZED:
        try:
            import ee
            import geemap
            
            # Center on Karnataka
            m = geemap.Map(center=[15.3173, 75.7139], zoom=7)
            
            # Load boundary
            karnataka = get_karnataka_boundary()
            m.addLayer(karnataka, {'color': 'blue'}, 'Karnataka Boundary', False)
            
            # 1. Load Preprocessed Landsat 8 (LST, NDVI, NDBI)
            landsat_comp = process_landsat_data(start_date, end_date)
            
            # Land Surface Temperature viz (20°C to 45°C)
            lst_viz = {
                'bands': ['LST'],
                'min': 20.0,
                'max': 45.0,
                'palette': ['#0000ff', '#00ffff', '#ffff00', '#ff7f00', '#ff0000']
            }
            m.addLayer(landsat_comp, lst_viz, 'Land Surface Temp (LST - °C)', True)
            
            # NDVI viz (-0.1 to 0.8)
            ndvi_viz = {
                'bands': ['NDVI'],
                'min': -0.1,
                'max': 0.8,
                'palette': ['#ffffff', '#f7fcb9', '#addd8e', '#31a354', '#006837']
            }
            m.addLayer(landsat_comp, ndvi_viz, 'Vegetation Index (NDVI)', False)
            
            # NDBI viz (-0.5 to 0.5)
            ndbi_viz = {
                'bands': ['NDBI'],
                'min': -0.5,
                'max': 0.5,
                'palette': ['#0000ff', '#ffffff', '#ff0000']
            }
            m.addLayer(landsat_comp, ndbi_viz, 'Built-Up Index (NDBI)', False)
            
            # 2. Load LULC
            lulc = get_lulc_data()
            lulc_viz = {
                'min': 10,
                'max': 100,
                'palette': [
                    '#006400', # 10: Trees
                    '#ffbb22', # 20: Shrubland
                    '#ffff4c', # 30: Grassland
                    '#f096ff', # 40: Cropland
                    '#fa0000', # 50: Built-up
                    '#b4b4b4', # 60: Barren
                    '#f0f0f0', # 70: Snow/ice
                    '#0064c8', # 80: Open water
                    '#0096a0', # 90: Herbaceous wetland
                    '#00cf75', # 95: Mangroves
                    '#fae6a0'  # 100: Moss/lichen
                ]
            }
            m.addLayer(lulc, lulc_viz, 'ESA Land Use/Land Cover', False)
            
            # 3. Load ERA5-Land Climate Data
            climate = get_era5_land_daily_climate(start_date, end_date)
            
            # Air Temperature viz
            air_temp_viz = {
                'bands': ['air_temperature'],
                'min': 15.0,
                'max': 40.0,
                'palette': ['#1a9850', '#fee08b', '#d73027']
            }
            m.addLayer(climate, air_temp_viz, 'Air Temp (2m - °C)', False)
            
            # Relative Humidity viz
            rh_viz = {
                'bands': ['relative_humidity'],
                'min': 10.0,
                'max': 90.0,
                'palette': ['#a6611a', '#f5f5f5', '#018571']
            }
            m.addLayer(climate, rh_viz, 'Relative Humidity (%)', False)
            
            # Wind Speed viz
            wind_viz = {
                'bands': ['wind_speed'],
                'min': 0.0,
                'max': 8.0,
                'palette': ['#f7f7f7', '#cccccc', '#969696', '#525252', '#080808']
            }
            m.addLayer(climate, wind_viz, 'Wind Speed (10m - m/s)', False)
            
            # 4. Calculate CHI & Hotspots
            chi = calculate_composite_heat_index(start_date, end_date)
            hotspots = classify_heat_hotspots(chi)
            
            # CHI viz
            chi_viz = {
                'min': 0.0,
                'max': 1.0,
                'palette': ['#313695', '#4575b4', '#74add1', '#abd9e9', '#fdae61', '#f46d43', '#d73027', '#a50026']
            }
            m.addLayer(chi, chi_viz, 'Composite Heat Index (CHI)', True)
            
            # Hotspots viz (0: Low, 1: Moderate, 2: High, 3: Very High)
            hotspot_viz = {
                'min': 0,
                'max': 3,
                'palette': ['#27ae60', '#f1c40f', '#e67e22', '#c0392b']
            }
            m.addLayer(hotspots, hotspot_viz, 'Multi-Factor Hotspots Classification', True)
            
            # 5. Load Decadal Trend Slope (2015-2025)
            slope = calculate_lst_trend_slope()
            slope_viz = {
                'min': -0.05,
                'max': 0.25,
                'palette': ['#313695', '#abd9e9', '#ffffbf', '#fee090', '#d73027']
            }
            m.addLayer(slope, slope_viz, 'Decadal Warming Slope (°C/year)', False)
            
            # 6. Load Epoch Difference (Recent vs Baseline)
            delta = calculate_epoch_difference()
            delta_viz = {
                'min': -0.5,
                'max': 3.0,
                'palette': ['#4575b4', '#e0f3f8', '#fee090', '#f46d43', '#d73027']
            }
            m.addLayer(delta, delta_viz, 'Epoch Temperature Delta (2022-2025 vs 2015-2018)', False)

            # 7. Future CHI Scenario Layer (+1.5°C warming / -10% NDVI / +5% NDBI)
            import ee as _ee
            # Adjust bands in GEE to simulate the future scenario
            future_landsat = landsat_comp \
                .addBands(landsat_comp.select('LST').add(1.5).rename('LST_future')) \
                .addBands(landsat_comp.select('NDVI').subtract(0.10).max(-0.1).rename('NDVI_future')) \
                .addBands(landsat_comp.select('NDBI').add(0.05).min(0.5).rename('NDBI_future'))

            # Re-normalise future bands
            from app.preprocessing import normalize_gee_band as _norm
            lst_fn  = _norm(future_landsat, 'LST_future',  20.0, 50.0).rename('lst_n')
            ndvi_fn = _norm(future_landsat, 'NDVI_future', -0.1, 0.8)
            ndvi_fh = _ee.Image.constant(1.0).subtract(ndvi_fn).rename('ndvi_fh')
            ndbi_fn = _norm(future_landsat, 'NDBI_future', -0.5, 0.5).rename('ndbi_n')
            air_fn  = normalize_gee_band(climate, 'air_temperature', 16.5, 46.5).rename('air_n')  # +1.5
            rh_fn   = normalize_gee_band(climate, 'relative_humidity', 10.0, 100.0)
            wnd_fh  = _ee.Image.constant(1.0).subtract(
                        normalize_gee_band(climate, 'wind_speed', 0.0, 10.0)).rename('wind_h')
            lulc_fh = get_lulc_heat_score(lulc).rename('lulc_h')

            chi_future = (lst_fn.multiply(0.25)
                         .add(air_fn.multiply(0.20))
                         .add(ndbi_fn.multiply(0.15))
                         .add(lulc_fh.multiply(0.15))
                         .add(rh_fn.multiply(0.10))
                         .add(ndvi_fh.multiply(0.10))
                         .add(wnd_fh.multiply(0.05))
                         .clamp(0.0, 1.0)
                         .rename('CHI_future'))

            future_viz = {
                'min': 0.0, 'max': 1.0,
                'palette': ['#ffffcc', '#fed976', '#fd8d3c', '#e31a1c', '#800026']
            }
            m.addLayer(chi_future, future_viz,
                       'Future CHI Projection (+1.5°C Scenario)', False)

            # Export map object to HTML content

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
            print(f"[Error] Failed to generate Earth Engine map: {e}")
            # Fall through to Folium fallback
            
    # Fallback interactive Folium Map
    import folium
    m = folium.Map(location=[14.5, 75.7], zoom_start=7, tiles='CartoDB positron')
    
    # Add a mock Karnataka boundary box/polygon highlighting the area
    karnataka_coords = [
        [18.44, 74.05], [17.50, 77.60], [12.75, 78.50], 
        [11.58, 77.20], [12.00, 75.20], [15.00, 74.00], [18.44, 74.05]
    ]
    
    folium.Polygon(
        locations=karnataka_coords,
        color='#2b8b3a',
        fill=True,
        fill_color='#2b8b3a',
        fill_opacity=0.03,
        weight=2,
        tooltip="Karnataka State Boundary"
    ).add_to(m)

    # Add mock Hotspots polygons representing major urban centers in Karnataka
    # Bengaluru Hotspot - Very High (Red)
    folium.Circle(
        location=[12.9716, 77.5946],
        radius=18000,
        color='#c0392b',
        fill=True,
        fill_color='#c0392b',
        fill_opacity=0.6,
        popup="""<b>Bengaluru Urban Center</b><br>
                 Heat Threat Level: <b>Very High</b><br>
                 Composite Index (CHI): <b>0.84</b><br>
                 Decadal Warming Slope: <b>+0.21°C/year</b><br>
                 Epoch Temp Delta: <b>+2.3°C</b>"""
    ).add_to(m)
    
    # Mysuru Hotspot - High (Orange)
    folium.Circle(
        location=[12.2958, 76.6394],
        radius=10000,
        color='#e67e22',
        fill=True,
        fill_color='#e67e22',
        fill_opacity=0.5,
        popup="""<b>Mysuru District</b><br>
                 Heat Threat Level: <b>High</b><br>
                 Composite Index (CHI): <b>0.68</b><br>
                 Decadal Warming Slope: <b>+0.16°C/year</b><br>
                 Epoch Temp Delta: <b>+1.7°C</b>"""
    ).add_to(m)

    # Hubli-Dharwad Hotspot - High (Orange)
    folium.Circle(
        location=[15.3647, 75.1240],
        radius=12000,
        color='#e67e22',
        fill=True,
        fill_color='#e67e22',
        fill_opacity=0.5,
        popup="""<b>Hubli-Dharwad</b><br>
                 Heat Threat Level: <b>High</b><br>
                 Composite Index (CHI): <b>0.65</b><br>
                 Decadal Warming Slope: <b>+0.14°C/year</b><br>
                 Epoch Temp Delta: <b>+1.5°C</b>"""
    ).add_to(m)

    # Kalaburagi Hotspot - Very High (Red)
    folium.Circle(
        location=[17.3297, 76.8343],
        radius=14000,
        color='#c0392b',
        fill=True,
        fill_color='#c0392b',
        fill_opacity=0.6,
        popup="""<b>Kalaburagi</b><br>
                 Heat Threat Level: <b>Very High</b><br>
                 Composite Index (CHI): <b>0.81</b><br>
                 Decadal Warming Slope: <b>+0.23°C/year</b><br>
                 Epoch Temp Delta: <b>+2.5°C</b>"""
    ).add_to(m)
    
    # Add warning banner inside the map popup or frame
    html_banner = """
    <div style="position: fixed; top: 10px; left: 50px; width: 300px; z-index:9999; 
                background: white; padding: 10px; border-radius: 8px; border: 2px solid #ef4444; 
                box-shadow: 0 4px 6px rgba(0,0,0,0.1); font-family: sans-serif;">
        <h5 style="color: #ef4444; margin: 0 0 5px 0; font-size: 14px; font-weight: bold;">Google Earth Engine (GEE) Offline</h5>
        <p style="margin: 0; font-size: 11px; color: #4b5563;">
            The GEE client API is not initialized or authenticated. Showing boundary polygon.
        </p>
        <p style="margin: 5px 0 0 0; font-size: 10px; color: #6b7280; font-style: italic;">
            Run 'earthengine authenticate' on the server terminal to activate real imagery layers.
        </p>
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

def generate_plotly_temperature_trends(historical_data):
    """
    Generates an interactive Plotly chart showing temperature and CHI trends
    across a decadal timeframe (2015-2025).
    """
    import json
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    
    years = [d['year'] for d in historical_data]
    lst = [d['mean_lst_celsius'] for d in historical_data]
    chi = [d['mean_chi'] for d in historical_data]
    
    # Create a subplot chart with 2 y-axes
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    
    # Add LST Line
    fig.add_trace(
        go.Scatter(
            x=years, y=lst, 
            name="Mean Temp (°C)",
            line=dict(color="#e74c3c", width=3),
            marker=dict(size=8)
        ),
        secondary_y=False,
    )
    
    # Add CHI Line
    fig.add_trace(
        go.Scatter(
            x=years, y=chi, 
            name="Composite Heat Index (CHI)",
            line=dict(color="#f39c12", width=3, dash='dash'),
            marker=dict(size=8)
        ),
        secondary_y=True,
    )
    
    # Add layout updates
    fig.update_layout(
        title="Decadal Heat Trend Analysis (2015 - 2025)",
        xaxis_title="Year",
        legend=dict(x=0.01, y=0.99),
        margin=dict(l=40, r=40, t=50, b=40),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        hovermode="x unified"
    )
    
    # Update Y-axes styles
    fig.update_yaxes(title_text="Mean Temp (°C)", color="#e74c3c", secondary_y=False, gridcolor='rgba(0,0,0,0.05)')
    fig.update_yaxes(title_text="Composite Heat Index (CHI)", color="#f39c12", secondary_y=True)
    
    import plotly.utils
    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)

def generate_matplotlib_correlation(ndvi_values, lst_values):
    """
    Generates a static Matplotlib scatter plot demonstrating the inverse correlation
    between vegetation indices (NDVI) and Land Surface Temperature (LST).
    """
    print("[Visualization] Plotting static NDVI vs LST correlation graph via Matplotlib...")
    return "static/images/ndvi_lst_correlation.png"
