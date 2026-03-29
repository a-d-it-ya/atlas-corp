"""
ATLAS Naval Simulator v1.0
Python port of the JS navySimTick — runs server-side for multi-user sync.
All 20 INS assets: carriers, destroyers, frigates, submarines, UUVs, MPAs.
"""

import asyncio
import math
import random
import time
from copy import deepcopy
from typing import Callable, Optional

# ── Constants ─────────────────────────────────────────────────────────────────

NAVAL_BASES = {
    "ports": [
        {"id":"PORT-MUM","name":"Mumbai",        "lat":18.922,"lon":72.834,"type":"port",   "command":"Western"},
        {"id":"PORT-VZG","name":"Visakhapatnam", "lat":17.686,"lon":83.218,"type":"port",   "command":"Eastern"},
        {"id":"PORT-KOC","name":"Kochi",          "lat": 9.964,"lon":76.243,"type":"port",   "command":"Southern"},
        {"id":"PORT-KAR","name":"Karwar",         "lat":14.812,"lon":74.124,"type":"port",   "command":"Western"},
        {"id":"PORT-PBL","name":"Port Blair",     "lat":11.623,"lon":92.726,"type":"port",   "command":"Andaman"},
        {"id":"PORT-CHN","name":"Chennai",        "lat":13.083,"lon":80.270,"type":"port",   "command":"Eastern"},
    ],
    "airbases": [
        {"id":"AB-HANSA","name":"INS Hansa",  "lat":15.388,"lon":73.813,"type":"airbase","command":"Western"},
        {"id":"AB-RAJ",  "name":"INS Rajali", "lat":13.058,"lon":79.893,"type":"airbase","command":"Southern"},
        {"id":"AB-DEGA", "name":"INS Dega",   "lat":17.720,"lon":83.220,"type":"airbase","command":"Eastern"},
        {"id":"AB-BAAZ", "name":"INS Baaz",   "lat":13.105,"lon":92.730,"type":"airbase","command":"Andaman"},
    ],
    "subpens": [
        {"id":"SP-VZG","name":"Vizag Sub Base","lat":17.700,"lon":83.280,"type":"subpen","command":"Eastern"},
        {"id":"SP-KAR","name":"Karwar Sub Pen","lat":14.830,"lon":74.110,"type":"subpen","command":"Western"},
        {"id":"SP-MUM","name":"Mumbai Sub Pen","lat":18.940,"lon":72.850,"type":"subpen","command":"Western"},
    ],
}

ALL_BASES = (NAVAL_BASES["ports"] + NAVAL_BASES["airbases"] + NAVAL_BASES["subpens"])

HOME_BASE = {
    "INS-VKT":"PORT-VZG","INS-VKD":"PORT-MUM",
    "INS-D66":"PORT-VZG","INS-D67":"PORT-MUM","INS-D65":"PORT-VZG",
    "INS-F47":"PORT-MUM","INS-F48":"PORT-VZG","INS-F40":"PORT-KAR","INS-F43":"PORT-KAR",
    "INS-S2": "SP-VZG",  "INS-S73":"SP-VZG",  "INS-S50":"SP-KAR",
    "INS-S51":"SP-VZG",  "INS-SK": "SP-MUM",
    "INS-UUV1":"PORT-VZG","INS-UUV2":"PORT-MUM","INS-UUV3":"PORT-KOC","INS-UUV4":"PORT-VZG",
    "INS-P8A":"AB-DEGA", "INS-P8B":"AB-HANSA",
}

