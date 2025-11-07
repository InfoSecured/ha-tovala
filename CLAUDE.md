# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **Home Assistant Custom Integration** (HACS-installable) that connects to Tovala Smart Ovens via their undocumented cloud API. It polls oven status, exposes sensors for remaining cook time, and fires Home Assistant events when timers complete.

**Key constraints:**
- Tovala has no public API; this integration reverse-engineers their mobile app's HTTPS endpoints
- The integration tries both `api.beta.tovala.com` and `api.tovala.com` automatically
- Authentication requires specific headers including `X-Tovala-AppID: MAPP`
- All API paths include the user_id extracted from the JWT token: `/v0/users/{user_id}/...`

## Architecture

### Component Structure

```
custom_components/tovala/
├── __init__.py        # Entry point: setup, login, coordinator initialization
├── api.py             # TovalaClient: authentication, API discovery
├── coordinator.py     # DataUpdateCoordinator: polling, event firing
├── config_flow.py     # ConfigFlow: UI-based setup with email/password
├── sensor.py          # Time remaining sensor (seconds)
├── binary_sensor.py   # Timer running binary sensor
├── const.py           # Constants (domain, platforms, scan interval)
└── manifest.json      # Integration metadata
```

### Key Components

**api.py (`TovalaClient`):**
- Handles token-based authentication with automatic base URL discovery (beta → prod fallback)
- Extracts `userId` from JWT token payload for building API paths
- Rate limit detection (HTTP 429) stops login attempts immediately
- Token expiry tracking with automatic re-authentication
- **Critical:** All requests must include `X-Tovala-AppID: MAPP` header
- Known endpoints:
  - Login: `POST /v0/getToken` → returns `{"token": "jwt..."}`
  - List ovens: `GET /v0/users/{user_id}/ovens` → returns array of oven objects
  - Oven status: `GET /v0/users/{user_id}/ovens/{oven_id}/cook/status` → returns cooking state

**coordinator.py (`TovalaCoordinator`):**
- Extends Home Assistant's `DataUpdateCoordinator`
- Polls oven status every 10 seconds (configurable via `DEFAULT_SCAN_INTERVAL`)
- Calculates remaining cook time from `estimated_end_time` field (not a direct API field)
- Detects timer completion (remaining time crossing from >0 to 0)
- Fires `tovala_timer_finished` event with `{oven_id, data}` payload
- Handles missing oven_id gracefully (returns empty dict)
- Adds calculated `remaining` field to coordinator data for sensors

**__init__.py:**
- Entry setup flow: authenticate → discover ovens → create coordinator
- Automatically discovers and stores first oven_id if not configured
- Forwards setup to sensor and binary_sensor platforms
- Implements unload for clean removal

**config_flow.py:**
- Simple user step with email/password fields
- Error handling: `auth` (401/403), `cannot_connect` (network/other), rate limiting
- Creates config entry with credentials (oven_id added during async_setup_entry)

### Data Flow

1. User configures integration via UI → `config_flow.py` validates credentials
2. `__init__.py` creates `TovalaClient`, authenticates, discovers oven_id
3. `TovalaCoordinator` polls `client.oven_status(oven_id)` every 10s
4. Sensors (`sensor.py`, `binary_sensor.py`) read from coordinator's cached data
5. When `remaining` crosses to 0, coordinator fires `tovala_timer_finished` event

### API Structure

The Tovala API follows this pattern (discovered via Charles Proxy):
- **Base URL**: `https://api.beta.tovala.com` (primary) or `https://api.tovala.com` (fallback)
- **Authentication**: JWT token from `/v0/getToken` endpoint
- **User ID extraction**: Parse JWT payload to extract `userId` field
- **Path pattern**: All data endpoints use `/v0/users/{user_id}/...` structure
- **Oven ID format**: UUID like `b3d64c11-96db-4ed2-9589-b52fbd0a15b1`

## Development Commands

**Testing locally:**
```bash
# Copy integration to Home Assistant config directory
cp -r custom_components/tovala /path/to/homeassistant/config/custom_components/

# Restart Home Assistant (method varies by installation type)
# Then configure via UI: Settings → Devices & Services → Add Integration → Tovala
```

**Enable debug logging:**
Add to Home Assistant `configuration.yaml`:
```yaml
logger:
  default: warning
  logs:
    custom_components.tovala: debug
```

**Test authentication manually:**
```bash
curl -i -X POST "https://api.beta.tovala.com/v0/getToken" \
  -H "Content-Type: application/json" \
  -H "X-Tovala-AppID: MAPP" \
  -d '{"email":"EMAIL","password":"PASSWORD","type":"user"}'
```

**No automated tests exist** - testing requires a live Tovala account and oven.

## Code Patterns

### Error Handling
- `TovalaAuthError`: Authentication failures (401/403) - stop immediately, don't retry other bases
- `TovalaApiError`: Network errors, rate limits (429), or API failures - may retry other base URLs
- Rate limit errors (HTTP 429) are logged and raised immediately to avoid account lockout

