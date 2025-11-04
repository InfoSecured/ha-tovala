# custom_components/tovala/api.py
from __future__ import annotations
from typing import Any, Dict, List, Optional, Sequence
from aiohttp import ClientSession, ClientError, ClientTimeout
import time
import logging

_LOGGER = logging.getLogger(__name__)

# Prefer beta, fall back to prod if needed
DEFAULT_BASES: Sequence[str] = (
    "https://api.beta.tovala.com",
    "https://api.tovala.com",
)

LOGIN_PATH = "/v0/getToken"

class TovalaAuthError(Exception):
    """Authentication failed (bad credentials or denied)."""

class TovalaApiError(Exception):
    """Other API/HTTP failures."""

class TovalaClient:
    def __init__(
        self,
        session: ClientSession,
        email: Optional[str] = None,
        password: Optional[str] = None,
        token: Optional[str] = None,
        api_bases: Optional[Sequence[str]] = None,
    ):
        self._session = session
        self._email = email
        self._password = password
        self._token = token
        self._token_exp = 0
        self._bases: Sequence[str] = api_bases or DEFAULT_BASES
        self._base: Optional[str] = None  # set on successful login

    @property
    def base_url(self) -> Optional[str]:
        return self._base

    async def login(self) -> None:
        """Ensure we have a valid bearer token. Tries beta then prod."""
        if self._token and self._token_exp > time.time() + 60:
            _LOGGER.debug("Token still valid, skipping login")
            return
        if not (self._token or (self._email and self._password)):
            raise TovalaAuthError("Missing credentials")

        # If we already have a token but exp unknown, assume 1 hour left
        if self._token and not self._token_exp:
            self._token_exp = int(time.time()) + 3600
            self._base = self._bases[0]
            _LOGGER.debug("Using provided token with assumed expiry")
            return

        if self._token:
            # Token supplied by options: we don't yet know the right base.
            self._base = self._bases[0]
            _LOGGER.debug("Using provided token with base: %s", self._base)
            return

        # CRITICAL: X-Tovala-AppID header is required!
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "HomeAssistant-Tovala/0.1",
            "Origin": "https://my.tovala.com",
            "Referer": "https://my.tovala.com/",
            "X-Tovala-AppID": "MyTovala",
        }

        last_err: Optional[Exception] = None
        for base in self._bases:
            url = f"{base}{LOGIN_PATH}"
            _LOGGER.debug("Attempting login to %s", url)
            
            try:
                timeout = ClientTimeout(total=10)
                async with self._session.post(
                    url,
                    headers=headers,
                    json={"email": self._email, "password": self._password, "type": "user"},
                    timeout=timeout,
                ) as r:
                    txt = await r.text()
                    _LOGGER.debug("Login response from %s: status=%s, body=%s", base, r.status, txt[:200])
                    
                    if r.status == 429:
                        # Rate limited - stop immediately
                        _LOGGER.error("Rate limited by Tovala API: %s", txt)
                        raise TovalaApiError(f"Rate limited (HTTP 429): {txt}")
                    
                    if r.status in (401, 403):
                        # Stop immediately on explicit auth failure
                        _LOGGER.error("Authentication failed: HTTP %s - %s", r.status, txt)
                        raise TovalaAuthError(f"Invalid auth (HTTP {r.status}): {txt}")
                    
                    if r.status >= 400:
                        last_err = TovalaApiError(f"Login failed (HTTP {r.status}): {txt}")
                        _LOGGER.warning("Login failed for %s: %s", base, last_err)
                        continue
                    
                    data = await r.json()
                    _LOGGER.debug("Login JSON response keys: %s", list(data.keys()))

                # Support both 'token' and 'accessToken' response formats
                token = data.get("token") or data.get("accessToken") or data.get("jwt")
                if not token:
                    last_err = TovalaAuthError("No token returned from getToken")
                    _LOGGER.warning("No token in response from %s", base)
                    continue

                self._token = token
                self._token_exp = int(time.time()) + int(data.get("expiresIn", 3600))
                self._base = base
                _LOGGER.info("Successfully logged in to %s", base)
                return
                
            except TovalaAuthError:
                # Do not try other bases if credentials are wrong
                raise
            except TovalaApiError:
                # Also stop on rate limits
                raise
            except ClientError as e:
                last_err = e
                _LOGGER.error("Connection error for %s: %s", base, str(e))
                # Try next base
            except Exception as e:
                last_err = e
                _LOGGER.error("Unexpected error for %s: %s", base, str(e), exc_info=True)
                # Try next base

        # If we reach here, all bases failed
        _LOGGER.error("All login attempts failed. Last error: %s", last_err)
        if isinstance(last_err, Exception):
            raise TovalaApiError(f"Connection failed: {str(last_err)}")
        raise TovalaApiError("Login failed")

    async def _auth_headers(self) -> Dict[str, str]:
        await self.login()
        return {
            "Authorization": f"Bearer {self._token}",
            "X-Tovala-AppID": "MyTovala",
        }

    async def _get_json(self, path: str, **fmt) -> Any:
        if not self._base:
            # Ensure login determined the base URL
            await self.login()
        assert self._base, "Base URL not set after login"
        headers = await self._auth_headers()
        url = f"{self._base}{path.format(**fmt)}"
        _LOGGER.debug("GET %s", url)
        
        try:
            timeout = ClientTimeout(total=10)
            async with self._session.get(url, headers=headers, timeout=timeout) as r:
                txt = await r.text()
                _LOGGER.debug("GET %s -> %s, body=%s", url, r.status, txt[:200])
                
                if r.status == 404:
                    raise TovalaApiError("not_found")
                if r.status >= 400:
                    raise TovalaApiError(f"HTTP {r.status}: {txt}")
                try:
                    return await r.json()
                except Exception:
                    # Some endpoints may return empty body
                    return {}
        except ClientError as e:
            _LOGGER.error("Connection error for %s: %s", url, str(e))
            raise TovalaApiError(f"Connection failed: {str(e)}")

    # ---- Stubs until we confirm the read endpoints from the app traffic ----
    OVENS_LIST_CANDIDATES: Sequence[str] = (
        "/v0/ovens",
        "/v0/devices/ovens",
        "/v0/user/ovens",
        "/v0/devices",  # Added - might return all devices including ovens
    )
    
    OVEN_STATUS_CANDIDATES: Sequence[str] = (
        "/v0/ovens/{oven_id}/status",
        "/v0/ovens/{oven_id}",
        "/v0/devices/ovens/{oven_id}/status",
        "/v0/devices/{oven_id}/status",
        "/v0/devices/{oven_id}",
    )

    async def list_ovens(self) -> List[Dict[str, Any]]:
        """Try a few candidate endpoints to find user's ovens."""
        _LOGGER.debug("Attempting to list ovens")
        
        for path in self.OVENS_LIST_CANDIDATES:
            try:
                data = await self._get_json(path)
                _LOGGER.debug("Ovens endpoint %s returned: %s", path, data)
                
                if isinstance(data, dict) and "ovens" in data:
                    data = data["ovens"]
                if isinstance(data, list):
                    _LOGGER.info("Found %d ovens using endpoint %s", len(data), path)
                    return data
            except TovalaApiError as e:
                if str(e) == "not_found":
                    _LOGGER.debug("Endpoint %s not found, trying next", path)
                    continue
                _LOGGER.warning("Error fetching from %s: %s", path, e)
                continue
            except Exception as e:
                _LOGGER.warning("Unexpected error for %s: %s", path, e)
                continue
                
        raise TovalaApiError("Could not find an ovens endpoint in v0 API")

    async def oven_status(self, oven_id: str) -> Dict[str, Any]:
        """Try a few candidate endpoints to fetch oven status."""
        if not oven_id:
            _LOGGER.warning("oven_status called with empty oven_id")
            return {}
            
        _LOGGER.debug("Fetching status for oven %s", oven_id)
        
        for path in self.OVEN_STATUS_CANDIDATES:
            try:
                data = await self._get_json(path, oven_id=oven_id)
                _LOGGER.debug("Status endpoint %s returned: %s", path, data)
                return data
            except TovalaApiError as e:
                if str(e) == "not_found":
                    _LOGGER.debug("Endpoint %s not found, trying next", path)
                    continue
                _LOGGER.warning("Error fetching from %s: %s", path, e)
                continue
            except Exception as e:
                _LOGGER.warning("Unexpected error for %s: %s", path, e)
                continue
                
        raise TovalaApiError("Could not read oven status from any known endpoint")