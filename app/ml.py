"""
HeatSense Machine Learning Module — Module 4: Heat Prediction.
Implements a Random Forest Regression pipeline using Scikit-learn.

Training Features:
    LST, NDVI, NDBI, Air Temperature, Humidity, Wind Speed, LULC Heat Score

Target:
    Composite Heat Index (CHI)
"""

import os
# pyrefly: ignore [missing-import]
import numpy as np

# Constants
MODEL_DIR = os.path.join(os.path.dirname(__file__), 'models')
MODEL_PATH = os.path.join(MODEL_DIR, 'rf_chi_model.pkl')

FEATURE_NAMES = [
    'lst', 'ndvi', 'ndbi',
    'air_temp', 'relative_humidity',
    'wind_speed', 'lulc_heat'
]

# ──────────────────────────────────────────────────────────────────────────────
# 1. Dataset Preparation
# ──────────────────────────────────────────────────────────────────────────────

def extract_training_samples(start_date='2022-03-01', end_date='2024-05-31',
                              n_samples=500):
    """
    Extracts training pixel samples from Google Earth Engine by:
      1. Building all preprocessed bands as a single multi-band image.
      2. Sampling n_samples random pixels over Karnataka.
      3. Returning a list of feature dicts with the CHI target value.

    Falls back to a synthetic dataset if GEE is offline/unauthenticated.

    Args:
        start_date (str): GEE imagery start date.
        end_date   (str): GEE imagery end date.
        n_samples  (int): Number of sample pixels to extract.
    Returns:
        list[dict]: Each dict contains feature keys + 'chi'.
    """
    try:
        # pyrefly: ignore [missing-import]
        import ee
        from app.preprocessing import (
            _EE_INITIALIZED, initialize_earth_engine,
            get_karnataka_boundary,
            process_landsat_data, get_lulc_data,
            get_era5_land_daily_climate,
            normalize_gee_band, get_lulc_heat_score,
            calculate_composite_heat_index
        )

        if not _EE_INITIALIZED:
            initialize_earth_engine()

        karnataka = get_karnataka_boundary()
        landsat   = process_landsat_data(start_date, end_date)
        lulc      = get_lulc_data()
        climate   = get_era5_land_daily_climate(start_date, end_date)
        chi       = calculate_composite_heat_index(start_date, end_date)

        # Build all features + target into a single image
        lst_n  = normalize_gee_band(landsat, 'LST', 20.0, 50.0)
        ndvi_n = normalize_gee_band(landsat, 'NDVI', -0.1, 0.8)
        ndbi_n = normalize_gee_band(landsat, 'NDBI', -0.5, 0.5)
        air_n  = normalize_gee_band(climate, 'air_temperature', 15.0, 45.0)
        rh_n   = normalize_gee_band(climate, 'relative_humidity', 10.0, 100.0)
        wnd_n  = normalize_gee_band(climate, 'wind_speed', 0.0, 10.0)
        lulc_h = get_lulc_heat_score(lulc)

        # Raw (un-normalised) values for interpretability
        raw_lst = landsat.select('LST').rename('lst')
        raw_ndvi = landsat.select('NDVI').rename('ndvi')
        raw_ndbi = landsat.select('NDBI').rename('ndbi')
        raw_air  = climate.select('air_temperature').rename('air_temp')
        raw_rh   = climate.select('relative_humidity').rename('relative_humidity')
        raw_wnd  = climate.select('wind_speed').rename('wind_speed')
        lulc_band = lulc_h.rename('lulc_heat')
        chi_band  = chi.rename('chi')

        stacked = raw_lst.addBands([
            raw_ndvi, raw_ndbi, raw_air,
            raw_rh, raw_wnd, lulc_band, chi_band
        ])

        sample_fc = stacked.sample(
            region=karnataka.geometry(),
            scale=1000,
            numPixels=n_samples,
            seed=42,
            geometries=False
        )

        records = sample_fc.getInfo()['features']
        dataset = []
        for feat in records:
            props = feat['properties']
            row = {k: props.get(k, 0.0) or 0.0 for k in FEATURE_NAMES}
            row['chi'] = props.get('chi', 0.0) or 0.0
            dataset.append(row)

        print(f"[ML] Extracted {len(dataset)} GEE training samples.")
        return dataset

    except Exception as e:
        print(f"[ML] GEE sampling unavailable ({e}). Using synthetic dataset.")
        return _generate_synthetic_dataset(n_samples)


