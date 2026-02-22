#!/usr/bin/env python3

import os
import logging
from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS
from dotenv import load_dotenv
from wakeonlan import send_magic_packet

# Load .env file
load_dotenv(override=False)

# Configure logging to stdout
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    force=True
)

# Import our modules
from tv_utils import (
    SONY_TV_IP, SONY_TV_MAC, PSK,
    make_sony_api_request,
    set_power, set_volume, set_mute,
    launch_app, switch_input, send_ircc,
    resolve_app_name, friendly_input_name
)
from status_manager import status_manager

# Suppress werkzeug access logs
logging.getLogger('werkzeug').setLevel(logging.ERROR)

# Start the Status Manager background loop (Gunicorn/Docker friendly)
logging.info("Initializing background Status Manager...")
status_manager.start()

app = Flask(__name__, 
            static_folder='frontend/dist', 
            template_folder=None)
CORS(app)

# Cache for app icons to avoid heavy API calls
APP_ICONS_CACHE = {}

@app.route('/metrics')
def prometheus_metrics():
    """Expose TV metrics in Prometheus text format from the background status manager."""
    status = status_manager.get_status()
    lines = []

    # Power state: map to numeric (1=active, 0.5=standby, 0=off/unknown)
    power_status = status.get("power", "unknown")
    power_val = 0
    if power_status == "active":
        power_val = 1
    elif power_status == "standby":
        power_val = 0.5

    lines.append("# HELP tv_power_status TV power state (1=active, 0.5=standby, 0=off)")
    lines.append("# TYPE tv_power_status gauge")
    lines.append(f'tv_power_status{{state="{power_status}"}} {power_val}')

    # Volume
    volume = status.get("volume", 0)
    lines.append("# HELP tv_volume Current TV volume level")
    lines.append("# TYPE tv_volume gauge")
    lines.append(f"tv_volume {volume}")

    # Now Playing
    now_playing_id = status.get("now_playing_id", 0)
    lines.append("# HELP tv_now_playing Numeric ID of current content")
    lines.append("# TYPE tv_now_playing gauge")
    lines.append(f"tv_now_playing {now_playing_id}")

    return Response("\n".join(lines) + "\n", mimetype="text/plain; version=0.0.4; charset=utf-8")

@app.route('/api/status')
def get_status():
    """Get summarized TV status from background manager."""
    return jsonify({**status_manager.get_status(), "success": True})

@app.route('/api/health')
def health_check():
    """Verify if background monitor is alive."""
    status = status_manager.get_status()
    last_poll = status.get("timestamp", "Never")
    return jsonify({
        "status": "healthy",
        "last_poll": last_poll,
        "is_alive": status_manager.thread.is_alive()
    })

@app.route('/api/power', methods=['POST'])
def power_control():
    action = request.get_json().get('action')
    if action == 'on':
        try:
            broadcast = '.'.join(SONY_TV_IP.split('.')[:3] + ['255'])
            send_magic_packet(SONY_TV_MAC, ip_address=broadcast)
            send_magic_packet(SONY_TV_MAC, ip_address=SONY_TV_IP)
            set_power(True)
            return jsonify({"success": True, "message": "TV wake command sent"})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)})
    elif action == 'off':
        result = set_power(False)
        return jsonify(result)
    return jsonify({"success": False, "error": "Invalid action"})

@app.route('/api/volume', methods=['POST'])
def volume_control():
    data = request.get_json()
    action = data.get('action')
    if action == 'mute': result = set_mute(True)
    elif action == 'unmute': result = set_mute(False)
    elif action == 'up': result = set_volume("+5")
    elif action == 'down': result = set_volume("-5")
    elif action == 'set': result = set_volume(data.get('volume', 50))
    else: return jsonify({"success": False, "error": "Invalid action"})
    return jsonify(result)

@app.route('/api/volume')
def get_volume_api():
    status = status_manager.get_status()
    return jsonify({
        "success": True,
        "volume": status.get("volume", 50),
        "muted": status.get("muted", False)
    })

@app.route('/api/channel')
def get_channel():
    status = status_manager.get_status()
    return jsonify({
        "success": True,
        "title": status.get("title", "Unknown"),
        "uri": status.get("uri", "")
    })

