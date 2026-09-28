import os
import sys
import socket

# Add backend directory to sys.path
backend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backend')
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app import app

def is_port_in_use(port: int, host: str = '127.0.0.1') -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0

if __name__ == '__main__':
    default_port = 5001 if is_port_in_use(5000) else 5000
    port = int(os.environ.get('PORT', default_port))
    host = os.environ.get('HOST', '127.0.0.1')

    print(f"Starting Standalone Prophet Forecasting Server at http://{host}:{port}/")
    app.run(host=host, port=port, debug=False)
