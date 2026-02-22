#!/usr/bin/env python3

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests
import json
import logging
import os
from dotenv import load_dotenv

# Load .env file; real env vars take precedence (override=False)
load_dotenv(override=False)
import time
import socket
import subprocess
from wakeonlan import send_magic_packet
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager
import threading

# Suppress werkzeug access logs (e.g. "GET /api/status 200")
logging.getLogger('werkzeug').setLevel(logging.ERROR)

app = Flask(__name__, 
            static_folder='frontend/dist', 
            template_folder=None)
CORS(app)  # Enable CORS for React frontend

@app.route('/metrics')
def prometheus_metrics():
    """Expose TV metrics in Prometheus text format."""
    from flask import Response

    lines = []

    # Power state: map to numeric (1=active, 0.5=standby, 0=off/unknown)
    power_result = make_sony_api_request("system", "getPowerStatus")
    power_status = "unknown"
    power_val = 0
    if power_result["success"] and "result" in power_result["data"]:
        status_list = power_result["data"]["result"]
        if status_list and isinstance(status_list[0], dict):
            power_status = status_list[0].get("status", "unknown")
    if power_status == "active":
        power_val = 1
    elif power_status == "standby":
        power_val = 0.5

    lines.append("# HELP tv_power_status TV power state (1=active, 0.5=standby, 0=off)")
    lines.append("# TYPE tv_power_status gauge")
    lines.append(f'tv_power_status{{state="{power_status}"}} {power_val}')

    # Volume
    vol_result = make_sony_api_request("audio", "getVolumeInformation")
    volume = 0
    muted = 0
    if vol_result["success"] and "result" in vol_result["data"]:
        vol_list = vol_result["data"]["result"]
        if vol_list and isinstance(vol_list[0], list):
            for v in vol_list[0]:
                if isinstance(v, dict) and v.get("target") == "speaker":
                    volume = v.get("volume", 0)
                    muted = 1 if v.get("mute", False) else 0

    lines.append("# HELP tv_volume Current TV volume level")
    lines.append("# TYPE tv_volume gauge")
    lines.append(f"tv_volume {volume}")
    lines.append("# HELP tv_muted Whether TV is muted (1=muted, 0=unmuted)")
    lines.append("# TYPE tv_muted gauge")
    lines.append(f"tv_muted {muted}")

    # Current channel / app — query live so metrics are always fresh
    now_playing = _resolve_current_content()
    now_playing_escaped = now_playing.replace('"', '\\"')

    lines.append("# HELP tv_now_playing Current TV channel or app")
    lines.append("# TYPE tv_now_playing gauge")
    lines.append(f'tv_now_playing{{title="{now_playing_escaped}"}} 1')

    return Response("\n".join(lines) + "\n", mimetype="text/plain; version=0.0.4; charset=utf-8")

# Configuration
SONY_TV_IP = os.getenv('SONY_TV_IP')
SONY_TV_MAC = os.getenv('SONY_TV_MAC')
PSK = os.getenv('SONY_TV_PSK')
ADB_PORT = os.getenv('SONY_TV_ADB_PORT', '5555')

# Track the last switched content (since the TV API can't report the active app)
_current_content = {"title": None, "source": None, "uri": None}

class SourceAddressAdapter(HTTPAdapter):
    def __init__(self, source_address, **kwargs):
        self.source_address = source_address
        super(SourceAddressAdapter, self).__init__(**kwargs)

    def init_poolmanager(self, connections, maxsize, block=False):
        self.poolmanager = PoolManager(
            num_pools=connections, maxsize=maxsize,
            block=block, source_address=self.source_address)

