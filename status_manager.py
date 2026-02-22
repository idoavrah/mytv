import os
import json
import time
import logging
import threading
import subprocess
from datetime import datetime
from tv_utils import (
    make_sony_api_request, 
    friendly_input_name, 
    resolve_app_name, 
    get_hdmi_labels,
    SONY_TV_IP,
    ADB_PORT
)

# Mapping of "known" content to fixed integers. 0 is unknown/unmapped.
NOW_PLAYING_ID_MAP = {
    "Unknown": 0,
    "Home Screen": 1,
    "Web Browser": 2,
    "PS5": 10,
    "Switch": 11,
    "HDMI 3": 12,
    "HDMI 4": 13,
    "TV": 20,
    "AV": 21,
    "Component": 22,
    "Netflix": 100,
    "YouTube": 101,
    "Disney+": 102,
    "Prime Video": 103,
    "Apple TV": 104,
    "HBO Max": 105,
    "Spotify": 106,
    "Plex": 107,
    "Twitch": 108,
    "Crunchyroll": 109,
    "DAZN": 110,
    "MLB": 111,
    "NBA": 112,
}

class StatusManager:
    def __init__(self):
        self.poll_interval = int(os.getenv('POLL_INTERVAL', '10'))
        self.max_error_iterations = int(os.getenv('MAX_ERROR_ITERATIONS', '3'))
        
        self.current_status = {
            "power": "unknown",
            "volume": 0,
            "muted": False,
            "title": "Unknown",
            "uri": "",
            "now_playing_id": 0,
            "timestamp": None
        }
        
        # Track errors for each metric to implement grace period
        self.error_counts = {
            "power": 0,
            "volume": 0,
            "now_playing": 0
        }
        
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.last_override_time = 0  # Timestamp of last manual override
        logging.info("Initializing StatusManager instance...")
        self.thread = threading.Thread(target=self._update_loop, daemon=True)

    def start(self):
        self.thread.start()

    def get_status(self):
        with self.lock:
            return self.current_status.copy()

    def update_override(self, title, uri):
        """Manually override the status (e.g. after a launch action)."""
        with self.lock:
            self.current_status.update({
                "title": title,
                "uri": uri,
                "now_playing_id": self._get_now_playing_id(title),
                "timestamp": datetime.now().isoformat()
            })
            self.last_override_time = time.time()
            # Reset error count for now_playing since we just got a manual update
            self.error_counts["now_playing"] = 0


    def _update_loop(self):
        logging.info("StatusManager background update loop started.")
        while not self.stop_event.is_set():
            try:
                # If we just had a manual override, skip polling to allow TV to switch
                if time.time() - self.last_override_time < 5:
                    logging.info("Skipping background poll due to recent manual override.")
                else:
                    self._refresh_status()
                    # Log status as JSON
                    logging.info(f"Current Status: {json.dumps(self.current_status)}")
            except Exception as e:
                logging.error(f"Error in StatusManager loop: {e}")
            
            time.sleep(self.poll_interval)

    def _refresh_status(self):
        new_values = {}
        
        # 1. Power Status
        power_res = make_sony_api_request("system", "getPowerStatus")
        if power_res["success"] and "result" in power_res["data"]:
            new_values["power"] = power_res["data"]["result"][0]["status"]
            self.error_counts["power"] = 0
        else:
            self.error_counts["power"] += 1
            if self.error_counts["power"] > self.max_error_iterations:
                new_values["power"] = "offline"

        # 2. Volume Status
        vol_res = make_sony_api_request("audio", "getVolumeInformation")
        if vol_res["success"] and "result" in vol_res["data"]:
            vol_data = vol_res["data"]["result"]
            if vol_data and isinstance(vol_data[0], list) and vol_data[0]:
                for v in vol_data[0]:
                    if v.get("target") == "speaker":
                        new_values["volume"] = v.get("volume", 0)
                        new_values["muted"] = v.get("mute", False)
                        break
            self.error_counts["volume"] = 0
        else:
            self.error_counts["volume"] += 1
            # Keep previous if within grace period

        # 3. Now Playing Status
        title, uri = self._fetch_now_playing()
        if title != "Unknown" or uri:
            new_values["title"] = title
            new_values["uri"] = uri
            new_values["now_playing_id"] = self._get_now_playing_id(title)
            self.error_counts["now_playing"] = 0
        else:
            self.error_counts["now_playing"] += 1
            if self.error_counts["now_playing"] > self.max_error_iterations:
                new_values["title"] = "Unknown"
                new_values["uri"] = ""
                new_values["now_playing_id"] = 0

        # Update global status with new values
        with self.lock:
            self.current_status.update(new_values)
            self.current_status["timestamp"] = datetime.now().isoformat()

    def _fetch_now_playing(self):
        # Prefer Sony API
        res = make_sony_api_request("avContent", "getPlayingContentInfo")
        if res["success"] and "result" in res["data"] and res["data"]["result"]:
            info = res["data"]["result"][0]
            title = info.get("title", "")
            uri = info.get("uri", "")
            
            if uri and "hdmi" in uri:
                labels = get_hdmi_labels()
                title = labels.get(uri) or friendly_input_name(uri) or uri
            
            if not title and uri:
                title = friendly_input_name(uri) or uri
                
            if title:
                return title, uri

        # ADB Fallback
        try:
            subprocess.run(["adb", "connect", f"{SONY_TV_IP}:{ADB_PORT}"], capture_output=True, timeout=2)
            dump_cmd = f"adb -s {SONY_TV_IP}:{ADB_PORT} shell dumpsys window windows | grep -i 'mCurrentFocus'"
            proc = subprocess.run(dump_cmd, shell=True, capture_output=True, text=True, timeout=3)
            output = proc.stdout.strip()
            
            if output and "u0 " in output:
                pkg = output.split("u0 ")[-1].split("/")[0].strip().replace('}', '')
                if pkg:
                    return resolve_app_name(pkg), pkg
        except Exception:
            pass
            
        return "Unknown", ""

    def _get_now_playing_id(self, title):
        # Exact match
        if title in NOW_PLAYING_ID_MAP:
            return NOW_PLAYING_ID_MAP[title]
        
        # Substring match for dynamic names (e.g. apps)
        for key, val in NOW_PLAYING_ID_MAP.items():
            if key in title:
                return val
                
        return 0

# Global instance
status_manager = StatusManager()