def _generate_synthetic_dataset(n_samples=500):
    """
    Generates a realistic synthetic dataset representing Karnataka's
    environmental conditions across urban and rural gradients.
    """
    rng = np.random.RandomState(42)

    lst   = rng.uniform(22.0, 48.0, n_samples)
    ndvi  = rng.uniform(-0.05, 0.75, n_samples)
    ndbi  = rng.uniform(-0.45, 0.45, n_samples)
    air_t = rng.uniform(18.0, 42.0, n_samples)
    rh    = rng.uniform(15.0, 95.0, n_samples)
    wind  = rng.uniform(0.2, 9.5, n_samples)
    lulc  = rng.choice([0.0, 0.1, 0.4, 0.5, 0.8, 1.0], n_samples,
                       p=[0.05, 0.15, 0.20, 0.25, 0.15, 0.20])

    # CHI ground truth using the same weighted formula as preprocessing
    lst_n  = np.clip((lst  - 20.0) / 30.0, 0, 1)
    air_n  = np.clip((air_t - 15.0) / 30.0, 0, 1)
    ndbi_n = np.clip((ndbi + 0.5)  / 1.0,  0, 1)
    rh_n   = np.clip((rh   - 10.0) / 90.0, 0, 1)
    ndvi_n = np.clip((ndvi + 0.1)  / 0.9,  0, 1)
    wnd_n  = np.clip(wind / 10.0,          0, 1)

    chi = (lst_n * 0.25 + air_n * 0.20 + ndbi_n * 0.15 +
           lulc  * 0.15 + rh_n  * 0.10 + (1.0 - ndvi_n) * 0.10 +
           (1.0 - wnd_n) * 0.05)
    chi = np.clip(chi + rng.normal(0, 0.015, n_samples), 0, 1)

    dataset = []
    for i in range(n_samples):
        dataset.append({
            'lst': round(float(lst[i]), 4),
            'ndvi': round(float(ndvi[i]), 4),
            'ndbi': round(float(ndbi[i]), 4),
            'air_temp': round(float(air_t[i]), 4),
            'relative_humidity': round(float(rh[i]), 4),
            'wind_speed': round(float(wind[i]), 4),
            'lulc_heat': round(float(lulc[i]), 4),
            'chi': round(float(chi[i]), 4)
        })

    return dataset


# ──────────────────────────────────────────────────────────────────────────────
# 2. Model Training & Evaluation
# ──────────────────────────────────────────────────────────────────────────────

def train_rf_model(start_date='2022-03-01', end_date='2024-05-31'):
    """
    Full pipeline: sample data → split → train → evaluate → save.

    Returns:
        dict: Training result containing model metrics and file path.
    """
    # pyrefly: ignore [missing-import]
    import joblib
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

    os.makedirs(MODEL_DIR, exist_ok=True)

    # 1. Data preparation
    dataset = extract_training_samples(start_date, end_date)
    X = np.array([[row[f] for f in FEATURE_NAMES] for row in dataset])
    y = np.array([row['chi'] for row in dataset])

    # 2. Train / Test split  (80/20)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, random_state=42
    )

    # 3. Train Random Forest
    print(f"[ML] Training RandomForest on {len(X_train)} samples…")
    model = RandomForestRegressor(
        n_estimators=100,
        max_depth=12,
        min_samples_split=4,
        min_samples_leaf=2,
        random_state=42,
        n_jobs=-1
    )
    model.fit(X_train, y_train)

    # 4. Evaluate
    y_pred = model.predict(X_test)
    mae  = mean_absolute_error(y_test, y_pred)
    rmse = np.sqrt(mean_squared_error(y_test, y_pred))
    r2   = r2_score(y_test, y_pred)

    # 5. Feature importances
    importances = dict(zip(FEATURE_NAMES, model.feature_importances_.tolist()))

    print(f"[ML] Training complete — MAE: {mae:.4f}  RMSE: {rmse:.4f}  R²: {r2:.4f}")

    # 6. Save model
    joblib.dump(model, MODEL_PATH)
    print(f"[ML] Model saved to {MODEL_PATH}")

    return {
        'status': 'trained',
        'samples_total': len(dataset),
        'train_size': len(X_train),
        'test_size': len(X_test),
        'mae': round(mae, 4),
        'rmse': round(rmse, 4),
        'r2': round(r2, 4),
        'feature_importances': importances,
        'model_path': MODEL_PATH
    }


def load_rf_model():
    """
    Loads the saved Random Forest model from disk.
    If the model file does not exist, triggers training automatically.

    Returns:
        sklearn estimator: Loaded model object.
    """
    # pyrefly: ignore [missing-import]
    import joblib
    if not os.path.exists(MODEL_PATH):
        print("[ML] No saved model found — triggering training pipeline…")
        train_rf_model()
    return joblib.load(MODEL_PATH)


# ──────────────────────────────────────────────────────────────────────────────
# 3. Inference & Future Scenario Prediction
# ──────────────────────────────────────────────────────────────────────────────