def get_local_ip():
    """Discover the local IP on the interface that can reach the TV."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((SONY_TV_IP, 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '0.0.0.0'
    finally:
        s.close()
    return IP

def create_session():
    session = requests.Session()
    local_ip = get_local_ip()
    if local_ip != '0.0.0.0':
        adapter = SourceAddressAdapter((local_ip, 0))
        session.mount('http://', adapter)
    return session

def make_sony_api_request(url_suffix, method, params=None, version="1.0"):
    """Generic function to make Sony TV API requests"""
    url = f"http://{SONY_TV_IP}/sony/{url_suffix}"
    headers = {
        "X-Auth-PSK": PSK,
        "Content-Type": "application/json"
    }
    data = {
        "method": method,
        "id": 1,
        "params": params or [],
        "version": version
    }
    
    session = create_session()
    try:
        response = session.post(url, headers=headers, json=data, timeout=5)
        if response.status_code == 200:
            result = response.json()
            # Sony returns HTTP 200 even for API-level errors; check for "error" key
            if "error" in result:
                code, msg = result["error"][0], result["error"][1]
                return {"success": False, "error": f"Sony API error {code}: {msg}"}
            return {"success": True, "data": result}
        else:
            return {"success": False, "error": f"HTTP {response.status_code}: {response.text}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.route('/api/status')
def get_status():
    """Get TV power status"""
    result = make_sony_api_request("system", "getPowerStatus")
    if result["success"] and "result" in result["data"]:
        status = result["data"]["result"][0]["status"]
        return jsonify({"status": status, "success": True})
    else:
        return jsonify({"status": "offline", "success": False, "error": result.get("error", "Unknown error")})

@app.route('/api/power', methods=['POST'])
def power_control():
    """Turn TV on or off"""
    data = request.get_json()
    action = data.get('action')  # 'on' or 'off'
    
    if action == 'on':
        # Try Wake-on-LAN first
        try:
            # Derive subnet broadcast from TV IP (e.g. 192.168.1.x -> 192.168.1.255)
            broadcast = '.'.join(SONY_TV_IP.split('.')[:3] + ['255'])
            send_magic_packet(SONY_TV_MAC, ip_address=broadcast)
            send_magic_packet(SONY_TV_MAC, ip_address=SONY_TV_IP)
            
            # Also try the API power on method
            result = make_sony_api_request("system", "setPowerStatus", [{"status": True}])
            return jsonify({"success": True, "message": "TV wake command sent"})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)})
    
    elif action == 'off':
        result = make_sony_api_request("system", "setPowerStatus", [{"status": False}])
        if result["success"]:
            return jsonify({"success": True, "message": "TV turned off"})
        else:
            return jsonify({"success": False, "error": result["error"]})
    
    return jsonify({"success": False, "error": "Invalid action"})

@app.route('/api/volume', methods=['POST'])
def volume_control():
    """Control volume"""
    data = request.get_json()
    action = data.get('action')  # 'up', 'down', 'mute', 'unmute', 'set'
    
    if action == 'mute':
        result = make_sony_api_request("audio", "setAudioMute", [{"status": True}])
    elif action == 'unmute':
        result = make_sony_api_request("audio", "setAudioMute", [{"status": False}])
    elif action == 'up':
        result = make_sony_api_request("audio", "setAudioVolume", [{"target": "speaker", "volume": "+5"}])
    elif action == 'down':
        result = make_sony_api_request("audio", "setAudioVolume", [{"target": "speaker", "volume": "-5"}])
    elif action == 'set':
        volume = data.get('volume', 50)
        result = make_sony_api_request("audio", "setAudioVolume", [{"target": "speaker", "volume": str(volume)}])
    else:
        return jsonify({"success": False, "error": "Invalid action"})
    
    if result["success"]:
        return jsonify({"success": True, "message": f"Volume {action} successful"})
    else:
        return jsonify({"success": False, "error": result["error"]})

@app.route('/api/volume')
def get_volume():
    """Get current volume and mute status"""
    volume_result = make_sony_api_request("audio", "getVolumeInformation")
    
    if volume_result["success"] and "result" in volume_result["data"]:
        try:
            result_data = volume_result["data"]["result"]
            if isinstance(result_data, list) and len(result_data) > 0:
                volume_info = result_data[0]
                # Handle case where volume_info might be a list instead of dict
                if isinstance(volume_info, list) and len(volume_info) > 0:
                    volume_info = volume_info[0]
                
                # Ensure volume_info is a dictionary
                if isinstance(volume_info, dict):
                    return jsonify({
                        "success": True,
                        "volume": volume_info.get("volume", 50),
                        "muted": volume_info.get("mute", False),
                        "target": volume_info.get("target", "speaker")
                    })
                else:
                    # If we still don't have a dict, return default values
                    return jsonify({
                        "success": True,
                        "volume": 50,
                        "muted": False,
                        "target": "speaker"
                    })
            else:
                return jsonify({"success": False, "error": "No volume data available"})
        except (KeyError, IndexError, TypeError) as e:
            return jsonify({"success": False, "error": f"Error parsing volume data: {str(e)}"})
    else:
        return jsonify({"success": False, "error": volume_result.get("error", "Could not get volume info")})

def _friendly_input_name(uri):
    """Convert a Sony input URI to a human-readable name."""
    if not uri:
        return None
    if 'hdmi' in uri:
        # extInput:hdmi?port=1 -> HDMI 1
        try:
            port = uri.split('port=')[1].split('&')[0]
            return f"HDMI {port}"
        except (IndexError, ValueError):
            return "HDMI"
    if uri.startswith('tv:'):
        return "TV"
    if 'composite' in uri:
        return "AV"
    if 'component' in uri:
        return "Component"
    return None

def _resolve_app_name(app_uri):
    """Derive a friendly app name from a Sony app URI."""
    if not app_uri:
        return "App"
    known = {
        "netflix": "Netflix", "youtube": "YouTube", "disney": "Disney+",
        "amazon": "Prime Video", "apple.atve": "Apple TV", "hbo": "HBO Max",
        "spotify": "Spotify", "plex": "Plex", "twitch": "Twitch",
        "crunchyroll": "Crunchyroll", "dazn": "DAZN", "atbat": "MLB",
    }
    lower_uri = app_uri.lower()
    for key, name in known.items():
        if key in lower_uri:
            return name
    # Last resort: extract last meaningful segment
    parts = app_uri.split(".")
    return parts[-1] if parts else "App"

def _get_hdmi_labels():
    """Fetch user-set HDMI labels from the TV (e.g. PS5, Switch)."""
    result = make_sony_api_request("avContent", "getCurrentExternalInputsStatus", [], "1.1")
    labels = {}
    if result["success"] and "result" in result["data"]:
        inputs = result["data"]["result"][0] if result["data"]["result"] else []
        for inp in inputs:
            if isinstance(inp, dict) and inp.get("uri"):
                labels[inp["uri"]] = inp.get("label", "")
    return labels

def _resolve_current_content():
    """Query the TV for what's playing, update _current_content, and return
    just the title (e.g. 'Netflix' or 'HDMI 1').
    """
    global _current_content

    # --- Step 1: getPlayingContentInfo ---
    result = make_sony_api_request("avContent", "getPlayingContentInfo")
    if result["success"] and "result" in result["data"]:
        content_info = result["data"]["result"][0] if result["data"]["result"] else {}
        title = content_info.get("title", "") or ""
        uri = content_info.get("uri", "")
        source = content_info.get("source", "") or ""

        # For HDMI inputs, prefer user-set labels (e.g. "PS5", "Switch")
        if uri and "hdmi" in uri:
            labels = _get_hdmi_labels()
            if uri in labels and labels[uri]:
                title = labels[uri]

        # Derive a friendly name from the URI if title is still empty
        if not title and uri:
            title = _friendly_input_name(uri) or uri

        if title:
            _current_content = {"title": title, "source": source or "Input", "uri": uri}
            # Skip step 2 — we already have a result
            return _current_content.get("title") or "Unknown"

    # --- Step 2: ADB Fallback (Active App) ---
    # Sony's API doesn't report the foreground app, but Android TV ADB does.
    try:
        # Ensure we are connected
        subprocess.run(["adb", "connect", f"{SONY_TV_IP}:{ADB_PORT}"], capture_output=True, timeout=2)
        
        # This dumpsys command extracts the focused activity package name
        # e.g., mCurrentFocus=Window{... u0 com.netflix.ninja/com.netflix.ninja.MainActivity}
        cmd = ["adb", "-s", f"{SONY_TV_IP}:{ADB_PORT}", "shell", "dumpsys", "activity", "activities", "|", "grep", "mResumedActivity"]
        # On newer Androids mResumedActivity is reliable, but let's just grab the whole block and parse safely.
        # Actually a simpler cross-version way: dumpsys window windows | grep -E 'mCurrentFocus|mFocusedApp'
        dump_cmd = "adb -s " + f"{SONY_TV_IP}:{ADB_PORT}" + " shell dumpsys window windows | grep -i 'mCurrentFocus'"
        proc = subprocess.run(dump_cmd, shell=True, capture_output=True, text=True, timeout=3)
        output = proc.stdout.strip()
        
        if output and "u0 " in output:
            # Parse `u0 com.google.android.youtube.tv/...`
            pkg_part = output.split("u0 ")[-1].split("/")[0].strip()
            # Clean up trailing braces if present
            pkg_part = pkg_part.replace('}', '')
            
            if pkg_part:
                # If we know the friendly name via our app cache or heuristic:
                app_name = _resolve_app_name(pkg_part)
                if "nba" in app_name.lower():
                    app_name = "NBA"
                
                # Check if we have the real title in _icon_cache (which maps uri -> icon)
                # App URIs look like com.sony.dtv.com.netflix.ninja.com.netflix.ninja.MainActivity
                # We can do a fuzzy match against the package
                global _icon_cache
                if not _icon_cache:
                    # trigger fetch invisibly if empty
                    make_sony_api_request("appControl", "getApplicationList") # we just need it loaded later, not strictly now
                    
                _current_content = {"title": app_name, "source": "App", "uri": pkg_part}
                return app_name
                
    except Exception:
        pass
    
    return _current_content.get("title") or "Unknown"


@app.route('/api/channel')
def get_channel():
    """Get current channel/input information."""
    _resolve_current_content()  # refreshes _current_content from TV
    title = _current_content.get("title") or "Unknown"
    return jsonify({
        "success": True,
        "title": title,
        "uri": _current_content.get("uri", "")
    })

@app.route('/api/inputs/hdmi')
def get_hdmi_inputs():
    """Get HDMI inputs with friendly labels and connection status."""
    # Map known device labels to local icon paths
    DEVICE_ICONS = {
        "ps5": "/icons/ps5.png",
        "ps4": "/icons/ps4.png",
        "switch": "/icons/switch.png",
    }
    
    result = make_sony_api_request("avContent", "getCurrentExternalInputsStatus", [], "1.1")
    if result["success"] and "result" in result["data"]:
        inputs = result["data"]["result"][0] if result["data"]["result"] else []
        hdmi = []
        for inp in inputs:
            if not isinstance(inp, dict):
                continue
            uri = inp.get("uri", "")
            if "hdmi" not in uri:
                continue
            label = inp.get("label", "")
            title = inp.get("title", "")
            connected = inp.get("connection", False)
            # Build display name: use label if set, otherwise title
            display_name = label if label else title
            # Match icon from known devices
            icon = DEVICE_ICONS.get(label.lower(), None) if label else None
            hdmi.append({
                "uri": uri,
                "title": title,
                "label": label,
                "displayName": display_name,
                "connected": connected,
                "icon": icon,
            })
        return jsonify({"success": True, "inputs": hdmi})
    return jsonify({"success": False, "error": "Could not get HDMI status"})

_icon_cache = {}  # uri -> data URI (base64)

@app.route('/api/app-icons')
def get_app_icons():
    """Get a map of app URI -> icon data URI, cached after first fetch."""
    global _icon_cache
    if _icon_cache:
        return jsonify({"success": True, "icons": _icon_cache})

    result = make_sony_api_request("appControl", "getApplicationList")
    if result["success"] and "result" in result["data"]:
        apps = result["data"]["result"][0] if result["data"]["result"] else []
        icon_map = {}
        for app_info in apps:
            if isinstance(app_info, dict) and app_info.get("uri") and app_info.get("icon"):
                # Download the icon and convert to data URI
                try:
                    import base64
                    session = create_session()
                    resp = session.get(app_info["icon"], timeout=5)
                    if resp.status_code == 200:
                        ct = resp.headers.get("content-type", "image/png")
                        b64 = base64.b64encode(resp.content).decode()
                        icon_map[app_info["uri"]] = f"data:{ct};base64,{b64}"
                except Exception:
                    pass  # skip icons that fail to download
        _icon_cache = icon_map
        return jsonify({"success": True, "icons": icon_map})
    return jsonify({"success": False, "error": "Could not get app icons"})

@app.route('/api/applications')
def get_applications():
    """Get list of available applications"""
    result = make_sony_api_request("appControl", "getApplicationList")
    
    if result["success"] and "result" in result["data"]:
        apps = result["data"]["result"][0] if result["data"]["result"] else []
        return jsonify({"success": True, "applications": apps})
    else:
        return jsonify({"success": False, "error": result.get("error", "Could not get applications")})

@app.route('/api/applications/launch', methods=['POST'])
def launch_application():
    """Launch a specific application"""
    global _current_content
    data = request.get_json()
    app_uri = data.get('uri')
    app_title = data.get('title')  # optional friendly name from frontend
    
    if not app_uri:
        return jsonify({"success": False, "error": "Application URI required"})
    
    result = make_sony_api_request("appControl", "setActiveApp", [{"uri": app_uri}])
    
    if result["success"]:
        _current_content = {
            "title": app_title or _resolve_app_name(app_uri),
            "source": "App",
            "uri": app_uri
        }
        return jsonify({"success": True, "message": "Application launched"})
    else:
        return jsonify({"success": False, "error": result["error"]})

@app.route('/api/remote', methods=['POST'])
def remote_control():
    """Send remote control commands via IRCC codes."""
    IRCC_CODES = {
        "Up":       "AAAAAQAAAAEAAAB0Aw==",
        "Down":     "AAAAAQAAAAEAAAB1Aw==",
        "Left":     "AAAAAQAAAAEAAAA0Aw==",
        "Right":    "AAAAAQAAAAEAAAAzAw==",
        "Confirm":  "AAAAAQAAAAEAAABlAw==",
        "Return":   "AAAAAgAAAJcAAAAjAw==",
        "Home":     "AAAAAQAAAAEAAABgAw==",
        "Back":     "AAAAAgAAAJcAAAAjAw==",
    }

    data = request.get_json()
    command = data.get('command')

    if not command:
        return jsonify({"success": False, "error": "Command required"})

    ircc_code = IRCC_CODES.get(command)
    if not ircc_code:
        return jsonify({"success": False, "error": f"Unknown command: {command}"})

    # Send IRCC code via XML SOAP request
    xml_body = f'''<?xml version="1.0"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:X_SendIRCC xmlns:u="urn:schemas-sony-com:service:IRCC:1">
      <IRCCCode>{ircc_code}</IRCCCode>
    </u:X_SendIRCC>
  </s:Body>
</s:Envelope>'''

    try:
        session = create_session()
        resp = session.post(
            f"http://{SONY_TV_IP}/sony/IRCC",
            data=xml_body,
            headers={
                "Content-Type": "text/xml; charset=UTF-8",
                "X-Auth-PSK": PSK,
                "SOAPACTION": '"urn:schemas-sony-com:service:IRCC:1#X_SendIRCC"',
            },
            timeout=5,
        )
        if resp.status_code == 200:
            return jsonify({"success": True, "message": f"Command {command} sent"})
        else:
            return jsonify({"success": False, "error": f"IRCC returned {resp.status_code}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/inputs')
def get_inputs():
    """Get available input sources"""
    result = make_sony_api_request("avContent", "getSourceList", [], "1.0")
    
    if result["success"] and "result" in result["data"]:
        sources = result["data"]["result"][0] if result["data"]["result"] else []
        return jsonify({"success": True, "inputs": sources})
    else:
        return jsonify({"success": False, "error": result.get("error", "Could not get input sources")})

@app.route('/api/inputs/switch', methods=['POST'])
def switch_input():
    """Switch to a specific input source"""
    global _current_content
    data = request.get_json()
    source_uri = data.get('uri')
    input_title = data.get('title')  # optional friendly name from frontend
    
    if not source_uri:
        return jsonify({"success": False, "error": "Source URI required"})
    
    result = make_sony_api_request("avContent", "setPlayContent", [{"uri": source_uri}])
    
    if result["success"]:
        _current_content = {
            "title": input_title or _friendly_input_name(source_uri) or source_uri,
            "source": "Input",
            "uri": source_uri
        }
        return jsonify({"success": True, "message": "Input switched"})
    else:
        return jsonify({"success": False, "error": result["error"]})

# SPA Serving: Catch-all for frontend assets and routing
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    if path and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, 'index.html')

if __name__ == '__main__':
    print(f"Starting Sony TV Remote Control Server")
    print(f"TV IP: {SONY_TV_IP}")
    print(f"Server will be available at: http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)