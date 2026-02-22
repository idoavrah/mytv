import React, { useState, useEffect } from "react";
import axios from "axios";
import {
  Power,
  VolumeX,
  Volume2,
  Volume1,
  VolumeIcon,
  Tv,
  Wifi,
  WifiOff,
  ChevronUp,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Undo2,
} from "lucide-react";

// Configure axios to use relative URLs (proxied by Vite)
const api = axios.create({
  baseURL: "",
  timeout: 10000,
});

function App() {
  const [tvStatus, setTvStatus] = useState({
    power: "offline",
    volume: 0,
    muted: false,
    channel: "Unknown",
    application: "Unknown",
    currentUri: "",
  });

  const [sliderVolume, setSliderVolume] = useState(null);
  const [isDragging, setIsDragging] = useState(false);
  const [loading, setLoading] = useState(false);
  const [lastUpdate, setLastUpdate] = useState(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState(null);

  const fetchStatus = async () => {
    try {
      setError(null);
      const res = await api.get("/api/status");

      if (res.data && res.data.success) {
        setTvStatus((prev) => {
          const power = res.data.power || "offline";
          const newStatus = {
            ...prev,
            power: power,
            volume: res.data.volume ?? prev.volume,
            muted: res.data.muted ?? prev.muted,
            channel: res.data.title || "Unknown",
            currentUri: res.data.uri || "",
            // Use title as application if channel is Unknown, otherwise it's self-contained
            application: res.data.title || "Unknown",
          };

          if (power === "active") {
            setConnected(true);
          } else {
            setConnected(false);
            // Reset fields on standby/offline
            newStatus.volume = 0;
            newStatus.muted = false;
            newStatus.channel = "—";
            newStatus.application = "—";
            newStatus.currentUri = "";
          }

          return newStatus;
        });

        setLastUpdate(
          new Date().toLocaleTimeString("de-DE", {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
          }),
        );
      } else {
        setConnected(false);
        setTvStatus((prev) => ({ ...prev, power: "offline" }));
      }
    } catch (error) {
      console.error("Error fetching status:", error);
      setError("Failed to fetch TV status");
      setConnected(false);
      setTvStatus((prev) => ({ ...prev, power: "offline" }));
    }
  };

  // Power control
  const handlePower = async (action) => {
    setLoading(true);
    setError(null);
    try {
      const response = await api.post("/api/power", { action });
      if (response.data.success) {
        // Wait a bit then refresh status
        setTimeout(fetchStatus, 2000);
      }
    } catch (error) {
      console.error("Power control error:", error);
      setError(`Failed to ${action} TV`);
    }
    setLoading(false);
  };

  // Volume control
  const handleVolume = async (action, volume = null) => {
    setLoading(true);
    setError(null);
    try {
      const payload = { action };
      if (volume !== null) payload.volume = volume;

      const response = await api.post("/api/volume", payload);
      if (response.data.success) {
        // Refresh volume info
        setTimeout(() => {
          api
            .get("/api/status")
            .then((res) => {
              if (res.data.success) {
                setTvStatus((prev) => ({
                  ...prev,
                  volume: res.data.volume ?? prev.volume,
                  muted: res.data.muted ?? prev.muted,
                }));
              }
            })
            .catch(console.error);
        }, 500);
      }
    } catch (error) {
      console.error("Volume control error:", error);
      setError(`Failed to control volume`);
    }
    setLoading(false);
  };

  // App presets
  const APP_PRESETS = [
    {
      label: "Netflix",
      type: "app",
      uri: "com.sony.dtv.com.netflix.ninja.com.netflix.ninja.MainActivity",
    },
    {
      label: "YouTube",
      type: "app",
      uri: "com.sony.dtv.com.google.android.youtube.tv.com.google.android.apps.youtube.tv.activity.ShellActivity",
    },
    {
      label: "Prime Video",
      type: "app",
      uri: "com.sony.dtv.com.amazon.amazonvideo.livingroom.com.amazon.ignition.IgnitionActivity",
    },
    {
      label: "Spotify",
      type: "app",
      uri: "com.sony.dtv.com.spotify.tv.android.com.spotify.tv.android.SpotifyTVActivity",
    },
    {
      label: "NBA",
      type: "app",
      uri: "com.sony.dtv.com.nbaimd.gametime.nba2011.com.nba.tv.ui.splash.SplashActivity",
    },
    {
      label: "MLB",
      type: "app",
      uri: "com.sony.dtv.com.bamnetworks.mobile.android.gameday.atbat.mlb.atbat.activity.MainActivity",
    },
  ];

  // Dynamic HDMI inputs from TV
  const [hdmiInputs, setHdmiInputs] = useState([]);
  // App icon URLs from TV
  const [appIcons, setAppIcons] = useState({});

  const fetchHdmiInputs = async () => {
    try {
      const res = await api.get("/api/inputs/hdmi");
      if (res.data.success) {
        // Only show HDMI 1 (PS5) and HDMI 2 (Switch)
        const filtered = res.data.inputs.filter(
          (inp) =>
            (inp.label || inp.displayName || inp.connected) &&
            !inp.uri.includes("port=3") &&
            !inp.uri.includes("port=4"),
        );
        setHdmiInputs(filtered);
      }
    } catch (e) {
      console.error("Failed to fetch HDMI inputs:", e);
    }
  };

  const fetchAppIcons = async () => {
    try {
      const res = await api.get("/api/app-icons");
      if (res.data.success) {
        setAppIcons(res.data.icons);
      }
    } catch (e) {
      console.error("Failed to fetch app icons:", e);
    }
  };

  // Switch input or launch app
  const handleSwitchInput = async (item) => {
    setLoading(true);
    setError(null);
    try {
      let response;
      const title = item.displayName || item.label;
      if (item.type === "app") {
        response = await api.post("/api/applications/launch", {
          uri: item.uri,
          title,
        });
      } else {
        response = await api.post("/api/inputs/switch", {
          uri: item.uri,
          title,
        });
      }
      if (response.data.success) {
        setTimeout(fetchStatus, 2000);
      } else {
        setError(response.data.error || `Failed to switch to ${title}`);
      }
    } catch (error) {
      console.error("Switch input error:", error);
      setError(`Failed to switch to ${item.displayName || item.label}`);
    }
    setLoading(false);
  };

  // Auto-refresh status
  useEffect(() => {
    fetchStatus();
    fetchHdmiInputs();
    fetchAppIcons();
    const interval = setInterval(fetchStatus, 10000);
    return () => clearInterval(interval);
  }, []);

  const getStatusColor = (status) => {
    switch (status) {
      case "active":
        return "success";
      case "standby":
        return "loading";
      case "offline":
        return "error";
      default:
        return "error";
    }
  };

  return (
    <div className="remote-container">
      <h1
        style={{
          marginBottom: "2rem",
          color: "#fff",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          gap: "0.5rem",
        }}
      >
        <Tv size={32} />
        Sony TV Remote Control
      </h1>

      {/* Error Display */}
      {error && (
        <div
          style={{
            background: "rgba(255, 0, 0, 0.2)",
            border: "1px solid rgba(255, 0, 0, 0.5)",
            borderRadius: "8px",
            padding: "1rem",
            marginBottom: "1rem",
            color: "#ff6b6b",
          }}
        >
          {error}
        </div>
      )}

      {/* Status Display */}
      <div className="status-display">
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: "1rem",
          }}
        >
          <h2 style={{ color: "#fff", fontSize: "1.5rem" }}>TV Status</h2>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            {connected ? (
              <Wifi size={20} className="success" />
            ) : (
              <WifiOff size={20} className="error" />
            )}
            <span
              style={{ fontSize: "0.8rem", color: "rgba(255,255,255,0.6)" }}
            >
              {lastUpdate && `Last update: ${lastUpdate}`}
            </span>
          </div>
        </div>

        <div className="status-item">
          <span className="status-label">Power:</span>
          <span className={`status-value ${getStatusColor(tvStatus.power)}`}>
            {tvStatus.power.toUpperCase()}
          </span>
        </div>

        <div className="status-item">
          <span className="status-label">Volume:</span>
          <span className="status-value">
            {tvStatus.muted ? "MUTED" : `${tvStatus.volume}%`}
          </span>
        </div>

        <div className="status-item">
          <span className="status-label">Now Playing:</span>
          <span className="status-value">
            {tvStatus.channel !== "Unknown"
              ? tvStatus.channel
              : tvStatus.application !== "Unknown"
                ? tvStatus.application
                : "—"}
          </span>
        </div>
      </div>

      {/* Power Controls */}
      <div className="control-section">
        <h3>Power Control</h3>
        <div className="button-group">
          <button
            className="control-button power-on"
            onClick={() => handlePower("on")}
            disabled={loading}
          >
            <Power size={20} />
            Turn On
          </button>
          <button
            className="control-button power-off"
            onClick={() => handlePower("off")}
            disabled={loading}
          >
            <Power size={20} />
            Turn Off
          </button>
        </div>
      </div>

      {/* Input / App Switcher */}
      <div className="control-section">
        <div className="input-grid input-grid-centered">
          {hdmiInputs.map((inp) => (
            <button
              key={inp.uri}
              className={`input-button-logo${tvStatus.currentUri === inp.uri ? " input-button-active" : ""}`}
              onClick={() => handleSwitchInput({ ...inp, type: "input" })}
              disabled={loading}
              title={inp.displayName}
            >
              {inp.icon ? (
                <img
                  src={inp.icon}
                  alt={inp.displayName}
                  className="input-logo-img"
                />
              ) : (
                <span className="input-button-emoji">🖥️</span>
              )}
            </button>
          ))}
          {APP_PRESETS.map((app) => (
            <button
              key={app.uri}
              className={`input-button-logo${tvStatus.currentUri === app.uri ? " input-button-active" : ""}`}
              onClick={() => handleSwitchInput(app)}
              disabled={loading}
              title={app.label}
            >
              {appIcons[app.uri] ? (
                <img
                  src={appIcons[app.uri]}
                  alt={app.label}
                  className="input-logo-img"
                />
              ) : (
                <span className="input-button-emoji">{app.label[0]}</span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* D-pad Navigation */}
      <div className="control-section">
        <div className="dpad-container">
          <div className="dpad-row">
            <button
              className="dpad-button"
              onClick={() => api.post("/api/remote", { command: "Up" })}
              disabled={loading}
            >
              <ChevronUp size={28} />
            </button>
          </div>
          <div className="dpad-row">
            <button
              className="dpad-button"
              onClick={() => api.post("/api/remote", { command: "Left" })}
              disabled={loading}
            >
              <ChevronLeft size={28} />
            </button>
            <button
              className="dpad-button dpad-ok"
              onClick={() => api.post("/api/remote", { command: "Confirm" })}
              disabled={loading}
            >
              OK
            </button>
            <button
              className="dpad-button"
              onClick={() => api.post("/api/remote", { command: "Right" })}
              disabled={loading}
            >
              <ChevronRight size={28} />
            </button>
          </div>
          <div className="dpad-row">
            <button
              className="dpad-button"
              onClick={() => api.post("/api/remote", { command: "Down" })}
              disabled={loading}
            >
              <ChevronDown size={28} />
            </button>
          </div>
          <div className="dpad-row" style={{ marginTop: "0.5rem" }}>
            <button
              className="dpad-button dpad-back"
              onClick={() => api.post("/api/remote", { command: "Return" })}
              disabled={loading}
            >
              <Undo2 size={18} /> Back
            </button>
          </div>
        </div>
      </div>

      {/* Volume Controls */}
      <div className="control-section">
        <h3>Volume Control</h3>
        <div className="button-group">
          <button
            className="control-button"
            onClick={() =>
              handleVolume("set", Math.max(0, tvStatus.volume - 1))
            }
            disabled={loading}
          >
            <Volume1 size={20} />−
          </button>
          <button
            className="control-button"
            onClick={() => handleVolume(tvStatus.muted ? "unmute" : "mute")}
            disabled={loading}
          >
            {tvStatus.muted ? <Volume2 size={20} /> : <VolumeX size={20} />}
            {tvStatus.muted ? "Unmute" : "Mute"}
          </button>
          <button
            className="control-button"
            onClick={() =>
              handleVolume("set", Math.min(100, tvStatus.volume + 1))
            }
            disabled={loading}
          >
            <VolumeIcon size={20} />+
          </button>
        </div>

        {/* Volume Slider */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: "1rem",
          }}
        >
          <input
            type="range"
            min="0"
            max="100"
            value={isDragging ? sliderVolume : tvStatus.volume}
            onChange={(e) => {
              setSliderVolume(parseInt(e.target.value));
              setIsDragging(true);
            }}
            onMouseUp={() => {
              if (isDragging && sliderVolume !== null) {
                setTvStatus((prev) => ({ ...prev, volume: sliderVolume }));
                handleVolume("set", sliderVolume);
              }
              setIsDragging(false);
            }}
            onTouchEnd={() => {
              if (isDragging && sliderVolume !== null) {
                setTvStatus((prev) => ({ ...prev, volume: sliderVolume }));
                handleVolume("set", sliderVolume);
              }
              setIsDragging(false);
            }}
            className="volume-slider"
            style={{
              background: `linear-gradient(to right, #4299e1 0%, #4299e1 ${isDragging ? sliderVolume : tvStatus.volume}%, rgba(255,255,255,0.3) ${isDragging ? sliderVolume : tvStatus.volume}%, rgba(255,255,255,0.3) 100%)`,
            }}
          />
          <span
            style={{
              color: "rgba(255,255,255,0.8)",
              fontSize: "1.1rem",
              fontWeight: 600,
            }}
          >
            {isDragging ? sliderVolume : tvStatus.volume}%
          </span>
        </div>
      </div>
    </div>
  );
}

export default App;