def predict_current_conditions(district_features):
    """
    Predicts the current CHI for a district using the trained model.

    Args:
        district_features (dict): Keys matching FEATURE_NAMES.
    Returns:
        float: Predicted CHI [0.0 – 1.0].
    """
    model = load_rf_model()
    X = np.array([[district_features.get(f, 0.0) for f in FEATURE_NAMES]])
    chi = float(model.predict(X)[0])
    return round(np.clip(chi, 0.0, 1.0), 4)


def predict_future_conditions(district_features,
                               temp_offset=1.5,
                               ndvi_offset=-0.10,
                               ndbi_offset=0.05):
    """
    Applies a climate-warming scenario offset and predicts future CHI.

    Scenario defaults represent a +1.5°C warming world with
    10% vegetation loss and 5% additional urban expansion:
        LST_future    = LST_current  + temp_offset
        AirT_future   = AirT_current + temp_offset
        NDVI_future   = max(-0.1, NDVI_current + ndvi_offset)
        NDBI_future   = min(0.5,  NDBI_current + ndbi_offset)

    Args:
        district_features (dict): Current feature values.
        temp_offset  (float): °C added to LST and Air Temperature.
        ndvi_offset  (float): Change in NDVI (negative = vegetation loss).
        ndbi_offset  (float): Change in NDBI (positive = urban expansion).
    Returns:
        dict: Future feature set and predicted CHI.
    """
    future = dict(district_features)
    future['lst']      = min(50.0, future.get('lst', 30.0)      + temp_offset)
    future['air_temp'] = min(45.0, future.get('air_temp', 28.0) + temp_offset)
    future['ndvi']     = max(-0.1, future.get('ndvi', 0.4)      + ndvi_offset)
    future['ndbi']     = min(0.5,  future.get('ndbi', 0.1)      + ndbi_offset)

    model = load_rf_model()
    X = np.array([[future.get(f, 0.0) for f in FEATURE_NAMES]])
    chi_future = float(model.predict(X)[0])
    chi_future = round(np.clip(chi_future, 0.0, 1.0), 4)

    return {
        'future_features': future,
        'predicted_chi': chi_future
    }


def chi_to_risk_level(chi_value):
    """
    Maps a CHI value to a categorical risk level string.
    """
    if chi_value < 0.35:
        return 'Low'
    elif chi_value < 0.55:
        return 'Moderate'
    elif chi_value < 0.75:
        return 'High'
    else:
        return 'Very High'


def get_model_metrics():
    """
    Returns stored training metrics if available, or triggers training first.
    """
    if not os.path.exists(MODEL_PATH):
        return train_rf_model()

    # pyrefly: ignore [missing-import]
    import joblib
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

    model = joblib.load(MODEL_PATH)
    # Return feature importances from the saved model
    importances = dict(zip(FEATURE_NAMES, model.feature_importances_.tolist()))
    return {
        'status': 'loaded_from_disk',
        'model_path': MODEL_PATH,
        'feature_importances': importances
    }


# ──────────────────────────────────────────────────────────────────────────────
# 5. Factor Analysis
# ──────────────────────────────────────────────────────────────────────────────

# Human-readable labels and grouping for each model feature
FEATURE_LABELS = {
    'lst':                'Land Surface Temp (LST)',
    'ndvi':               'Vegetation (NDVI)',
    'ndbi':               'Built-Up Area (NDBI)',
    'air_temp':           'Air Temperature',
    'relative_humidity':  'Humidity',
    'wind_speed':         'Wind Speed',
    'lulc_heat':          'Land Use / Land Cover',
}

# Category colours per feature for visual consistency across all charts
FEATURE_COLOURS = {
    'lst':                '#e74c3c',   # red
    'ndvi':               '#27ae60',   # green
    'ndbi':               '#c0392b',   # dark red
    'air_temp':           '#e67e22',   # orange
    'relative_humidity':  '#2980b9',   # blue
    'wind_speed':         '#8e44ad',   # purple
    'lulc_heat':          '#f39c12',   # amber
}


