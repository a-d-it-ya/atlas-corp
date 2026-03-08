"""
ATLAS MAVLink + Sensor Simulator v0.5
- 7 drones (UAVs) flying autonomous waypoint routes
- 5 UGVs (Unmanned Ground Vehicles) patrolling ground routes
- 4 sensor nodes detecting threats
- Supports mission assignment, RTB, and drone deployment
"""

import asyncio
import math
import random
import time
from dataclasses import dataclass, field
from typing import Callable


# ── Drone State (UAV) ─────────────────────────────────────────────────────────

@dataclass
class DroneState:
    sys_id:    int
    name:      str
    lat:       float
    lon:       float
    alt:       float
    heading:   float
    speed:     float        # m/s
    battery:   float
    armed:     bool         = True
    mode:      str          = 'AUTO'
    waypoints: list         = field(default_factory=list)
    wp_idx:    int          = 0
    roll:      float        = 0.0
    pitch:     float        = 0.0
    yaw:       float        = 0.0

    # Battery config
    DRAIN_RATE:   float = 0.008   # % per second while flying
    CHARGE_RATE:  float = 0.25    # % per second while charging at HQ

    def advance(self, dt: float):
        # ── Charging at HQ ───────────────────────────────────────────────────
        if self.mode == 'CHARGING':
            self.battery = min(100.0, self.battery + self.CHARGE_RATE * dt)
            if self.battery >= 100.0:
                self.battery = 100.0
                self.mode    = 'STANDBY'
                print(f"[SIM] {self.name} fully charged. STANDBY.")
            return

        if not self.waypoints or not self.armed:
            self.alt   += random.gauss(0, 0.3)
            self.alt    = max(50, min(800, self.alt))
            self.roll   = math.sin(time.time() * 0.5) * 0.05
            self.pitch  = math.cos(time.time() * 0.4) * 0.03
            # Drain even when hovering (idle)
            if self.armed:
                self.battery = max(0.0, self.battery - (self.DRAIN_RATE * 0.4) * dt)
            return

        target = self.waypoints[self.wp_idx % len(self.waypoints)]
        dlat   = target[0] - self.lat
        dlon   = target[1] - self.lon
        dist   = math.hypot(dlat * 111320,
                            dlon * 111320 * math.cos(math.radians(self.lat)))

        if dist < 30:
            self.wp_idx = (self.wp_idx + 1) % len(self.waypoints)
            if self.mode == 'RTB' and self.wp_idx == 0:
                # Landed at HQ — begin charging
                self.armed     = False
                self.mode      = 'CHARGING'
                self.alt       = 0
                self.speed     = 0
                self.waypoints = []
                print(f"[SIM] {self.name} landed at HQ. Charging... ({self.battery:.0f}%)")
            elif self.mode == 'DEPLOY' and self.wp_idx == 0:
                self.mode      = 'LOITER'
                self.waypoints = [(self.lat, self.lon, self.alt)]
        else:
            desired_hdg  = math.degrees(math.atan2(dlon, dlat)) % 360
            hdg_err      = (desired_hdg - self.heading + 180) % 360 - 180
            self.heading = (self.heading + min(3, max(-3, hdg_err * 0.5))) % 360
            dx = self.speed * dt * math.cos(math.radians(self.heading))
            dy = self.speed * dt * math.sin(math.radians(self.heading))
            self.lat += dx / 111320
            self.lon += dy / (111320 * math.cos(math.radians(self.lat)))

        tgt_alt   = target[2] if len(target) > 2 else 300
        self.alt += (tgt_alt - self.alt) * 0.02 + random.gauss(0, 0.5)
        self.alt  = max(0 if self.mode in ('RTB','CHARGING') else 50, min(800, self.alt))
        self.roll  = math.sin(time.time() * 0.6) * 0.08
        self.pitch = math.cos(time.time() * 0.5) * 0.05
        self.yaw   = math.radians(self.heading)

        # Battery drain — faster at high speed
        speed_factor = 1.0 + (self.speed / 50.0) * 0.5
        if self.armed:
            self.battery = max(0.0, self.battery - self.DRAIN_RATE * speed_factor * dt)


# ── UGV State ─────────────────────────────────────────────────────────────────

