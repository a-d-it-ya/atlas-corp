"""
ATLAS ADS-B Feed Module v1.1
- Primary: OpenSky Network (anonymous)
- Fallback: airplanes.live API
- Falls back gracefully if both unavailable
"""
 
import asyncio
import time
import logging
import os
 
logger = logging.getLogger("atlas.adsb")
 
INDIA_BBOX = dict(lamin=6.0, lomin=68.0, lamax=36.0, lomax=98.0)
 
OPENSKY_URL    = "https://opensky-network.org/api/states/all"
AIRPLANESLIVE_URL = "https://api.airplanes.live/v2/point/20.0/78.0/2000"  # center India, 2000km radius
 
OPENSKY_USER = os.getenv("OPENSKY_USER", "")
OPENSKY_PASS = os.getenv("OPENSKY_PASS", "")
 
FETCH_INTERVAL = 30
CACHE_TTL      = 60
 
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, */*",
    "Accept-Language": "en-US,en;q=0.9",
}
 
class ADSBFeed:
    def __init__(self):
        self._cache: list[dict] = []
        self._last_fetch: float  = 0
        self._last_success: float = 0
        self._fetch_count: int   = 0
        self._error_count: int   = 0
        self._status: str        = "initializing"
        self._source: str        = "none"
 
    @property
    def status(self):   return self._status
    @property
    def aircraft(self): return self._cache
    @property
    def last_updated(self): return self._last_success
    @property
    def is_stale(self): return time.time() - self._last_success > CACHE_TTL
 
    def _parse_opensky(self, states: list) -> list[dict]:
        result = []
        for s in (states or []):
            if not s or len(s) < 11: continue
            icao     = s[0] or ""
            callsign = (s[1] or "").strip() or icao.upper()
            country  = s[2] or "Unknown"
            lon, lat = s[5], s[6]
            alt_m    = s[7]
            on_ground= s[8]
            velocity = s[9]
            heading  = s[10]
            if lat is None or lon is None or on_ground: continue
            is_mil = any(p in callsign.upper() for p in ['IAF','IND','AFB','RB0','RB1','RB2','VVIP','HVK'])
            result.append({
                "icao": icao, "callsign": callsign, "country": country,
                "lat": round(lat,5), "lon": round(lon,5),
                "alt_ft": int(alt_m*3.281) if alt_m else 0,
                "speed_kts": int(velocity*1.944) if velocity else 0,
                "heading": int(heading) if heading else 0,
                "type": "military" if is_mil else "civil",
            })
        return result
 
    def _parse_airplaneslive(self, ac_list: list) -> list[dict]:
        result = []
        for a in (ac_list or []):
            lat = a.get("lat"); lon = a.get("lon")
            if lat is None or lon is None: continue
            # Filter to India bbox
            if not (6 <= lat <= 36 and 68 <= lon <= 98): continue
            callsign = (a.get("flight") or a.get("r") or "").strip()
            is_mil = any(p in callsign.upper() for p in ['IAF','IND','AFB','RB'])
            result.append({
                "icao": a.get("hex",""),
                "callsign": callsign or a.get("hex","???").upper(),
                "country": a.get("cou","Unknown"),
                "lat": round(lat,5), "lon": round(lon,5),
                "alt_ft": a.get("alt_baro", 0) or 0,
                "speed_kts": int(a.get("gs", 0) or 0),
                "heading": int(a.get("track", 0) or 0),
                "type": "military" if is_mil else "civil",
            })
        return result
 
    async def _fetch_opensky(self) -> bool:
        import httpx
        params = dict(**INDIA_BBOX)
        auth   = (OPENSKY_USER, OPENSKY_PASS) if OPENSKY_USER else None
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(OPENSKY_URL, params=params, auth=auth, headers=HEADERS)
                if resp.status_code == 429:
                    self._status = "rate_limited"; return False
                if resp.status_code != 200:
                    self._status = f"opensky_error_{resp.status_code}"; return False
                data   = resp.json()
                parsed = self._parse_opensky(data.get("states",[]))
                self._cache = parsed; self._last_success = time.time()
                self._fetch_count += 1; self._error_count = 0
                self._status = "live_opensky"; self._source = "OpenSky"
                logger.info(f"[ADS-B] OpenSky: {len(parsed)} aircraft over India")
                return True
        except Exception as e:
            logger.warning(f"[ADS-B] OpenSky failed: {e}"); return False
 
    async def _fetch_airplaneslive(self) -> bool:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(AIRPLANESLIVE_URL, headers=HEADERS)
                if resp.status_code != 200:
                    self._status = f"al_error_{resp.status_code}"; return False
                data   = resp.json()
                ac     = data.get("ac") or data.get("aircraft") or []
                parsed = self._parse_airplaneslive(ac)
                self._cache = parsed; self._last_success = time.time()
                self._fetch_count += 1; self._error_count = 0
                self._status = "live_airplaneslive"; self._source = "airplanes.live"
                logger.info(f"[ADS-B] airplanes.live: {len(parsed)} aircraft over India")
                return True
        except Exception as e:
            logger.warning(f"[ADS-B] airplanes.live failed: {e}"); return False
 
    async def _fetch_once(self):
        # Try OpenSky first, fall back to airplanes.live
        if await self._fetch_opensky(): return
        logger.info("[ADS-B] OpenSky unavailable, trying airplanes.live...")
        if await self._fetch_airplaneslive(): return
        self._status  = "unavailable"
        self._error_count += 1
        logger.warning("[ADS-B] All sources unavailable")
 
    async def run(self):
        logger.info(f"[ADS-B] Feed starting — India FIR, {FETCH_INTERVAL}s interval")
        while True:
            self._last_fetch = time.time()
            await self._fetch_once()
            await asyncio.sleep(FETCH_INTERVAL)
 
    def get_summary(self) -> dict:
        return {
            "status":       self._status,
            "source":       self._source,
            "count":        len(self._cache),
            "last_updated": int(self._last_success),
            "fetch_count":  self._fetch_count,
            "error_count":  self._error_count,
            "stale":        self.is_stale,
        }
 
adsb_feed = ADSBFeed()