def get_feature_analysis():
    """
    Extracts Random Forest feature importances and returns:
      - A ranked list of factors with percentages.
      - Plotly JSON for three charts:
          1. Horizontal bar chart   (Feature Importance)
          2. Donut / pie chart      (Percentage Contribution)
          3. Table chart            (Ranked factors with %)

    Falls back to a theoretically-derived importance set if the model
    has not been trained yet (first-start scenario).

    Returns:
        dict: {
            'ranked_factors': [...],
            'bar_chart_json': '...',
            'pie_chart_json': '...',
            'table_chart_json': '...',
        }
    """
    
    import json
    # pyrefly: ignore [missing-import]
    import joblib
    # pyrefly: ignore [missing-import]
    import plotly.graph_objects as go
    # pyrefly: ignore [missing-import]
    import plotly.utils

    # ── 1. Load importances ──────────────────────────────────────────────────
    if os.path.exists(MODEL_PATH):
        model = joblib.load(MODEL_PATH)
        raw_importances = dict(zip(FEATURE_NAMES, model.feature_importances_.tolist()))
    else:
        # Physics-based fallback (approximate expected order for UHI systems)
        raw_importances = {
            'lst': 0.28, 'air_temp': 0.21, 'ndbi': 0.17,
            'lulc_heat': 0.14, 'relative_humidity': 0.09,
            'ndvi': 0.07, 'wind_speed': 0.04,
        }

    total = sum(raw_importances.values()) or 1.0
    ranked = sorted(raw_importances.items(), key=lambda x: x[1], reverse=True)

    ranked_factors = []
    for rank, (feat, importance) in enumerate(ranked, start=1):
        pct = round((importance / total) * 100, 2)
        ranked_factors.append({
            'rank':       rank,
            'feature':    feat,
            'label':      FEATURE_LABELS[feat],
            'importance': round(importance, 5),
            'percentage': pct,
            'colour':     FEATURE_COLOURS[feat],
        })

    labels  = [r['label']      for r in ranked_factors]
    values  = [r['importance'] for r in ranked_factors]
    pcts    = [r['percentage'] for r in ranked_factors]
    colours = [r['colour']     for r in ranked_factors]
    ranks   = [str(r['rank'])  for r in ranked_factors]

    # ── 2. Horizontal bar chart ──────────────────────────────────────────────
    bar_fig = go.Figure(go.Bar(
        x=values[::-1],
        y=labels[::-1],
        orientation='h',
        marker=dict(
            color=colours[::-1],
            line=dict(color='rgba(0,0,0,0.15)', width=1)
        ),
        text=[f'{p}%' for p in pcts[::-1]],
        textposition='outside',
        hovertemplate='<b>%{y}</b><br>Importance: %{x:.5f}<br>Contribution: %{text}<extra></extra>',
    ))
    bar_fig.update_layout(
        title='Feature Importance — Random Forest Regressor',
        xaxis_title='Importance Score',
        margin=dict(l=30, r=60, t=50, b=30),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        xaxis=dict(showgrid=True, gridcolor='rgba(0,0,0,0.06)'),
        yaxis=dict(showgrid=False),
        height=360,
    )

    # ── 3. Donut / pie chart ─────────────────────────────────────────────────
    pie_fig = go.Figure(go.Pie(
        labels=labels,
        values=pcts,
        hole=0.48,
        marker=dict(colors=colours, line=dict(color='white', width=2)),
        textinfo='label+percent',
        hovertemplate='<b>%{label}</b><br>Contribution: %{value:.2f}%<extra></extra>',
        sort=False,
    ))
    pie_fig.update_layout(
        title='Percentage Contribution to Composite Heat Index',
        margin=dict(l=20, r=20, t=50, b=20),
        paper_bgcolor='rgba(0,0,0,0)',
        legend=dict(orientation='v', x=1.01, y=0.5),
        height=360,
    )

    # ── 4. Ranked table chart ────────────────────────────────────────────────
    table_fig = go.Figure(go.Table(
        columnwidth=[30, 200, 100, 90],
        header=dict(
            values=['<b>Rank</b>', '<b>Factor</b>',
                    '<b>Importance</b>', '<b>% Share</b>'],
            fill_color='#2c3e50',
            font=dict(color='white', size=12),
            align=['center', 'left', 'center', 'center'],
            height=32,
        ),
        cells=dict(
            values=[
                ranks,
                labels,
                [f'{v:.5f}' for v in values],
                [f'{p:.2f}%' for p in pcts],
            ],
            fill_color=[
                ['#f5f5f5' if i % 2 == 0 else 'white' for i in range(len(ranks))],
                ['#f5f5f5' if i % 2 == 0 else 'white' for i in range(len(ranks))],
                colours,
                colours,
            ],
            font=dict(color=['#2c3e50', '#2c3e50', 'white', 'white'], size=12),
            align=['center', 'left', 'center', 'center'],
            height=30,
        ),
    ))
    table_fig.update_layout(
        title='Ranked Factor Contributions',
        margin=dict(l=10, r=10, t=50, b=10),
        paper_bgcolor='rgba(0,0,0,0)',
        height=310,
    )

    return {
        'ranked_factors':    ranked_factors,
        'bar_chart_json':    json.dumps(bar_fig,   cls=plotly.utils.PlotlyJSONEncoder),
        'pie_chart_json':    json.dumps(pie_fig,   cls=plotly.utils.PlotlyJSONEncoder),
        'table_chart_json':  json.dumps(table_fig, cls=plotly.utils.PlotlyJSONEncoder),
    }

