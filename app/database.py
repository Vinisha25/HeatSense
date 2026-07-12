import sqlite3
# pyrefly: ignore [missing-import]
from flask import g, current_app

def get_db():
    """
    Retrieves or establishes a connection to the application's SQLite database.
    Saves the connection in Flask's application context globals 'g'.
    """
    db_path = current_app.config['DATABASE']
    if 'db' not in g:
        g.db = sqlite3.connect(
            db_path,
            detect_types=sqlite3.PARSE_DECLTYPES
        )
        g.db.row_factory = sqlite3.Row

    return g.db

def close_db(e=None):
    """
    Closes the database connection if it exists in application context globals.
    """
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db(db_path):
    """
    Initializes the database schema by establishing a direct connection and
    executing table creation commands. Called during application factory setup.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Create tables for districts, predictions, alerts, and mitigation scenarios
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS districts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        latitude REAL NOT NULL,
        longitude REAL NOT NULL
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS uhi_predictions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        district_id INTEGER,
        prediction_date TEXT NOT NULL,
        predicted_lst REAL NOT NULL, -- Land Surface Temperature
        predicted_index REAL NOT NULL, -- UHI Intensity Index
        model_name TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (district_id) REFERENCES districts (id)
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS health_alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        district_id INTEGER,
        alert_date TEXT NOT NULL,
        risk_level TEXT NOT NULL, -- e.g., Low, Medium, High, Extreme
        advisory_message TEXT NOT NULL,
        status TEXT DEFAULT 'active', -- Active or Resolved
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (district_id) REFERENCES districts (id)
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS mitigation_scenarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        district_id INTEGER,
        scenario_name TEXT NOT NULL, -- e.g., 'Double Green Cover', 'Cool Roof Retrofitting'
        temp_reduction REAL NOT NULL, -- Simulated reduction in °C
        run_date TEXT NOT NULL,
        FOREIGN KEY (district_id) REFERENCES districts (id)
    );
    """)
    
    # Seed initial Karnataka district placeholders
    karnataka_districts = [
        ("Bengaluru Urban", 12.9716, 77.5946),
        ("Mysuru", 12.2958, 76.6394),
        ("Hubli-Dharwad", 15.3647, 75.1240),
        ("Mangaluru", 12.9141, 74.8560),
        ("Belagavi", 15.8497, 74.4977),
        ("Kalaburagi", 17.3297, 76.8343),
    ]
    
    cursor.executemany("""
    INSERT OR IGNORE INTO districts (name, latitude, longitude)
    VALUES (?, ?, ?);
    """, karnataka_districts)
    
    conn.commit()
    conn.close()
    print("[Database] Schema successfully initialized & seeded.")
