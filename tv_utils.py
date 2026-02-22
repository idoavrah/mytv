import os
import socket
import requests
import subprocess
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager

# Configuration from environment
SONY_TV_IP = os.getenv('SONY_TV_IP')
SONY_TV_MAC = os.getenv('SONY_TV_MAC')
PSK = os.getenv('SONY_TV_PSK')
ADB_PORT = os.getenv('SONY_TV_ADB_PORT', '5555')

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

def friendly_input_name(uri):
    """Convert a Sony input URI to a human-readable name."""
    if not uri:
        return None
    if 'hdmi' in uri:
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

def resolve_app_name(app_uri):
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
            
    # Custom rule for NBA
    if "nba" in lower_uri:
        return "NBA"

    # Last resort: extract last meaningful segment
    parts = app_uri.split(".")
    return parts[-1] if parts else "App"

def get_hdmi_labels():
    """Fetch user-set HDMI labels from the TV (e.g. PS5, Switch)."""
    result = make_sony_api_request("avContent", "getCurrentExternalInputsStatus", [], "1.1")
    labels = {}
    if result["success"] and "result" in result["data"]:
        inputs = result["data"]["result"][0] if result["data"]["result"] else []
        for inp in inputs:
            if isinstance(inp, dict) and inp.get("uri"):
                labels[inp["uri"]] = inp.get("label", "")
    return labels

def set_power(status):
    return make_sony_api_request("system", "setPowerStatus", [{"status": status}])

def set_volume(volume):
    # volume can be numeric or "+5"/"-5"
    return make_sony_api_request("audio", "setAudioVolume", [{"target": "speaker", "volume": str(volume)}])

def set_mute(status):
    return make_sony_api_request("audio", "setAudioMute", [{"status": status}])

def launch_app(uri):
    return make_sony_api_request("appControl", "setActiveApp", [{"uri": uri}])

def switch_input(uri):
    return make_sony_api_request("avContent", "setPlayContent", [{"uri": uri}], "1.0")

def send_ircc(code):
    xml_body = f'''<?xml version="1.0"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:X_SendIRCC xmlns:u="urn:schemas-sony-com:service:IRCC:1">
      <IRCCCode>{code}</IRCCCode>
    </u:X_SendIRCC>
  </s:Body>
</s:Envelope>'''
    
    headers = {
        "Content-Type": "text/xml; charset=UTF-8",
        "X-Auth-PSK": PSK,
        "SOAPACTION": '"urn:schemas-sony-com:service:IRCC:1#X_SendIRCC"',
    }
    
    url = f"http://{SONY_TV_IP}/sony/IRCC"
    session = create_session()
    try:
        resp = session.post(url, data=xml_body, headers=headers, timeout=5)
        if resp.status_code == 200:
            return {"success": True}
        else:
            return {"success": False, "error": f"IRCC returned {resp.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