### Logging Strategy
- `_LOGGER.debug()`: All HTTP requests/responses, login attempts, endpoint discovery
- `_LOGGER.info()`: Successful login, oven discovery
- `_LOGGER.warning()`: Failed endpoint attempts (expected during discovery)
- `_LOGGER.error()`: Connection failures, rate limits, unexpected errors

### Home Assistant Patterns
- Use `async_get_clientsession(hass)` for HTTP - never create your own session
- Entities must define `unique_id` for persistence across restarts
- Coordinator-based entities should check `coordinator.last_update_success` for availability
- Config entries store credentials; coordinator stores runtime state

## Common Tasks

**Adding a new sensor:**
1. Create entity class in `sensor.py` or new file
2. Extract value from `self.coordinator.data`
3. Add platform to `PLATFORMS` in `const.py` if new file
4. Add to `async_setup_entry()` entities list

**Modifying API behavior:**
- Authentication: edit `TovalaClient.login()` in api.py
- JWT parsing: edit `TovalaClient._decode_jwt_user_id()` in api.py
- API endpoints: edit `list_ovens()` and `oven_status()` in api.py
- Poll interval: change `DEFAULT_SCAN_INTERVAL` in const.py
- Remaining time calculation: edit `TovalaCoordinator._async_update_data()` in coordinator.py

**Updating version:**
1. Edit `manifest.json` version field
2. Commit changes
3. Tag with `git tag vX.Y.Z && git push --tags`
4. HACS detects new releases automatically

## API Response Expectations

**Token response** (`POST /v0/getToken`):
```json
{
  "token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyIjp0cnVlLCJ1c2VySWQiOjE3MzE2MDEsImV4cCI6MTc2MzY4Nzg5MCwiaWF0IjoxNzYyNDc4MjkwLCJpc3MiOiI5MDIwY2UxNGU4NjM6OmNvbWJpbmVkYXBpIn0..."
}
```
JWT payload contains: `{"user": true, "userId": 1731601, "exp": ..., "iat": ..., "iss": "..."}`

**Ovens list response** (`GET /v0/users/{user_id}/ovens`):
```json
[{
  "id": "b3d64c11-96db-4ed2-9589-b52fbd0a15b1",
  "userid": 1731601,
  "type": "tovala",
  "model": "gen2",
  "name": "My Tovala",
  "created": "2025-09-25T21:10:12.757077Z",
  "updated": "2025-09-25T21:10:12.757077Z",
  "cook_modes": ["convection_steam_variable", "convection_bake", "broil_variable"],
  "routine_schemas": ["2018-09-07"],
  "tovala": {
    "id": "b3d64c11-96db-4ed2-9589-b52fbd0a15b1",
    "agentid": "ypaelOLxNwq9",
    "deviceid": "40000c2a69245398",
    "planid": "1a09dc809156df64",
    "serial": "TOVMN21130001"
  }
}]
```

**Oven status response** (`GET /v0/users/{user_id}/ovens/{oven_id}/cook/status`):

When idle:
```json
{
  "remote_control_enabled": true,
  "state": "idle"
}
```

When cooking:
```json
{
  "remote_control_enabled": true,
  "state": "cooking",
  "estimated_start_time": "2025-11-07T01:45:47Z",
  "estimated_end_time": "2025-11-07T01:53:02.00000245Z",
  "barcode": "133A254|463|5E34BF80",
  "routine": {
    "version": "2018-09-07",
    "routine": [
      {"bottom": 1, "broil": 0, "cookTime": 75, "fan": 1, "mode": "", "steam": 0.65, "temperature": 450, "top": 1},
      ...
    ],
    "oven_type": "tovala",
    "oven_model": "gen2",
    "barcode": "133A254|463|5E34BF80",
    "routineID": "96e7568f-a93b-bf67-1cee-432b7d8bee5d"
  }
}
```

**Note**: Remaining cook time is NOT a direct field. Calculate it as:
```python
remaining_seconds = (estimated_end_time - current_time).total_seconds()
```

## Known Issues & Limitations

- No oven selection UI yet (uses first oven found)
- No configuration options for poll interval (hardcoded 10s)
- Credentials stored in plain text in config entry (Home Assistant standard)
- No support for oven controls (start/stop/set temperature) - read-only integration
- Timer events rely on polling (every 10s), not real-time WebSocket updates
- Tovala also uses Pusher WebSockets for real-time updates (not implemented yet)

## Real-time Updates (Future Enhancement)

The Tovala app uses Pusher WebSockets for real-time state changes:
- WebSocket: `wss://ws-mt1.pusher.com/app/e0ce4b79beeee326e8d8`
- Channel format: `impPub-{agentid}` (e.g., `impPub-ypaelOLxNwq9`)
- Events: `stateChanged` with payloads like `{"currentState": "ovenConnected", "id": "40000c2a69245398", ...}`

This could be implemented to eliminate polling delay and provide instant updates.
