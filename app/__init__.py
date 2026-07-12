import os
# pyrefly: ignore [missing-import]
from flask import Flask
from app.database import init_db

def create_app(test_config=None):
    """
    Application Factory Pattern for Flask.
    Creates and configures the HeatSense application instance.
    """
    app = Flask(__name__, instance_relative_config=True)
    
    # Define default configurations
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('SECRET_KEY', 'heatsense_default_dev_secret_key_12938'),
        DATABASE=os.path.join(app.instance_path, 'heatsense.sqlite'),
    )

    if test_config is None:
        # Load the instance config, if it exists, when not testing
        app.config.from_pyfile('config.py', silent=True)
    else:
        # Load the test config if passed in
        app.config.from_mapping(test_config)

    # Ensure the instance folder exists for SQLite db storage
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    # Initialize the database schema
    with app.app_context():
        init_db(app.config['DATABASE'])

    # Register routes
    from app.routes import main_bp
    app.register_blueprint(main_bp)

    # Auto-train the Random Forest model on first startup if not already saved
    from app.ml import MODEL_PATH, train_rf_model
    if not os.path.exists(MODEL_PATH):
        print("[Startup] No trained model found. Running training pipeline…")
        with app.app_context():
            try:
                train_rf_model()
            except Exception as e:
                print(f"[Startup] Model training deferred: {e}")

    # Auto-generate today's health alerts for all districts at startup
    try:
        from app.health_risk import generate_alerts_for_all_districts
        generate_alerts_for_all_districts(app)
    except Exception as e:
        print(f"[Startup] Health alert generation deferred: {e}")

    return app
