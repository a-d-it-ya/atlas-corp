"""
ATLAS ADS-B Feed Module
- Fetches live aircraft from OpenSky Network over India FIR
- Caches results, handles rate limiting gracefully
- Falls back to empty list if unavailable
"""

import asyncio
import time
import logging
from typing import Optional

logger = logging.getLogger("atlas.adsb")

# India FIR bounding box
INDIA_BBOX = dict(lamin=6.0, lomin=68.0, lamax=36.0, lomax=98.0)
OPENSKY_URL = "https://opensky-network.org/api/states/all"

# Optional credentials — set OPENSKY_USER / OPENSKY_PASS env vars for higher rate limit
import os
OPENSKY_USER = os.getenv("OPENSKY_USER", "")
OPENSKY_PASS = os.getenv("OPENSKY_PASS", "")

FETCH_INTERVAL   = 30   # seconds between fetches (anonymous rate limit: 10s, we use 30 to be safe)
CACHE_TTL        = 60   # serve cached data for up to 60s before marking stale

class ADSBFeed:
    def __init__(self):
        self._cache: list[dict] = []
        self._last_fetch: float = 0
        self._last_success: float = 0
        self._fetch_count: int = 0
        self._error_count: int = 0
        self._running: bool = False
        self._status: str = "initializing"

    @property
    def status(self) -> str:
        return self._status

    @property 
    def aircraft(self) -> list[dict]:
        return self._cache

    @property
    def last_updated(self) -> float:
        return self._last_success

    @property
    def is_stale(self) -> bool:
        return time.time() - self._last_success > CACHE_TTL

    def _parse_states(self, states: list) -> list[dict]:
        """Convert raw OpenSky state vectors to clean dicts."""
        result = []
        for s in states:
            if s is None or len(s) < 11:
                continue
            # Unpack relevant fields
            icao     = s[0] or ""
            callsign = (s[1] or "").strip() or icao.upper()
            country  = s[2] or "Unknown"
            lon      = s[5]
            lat      = s[6]
            alt_m    = s[7]   # baro altitude in metres
            on_ground= s[8]
            velocity = s[9]   # m/s
            heading  = s[10]  # degrees
            vert_rate= s[11]  # m/s

            # Skip if no position
            if lat is None or lon is None:
                continue
            # Skip ground vehicles
            if on_ground:
                continue

            alt_ft  = int(alt_m * 3.281) if alt_m else 0
            spd_kts = int(velocity * 1.944) if velocity else 0
            hdg     = int(heading) if heading else 0

            # Classify likely type
            is_military = any(pfx in callsign.upper() for pfx in 
                            ['IAF','IND','AFB','RB0','RB1','RB2','RB3','RB4','RB5',
                             'VVIP','HVK','SVC','ARMED'])
            aircraft_type = "military" if is_military else "civil"

            result.append({
                "icao":     icao,
                "callsign": callsign,
                "country":  country,
                "lat":      round(lat, 5),
                "lon":      round(lon, 5),
                "alt_ft":   alt_ft,
                "speed_kts":spd_kts,
                "heading":  hdg,
                "type":     aircraft_type,
                "on_ground":on_ground,
            })
        return result

    async def _fetch_once(self):
        """Fetch one batch from OpenSky."""
        import httpx
        params = dict(**INDIA_BBOX)
        auth = (OPENSKY_USER, OPENSKY_PASS) if OPENSKY_USER else None

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    OPENSKY_URL, params=params,
                    auth=auth,
                    headers={"User-Agent": "ATLAS-OS/1.0 (defense-c2-sim)"}
                )
                if resp.status_code == 429:
                    self._status = "rate_limited"
                    self._error_count += 1
                    logger.warning("[ADS-B] Rate limited by OpenSky")
                    return
                if resp.status_code != 200:
                    self._status = f"error_{resp.status_code}"
                    self._error_count += 1
                    logger.warning(f"[ADS-B] HTTP {resp.status_code}")
                    return

                data = resp.json()
                states = data.get("states") or []
                parsed = self._parse_states(states)
                self._cache = parsed
                self._last_success = time.time()
                self._fetch_count += 1
                self._error_count = 0
                self._status = "live"
                logger.info(f"[ADS-B] {len(parsed)} aircraft over India FIR")

        except httpx.TimeoutException:
            self._status = "timeout"
            self._error_count += 1
            logger.warning("[ADS-B] Fetch timeout")
        except Exception as e:
            self._status = f"error"
            self._error_count += 1
            logger.warning(f"[ADS-B] Fetch error: {e}")

    async def run(self):
        """Background loop — fetch every FETCH_INTERVAL seconds."""
        self._running = True
        logger.info(f"[ADS-B] Feed starting — India FIR bbox, {FETCH_INTERVAL}s interval")
        while self._running:
            self._last_fetch = time.time()
            await self._fetch_once()
            await asyncio.sleep(FETCH_INTERVAL)

    def get_summary(self) -> dict:
        return {
            "status":       self._status,
            "count":        len(self._cache),
            "last_updated": int(self._last_success),
            "fetch_count":  self._fetch_count,
            "error_count":  self._error_count,
            "stale":        self.is_stale,
        }

# Singleton
adsb_feed = ADSBFeed()
