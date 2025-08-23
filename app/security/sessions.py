# app/security/sessions.py
import secrets
import time
from typing import Optional, Dict, Any

_SESSION_DATA: dict[str, dict] = {}  

class MemorySessions:
    def __init__(self, ttl_seconds: int = 7 * 24 * 3600):
        self.ttl = ttl_seconds

    def create(self, payload: Dict[str, Any]) -> str:
        sid = secrets.token_urlsafe(32)
        _SESSION_DATA[sid] = {"payload": payload, "exp": time.time() + self.ttl}
        return sid

    def get(self, sid: str) -> Optional[Dict[str, Any]]:
        s = _SESSION_DATA.get(sid)
        if not s:
            return None
        if s["exp"] < time.time():
            _SESSION_DATA.pop(sid, None)
            return None
        return s["payload"]

    def delete(self, sid: str) -> None:
        _SESSION_DATA.pop(sid, None)

    def touch(self, sid: str) -> None:
        s = _SESSION_DATA.get(sid)
        if s:
            s["exp"] = time.time() + self.ttl
