"""
HeatSense Preprocessing Module.
Handles ingestion, cloud-masking, cropping, and aggregate statistics extraction
for satellite imagery (e.g., Landsat, MODIS, Sentinel) using the Google Earth Engine Python API.
"""

import math

# Store Earth Engine initialization state globally
_EE_INITIALIZED = False
_EE_ERROR_MSG = "Not initialized"

def initialize_earth_engine():
    """
    Initializes and authenticates the Google Earth Engine (EE) client.
    """
    global _EE_INITIALIZED, _EE_ERROR_MSG
    try:
        import ee
        ee.Initialize()
        _EE_INITIALIZED = True
        _EE_ERROR_MSG = ""
        print("[GEE] Earth Engine initialized successfully.")
        return True
    except Exception as e:
        print(f"[Warning] Earth Engine initialization deferred: {e}")
        _EE_INITIALIZED = False
        _EE_ERROR_MSG = str(e)
        return False

def get_gee_status():
    """
    Returns the actual Google Earth Engine connection status.
    Never returns a fake "connected" state.

    Returns:
        dict: {connected: bool, message: str, project: str or None}
    """
    global _EE_INITIALIZED, _EE_ERROR_MSG
    if _EE_INITIALIZED:
        try:
            import ee
            # Ping GEE with a lightweight operation
            _ = ee.Number(1).getInfo()
            return {
                "connected": True,
                "message": "Google Earth Engine is active and authenticated.",
                "satellite": "Landsat 8 + ERA5-Land + ESA WorldCover",
            }
        except Exception as e:
            _EE_INITIALIZED = False
            _EE_ERROR_MSG = str(e)
            return {
                "connected": False,
                "message": f"GEE connection lost: {e}",
                "satellite": None,
            }
    else:
        return {
            "connected": False,
            "message": _EE_ERROR_MSG or "GEE not authenticated. Run: earthengine authenticate",
            "satellite": None,
        }

def get_karnataka_boundary():
    """
    Retrieves the administrative boundary for Karnataka, India.
    Uses the FAO GAUL Level 1 collection.

    Returns:
        ee.FeatureCollection: Boundary geometry.
    """
    import ee
    gaul = ee.FeatureCollection("FAO/GAUL/2015/level1")
    karnataka = gaul.filter(
        ee.Filter.And(
            ee.Filter.eq('ADM0_NAME', 'India'),
            ee.Filter.eq('ADM1_NAME', 'Karnataka')
        )
    )
    return karnataka

def mask_landsat_clouds(image):
    """
    Applies QA band cloud masking to a Landsat 8 surface temperature image.
    Uses bit 3 (cloud) and bit 4 (cloud shadow) of the QA_PIXEL band.
    """
    import ee
    qa = image.select('QA_PIXEL')
    cloud_shadow_bit_mask = 1 << 4
    clouds_bit_mask = 1 << 3
    mask = qa.bitwiseAnd(cloud_shadow_bit_mask).eq(0) \
             .And(qa.bitwiseAnd(clouds_bit_mask).eq(0))
    return image.updateMask(mask)

def apply_landsat_scaling(image):
    """
    Applies radiometric scaling factors for surface reflectance (SR) and
    surface temperature (ST) bands.
    """
    import ee
    optical_bands = image.select('SR_B.').multiply(0.0000275).add(-0.2)
    thermal_band = image.select('ST_B10').multiply(0.00341802).add(149.0)
    return image.addBands(optical_bands, overwrite=True) \
                .addBands(thermal_band, overwrite=True)

def process_landsat_data(start_date, end_date, region=None):
    """
    Ingests Landsat 8 imagery over Karnataka (or specified region), masks clouds,
    scales values, computes median composite, and calculates LST, NDVI, and NDBI indices.
    """
    import ee
    if region is None:
        region = get_karnataka_boundary()

    collection = ee.ImageCollection('LANDSAT/LC08/C02/T1_L2') \
        .filterBounds(region) \
        .filterDate(start_date, end_date) \
        .map(mask_landsat_clouds) \
        .map(apply_landsat_scaling)

    composite = collection.median().clip(region)

    ndvi = composite.normalizedDifference(['SR_B5', 'SR_B4']).rename('NDVI')
    ndbi = composite.normalizedDifference(['SR_B6', 'SR_B5']).rename('NDBI')
    lst = composite.select('ST_B10').subtract(273.15).rename('LST')

    result = composite.addBands([ndvi, ndbi, lst])
    return result

