# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **Home Assistant Custom Integration** (HACS-installable) that connects to Tovala Smart Ovens via their undocumented cloud API. It polls oven status, exposes sensors for remaining cook time, and fires Home Assistant events when timers complete.

**Key constraints:**
- Tovala has no public API; this integration reverse-engineers their web app's HTTPS endpoints
- The integration tries both `api.beta.tovala.com` and `api.tovala.com` automatically
- Authentication requires specific headers including `X-Tovala-AppID: MyTovala`

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
- Implements endpoint discovery for ovens list and status (multiple candidate paths tried)
- Rate limit detection (HTTP 429) stops login attempts immediately
- Token expiry tracking with automatic re-authentication
- **Critical:** All requests must include `X-Tovala-AppID: MyTovala` header

**coordinator.py (`TovalaCoordinator`):**
- Extends Home Assistant's `DataUpdateCoordinator`
- Polls oven status every 10 seconds (configurable via `DEFAULT_SCAN_INTERVAL`)
- Detects timer completion (remaining time crossing from >0 to 0)
- Fires `tovala_timer_finished` event with `{oven_id, data}` payload
- Handles missing oven_id gracefully (returns empty dict)

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

### API Discovery Pattern

Both `list_ovens()` and `oven_status()` try multiple endpoint candidates:
- `/v0/ovens`, `/v0/devices/ovens`, `/v0/user/ovens`, `/v0/devices` (ovens list)
- `/v0/ovens/{id}/status`, `/v0/ovens/{id}`, `/v0/devices/{id}/status`, etc. (status)

This approach handles API changes without requiring integration updates.

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
  -H "X-Tovala-AppID: MyTovala" \
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
- Authentication: edit `TovalaClient.login()` in api.py:45
- Endpoint discovery: add paths to `OVENS_LIST_CANDIDATES` or `OVEN_STATUS_CANDIDATES` in api.py:180-193
- Poll interval: change `DEFAULT_SCAN_INTERVAL` in const.py:9

**Updating version:**
1. Edit `manifest.json` version field
2. Commit changes
3. Tag with `git tag vX.Y.Z && git push --tags`
4. HACS detects new releases automatically

## API Response Expectations

**Token response** (getToken):
```json
{"token": "...", "expiresIn": 3600}
// or: {"accessToken": "...", "expiresIn": 3600}
// or: {"jwt": "...", "expiresIn": 3600}
```

**Oven status response** (expected fields):
```json
{
  "remaining": 123,        // or "time_remaining"
  "state": "cooking",      // or "idle"
  "mode": "air_fry",       // cooking mode
  // other fields TBD
}
```

## Known Issues & Limitations

- No oven selection UI yet (uses first oven found)
- Endpoint paths are guesses based on common REST patterns (discovery mitigates this)
- No configuration options for poll interval (hardcoded 10s)
- Credentials stored in plain text in config entry (Home Assistant standard)
- No support for oven controls (start/stop/set temperature) - read-only integration
