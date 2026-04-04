# ATLAS OS
### Multi-Domain Command & Control System

Real-time unified operational picture across Land, Naval, and Air domains.  
Built for operators. Designed for scale. Made for India.

[![Live](https://img.shields.io/badge/LIVE-atlascorporation.onrender.com-00ff88?style=for-the-badge)](https://atlascorporation.onrender.com)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-WebSocket-009688?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com)

---

## THE PROBLEM

Modern military operations span three domains simultaneously — land, sea, and air. Today these operate in silos. Army doesn't see what Navy is doing. Air Force operates independently. Commanders make decisions with an incomplete picture.

The cost of that blind spot is measured in lives.

Atlas OS is the unified layer that sits above all three domains and gives commanders a single, real-time operational picture — from one screen.

---

## THREE THEATERS. ONE SCREEN.

### ARMY THEATER
Real-time tracking of unmanned ground and aerial assets across a forward operating area.

- 7 autonomous UAVs with live telemetry — position, altitude, battery, heading, speed
- 5 UGVs patrolling perimeter and sector routes
- 4 sensor nodes — acoustic, seismic, RF, radar
- Automatic threat detection with operator-in-the-loop approval
- Mission upload, waypoint assignment, RTB commands
- Sensor-to-shooter loop: threat detected → operator approves → drone deploys

### NAVAL THEATER
Full oceanic tactical picture. 20 assets tracked in real time with server-side physics engine.

- 2 fleet carriers with battle group coordination
- 3 destroyers, 4 frigates across eastern and western fleets
- 5 submarines — strategic, attack, and patrol classes
- 4 autonomous underwater vehicles
- 2 maritime patrol aircraft
- Submarine depth control, speed orders, silent running
- Fleet RTB, individual port/subpen assignments
- Underwater sensor network with contact generation
- Base management — refuel and deploy from 6 ports, 3 subpens, 4 airbases
- Multi-user sync — commands from one operator visible to all in under 1 second

### AIR THEATER
National airspace tactical display with fighter coverage and integrated radar network.

- Fighter pairs on border patrol — northern, eastern, and southern sectors
- AWACS surveillance orbit — central airspace coverage
- 7 ground radar stations across the country
- SAM battery coverage rings — layered air defense picture
- AWACS detection radius overlay
- Scramble, RTB, CAP establishment, intercept vectoring
- Automatic threat detection — ballistic missiles, stealth contacts, UAV swarms, FIR violations
- Live ADS-B traffic overlay — real aircraft over Indian airspace

---

## MULTI-USER

Multiple operators. Same picture. Real time.

Naval theater runs on a server-side physics engine. Every operator connected to the system sees identical fleet positions. A command issued by one operator — RTB, depth change, intercept — is reflected for every connected client within one second.

This is what makes it a C2 system, not a dashboard.

---

## HARDWARE INTEGRATION *(in progress)*

```
ESP32-CAM + Neo-6M GPS
        ↓
   WiFi → /api/track
        ↓
   Atlas OS server
        ↓
   Live marker on army map
        ↓
   RTB command issued
        ↓
   Command sent back to hardware
        ↓
   Physical LED response
```

Real hardware. Real GPS. Real closed-loop command execution.

The same architecture scales to actual flight hardware via MAVLink bridge.

---

## ARCHITECTURE

```
┌─────────────────────────────────────────────────────────┐
│                      ATLAS OS v0.7                       │
├─────────────────┬───────────────────┬───────────────────┤
│  ARMY THEATER   │  NAVAL THEATER    │   AIR THEATER     │
│  mavlink_sim.py │  naval_sim.py     │  airSimTick()     │
│  4 Hz physics   │  1 Hz physics     │  1 Hz physics     │
├─────────────────┴───────────────────┴───────────────────┤
│                     server.py                            │
│           FastAPI · WebSocket broadcast hub              │
│               adsb_feed.py · ADS-B feed                 │
├─────────────────────────────────────────────────────────┤
│                    atlas-os.html                         │
│         Leaflet maps · Three theaters · WS client        │
└─────────────────────────────────────────────────────────┘
```

---

## STACK

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11, FastAPI, uvicorn |
| Real-time | WebSocket |
| Physics engines | mavlink_sim.py, naval_sim.py |
| ADS-B | OpenSky Network / airplanes.live |
| Frontend | Vanilla JS, Leaflet.js |
| Maps | CartoDB |
| Fonts | Orbitron, Share Tech Mono |
| Deploy | Render |

---

## RUNNING LOCALLY

```bash
git clone https://github.com/a-d-it-ya/atlas-corp.git
cd atlas-corp

pip install -r requirements.txt

python server.py
```

Open `http://localhost:8000`

---

## API

```
GET  /                          → Atlas OS interface
GET  /api/status                → Server + subsystem health
GET  /api/assets                → Army assets
GET  /api/naval/state           → Full naval fleet state
GET  /api/adsb                  → Live ADS-B snapshot
WS   /ws                        → Main WebSocket
POST /api/track                 → Field asset telemetry (hardware)
POST /api/naval/command/{id}    → Naval unit command
POST /api/naval/fleet_rtb       → Fleet RTB
POST /api/rtb                   → Army RTB all
POST /api/missions              → Mission upload
```

---

## ROADMAP

- [x] Army theater — UAVs, UGVs, sensor network, threat detection
- [x] Naval theater — 20 assets, full command suite, server-side physics
- [x] Air theater — fighters, AWACS, radar network, threat detection
- [x] Multi-user sync
- [x] Live ADS-B feed
- [x] Deployed live
- [ ] ESP32-CAM hardware integration — GPS tracking + live camera feed
- [ ] RTL-SDR ground station — real ADS-B air picture
- [ ] AIS receiver — real naval picture
- [ ] State persistence
- [ ] Operator authentication and roles
- [ ] MAVLink bridge — real drone integration
- [ ] iDEX application

---

## BUILT BY

**Aditya Singh**  

---

<div align="center">

*Made with love in India 🇮🇳*

</div>