@dataclass
class UGVState:
    sys_id:    int
    name:      str
    lat:       float
    lon:       float
    heading:   float
    speed:     float        # m/s (UGVs are slower, ~3-8 m/s)
    battery:   float
    armed:     bool         = True
    mode:      str          = 'PATROL'
    waypoints: list         = field(default_factory=list)
    wp_idx:    int          = 0

    DRAIN_RATE:  float = 0.004   # % per second while moving
    CHARGE_RATE: float = 0.20    # % per second while charging at HQ

    def advance(self, dt: float):
        # ── Charging at HQ ───────────────────────────────────────────────────
        if self.mode == 'CHARGING':
            self.battery = min(100.0, self.battery + self.CHARGE_RATE * dt)
            if self.battery >= 100.0:
                self.battery = 100.0
                self.mode    = 'DOCKED'
                print(f"[SIM] {self.name} fully charged. DOCKED.")
            return

        if not self.waypoints or not self.armed:
            self.heading = (self.heading + random.gauss(0, 0.5)) % 360
            return

        target = self.waypoints[self.wp_idx % len(self.waypoints)]
        dlat   = target[0] - self.lat
        dlon   = target[1] - self.lon
        dist   = math.hypot(dlat * 111320,
                            dlon * 111320 * math.cos(math.radians(self.lat)))

        if dist < 15:
            self.wp_idx = (self.wp_idx + 1) % len(self.waypoints)
            if self.mode == 'RTB' and self.wp_idx == 0:
                self.armed  = False
                self.mode   = 'CHARGING'
                self.speed  = 0
                self.waypoints = []
                print(f"[SIM] {self.name} docked at HQ. Charging... ({self.battery:.0f}%)")
        else:
            desired_hdg  = math.degrees(math.atan2(dlon, dlat)) % 360
            hdg_err      = (desired_hdg - self.heading + 180) % 360 - 180
            self.heading = (self.heading + min(2, max(-2, hdg_err * 0.4))) % 360
            dx = self.speed * dt * math.cos(math.radians(self.heading))
            dy = self.speed * dt * math.sin(math.radians(self.heading))
            self.lat += dx / 111320
            self.lon += dy / (111320 * math.cos(math.radians(self.lat)))

        if self.armed:
            self.battery = max(0.0, self.battery - self.DRAIN_RATE * dt)


# ── Sensor Node ───────────────────────────────────────────────────────────────

@dataclass
class SensorNode:
    id:                   str
    name:                 str
    lat:                  float
    lon:                  float
    sensor_type:          str
    detection_radius:     float
    status:               str   = 'active'
    last_detection:       float = 0.0
    BASE_DETECT_INTERVAL: float = 120.0

    THREAT_TEMPLATES = {
        'acoustic': [
            ('Footstep pattern detected. Estimated 4–6 personnel.', 'PERSONNEL'),
            ('Vehicle acoustic signature. Type: light truck.', 'VEHICLE'),
            ('Rotary wing acoustic detected. Non-ATLAS signature.', 'UAV'),
        ],
        'seismic': [
            ('Ground vibration detected. Vehicle movement likely.', 'VEHICLE'),
            ('Seismic spike. Possible IED detonation or blast.', 'EXPLOSION'),
            ('Heavy vehicle signature. Armour class likely.', 'ARMOUR'),
        ],
        'rf': [
            ('RF emission burst detected. Encrypted comms.', 'COMMS'),
            ('Drone control signal intercepted. Freq: 2.4 GHz.', 'UAV'),
            ('Radar ping from unknown source. Bearing 047°.', 'RADAR'),
        ],
        'radar': [
            ('Fast-moving contact. Speed ~120 km/h. Heading 220°.', 'UAV'),
            ('Ground contact detected. Slow-moving. Possible personnel.', 'PERSONNEL'),
            ('Multiple contacts. Formation pattern. 3–5 units.', 'PERSONNEL'),
        ],
    }

    def should_detect(self, dt: float) -> bool:
        if self.status != 'active':
            return False
        return random.random() < (dt / self.BASE_DETECT_INTERVAL)

    def generate_detection(self) -> dict:
        templates  = self.THREAT_TEMPLATES.get(self.sensor_type, self.THREAT_TEMPLATES['acoustic'])
        msg, threat_class = random.choice(templates)
        angle      = random.uniform(0, 360)
        dist       = random.uniform(0.3, self.detection_radius)
        dlat       = dist * math.cos(math.radians(angle)) / 111.32
        dlon       = dist * math.sin(math.radians(angle)) / (111.32 * math.cos(math.radians(self.lat)))
        confidence = random.randint(62, 97)
        severity   = 'high'   if threat_class in ('ARMOUR','EXPLOSION','UAV') else \
                     'medium' if threat_class in ('VEHICLE','RADAR') else 'low'
        return {
            'type':         'threat_detected',
            'sensor_id':    self.id,
            'sensor_name':  self.name,
            'sensor_type':  self.sensor_type,
            'sensor_lat':   self.lat,
            'sensor_lon':   self.lon,
            'threat_lat':   round(self.lat + dlat, 5),
            'threat_lon':   round(self.lon + dlon, 5),
            'threat_class': threat_class,
            'message':      msg,
            'confidence':   confidence,
            'severity':     severity,
            'ts':           int(time.time() * 1000),
            'id':           f"THR-{int(time.time())}-{random.randint(100,999)}",
        }