NAVAL_THREATS = {
    "acoustic":[
        {"msg":"Broadband noise contact. Bearing 047°. Possible diesel-electric submarine.","cls":"SUBSURFACE CONTACT"},
        {"msg":"Cavitation signature detected. High-speed surface vessel. Non-cooperative.","cls":"SURFACE CONTACT"},
        {"msg":"Low-frequency tonal detected. Probable warship propulsion signature.","cls":"SURFACE CONTACT"},
    ],
    "sonar":[
        {"msg":"Passive sonar anomaly. Depth ~120m. Contact tracking initiated.","cls":"SONAR ANOMALY"},
        {"msg":"Magnetic anomaly detected. Possible submerged metallic object.","cls":"SUBSURFACE CONTACT"},
        {"msg":"Hull-mounted sonar ping return — uncharted contact bearing 220°.","cls":"SONAR ANOMALY"},
    ],
    "ais":[
        {"msg":"AIS signal lost — vessel was tracking 8.2 knots on bearing 315°. Contact: dark.","cls":"UNKNOWN VESSEL"},
        {"msg":"Unidentified vessel transiting EEZ without AIS. Size estimate: 180m.","cls":"UNKNOWN VESSEL"},
        {"msg":"Fast-moving unlit surface contact. Speed 35 knots. Intercept course.","cls":"SURFACE CONTACT"},
    ],
    "aerial":[
        {"msg":"Unidentified aerial contact. Altitude 800m. Radar cross-section: small UAV.","cls":"AERIAL CONTACT"},
        {"msg":"Maritime patrol aircraft — non-cooperative IFF. Entering sensor range.","cls":"AERIAL CONTACT"},
    ],
}

SENSOR_NODES = [
    {"id":"SOSUS-01","name":"SOSUS Node Alpha","lat":10.0,"lon":80.0,"type":"acoustic","radius":150},
    {"id":"SOSUS-02","name":"SOSUS Node Bravo","lat":14.5,"lon":71.0,"type":"sonar",   "radius":120},
    {"id":"SOSUS-03","name":"SOSUS Node Charlie","lat":6.0,"lon":77.0,"type":"acoustic","radius":180},
    {"id":"SOSUS-04","name":"AIS Station Delta","lat":8.5,"lon":76.5,"type":"ais",     "radius":200},
    {"id":"SOSUS-05","name":"Radar Post Echo", "lat":13.0,"lon":74.0,"type":"aerial",  "radius":250},
]

def _dist_km(lat1, lon1, lat2, lon2):
    dlat = (lat2 - lat1) * 111.32
    dlon = (lon2 - lon1) * 111.32 * math.cos(math.radians(lat1))
    return math.hypot(dlat, dlon)

def _bearing(lat1, lon1, lat2, lon2):
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    return (math.degrees(math.atan2(dlon, dlat)) + 360) % 360

# ── Initial state ─────────────────────────────────────────────────────────────

