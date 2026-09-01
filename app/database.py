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
    Initializes the database schema. Called during application factory setup.
    Creates all tables including user-selected locations table.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Users table for secure authentication
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL COLLATE NOCASE,
        phone_number TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Districts table (Karnataka administrative districts — seed data)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS districts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        latitude REAL NOT NULL,
        longitude REAL NOT NULL
    );
    """)

    # Dynamic locations table (user-selected locations from location picker)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS locations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        latitude REAL NOT NULL,
        longitude REAL NOT NULL,
        radius_km REAL DEFAULT 15,
        district TEXT,
        taluk TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS uhi_predictions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        district_id INTEGER,
        prediction_date TEXT NOT NULL,
        predicted_lst REAL NOT NULL,
        predicted_index REAL NOT NULL,
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
        risk_level TEXT NOT NULL,
        advisory_message TEXT NOT NULL,
        status TEXT DEFAULT 'active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (district_id) REFERENCES districts (id)
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS mitigation_scenarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        district_id INTEGER,
        scenario_name TEXT NOT NULL,
        temp_reduction REAL NOT NULL,
        run_date TEXT NOT NULL,
        FOREIGN KEY (district_id) REFERENCES districts (id)
    );
    """)

    # Seed all 31 Karnataka districts for comprehensive coverage
    karnataka_districts = [
        ("Bengaluru Urban",   12.9716, 77.5946),
        ("Bengaluru Rural",   13.1986, 77.5660),
        ("Mysuru",            12.2958, 76.6394),
        ("Tumakuru",          13.3409, 77.1010),
        ("Kolar",             13.1363, 78.1294),
        ("Chikkaballapura",   13.4355, 77.7315),
        ("Ramanagara",        12.7157, 77.2812),
        ("Chamarajanagara",   11.9261, 76.9440),
        ("Mandya",            12.5218, 76.8951),
        ("Hassan",            13.0033, 76.1004),
        ("Kodagu",            12.4244, 75.7382),
        ("Dakshina Kannada",  12.8438, 74.9931),
        ("Udupi",             13.3409, 74.7421),
        ("Mangaluru",         12.9141, 74.8560),
        ("Shivamogga",        13.9299, 75.5681),
        ("Chikkamagaluru",    13.3153, 75.7754),
        ("Davanagere",        14.4644, 75.9218),
        ("Chitradurga",       14.2290, 76.3986),
        ("Belagavi",          15.8497, 74.4977),
        ("Dharwad",           15.4589, 75.0078),
        ("Gadag",             15.4310, 75.6354),
        ("Bagalkote",         16.1689, 75.6966),
        ("Vijayapura",        16.8302, 75.7100),
        ("Hubli-Dharwad",     15.3647, 75.1240),
        ("Haveri",            14.7957, 75.3997),
        ("Uttara Kannada",    14.7902, 74.6883),
        ("Koppal",            15.3508, 76.1562),
        ("Ballari",           15.1394, 76.9214),
        ("Raichur",           16.2120, 77.3439),
        ("Yadgir",            16.7676, 77.1383),
        ("Kalaburagi",        17.3297, 76.8343),
        ("Bidar",             17.9104, 77.5199),
    ]

    cursor.executemany("""
    INSERT OR IGNORE INTO districts (name, latitude, longitude)
    VALUES (?, ?, ?);
    """, karnataka_districts)

    conn.commit()
    conn.close()
    print(f"[Database] Schema initialized. {len(karnataka_districts)} Karnataka districts seeded.")
