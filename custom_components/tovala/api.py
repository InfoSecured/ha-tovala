# custom_components/tovala/api.py
from __future__ import annotations
from typing import Any, Dict, List, Optional
from aiohttp import ClientSession
import time

BASE = "https://api.beta.tovala.com"
LOGIN_PATH = "/v0/getToken"

# Candidates observed/typical in v0 APIs; we probe until one works.
OVENS_LIST_CANDIDATES = [
    "/v0/ovens",          # returns [{id,name,...}]
    "/v0/devices/ovens",  # alt naming
    "/v0/user/ovens",     # user-scoped
]
OVEN_STATUS_CANDIDATES = [
    "/v0/ovens/{oven_id}/status",
    "/v0/ovens/{oven_id}",          # sometimes status is in the base object
    "/v0/devices/ovens/{oven_id}/status",
]

class TovalaAuthError(Exception): ...
class TovalaApiError(Exception): ...

class TovalaClient:
    def __init__(self, session: ClientSession, email: Optional[str] = None, password: Optional[str] = None, token: Optional[str] = None):
        self._session = session
        self._email = email
        self._password = password
        self._token = token
        self._token_exp = 0

    async def login(self) -> None:
        # if we already have a fresh token, skip
        if self._token and self._token_exp > time.time() + 60:
            return
        if not (self._token or (self._email and self._password)):
            raise TovalaAuthError("Missing credentials")

        # If no token, exchange email/password for one.
        if not self._token:
            async with self._session.post(
                f"{BASE}{LOGIN_PATH}",
                json={"email": self._email, "password": self._password, "type": "user"},
            ) as r:
                if r.status >= 400:
                    txt = await r.text()
                    raise TovalaAuthError(f"Login HTTP {r.status}: {txt}")
                data = await r.json()

            # Common names: token | accessToken | jwt
            self._token = data.get("token") or data.get("accessToken") or data.get("jwt")
            # Some APIs return expiresIn (seconds); fall back to 1 hour
            self._token_exp = int(time.time()) + int(data.get("expiresIn", 3600))

        if not self._token:
            raise TovalaAuthError("No token returned from getToken")

    async def _auth_headers(self) -> Dict[str, str]:
        await self.login()
        return {"Authorization": f"Bearer {self._token}"}

    async def _get_json(self, path: str, **fmt) -> Any:
        headers = await self._auth_headers()
        url = f"{BASE}{path.format(**fmt)}"
        async with self._session.get(url, headers=headers) as r:
            if r.status == 404:
                raise TovalaApiError("not_found")
            if r.status >= 400:
                txt = await r.text()
                raise TovalaApiError(f"HTTP {r.status}: {txt}")
            return await r.json()

    async def list_ovens(self) -> List[Dict[str, Any]]:
        # Probe candidates until one returns a list
        for path in OVENS_LIST_CANDIDATES:
            try:
                data = await self._get_json(path)
                if isinstance(data, dict) and "ovens" in data:
                    data = data["ovens"]
                if isinstance(data, list) and data:
                    return data
            except TovalaApiError as e:
                if str(e) != "not_found":
                    continue
            except Exception:
                continue
        # If nothing worked:
        raise TovalaApiError("Could not find an ovens endpoint in v0 API")

    async def oven_status(self, oven_id: str) -> Dict[str, Any]:
        for path in OVEN_STATUS_CANDIDATES:
            try:
                data = await self._get_json(path, oven_id=oven_id)
                return data
            except TovalaApiError as e:
                if str(e) != "not_found":
                    continue
            except Exception:
                continue
        raise TovalaApiError("Could not read oven status from any known endpoint")