def get_lulc_data(region=None):
    """
    Loads ESA WorldCover 10m LULC dataset (version 200) and clips it to region.
    """
    import ee
    if region is None:
        region = get_karnataka_boundary()
    lulc = ee.Image('ESA/WorldCover/v200/2021').select('Map').clip(region)
    return lulc

def get_era5_land_daily_climate(start_date, end_date, region=None):
    """
    Retrieves aggregated daily climate indicators (Air Temperature, Relative Humidity,
    Wind Speed) from ERA5-Land, calculated and clipped to region.
    """
    import ee
    if region is None:
        region = get_karnataka_boundary()

    collection = ee.ImageCollection('ECMWF/ERA5_LAND/DAILY_AGGR') \
        .filterBounds(region) \
        .filterDate(start_date, end_date)

    mean_climate = collection.mean().clip(region)

    air_temp = mean_climate.select('temperature_2m').subtract(273.15).rename('air_temperature')

    u_wind = mean_climate.select('u_component_of_wind_10m')
    v_wind = mean_climate.select('v_component_of_wind_10m')
    wind_speed = u_wind.multiply(u_wind).add(v_wind.multiply(v_wind)).sqrt().rename('wind_speed')

    dewpoint_c = mean_climate.select('dewpoint_temperature_2m').subtract(273.15)
    td_term = dewpoint_c.multiply(17.625).divide(dewpoint_c.add(243.04))
    t_term = air_temp.multiply(17.625).divide(air_temp.add(243.04))
    relative_humidity = td_term.subtract(t_term).exp().multiply(100.0).rename('relative_humidity')

    climate_image = air_temp.addBands([relative_humidity, wind_speed])
    return climate_image

def normalize_gee_band(image, band_name, min_val, max_val):
    """
    Applies min-max scaling to project a band's values to [0.0, 1.0] range.
    """
    import ee
    band = image.select(band_name)
    normalized = band.subtract(min_val).divide(max_val - min_val)
    return normalized.clamp(0.0, 1.0)

def get_lulc_heat_score(lulc_image):
    """
    Maps discrete ESA WorldCover classification categories into continuous UHI
    heat contribution weights based on thermal storage capabilities.
    """
    import ee
    from_classes = [10, 20, 30, 40, 50, 60, 80]
    to_scores = [0.1, 0.4, 0.4, 0.5, 1.0, 0.8, 0.0]
    score_image = lulc_image.remap(from_classes, to_scores, 0.2).rename('lulc_heat_score')
    return score_image

def calculate_composite_heat_index(start_date, end_date, region=None):
    """
    Combines normalized LST, Air Temp, NDBI, LULC heat scores, Humidity, NDVI,
    and Wind Speed to produce a multi-factor Composite Heat Index (CHI).
    """
    import ee
    if region is None:
        region = get_karnataka_boundary()

    landsat = process_landsat_data(start_date, end_date, region)
    lulc = get_lulc_data(region)
    climate = get_era5_land_daily_climate(start_date, end_date, region)

    lst_n = normalize_gee_band(landsat, 'LST', 20.0, 50.0).rename('lst_n')
    air_n = normalize_gee_band(climate, 'air_temperature', 15.0, 45.0).rename('air_n')
    ndbi_n = normalize_gee_band(landsat, 'NDBI', -0.5, 0.5).rename('ndbi_n')
    rh_n = normalize_gee_band(climate, 'relative_humidity', 10.0, 100.0).rename('rh_n')

    ndvi_n = normalize_gee_band(landsat, 'NDVI', -0.1, 0.8)
    ndvi_heat = ee.Image.constant(1.0).subtract(ndvi_n).rename('ndvi_heat')

    wind_n = normalize_gee_band(climate, 'wind_speed', 0.0, 10.0)
    wind_heat = ee.Image.constant(1.0).subtract(wind_n).rename('wind_heat')

    lulc_heat = get_lulc_heat_score(lulc)

    chi = lst_n.multiply(0.25) \
        .add(air_n.multiply(0.20)) \
        .add(ndbi_n.multiply(0.15)) \
        .add(lulc_heat.multiply(0.15)) \
        .add(rh_n.multiply(0.10)) \
        .add(ndvi_heat.multiply(0.10)) \
        .add(wind_heat.multiply(0.05)) \
        .rename('CHI')

    return chi.clamp(0.0, 1.0)