# ── Main Simulator ────────────────────────────────────────────────────────────

class MAVLinkSimulator:
    def __init__(self,
                 on_packet:    Callable[[int, dict], None],
                 on_ugv:       Callable[[dict], None],
                 on_detection: Callable[[dict], None]):
        self.on_packet    = on_packet
        self.on_ugv       = on_ugv
        self.on_detection = on_detection
        self.drones:  list[DroneState] = []
        self.ugvs:    list[UGVState]   = []
        self.sensors: list[SensorNode] = []
        self._setup_drones()
        self._setup_ugvs()
        self._setup_sensors()

    def _setup_drones(self):
        self.drones = [
            DroneState(sys_id=1, name='ATLAS-D-01',
                lat=34.050, lon=74.020, alt=312, heading=224, speed=41.0, battery=80,
                waypoints=[(34.080,74.050,320),(34.100,74.080,280),(34.070,74.110,300),(34.040,74.090,340),(34.050,74.020,312)]),
            DroneState(sys_id=2, name='ATLAS-D-02',
                lat=34.030, lon=74.060, alt=280, heading=87, speed=45.0, battery=78,
                waypoints=[(34.060,74.100,260),(34.090,74.130,290),(34.110,74.100,270),(34.080,74.070,285),(34.030,74.060,280)]),
            DroneState(sys_id=3, name='ATLAS-D-03',
                lat=34.020, lon=74.000, alt=0, heading=0, speed=0, battery=91,
                armed=False, mode='STANDBY', waypoints=[]),
            DroneState(sys_id=4, name='ATLAS-D-04',
                lat=34.115, lon=74.045, alt=350, heading=190, speed=38.0, battery=65,
                waypoints=[(34.090,74.020,340),(34.060,74.010,320),(34.050,74.040,310),(34.080,74.060,330),(34.115,74.045,350)]),
            DroneState(sys_id=5, name='ATLAS-D-05',
                lat=34.005, lon=74.110, alt=290, heading=310, speed=43.0, battery=55,
                waypoints=[(34.030,74.130,280),(34.055,74.120,300),(34.070,74.140,270),(34.045,74.150,290),(34.005,74.110,290)]),
            DroneState(sys_id=6, name='ATLAS-D-06',
                lat=34.120, lon=74.110, alt=0, heading=0, speed=0, battery=100,
                armed=False, mode='STANDBY', waypoints=[]),
            DroneState(sys_id=7, name='ATLAS-D-07',
                lat=34.000, lon=73.980, alt=260, heading=45, speed=40.0, battery=88,
                waypoints=[(34.020,74.000,270),(34.035,74.015,280),(34.025,74.035,260),(34.010,74.020,270),(34.000,73.980,260)]),
        ]

    def _setup_ugvs(self):
        self.ugvs = [
            UGVState(sys_id=101, name='ATLAS-G-01',
                lat=34.038, lon=74.032, heading=60, speed=4.5, battery=82,
                mode='PATROL',
                waypoints=[(34.042,74.038),(34.048,74.042),(34.044,74.050),(34.038,74.045),(34.032,74.038),(34.038,74.032)]),
            UGVState(sys_id=102, name='ATLAS-G-02',
                lat=34.055, lon=74.065, heading=120, speed=5.0, battery=71,
                mode='PATROL',
                waypoints=[(34.060,74.075),(34.065,74.080),(34.068,74.070),(34.062,74.060),(34.055,74.065)]),
            UGVState(sys_id=103, name='ATLAS-G-03',
                lat=34.025, lon=74.080, heading=200, speed=3.8, battery=94,
                mode='PATROL',
                waypoints=[(34.020,74.090),(34.015,74.085),(34.018,74.075),(34.025,74.070),(34.030,74.078),(34.025,74.080)]),
            UGVState(sys_id=104, name='ATLAS-G-04',
                lat=34.070, lon=74.025, heading=270, speed=4.2, battery=60,
                mode='PATROL',
                waypoints=[(34.075,74.015),(34.080,74.020),(34.078,74.030),(34.072,74.035),(34.065,74.028),(34.070,74.025)]),
            UGVState(sys_id=105, name='ATLAS-G-05',
                lat=34.010, lon=74.050, heading=90, speed=5.5, battery=45,
                mode='PATROL',
                waypoints=[(34.015,74.060),(34.012,74.070),(34.008,74.065),(34.005,74.055),(34.008,74.045),(34.010,74.050)]),
        ]

    def _setup_sensors(self):
        self.sensors = [
            SensorNode(id='ATLAS-S-01', name='Sensor Node Gamma',
                lat=34.045, lon=74.055, sensor_type='acoustic',
                detection_radius=2.5, BASE_DETECT_INTERVAL=120),
            SensorNode(id='ATLAS-S-02', name='Sensor Node Delta',
                lat=34.035, lon=74.095, sensor_type='seismic',
                detection_radius=2.0, BASE_DETECT_INTERVAL=150),
            SensorNode(id='ATLAS-S-03', name='Sensor Node Echo',
                lat=34.075, lon=74.030, sensor_type='rf',
                detection_radius=5.0, BASE_DETECT_INTERVAL=120),
            SensorNode(id='ATLAS-S-04', name='Radar Post Foxtrot',
                lat=34.010, lon=74.070, sensor_type='radar',
                detection_radius=8.0, BASE_DETECT_INTERVAL=180),
        ]

    # ── Mission control ───────────────────────────────────────────────────────

    def assign_mission(self, drone_name: str, waypoints: list) -> bool:
        for drone in self.drones:
            if drone.name == drone_name:
                drone.waypoints = [(wp['lat'], wp['lon'], wp.get('alt', 300)) for wp in waypoints]
                drone.wp_idx = 0; drone.armed = True
                drone.mode = 'MISSION'; drone.speed = max(drone.speed, 30.0)
                print(f"[SIM] Mission → {drone_name} | {len(waypoints)} waypoints")
                return True
        return False

    def deploy_to_threat(self, drone_name: str, threat_lat: float,
                         threat_lon: float, alt: float = 250) -> bool:
        for drone in self.drones:
            if drone.name == drone_name:
                drone.waypoints = [(threat_lat, threat_lon, alt)]
                drone.wp_idx = 0; drone.armed = True
                drone.mode = 'DEPLOY'; drone.speed = max(drone.speed, 45.0)
                print(f"[SIM] DEPLOY → {drone_name} to ({threat_lat}, {threat_lon})")
                return True
        return False

    def get_available_drone(self) -> str | None:
        for drone in self.drones:
            if not drone.armed and drone.mode in ('STANDBY', 'LANDED'):
                return drone.name
        for drone in self.drones:
            if drone.armed and drone.mode in ('AUTO', 'MISSION', 'LOITER'):
                return drone.name
        return None

    def rtb_all(self) -> int:
        BASE = (34.040, 74.040, 80)
        count = 0
        for drone in self.drones:
            if drone.armed and drone.mode not in ('CHARGING', 'RTB'):
                drone.waypoints = [BASE]; drone.wp_idx = 0
                drone.mode = 'RTB'; count += 1
        # Also recall UGVs
        UGV_BASE = (34.040, 74.040)
        for ugv in self.ugvs:
            if ugv.armed and ugv.mode not in ('CHARGING', 'DOCKED', 'RTB'):
                ugv.waypoints = [UGV_BASE]; ugv.wp_idx = 0
                ugv.mode = 'RTB'; count += 1
        print(f"[SIM] RTB ALL — {count} units")
        return count

    def rtb_single(self, name: str) -> bool:
        BASE = (34.040, 74.040, 80)
        for drone in self.drones:
            if drone.name == name and drone.armed and drone.mode not in ('CHARGING', 'RTB'):
                drone.waypoints = [BASE]; drone.wp_idx = 0
                drone.mode = 'RTB'; print(f"[SIM] RTB → {name}"); return True
        UGV_BASE = (34.040, 74.040)
        for ugv in self.ugvs:
            if ugv.name == name and ugv.armed and ugv.mode not in ('CHARGING', 'DOCKED', 'RTB'):
                ugv.waypoints = [UGV_BASE]; ugv.wp_idx = 0
                ugv.mode = 'RTB'; print(f"[SIM] RTB → {name}"); return True
        return False

    def redeploy_ugv(self, name: str) -> bool:
        """Send a docked/charged UGV back to its default patrol route."""
        DEFAULT_PATROLS = {
            'ATLAS-G-01': [(34.042,74.038),(34.048,74.042),(34.044,74.050),(34.038,74.045),(34.032,74.038),(34.038,74.032)],
            'ATLAS-G-02': [(34.060,74.075),(34.065,74.080),(34.068,74.070),(34.062,74.060),(34.055,74.065)],
            'ATLAS-G-03': [(34.020,74.090),(34.015,74.085),(34.018,74.075),(34.025,74.070),(34.030,74.078),(34.025,74.080)],
            'ATLAS-G-04': [(34.075,74.015),(34.080,74.020),(34.078,74.030),(34.072,74.035),(34.065,74.028),(34.070,74.025)],
            'ATLAS-G-05': [(34.015,74.060),(34.012,74.070),(34.008,74.065),(34.005,74.055),(34.008,74.045),(34.010,74.050)],
        }
        for ugv in self.ugvs:
            if ugv.name == name and ugv.mode in ('DOCKED', 'CHARGING'):
                ugv.waypoints = DEFAULT_PATROLS.get(name, [])
                ugv.wp_idx    = 0
                ugv.armed     = True
                ugv.mode      = 'PATROL'
                ugv.speed     = 4.5
                print(f"[SIM] REDEPLOY → {name} (bat: {ugv.battery:.0f}%)")
                return True
        return False

    def arm_drone(self, name: str) -> bool:
        for drone in self.drones:
            if drone.name == name and not drone.armed:
                drone.armed = True; drone.mode = 'STANDBY'
                drone.speed = 35.0; print(f"[SIM] ARMED → {name}"); return True
        return False

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def run(self, hz: float = 4.0):
        dt = 1.0 / hz
        print(f"[SIM] Running at {hz} Hz — {len(self.drones)} drones, "
              f"{len(self.ugvs)} UGVs, {len(self.sensors)} sensors")
        while True:
            for drone in self.drones:
                drone.advance(dt)
                self._emit_drone(drone)
            for ugv in self.ugvs:
                ugv.advance(dt)
                self._emit_ugv(ugv)
            for sensor in self.sensors:
                if sensor.should_detect(dt):
                    detection = sensor.generate_detection()
                    sensor.last_detection = time.time()
                    self.on_detection(detection)
            await asyncio.sleep(dt)

    def _emit_drone(self, d: DroneState):
        self.on_packet(d.sys_id, {
            'sys_id': d.sys_id, 'name': d.name, 'type': 'telemetry',
            'armed': d.armed, 'mode': d.mode,
            'lat': round(d.lat,6), 'lon': round(d.lon,6), 'alt': round(d.alt,1),
            'heading': round(d.heading,1), 'speed': round(d.speed*3.6,1),
            'battery': round(d.battery),
            'roll': round(math.degrees(d.roll),2), 'pitch': round(math.degrees(d.pitch),2),
            'signal': random.randint(-78,-62), 'ts': int(time.time()*1000), '_mavlink': {}
        })

    def _emit_ugv(self, g: UGVState):
        self.on_ugv({
            'sys_id': g.sys_id, 'name': g.name, 'type': 'ugv',
            'armed': g.armed, 'mode': g.mode,
            'lat': round(g.lat,6), 'lon': round(g.lon,6), 'alt': 0,
            'heading': round(g.heading,1), 'speed': round(g.speed*3.6,1),
            'battery': round(g.battery),
            'signal': random.randint(-72,-55), 'ts': int(time.time()*1000),
        })