@app.route('/api/inputs/hdmi')
def get_hdmi_inputs():
    DEVICE_ICONS = {"ps5": "/icons/ps5.png", "ps4": "/icons/ps4.png", "switch": "/icons/switch.png"}
    result = make_sony_api_request("avContent", "getCurrentExternalInputsStatus", [], "1.1")
    if result["success"] and "result" in result["data"]:
        inputs = result["data"]["result"][0]
        hdmi = []
        for inp in [i for i in inputs if "hdmi" in i.get("uri", "")]:
            label = inp.get("label", "")
            icon = None
            if label:
                for key, path in DEVICE_ICONS.items():
                    if key in label.lower():
                        icon = path
                        break

            hdmi.append({
                "uri": inp.get("uri"),
                "label": label,
                "displayName": label if label else inp.get("title", "HDMI"),
                "connected": inp.get("connection", False),
                "icon": icon
            })
        return jsonify({"success": True, "inputs": hdmi})
    return jsonify({"success": False, "error": "Could not get HDMI status"})

@app.route('/api/app-icons')
def get_app_icons():
    global APP_ICONS_CACHE
    if not APP_ICONS_CACHE:
        result = make_sony_api_request("appControl", "getApplicationList")
        if result["success"]:
            apps = result["data"]["result"][0]
            APP_ICONS_CACHE = {a["uri"]: a["icon"] for a in apps if "uri" in a and "icon" in a}
    
    return jsonify({"success": True, "icons": APP_ICONS_CACHE})

@app.route('/api/applications')
def get_applications():
    global APP_ICONS_CACHE
    result = make_sony_api_request("appControl", "getApplicationList")
    if result["success"]:
        apps = result["data"]["result"][0]
        # Refresh cache while we're at it
        APP_ICONS_CACHE = {a["uri"]: a["icon"] for a in apps if "uri" in a and "icon" in a}
        return jsonify({"success": True, "applications": apps})
    return jsonify({"success": False, "error": "Could not get applications"})

@app.route('/api/applications/launch', methods=['POST'])
def launch_app_api():
    data = request.get_json()
    uri = data.get('uri')
    title = data.get('title')
    if not uri: return jsonify({"success": False, "error": "URI required"})
    
    result = launch_app(uri)
    if result.get("success"):
        status_manager.update_override(title or resolve_app_name(uri), uri)
    return jsonify(result)

@app.route('/api/remote', methods=['POST'])
def remote_control():
    IRCC_CODES = {
        "Up": "AAAAAQAAAAEAAAB0Aw==", "Down": "AAAAAQAAAAEAAAB1Aw==",
        "Left": "AAAAAQAAAAEAAAA0Aw==", "Right": "AAAAAQAAAAEAAAAzAw==",
        "Confirm": "AAAAAQAAAAEAAABlAw==", "Return": "AAAAAgAAAJcAAAAjAw==",
        "Home": "AAAAAQAAAAEAAABgAw==", "Back": "AAAAAgAAAJcAAAAjAw=="
    }
    command = request.get_json().get('command')
    code = IRCC_CODES.get(command)
    if not code: return jsonify({"success": False, "error": "Unknown command"})
    return jsonify(send_ircc(code))

@app.route('/api/inputs')
def get_inputs():
    result = make_sony_api_request("avContent", "getSourceList", [], "1.0")
    if result["success"]:
        return jsonify({"success": True, "inputs": result["data"]["result"][0]})
    return jsonify({"success": False, "error": "Could not get inputs"})

@app.route('/api/inputs/switch', methods=['POST'])
def switch_input_api():
    data = request.get_json()
    uri = data.get('uri')
    title = data.get('title')
    if not uri: return jsonify({"success": False, "error": "URI required"})
    
    result = switch_input(uri)
    if result.get("success"):
        status_manager.update_override(title or friendly_input_name(uri) or uri, uri)
    return jsonify(result)

# SPA Serving
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    if path and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, 'index.html')

if __name__ == '__main__':
    print(f"Starting API Server on http://0.0.0.0:5000", flush=True)
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)