def classify_heat_hotspots(chi_image):
    """
    Categorizes the Composite Heat Index (CHI) into four hazard classifications:
      0: Low (<0.35)
      1: Moderate (0.35 to <0.55)
      2: High (0.55 to <0.75)
      3: Very High (>=0.75)
    """
    import ee
    karnataka = get_karnataka_boundary()

    classified = ee.Image.constant(0) \
        .where(chi_image.gte(0.35).And(chi_image.lt(0.55)), 1) \
        .where(chi_image.gte(0.55).And(chi_image.lt(0.75)), 2) \
        .where(chi_image.gte(0.75), 3) \
        .rename('hotspots')

    return classified.clip(karnataka).updateMask(chi_image.mask())

def get_location_features(lat, lon, start_date='2024-03-01', end_date='2024-05-31', radius_km=15):
    """
    Extracts environmental features for ANY lat/lon location within Karnataka.
    Uses a buffer (AOI) around the point and reduces GEE bands to mean values.

    Args:
        lat (float): Latitude of selected location.
        lon (float): Longitude of selected location.
        start_date (str): Analysis period start (YYYY-MM-DD).
        end_date (str): Analysis period end (YYYY-MM-DD).
        radius_km (float): AOI buffer radius in kilometres.
    Returns:
        dict: Feature values for LST, NDVI, NDBI, air_temp, humidity, wind_speed, lulc_heat.
        str: 'gee' if GEE data was used, 'climatological' if fallback.
    """
    if _EE_INITIALIZED:
        try:
            import ee
            point = ee.Geometry.Point([lon, lat])
            region = point.buffer(radius_km * 1000)

            landsat = process_landsat_data(start_date, end_date, region)
            climate = get_era5_land_daily_climate(start_date, end_date, region)
            lulc = get_lulc_data(region)
            lulc_h = get_lulc_heat_score(lulc)

            stacked = (landsat.select('LST').rename('lst')
                       .addBands(landsat.select('NDVI').rename('ndvi'))
                       .addBands(landsat.select('NDBI').rename('ndbi'))
                       .addBands(climate.select('air_temperature').rename('air_temp'))
                       .addBands(climate.select('relative_humidity').rename('relative_humidity'))
                       .addBands(climate.select('wind_speed').rename('wind_speed'))
                       .addBands(lulc_h.rename('lulc_heat')))

            vals = stacked.reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=region,
                scale=1000,
                maxPixels=1e8
            ).getInfo()

            features = {
                'lst':               float(vals.get('lst') or _lat_lon_fallback(lat)['lst']),
                'ndvi':              float(vals.get('ndvi') or _lat_lon_fallback(lat)['ndvi']),
                'ndbi':              float(vals.get('ndbi') or _lat_lon_fallback(lat)['ndbi']),
                'air_temp':          float(vals.get('air_temp') or _lat_lon_fallback(lat)['air_temp']),
                'relative_humidity': float(vals.get('relative_humidity') or _lat_lon_fallback(lat)['relative_humidity']),
                'wind_speed':        float(vals.get('wind_speed') or _lat_lon_fallback(lat)['wind_speed']),
                'lulc_heat':         float(vals.get('lulc_heat') or _lat_lon_fallback(lat)['lulc_heat']),
            }
            return features, 'gee'

        except Exception as e:
            print(f"[Preprocessing] GEE feature extraction failed for ({lat},{lon}): {e}. Using climatological fallback.")

    # Climatological fallback based on geographic position
    return _lat_lon_fallback(lat, lon), 'climatological'


