# HeatSense – AI-Based Urban Heat Island Analysis, Prediction and Health Alert System

HeatSense is an advanced, modular full-stack application designed to analyze, predict, and issue public health alerts for Urban Heat Island (UHI) effects in Karnataka, India.

It integrates satellite thermal imagery (Landsat 8 LST), climate data (ERA5-Land), and machine learning (Random Forest Regression) to calculate multi-factor Composite Heat Index (CHI) scores, evaluate heat risk, simulate cooling mitigation strategies, and display insights through a premium interactive dashboard.

---

## Tech Stack & Architecture
- **Backend Framework:** Python Flask
- **GIS Engine:** Google Earth Engine (Python API)
- **Machine Learning:** Scikit-learn (Random Forest Regression)
- **Model Persistence:** Joblib serialization
- **Database:** SQLite (Relational storage for districts and health alerts)
- **Visualization:** Geemap & Folium (Interactive GIS layers), Plotly (Interactive trendlines, gauge indicators, contribution charts, and grouped bars)
- **Frontend Framework:** Bootstrap 5 with responsive styles
- **Frontend Interaction:** Custom CSS and Vanilla JavaScript with dynamically updating layouts

---

## Project Structure
```text
HeatSense/
├── app/
│   ├── __init__.py           # Flask app factory and SQLite database bootstrapping
│   ├── database.py           # Database connection helpers & schema setup
│   ├── routes.py             # Route handlers (Pages and APIs)
│   ├── preprocessing.py      # Earth Engine & local GIS dataset processing stubs
│   ├── ml.py                 # Scikit-learn model definitions, training, and predicting
│   ├── visualization.py      # Geemap, Plotly, and Matplotlib chart generators
│   ├── mitigation.py         # UHI simulation & mitigation scenarios analyzer
│   ├── health_risk.py        # Health risk analysis & alert distribution logic
│   ├── static/
│   │   ├── css/
│   │   │   └── style.css     # UI layouts styling & aesthetics overrides
│   │   └── js/
│   │       └── main.js       # AJAX requests and map UI bindings
│   └── templates/
│       ├── base.html         # Bootstrap-enabled base structure
│       ├── index.html        # Dashboard layout with map placeholders
│       └── alerts.html       # UHI active heat alert logs
├── requirements.txt          # Project python package list
├── README.md                 # Project configuration instructions
└── run.py                    # Application launch script
```

---

## Installation & Setup

### 1. Clone or Copy Workspace
Ensure you are in the project folder containing `run.py`.

### 2. Set Up a Virtual Environment (Recommended)
```bash
python -m venv venv
# On Windows (PowerShell):
venv\Scripts\Activate.ps1
# On Linux/macOS:
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Authenticate Google Earth Engine
Since HeatSense integrates Google Earth Engine for GIS analysis, authenticate your environment using your Google Cloud Earth Engine enabled account:
```bash
earthengine authenticate
```

---

## Running the Application
To launch the Flask development server, run:
```bash
python run.py
```
Open a browser and navigate to `http://127.0.0.1:5000/`.

---

## 🛠️ Implemented Modules Checklist

- [x] **Module 1: Data Collection & Preprocessing**
  - Clips Landsat 8, ESA WorldCover, and ERA5-Land parameters to Karnataka boundary.
  - Automatically handles cloud masking, scaling factors, and GEE compilation.
- [x] **Module 2: Multi-Factor Heat Detection (CHI)**
  - Normalizes and weights 7 key variables (LST, NDVI, NDBI, Air Temp, Humidity, Wind Speed, LULC heat score) into a single Composite Heat Index.
- [x] **Module 3: Historical Trend Analysis**
  - Performs pixel-by-pixel decadal regression (2015-2025) to map local warming slopes and delta epochs.
- [x] **Module 4: Heat Prediction**
  - Trains a Random Forest Regressor on sampled pixels; exports and saves the model using Joblib.
  - Simulates future warming scenarios (+1.5°C temp offset, -10% green cover, +5% buildup expansion) and displays current vs. future CHI values.
- [x] **Module 5: Factor Analysis**
  - Extracts Random Forest feature importances.
  - Renders horizontal bar, donut pie, and ranked list comparison charts using Plotly.
- [x] **Module 6: Cooling Mitigation Simulation**
  - Simulates 4 cooling interventions (Vegetation Expansion, Green Roofs, Density Reduction, Park Development).
  - Displays side-by-side grouped bars, LST reduction overlay bars, and improvement gauges.
- [x] **Module 7: Health Risk & Alerts System**
  - Computes district Heat Health Risk Index (HHRI) combining CHI, air temperature, relative humidity, and demographic vulnerability.
  - Automatically seeds daily active alerts in the SQLite database and renders warnings on a dedicated public health alerts dashboard.
- [x] **Module 8: Interactive Dashboard and Web Interface**
  - Designed premium glassmorphic dark UI layout (`style.css`) with a left sidebar menu managing 9 functional views.
  - Implemented interactive GEE layer control checkboxes, legend legends, global quick search, HHRI sliders, and report downloads.