def _make_units():
    return [
        {"id":"INS-VKT","name":"INS Vikrant","pennant":"R11","type":"carrier","sub":"Fleet Carrier · Eastern Command",
         "lat":10.5,"lon":83.5,"heading":275,"speed":18,"fuel":82,"depth":0,"status":"patrol",
         "waypoints":[[10.5,83.5],[11.0,84.2],[11.5,84.8],[11.0,84.0]],"wp_idx":0,"looping":True},
        {"id":"INS-VKD","name":"INS Vikramaditya","pennant":"R33","type":"carrier","sub":"Fleet Carrier · Western Command",
         "lat":14.2,"lon":71.5,"heading":90,"speed":16,"fuel":75,"depth":0,"status":"patrol",
         "waypoints":[[14.2,71.5],[14.0,72.3],[13.6,73.1],[13.9,72.5]],"wp_idx":0,"looping":True},
        {"id":"INS-D66","name":"INS Visakhapatnam","pennant":"D66","type":"destroyer","sub":"Kolkata-class DDG · Eastern Fleet",
         "lat":11.2,"lon":82.5,"heading":220,"speed":24,"fuel":68,"depth":0,"status":"patrol",
         "waypoints":[[11.2,82.5],[10.8,82.8],[10.4,83.2],[10.9,83.0]],"wp_idx":0,"looping":True},
        {"id":"INS-D67","name":"INS Mormugao","pennant":"D67","type":"destroyer","sub":"Kolkata-class DDG · Western Fleet",
         "lat":15.1,"lon":70.8,"heading":135,"speed":22,"fuel":71,"depth":0,"status":"patrol",
         "waypoints":[[15.1,70.8],[14.6,71.4],[14.2,70.9],[14.7,70.3]],"wp_idx":0,"looping":True},
        {"id":"INS-D65","name":"INS Chennai","pennant":"D65","type":"destroyer","sub":"Kolkata-class DDG · Eastern Fleet",
         "lat":8.5,"lon":83.0,"heading":310,"speed":20,"fuel":90,"depth":0,"status":"patrol",
         "waypoints":[[8.5,83.0],[8.0,83.8],[7.5,84.5],[8.0,83.8]],"wp_idx":0,"looping":True},
        {"id":"INS-F47","name":"INS Shivalik","pennant":"F47","type":"frigate","sub":"Shivalik-class Frigate · Western Fleet",
         "lat":16.2,"lon":72.1,"heading":180,"speed":19,"fuel":55,"depth":0,"status":"patrol",
         "waypoints":[[16.2,72.1],[15.8,72.5],[15.4,72.0],[15.8,71.6]],"wp_idx":0,"looping":True},
        {"id":"INS-F48","name":"INS Satpura","pennant":"F48","type":"frigate","sub":"Shivalik-class Frigate · Eastern Fleet",
         "lat":12.5,"lon":83.1,"heading":45,"speed":17,"fuel":63,"depth":0,"status":"patrol",
         "waypoints":[[12.5,83.1],[12.9,83.5],[13.2,83.0],[12.8,82.6]],"wp_idx":0,"looping":True},
        {"id":"INS-F40","name":"INS Talwar","pennant":"F40","type":"frigate","sub":"Talwar-class Frigate · Western Fleet",
         "lat":17.0,"lon":70.2,"heading":270,"speed":21,"fuel":44,"depth":0,"status":"patrol",
         "waypoints":[[17.0,70.2],[16.6,70.8],[16.2,70.3],[16.6,69.8]],"wp_idx":0,"looping":True},
        {"id":"INS-F43","name":"INS Trishul","pennant":"F43","type":"frigate","sub":"Talwar-class Frigate · Western Fleet",
         "lat":13.8,"lon":70.5,"heading":90,"speed":18,"fuel":77,"depth":0,"status":"patrol",
         "waypoints":[[13.8,70.5],[14.0,71.2],[14.2,71.9],[14.0,71.1]],"wp_idx":0,"looping":True},
        {"id":"INS-S2","name":"INS Arihant","pennant":"S2","type":"sub","sub":"Arihant-class SSBN · Strategic Patrol",
         "lat":8.2,"lon":79.5,"heading":180,"speed":12,"fuel":95,"depth":180,"status":"submerged",
         "waypoints":[[8.2,79.5],[7.8,80.1],[7.4,79.8],[7.8,79.2]],"wp_idx":0,"looping":True},
        {"id":"INS-S73","name":"INS Chakra","pennant":"S73","type":"sub","sub":"Akula-class SSN · Attack Patrol",
         "lat":6.5,"lon":76.2,"heading":90,"speed":15,"fuel":88,"depth":240,"status":"submerged",
         "waypoints":[[6.5,76.2],[6.8,77.0],[7.1,77.8],[6.8,77.0]],"wp_idx":0,"looping":True},
        {"id":"INS-S50","name":"INS Kalvari","pennant":"S50","type":"sub","sub":"Scorpène-class SSK · Western Patrol",
         "lat":15.5,"lon":68.8,"heading":315,"speed":8,"fuel":62,"depth":120,"status":"submerged",
         "waypoints":[[15.5,68.8],[15.8,68.2],[16.1,67.6],[15.8,68.2]],"wp_idx":0,"looping":True},
        {"id":"INS-S51","name":"INS Khanderi","pennant":"S51","type":"sub","sub":"Scorpène-class SSK · Eastern Patrol",
         "lat":11.8,"lon":84.5,"heading":45,"speed":9,"fuel":71,"depth":150,"status":"submerged",
         "waypoints":[[11.8,84.5],[12.1,85.0],[12.4,85.5],[12.1,85.0]],"wp_idx":0,"looping":True},
        {"id":"INS-SK","name":"INS Sindhurakshak","pennant":"SK","type":"sub","sub":"Kilo-class SSK · Indian Ocean Patrol",
         "lat":4.2,"lon":73.8,"heading":270,"speed":7,"fuel":75,"depth":200,"status":"submerged",
         "waypoints":[[4.2,73.8],[4.0,73.0],[3.8,72.2],[4.0,73.0]],"wp_idx":0,"looping":True},
        {"id":"INS-UUV1","name":"NEMO-01","pennant":"UUV1","type":"uuv","sub":"Autonomous UUV · Eastern",
         "lat":9.5,"lon":82.5,"heading":180,"speed":4,"fuel":78,"depth":45,"status":"deployed",
         "waypoints":[[9.5,82.5],[9.2,83.0],[8.9,82.5],[9.2,82.0]],"wp_idx":0,"looping":True},
        {"id":"INS-UUV2","name":"NEMO-02","pennant":"UUV2","type":"uuv","sub":"Autonomous UUV · Western",
         "lat":14.8,"lon":70.0,"heading":90,"speed":4,"fuel":65,"depth":60,"status":"deployed",
         "waypoints":[[14.8,70.0],[14.9,70.6],[15.0,71.2],[14.9,70.6]],"wp_idx":0,"looping":True},
        {"id":"INS-UUV3","name":"NEMO-03","pennant":"UUV3","type":"uuv","sub":"Autonomous UUV · Southern",
         "lat":5.0,"lon":76.0,"heading":270,"speed":3,"fuel":88,"depth":80,"status":"deployed",
         "waypoints":[[5.0,76.0],[4.8,75.2],[4.6,74.4],[4.8,75.2]],"wp_idx":0,"looping":True},
        {"id":"INS-UUV4","name":"NEMO-04","pennant":"UUV4","type":"uuv","sub":"Autonomous UUV · Strait",
         "lat":6.0,"lon":80.2,"heading":135,"speed":3,"fuel":72,"depth":55,"status":"deployed",
         "waypoints":[[6.0,80.2],[5.7,80.7],[5.4,81.2],[5.7,80.7]],"wp_idx":0,"looping":True},
        {"id":"INS-P8A","name":"IN P-8I Poseidon Alpha","pennant":"P8A","type":"mpa","sub":"P-8I Neptune · Eastern Patrol",
         "lat":13.0,"lon":82.0,"heading":315,"speed":200,"fuel":70,"depth":0,"status":"patrol",
         "waypoints":[[13.0,82.0],[14.0,81.0],[15.0,80.0],[14.0,81.0]],"wp_idx":0,"looping":True},
        {"id":"INS-P8B","name":"IN P-8I Poseidon Bravo","pennant":"P8B","type":"mpa","sub":"P-8I Neptune · Western Patrol",
         "lat":16.0,"lon":71.0,"heading":225,"speed":190,"fuel":60,"depth":0,"status":"patrol",
         "waypoints":[[16.0,71.0],[15.0,72.5],[14.0,74.0],[15.0,72.5]],"wp_idx":0,"looping":True},
    ]