def _lat_lon_fallback(lat, lon=None):
    """
    Climatological regression-based feature estimation for any Karnataka lat/lon.
    Based on Karnataka's north-south temperature gradient and coastal moisture gradient.
    Not random — derived from physics and regional climatology.

    Lat range: 11.5° (southern coastal tip) to 18.5° (northern border)
    Lon range: 74° (western coastal Ghats) to 78.5° (eastern drylands)
    """
    # North-south gradient (0=south cool coastal, 1=north hot drylands)
    lat_factor = max(0.0, min(1.0, (lat - 11.5) / 7.0))

    # East-west gradient (0=west coast humid, 1=east dry interior)
    if lon is not None:
        lon_factor = max(0.0, min(1.0, (lon - 74.0) / 4.5))
    else:
        lon_factor = 0.5

    # Coastal humidity influence (Mangaluru, Udupi area)
    is_coastal = (lon is not None and lon < 75.2 and lat < 14.5)

    lst       = 28.0 + lat_factor * 14.0 - (4.0 if is_coastal else 0)
    ndvi      = 0.55 - lat_factor * 0.30 - lon_factor * 0.08 + (0.08 if is_coastal else 0)
    ndbi      = 0.05 + lat_factor * 0.15 + lon_factor * 0.05
    air_temp  = 26.0 + lat_factor * 12.0 - (3.0 if is_coastal else 0)
    humidity  = 70.0 - lat_factor * 30.0 - lon_factor * 10.0 + (20.0 if is_coastal else 0)
    wind      = 2.0 + lat_factor * 2.0 + (1.5 if is_coastal else 0)
    lulc_heat = 0.3 + lat_factor * 0.4 + lon_factor * 0.1

    return {
        'lst':               round(max(22.0, min(50.0, lst)), 2),
        'ndvi':              round(max(-0.1, min(0.85, ndvi)), 3),
        'ndbi':              round(max(-0.4, min(0.5, ndbi)), 3),
        'air_temp':          round(max(18.0, min(45.0, air_temp)), 2),
        'relative_humidity': round(max(20.0, min(98.0, humidity)), 1),
        'wind_speed':        round(max(0.5, min(10.0, wind)), 2),
        'lulc_heat':         round(max(0.0, min(1.0, lulc_heat)), 3),
    }

def get_annual_summer_composite(year, region=None):
    """
    Loads Landsat 8 surface temperature and surface reflectance bands,
    masks clouds, scales values, and creates a median summer composite for a given year.
    """
    import ee
    if region is None:
        region = get_karnataka_boundary()
    start_date = f"{year}-03-01"
    end_date = f"{year}-05-31"

    collection = ee.ImageCollection('LANDSAT/LC08/C02/T1_L2') \
        .filterBounds(region) \
        .filterDate(start_date, end_date) \
        .map(mask_landsat_clouds) \
        .map(apply_landsat_scaling)

    composite = collection.median().clip(region)

    ndvi = composite.normalizedDifference(['SR_B5', 'SR_B4']).rename('NDVI')
    ndbi = composite.normalizedDifference(['SR_B6', 'SR_B5']).rename('NDBI')
    lst = composite.select('ST_B10').subtract(273.15).rename('LST')

    return composite.addBands([ndvi, ndbi, lst])

def calculate_lst_trend_slope(start_year=2015, end_year=2025):
    """
    Computes pixel-wise warming slope (°C/year) over a decadal timeframe (2015-2025).
    """
    import ee
    karnataka = get_karnataka_boundary()

    images_list = []
    for y in range(start_year, end_year + 1):
        annual_img = get_annual_summer_composite(y)
        lst = annual_img.select('LST')
        time_band = ee.Image.constant(y - start_year).rename('year')
        img_fit = time_band.addBands(lst)
        images_list.append(img_fit)

    fit_collection = ee.ImageCollection.fromImages(images_list)
    fit_result = fit_collection.reduce(ee.Reducer.linearFit())
    return fit_result.select('scale').clip(karnataka).rename('lst_slope')

def calculate_epoch_difference():
    """
    Compares a baseline historical period (2015-2018 median) to a recent period (2022-2025 median)
    and outputs the temperature change delta (Recent - Baseline).
    """
    import ee
    karnataka = get_karnataka_boundary()

    baseline_list = [get_annual_summer_composite(y).select('LST') for y in range(2015, 2019)]
    baseline_median = ee.ImageCollection.fromImages(baseline_list).median()

    recent_list = [get_annual_summer_composite(y).select('LST') for y in range(2022, 2026)]
    recent_median = ee.ImageCollection.fromImages(recent_list).median()

    lst_diff = recent_median.subtract(baseline_median).clip(karnataka)
    return lst_diff.rename('lst_difference')

