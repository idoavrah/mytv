# Sony TV Remote Control Web App

A modern web-based remote control for Sony TVs with a Python Flask backend and React frontend.

## Features

- **Power Control**: Turn TV on/off with Wake-on-LAN support
- **Volume Control**: Volume up/down, mute/unmute, and volume slider
- **Status Display**: Real-time display of TV status, volume, channel, and application
- **Text Messaging**: Send text messages to display on the TV screen
- **Modern UI**: Responsive design with glass-morphism styling
- **Auto-refresh**: Status updates every 10 seconds

## Prerequisites

- Python 3.8+
- Node.js 16+
- Sony TV with network connectivity
- TV's IP address and Pre-Shared Key (PSK)

## Setup

### Backend (Python Flask)

1. **Install Python dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment variables:**
   Copy `.env.example` to `.env` and fill in your values:

   ```bash
   cp .env.example .env
   ```

3. **Start the backend server:**

   ```bash
   python app.py
   ```

   The backend will be available at `http://localhost:5000`

### Frontend (React/Vite)

1. **Navigate to the frontend directory:**

   ```bash
   cd frontend
   ```

2. **Install Node.js dependencies:**

   ```bash
   npm install
   ```

3. **Start the development server:**

   ```bash
   npm run dev
   ```

   The frontend will be available at `http://localhost:3000`

## Sony TV Configuration

### Enable Remote Control API

1. On your Sony TV, go to: **Settings** → **Network & Internet** → **Home Network** → **IP Control**
2. Set **Authentication** to **Pre-Shared Key**
3. Set your **Pre-Shared Key** (this maps to the `PSK` field in your `.env`)
4. Enable **Simple IP Control**

### Find TV Information

- **IP Address**: Check your router's admin panel or TV network settings
- **MAC Address**: Check router's device list or use `arp -a` command
- **PSK**: Set this in the TV's IP Control settings

## API Endpoints

The backend provides the following REST API endpoints:

- `GET /api/status` - Get TV power status
- `POST /api/power` - Control TV power (on/off)
- `GET /api/volume` - Get volume information
- `POST /api/volume` - Control volume (up/down/mute/set)
- `GET /api/channel` - Get current channel/content info
- `POST /api/text` - Send text message to TV
- `GET /api/applications` - Get available apps
- `POST /api/applications/launch` - Launch an app
- `GET /api/inputs` - Get input sources
- `POST /api/inputs/switch` - Switch input source

## Usage

1. Start both the backend and frontend servers
2. Open your browser to `http://localhost:3000`
3. Use the web interface to:
   - Monitor TV status in real-time
   - Turn TV on/off
   - Adjust volume or mute
   - Send text messages to the TV screen
   - View current channel and application info

## Troubleshooting

### TV Not Responding

- Verify the TV's IP address and PSK
- Ensure TV is connected to the same network
- Check that IP Control is enabled in TV settings

### Wake-on-LAN Issues

- Verify the MAC address is correct
- Ensure TV supports Wake-on-LAN
- Try waking the TV manually first

### Connection Errors

- Check firewall settings
- Ensure both devices are on the same network
- Try accessing `http://[TV_IP]/sony/system` manually

## Development

### Backend Development

- The Flask server runs in debug mode for development
- API changes are automatically reloaded
- Check console for detailed error logs

### Frontend Development

- Vite provides hot-reload for instant updates
- React DevTools can be used for debugging
- API calls are proxied to the backend server

## Building for Production

### Frontend Build

```bash
cd frontend
npm run build
```

The built files will be in `frontend/dist/`

### Backend Production

For production deployment, consider using:

- Gunicorn or uWSGI for the Python server
- Nginx for serving static files and reverse proxy
- Environment-specific configuration files

## License

This project is open source and available under the MIT License.