# ── Simulator class ───────────────────────────────────────────────────────────

class NavalSimulator:
    def __init__(self, on_log: Callable[[str,str,str], None],
                       on_threat: Optional[Callable[[dict], None]] = None):
        self.units = _make_units()
        self.on_log = on_log        # on_log(unit_name, message, level)
        self.on_threat = on_threat  # on_threat(threat_dict)
        self._last_threat = 0
        self._running = False

    # ── Physics tick ──────────────────────────────────────────────────────────

    def tick(self):
        for u in self.units:
            self._tick_unit(u)
        # Maybe generate a threat
        if time.time() - self._last_threat > 90 and random.random() < 0.015:
            self._generate_threat()

    def _tick_unit(self, u: dict):
        uid   = u["id"]
        utype = u["type"]

        # UUV carrier tracking
        if u.get("_trackCarrierId"):
            carrier = next((c for c in self.units if c["id"] == u["_trackCarrierId"]), None)
            if carrier:
                if carrier["status"] not in ("moored","grounded","recovered"):
                    u["waypoints"] = [[carrier["lat"], carrier["lon"]]]
                    u["wp_idx"] = 0
                else:
                    u["waypoints"] = [[carrier["lat"], carrier["lon"]]]
                    u.pop("_trackCarrierId", None)

        # Refuel while at base (even moored)
        if u["fuel"] < 99.5:
            valid = (["airbase"] if utype=="mpa" else
                     ["subpen","port"] if utype=="sub" else
                     ["port","subpen"])
            near = next((b for b in ALL_BASES
                         if b["type"] in valid and
                         _dist_km(b["lat"],b["lon"],u["lat"],u["lon"]) < 22), None)
            if near:
                rate     = 0.15 if utype=="mpa" else 0.04
                fuel_dt  = 120  if utype=="mpa" else 180
                u["fuel"] = min(100.0, u["fuel"] + rate * fuel_dt * 0.01)
                if u["fuel"] >= 99.5:
                    u["fuel"] = 100.0
                    u.pop("_lowFuelWarned", None)
                    u.pop("_critFuelWarned", None)
                    self.on_log(u["name"], "Refueling complete — 100%. Ready for deployment.", "ok")

        # Skip movement for docked units
        if u["status"] in ("moored","grounded","recovered"):
            u["speed"] = 0
            return

        wps = u.get("waypoints", [])
        if not wps:
            return

        wp_idx = u.get("wp_idx", 0) % len(wps)
        target = wps[wp_idx]
        dist   = _dist_km(u["lat"], u["lon"], target[0], target[1])

        # Adaptive dt
        if utype == "mpa":
            dt = 120.0
        elif dist > 400:
            dt = 1800.0
        elif dist > 100:
            dt = 600.0
        else:
            dt = 180.0

        speed_kmh  = u["speed"] * 1.852
        step_km    = speed_kmh * dt / 3600.0
        arr_thresh = max(0.5, step_km * 1.2)

        if dist < arr_thresh:
            next_idx = wp_idx + 1
            if next_idx >= len(wps):
                if u.get("looping", True):
                    u["wp_idx"] = 0
                else:
                    # RTB — arrival
                    if utype == "mpa" and u["status"] != "grounded":
                        u["speed"] = 0; u["targetSpeed"] = 0; u["status"] = "grounded"
                        self.on_log(u["name"], "Landed at base. Engines shutdown.", "ok")
                    elif utype == "sub" and u["status"] != "moored":
                        u["targetSpeed"] = 0; u["targetDepth"] = 0; u["status"] = "moored"
                        self.on_log(u["name"], f"({u['pennant']}) Moored at sub pen. All stop.", "ok")
                    elif utype in ("carrier","destroyer","frigate") and u["status"] != "moored":
                        u["targetSpeed"] = 0; u["status"] = "moored"
                        self.on_log(u["name"], f"({u['pennant']}) Alongside at port. Mooring complete.", "ok")
                    elif utype == "uuv" and u["status"] != "recovered":
                        u["targetSpeed"] = 0; u["targetDepth"] = 5; u["status"] = "recovered"
                        u.pop("_trackCarrierId", None)
                        self.on_log(u["name"], "Recovered to carrier. Charging.", "ok")
            else:
                u["wp_idx"] = next_idx
        else:
            # Move toward target
            bearing_rad = math.atan2(target[1]-u["lon"], target[0]-u["lat"])
            desired_hdg = math.degrees(bearing_rad) % 360
            err         = ((desired_hdg - u["heading"] + 180) % 360) - 180
            max_turn    = 15 if utype=="mpa" else 12 if utype=="uuv" else 8 if utype=="sub" else 6
            u["heading"] = (u["heading"] + max(-max_turn, min(max_turn, err*0.9)) + 360) % 360

            if dist < step_km * 3:
                move_km = min(step_km, dist)
                u["lat"] += move_km * math.cos(bearing_rad) / 111.32
                u["lon"] += move_km * math.sin(bearing_rad) / (111.32 * math.cos(math.radians(u["lat"])))
            else:
                hdg_rad = math.radians(u["heading"])
                u["lat"] += step_km * math.cos(hdg_rad) / 111.32
                u["lon"] += step_km * math.sin(hdg_rad) / (111.32 * math.cos(math.radians(u["lat"])))

        # Fuel drain
        fuel_dt_f  = 120 if utype=="mpa" else 180
        base_drain = (0.00000185 if utype=="sub" else
                      0.00000116 if utype=="uuv" else
                      0.00000694 if utype=="mpa" else
                      0.00000162 if utype=="carrier" else
                      0.00000231)
        spd_factor = (0.3 + 0.7*(u["speed"]/30)) if u["speed"] > 0 else 0.05
        u["fuel"]  = max(0.0, u["fuel"] - base_drain * fuel_dt_f * spd_factor * 100)

        # Low fuel warnings
        if u["fuel"] <= 20 and not u.get("_lowFuelWarned"):
            u["_lowFuelWarned"] = True
            self.on_log(u["name"], f"⚠ LOW FUEL: {round(u['fuel'])}%. RTB recommended.", "warn")
        if u["fuel"] > 25:
            u["_lowFuelWarned"] = False
        if u["fuel"] <= 5 and not u.get("_critFuelWarned"):
            u["_critFuelWarned"] = True
            self.on_log(u["name"], f"🔴 CRITICAL FUEL: {round(u['fuel'])}%. Emergency RTB.", "warn")
            self._emergency_rtb(u)

        # Depth (subs + UUVs)
        if utype in ("sub","uuv"):
            td = u.get("targetDepth")
            if td is not None:
                err_d  = td - u["depth"]
                u["depth"] = td if abs(err_d) < 3 else u["depth"] + math.copysign(min(5,abs(err_d)),err_d)
            else:
                u["depth"] += random.uniform(-0.5, 0.5)
                u["depth"]  = max(5, min(400 if utype=="sub" else 100, u["depth"]))

        # Speed ramp
        ts = u.get("targetSpeed")
        if ts is not None:
            s_err = ts - u["speed"]
            ramp  = 5 if utype=="mpa" else 0.5
            u["speed"] += math.copysign(min(ramp, abs(s_err)), s_err)
            if abs(s_err) < 0.5:
                u["speed"] = ts
        else:
            u["speed"] += random.uniform(-0.15, 0.15)
            max_spd = 220 if utype=="mpa" else 25 if utype=="sub" else 6 if utype=="uuv" else 30
            min_spd = (150 if utype=="mpa" and u.get("looping") != False else
                       0   if utype=="mpa" else 2)
            u["speed"] = max(min_spd, min(max_spd, u["speed"]))

    def _emergency_rtb(self, u: dict):
        valid = (["subpen","port"] if u["type"]=="sub" else
                 ["airbase"]       if u["type"]=="mpa" else ["port"])
        candidates = [(b, _dist_km(u["lat"],u["lon"],b["lat"],b["lon"]))
                      for b in ALL_BASES if b["type"] in valid]
        if not candidates:
            return
        nearest = min(candidates, key=lambda x: x[1])[0]
        u["waypoints"] = [[nearest["lat"], nearest["lon"]]]
        u["wp_idx"]    = 0
        u["looping"]   = False
        u["status"]    = "submerged" if u["type"]=="sub" else "transit"
        u["targetSpeed"] = 15 if u["type"]=="sub" else 25
        if u["type"] == "sub":
            u["targetDepth"] = 80
        u["heading"] = _bearing(u["lat"],u["lon"],nearest["lat"],nearest["lon"])

    # ── Threat generation ────────────────────────────────────────────────────

    def _generate_threat(self):
        sensor = random.choice(SENSOR_NODES)
        templates = NAVAL_THREATS[sensor["type"]]
        tmpl   = random.choice(templates)
        angle  = random.uniform(0, 360)
        dist   = random.uniform(20, sensor["radius"] * 0.8)
        threat = {
            "id":          f"NTH-{int(time.time())}-{random.randint(100,999)}",
            "type":        "navy_threat",
            "sensor_id":   sensor["id"],
            "sensor_name": sensor["name"],
            "sensor_type": sensor["type"],
            "threat_class":tmpl["cls"],
            "message":     tmpl["msg"],
            "threat_lat":  round(sensor["lat"] + dist*math.cos(math.radians(angle))/111.32, 4),
            "threat_lon":  round(sensor["lon"] + dist*math.sin(math.radians(angle))/111.32, 4),
            "confidence":  random.randint(62, 97),
            "severity":    "high" if "SUBSURFACE" in tmpl["cls"] or "SONAR" in tmpl["cls"] else "medium",
            "ts":          int(time.time()*1000),
        }
        self._last_threat = time.time()
        self.on_log(sensor["name"], f"[{threat['threat_class']}] {threat['message']} Conf: {threat['confidence']}%", "warn")
        if self.on_threat:
            self.on_threat(threat)

    # ── Command API ──────────────────────────────────────────────────────────

    def cmd(self, unit_id: str, command: str, params: dict = {}):
        u = next((x for x in self.units if x["id"] == unit_id), None)
        if not u:
            return False

        if command == "set_speed":
            speed = params.get("speed", 0)
            u["targetSpeed"] = speed
            if speed == 0 and u["type"] == "sub":
                u["targetDepth"] = round(u["depth"])  # hover
            if u["status"] in ("moored","grounded","recovered"):
                u["status"] = "submerged" if u["type"]=="sub" else "patrol"

        elif command == "set_depth":
            depth = params.get("depth", 0)
            u["targetDepth"] = depth
            if u["status"] in ("moored","grounded","recovered"):
                u["status"] = "submerged"
            if depth == 0:
                u["targetSpeed"] = 4  # surface safely

        elif command == "rtb":
            home_id  = HOME_BASE.get(unit_id)
            home_base = next((b for b in ALL_BASES if b["id"]==home_id), None)
            if not home_base:
                return False
            u["waypoints"]    = [[home_base["lat"], home_base["lon"]]]
            u["wp_idx"]       = 0
            u["looping"]      = False
            u["status"]       = "submerged" if u["type"]=="sub" else "transit"
            u["_homeBase"]    = home_id
            u["heading"]      = _bearing(u["lat"],u["lon"],home_base["lat"],home_base["lon"])
            if u["type"] == "sub":
                u["targetDepth"] = 80
                u["targetSpeed"] = 12
            elif u["type"] == "mpa":
                u["targetSpeed"] = 200
            else:
                u["targetSpeed"] = 18
            dist = round(_dist_km(u["lat"],u["lon"],home_base["lat"],home_base["lon"]))
            self.on_log(u["name"], f"({u['pennant']}) RTB {home_base['name'].upper()}. Distance: {dist}km.", "ok")

        elif command == "rtb_to":
            base_id  = params.get("base_id","")
            base     = next((b for b in ALL_BASES if b["id"]==base_id), None)
            if not base:
                return False
            u["waypoints"]  = [[base["lat"], base["lon"]]]
            u["wp_idx"]     = 0; u["looping"] = False
            u["status"]     = "submerged" if u["type"]=="sub" else "transit"
            u["heading"]    = _bearing(u["lat"],u["lon"],base["lat"],base["lon"])
            if u["type"]=="sub":  u["targetDepth"]=80; u["targetSpeed"]=12
            elif u["type"]=="mpa": u["targetSpeed"]=200
            else:                  u["targetSpeed"]=18
            self.on_log(u["name"], f"RTB → {base['name']}.", "ok")

        elif command == "deploy":
            orig_wps = next((x["waypoints"] for x in _make_units() if x["id"]==unit_id), None)
            if orig_wps:
                u["waypoints"] = [list(wp) for wp in orig_wps]
            u["wp_idx"]  = 0; u["looping"] = True
            u["status"]  = "patrol" if u["type"]!="sub" else "submerged"
            if u["type"] == "mpa":
                u["targetSpeed"] = 190
            else:
                u.pop("targetSpeed", None)
            u.pop("targetDepth", None)
            self.on_log(u["name"], "Deployed from base. Patrol route set.", "ok")

        elif command == "refuel":
            u["fuel"] = 100.0
            self.on_log(u["name"], "Refueled to 100% at base.", "ok")

        elif command == "intercept":
            lat = params.get("lat"); lon = params.get("lon")
            if lat is None or lon is None:
                return False
            u["waypoints"] = [[lat, lon]]
            u["wp_idx"]    = 0; u["looping"] = False
            u["heading"]   = _bearing(u["lat"],u["lon"],lat,lon)
            u["status"]    = "transit"
            u["targetSpeed"] = 25
            dist = round(_dist_km(u["lat"],u["lon"],lat,lon))
            self.on_log(u["name"], f"INTERCEPT COURSE SET → {lat:.2f}°N {lon:.2f}°E. Distance: {dist}km.", "ok")

        elif command == "uuv_track_carrier":
            carrier_id = params.get("carrier_id","")
            u["_trackCarrierId"] = carrier_id
            self.on_log(u["name"], f"Tracking carrier {carrier_id}.", "ok")

        return True

    def fleet_rtb(self) -> int:
        count = 0
        for u in self.units:
            home_id = HOME_BASE.get(u["id"])
            base    = next((b for b in ALL_BASES if b["id"]==home_id), None)
            if not base:
                continue
            u["waypoints"]  = [[base["lat"], base["lon"]]]
            u["wp_idx"]     = 0; u["looping"] = False
            u["_homeBase"]  = home_id
            u["heading"]    = _bearing(u["lat"],u["lon"],base["lat"],base["lon"])
            if u["type"]=="sub":
                u["status"]="submerged"; u["targetDepth"]=80; u["targetSpeed"]=12
            elif u["type"]=="uuv":
                u["status"]="patrol"; u["targetDepth"]=20; u["targetSpeed"]=5
            elif u["type"]=="mpa":
                u["status"]="transit"; u["targetSpeed"]=200
            else:
                u["status"]="transit"; u["targetSpeed"]=18
            count += 1
        self.on_log("FLEET CMD", f"RTB ALL: {count} units ordered to home ports.", "warn")
        return count

    def get_state(self) -> list[dict]:
        """Return serialisable snapshot of all units."""
        snap = []
        for u in self.units:
            snap.append({
                "id":u["id"],"lat":round(u["lat"],5),"lon":round(u["lon"],5),
                "heading":round(u["heading"],1),"speed":round(u["speed"],1),
                "depth":round(u.get("depth",0),1),"fuel":round(u["fuel"],1),
                "status":u["status"],"wp_idx":u.get("wp_idx",0),
                "waypoints":u.get("waypoints",[]),"looping":u.get("looping",True),
                "targetDepth":u.get("targetDepth"),"targetSpeed":u.get("targetSpeed"),
            })
        return snap

    async def run(self, hz: float = 1.0):
        self._running = True
        dt = 1.0 / hz
        print(f"[NAVAL SIM] Running at {hz} Hz — {len(self.units)} units")
        while self._running:
            self.tick()
            await asyncio.sleep(dt)