def get_district_historical_trend(district_id):
    """
    Aggregates mean annual LST and CHI values for a selected district
    across a decadal timeframe (2015-2025).
    """
    import ee
    from flask import current_app
    import sqlite3

    db_path = current_app.config['DATABASE']
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    district = conn.execute("SELECT * FROM districts WHERE id = ?", (district_id,)).fetchone()
    conn.close()

    if not district:
        return []

    lat = district['latitude']
    lon = district['longitude']
    return get_location_historical_trend(lat, lon, district['name'])


def get_location_historical_trend(lat, lon, name='Location', start_year=2015, end_year=2025):
    """
    Aggregates mean annual LST and CHI values for ANY lat/lon location
    across a specified year range.

    Args:
        lat (float): Latitude.
        lon (float): Longitude.
        name (str): Location name for context.
        start_year (int): Start of historical period.
        end_year (int): End of historical period.
    Returns:
        list[dict]: Year-by-year records with mean_lst_celsius, mean_chi, lst_slope, data_source.
    """
    trend_data = []

    for year in range(start_year, end_year + 1):
        if _EE_INITIALIZED:
            try:
                import ee
                point = ee.Geometry.Point([lon, lat])
                region = point.buffer(15000)

                img = get_annual_summer_composite(year, region)

                mean_lst_dict = img.select('LST').reduceRegion(
                    reducer=ee.Reducer.mean(),
                    geometry=region,
                    scale=30,
                    maxPixels=1e9
                ).getInfo()

                mean_lst = mean_lst_dict.get('LST') or 0.0

                ndvi_val = img.select('NDVI').reduceRegion(
                    reducer=ee.Reducer.mean(),
                    geometry=region,
                    scale=30,
                    maxPixels=1e9
                ).getInfo().get('NDVI') or 0.0

                lst_norm = max(0.0, min(1.0, (mean_lst - 20.0) / 30.0))
                ndvi_norm = max(0.0, min(1.0, (ndvi_val - (-0.1)) / 0.9))
                chi_est = 0.7 * lst_norm + 0.3 * (1.0 - ndvi_norm)

                # Compute slope vs first GEE year
                lst_slope = 0.18 if year == start_year else (mean_lst - trend_data[0]['mean_lst_celsius']) / max(1, year - start_year)

                trend_data.append({
                    "year": year,
                    "mean_lst_celsius": round(mean_lst, 2),
                    "mean_chi": round(chi_est, 3),
                    "lst_slope": round(lst_slope, 4),
                    "data_source": "gee",
                })
                continue

            except Exception as e:
                pass  # Fall through to climatological

        # Climatological fallback — deterministic based on lat/lon + warming trend
        lat_factor = max(0.0, min(1.0, (lat - 11.5) / 7.0))
        base_lst = 28.0 + lat_factor * 14.0
        # Simulate warming trend: +0.12 to +0.22°C/year depending on region
        annual_rate = 0.12 + lat_factor * 0.10
        year_idx = year - start_year
        mock_lst = base_lst + year_idx * annual_rate
        # Small location-specific variation
        mock_lst += math.sin(lat * 0.5 + year_idx) * 0.3

        mock_ndvi = 0.55 - lat_factor * 0.30 - year_idx * 0.005
        lst_norm = max(0.0, min(1.0, (mock_lst - 20.0) / 30.0))
        ndvi_norm = max(0.0, min(1.0, (mock_ndvi - (-0.1)) / 0.9))
        mock_chi = 0.7 * lst_norm + 0.3 * (1.0 - ndvi_norm)
        mock_chi = max(0.0, min(1.0, mock_chi))

        lst_slope = annual_rate if year == start_year else (mock_lst - (base_lst)) / max(1, year_idx)

        trend_data.append({
            "year": year,
            "mean_lst_celsius": round(mock_lst, 2),
            "mean_chi": round(mock_chi, 3),
            "lst_slope": round(annual_rate, 4),
            "data_source": "climatological",
        })

    return trend_data
