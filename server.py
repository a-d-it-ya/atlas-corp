"""
ATLAS Backend Server v0.6
- Army theater: 7 drones + 5 UGVs with full simulation
- ADS-B: Live aircraft feed over India FIR via OpenSky Network
- WebSocket broadcast to all connected clients
"""

import asyncio
import json
import os
import random
import time
from collections import deque

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from mavlink_sim import MAVLinkSimulator
from adsb_feed import adsb_feed

app = FastAPI(title="ATLAS OS Backend", version="0.6")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/")
def serve_ui():
    return FileResponse(os.path.join(os.path.dirname(__file__), "atlas-os.html"))

# ── State ─────────────────────────────────────────────────────────────────────

telemetry_store: dict[int, dict] = {}
ugv_store:       dict[int, dict] = {}
ws_clients:      set[WebSocket]  = set()
event_log:       deque           = deque(maxlen=200)
missions:        list[dict]      = []
pending_threats: dict[str, dict] = {}
sim: MAVLinkSimulator | None     = None

STATIC_ASSETS = [
    {"id":"ATLAS-S-01","name":"ATLAS-S-01","sub":"Sensor Node Gamma",
     "type":"sensor","status":"active","battery":88,"signal":-72,
     "lat":34.045,"lon":74.055,"mode":"MONITOR"},
    {"id":"ATLAS-S-02","name":"ATLAS-S-02","sub":"Sensor Node Delta",
     "type":"sensor","status":"active","battery":75,"signal":-76,
     "lat":34.035,"lon":74.095,"mode":"MONITOR"},
    {"id":"ATLAS-S-03","name":"ATLAS-S-03","sub":"Sensor Node Echo",
     "type":"sensor","status":"active","battery":91,"signal":-68,
     "lat":34.075,"lon":74.030,"mode":"MONITOR"},
    {"id":"ATLAS-S-04","name":"ATLAS-S-04","sub":"Radar Post Foxtrot",
     "type":"sensor","status":"active","battery":100,"signal":-60,
     "lat":34.010,"lon":74.070,"mode":"RADAR"},
    {"id":"ATLAS-C-01","name":"ATLAS-C-01","sub":"Command Post HQ",
     "type":"command","status":"active","signal":"WIRED",
     "lat":34.040,"lon":74.040,"mode":"COMMAND"},
    {"id":"ATLAS-E-01","name":"ATLAS-E-01","sub":"EW Unit Foxtrot",
     "type":"ew","status":"standby","battery":100,"signal":-65,
     "lat":34.025,"lon":74.015,"mode":"STANDBY"},
]

# ── Logging ───────────────────────────────────────────────────────────────────

def push_log(src: str, msg: str, level: str = "info") -> dict:
    entry = {"ts": int(time.time()*1000),
             "time_utc": time.strftime("%H:%M:%S", time.gmtime()),
             "src": src, "msg": msg, "level": level}
    event_log.appendleft(entry)
    return entry

push_log("ATLAS CORE", "System boot complete. All subsystems nominal.", "ok")
push_log("SAT-LINK",   "Primary uplink established. ATLAS-SAT-01 acquired.", "ok")
push_log("ATLAS AI",   "Threat detection model loaded. YOLO v11 active.", "info")
push_log("ATLAS-C-01", "Command post online. 7 UAVs, 5 UGVs registered.", "ok")
push_log("ADS-B",      "India FIR ADS-B feed initializing...", "info")

# ── Callbacks ─────────────────────────────────────────────────────────────────

DRONE_LOGS = {
    1: [("Waypoint reached. Adjusting heading.", "ok"),
        ("Battery warning: below 35%. RTB recommended.", "warn"),
        ("Camera stream active. Sending to ATLAS AI.", "info")],
    2: [("ETA next waypoint: 4m 12s.", "info"),
        ("Speed nominal. Altitude holding.", "ok"),
        ("Radar ping detected. Continuing mission.", "warn")],
    3: [("Standby mode. Awaiting mission upload.", "info")],
    4: [("Sector sweep complete. No contacts.", "ok"),
        ("Wind correction applied. Heading stable.", "info")],
    5: [("Low battery. 55% remaining.", "warn"),
        ("Target area reached. Entering loiter.", "ok")],
    6: [("Standby mode. Pre-flight checks complete.", "info")],
    7: [("Perimeter patrol nominal.", "ok"),
        ("Thermal signature detected. Flagging.", "warn")],
}

UGV_LOGS = {
    101: [("Patrol route Alpha complete. Restarting.", "ok"),
          ("Obstacle detected. Rerouting.", "warn")],
    102: [("Sector Bravo clear. Continuing patrol.", "ok"),
          ("Low traction surface. Reducing speed.", "info")],
    103: [("Sensor uplink nominal. All nodes reachable.", "ok")],
    104: [("Battery at 60%. Nominal.", "info"),
          ("Perimeter breach marker placed.", "warn")],
    105: [("Low battery. 45% — RTB recommended.", "warn"),
          ("Contact visual. Holding position.", "warn")],
}

def on_mavlink_packet(sys_id: int, data: dict):
    prev = telemetry_store.get(sys_id, {})
    telemetry_store[sys_id] = data
    prev_mode = prev.get('mode', '')
    curr_mode = data.get('mode', '')
    if prev_mode != curr_mode:
        if curr_mode == 'CHARGING':
            push_log(data['name'], f"Landed at HQ. Charging from {data['battery']}%.", "ok")
        elif curr_mode == 'STANDBY' and prev_mode == 'CHARGING':
            push_log(data['name'], "Fully charged. Ready for deployment.", "ok")
        elif curr_mode == 'RTB':
            push_log(data['name'], f"RTB initiated. Battery: {data['battery']}%.", "warn")
    bat      = data.get('battery', 100)
    prev_bat = prev.get('battery', 100)
    if prev_bat > 20 >= bat and data.get('armed'):
        push_log(data['name'], f"CRITICAL: Battery at {bat}%. Immediate RTB required.", "warn")
    elif prev_bat > 35 >= bat and data.get('armed'):
        push_log(data['name'], f"Low battery: {bat}%. RTB recommended.", "warn")
    if random.random() < 0.008:
        options = DRONE_LOGS.get(sys_id, [("Telemetry nominal.", "info")])
        msg, level = random.choice(options)
        push_log(data['name'], msg, level)

def on_ugv_packet(data: dict):
    prev = ugv_store.get(data['sys_id'], {})
    ugv_store[data['sys_id']] = data
    prev_mode = prev.get('mode', '')
    curr_mode = data.get('mode', '')
    if prev_mode != curr_mode:
        if curr_mode == 'CHARGING':
            push_log(data['name'], f"Docked at HQ. Charging from {data['battery']}%.", "ok")
        elif curr_mode == 'DOCKED' and prev_mode == 'CHARGING':
            push_log(data['name'], "Fully charged. Docked and ready.", "ok")
        elif curr_mode == 'RTB':
            push_log(data['name'], f"RTB initiated. Battery: {data['battery']}%.", "warn")
    bat      = data.get('battery', 100)
    prev_bat = prev.get('battery', 100)
    if prev_bat > 15 >= bat and data.get('armed'):
        push_log(data['name'], f"CRITICAL: Battery at {bat}%. Returning to base.", "warn")
    if random.random() < 0.006:
        options = UGV_LOGS.get(data['sys_id'], [("Ground telemetry nominal.", "info")])
        msg, level = random.choice(options)
        push_log(data['name'], msg, level)

async def _broadcast_threat(detection: dict):
    await broadcast(detection)
    push_log(detection['sensor_name'],
             f"[{detection['threat_class']}] {detection['message']} "
             f"Conf: {detection['confidence']}%",
             "warn")

def on_detection(detection: dict):
    if len(pending_threats) >= 3:
        return
    pending_threats[detection['id']] = detection
    loop = asyncio.get_event_loop()
    loop.create_task(_broadcast_threat(detection))

# ── Broadcast ─────────────────────────────────────────────────────────────────

async def broadcast(payload: dict):
    dead = set()
    msg  = json.dumps(payload)
    for ws in ws_clients:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    ws_clients.difference_update(dead)

# ── Background loops ──────────────────────────────────────────────────────────

async def telemetry_broadcast_loop():
    subtitles = {1:"Stealth Alpha",2:"Stealth Bravo",3:"Recon Charlie",
                 4:"Stealth Delta",5:"Scout Echo",6:"Reserve Foxtrot",7:"Perimeter Golf"}
    while True:
        if ws_clients and (telemetry_store or ugv_store):
            drones = [{
                "id": t["name"], "name": t["name"],
                "sub": f"UAV · {subtitles.get(sid,'')}",
                "type": "drone", "armed": t["armed"],
                "status": "active" if t["armed"] else "standby",
                "mode": t["mode"], "lat": t["lat"], "lon": t["lon"],
                "alt": t["alt"], "heading": t["heading"], "speed": t["speed"],
                "battery": t["battery"], "signal": t["signal"],
                "roll": t["roll"], "pitch": t["pitch"], "ts": t["ts"],
            } for sid, t in telemetry_store.items()]

            ugvs = [{
                "id": g["name"], "name": g["name"],
                "sub": f"UGV · Ground Unit",
                "type": "ugv", "armed": g["armed"],
                "status": "active" if g["armed"] else "docked",
                "mode": g["mode"], "lat": g["lat"], "lon": g["lon"],
                "alt": 0, "heading": g["heading"], "speed": g["speed"],
                "battery": g["battery"], "signal": g["signal"], "ts": g["ts"],
            } for g in ugv_store.values()]

            await broadcast({
                "type": "telemetry_batch", "ts": int(time.time()*1000),
                "drones": drones, "ugvs": ugvs, "static": STATIC_ASSETS,
            })
        await asyncio.sleep(0.5)

async def log_broadcast_loop():
    last_ts = 0
    while True:
        if ws_clients and event_log:
            new = [e for e in event_log if e["ts"] > last_ts]
            if new:
                last_ts = new[0]["ts"]
                await broadcast({"type": "log_batch", "entries": new})
        await asyncio.sleep(1.0)

async def adsb_broadcast_loop():
    """Broadcast ADS-B data to all clients every 30s (synced with fetch interval)."""
    last_broadcast_ts = 0
    while True:
        await asyncio.sleep(5)  # check every 5s, broadcast when data is fresh
        if not ws_clients:
            continue
        feed_ts = adsb_feed.last_updated
        if feed_ts > last_broadcast_ts and not adsb_feed.is_stale:
            aircraft = adsb_feed.aircraft
            await broadcast({
                "type":      "adsb_update",
                "ts":        int(feed_ts * 1000),
                "count":     len(aircraft),
                "aircraft":  aircraft,
                "status":    adsb_feed.status,
            })
            last_broadcast_ts = feed_ts
            if aircraft:
                push_log("ADS-B",
                         f"India FIR: {len(aircraft)} aircraft tracked. "
                         f"Feed: {adsb_feed.status.upper()}.",
                         "info")

# ── REST endpoints ────────────────────────────────────────────────────────────

START_TIME = time.time()

@app.get("/api/status")
def get_status():
    return {
        "server":           "ATLAS CORE v0.6",
        "uptime_s":         int(time.time() - START_TIME),
        "drones_active":    sum(1 for t in telemetry_store.values() if t.get("armed")),
        "drones_total":     len(telemetry_store),
        "ugvs_active":      sum(1 for g in ugv_store.values() if g.get("armed")),
        "ugvs_total":       len(ugv_store),
        "ws_clients":       len(ws_clients),
        "log_entries":      len(event_log),
        "missions":         len(missions),
        "pending_threats":  len(pending_threats),
        "adsb":             adsb_feed.get_summary(),
        "ts":               int(time.time()*1000),
    }

@app.get("/api/adsb")
def get_adsb():
    """Latest ADS-B snapshot — India FIR."""
    return {
        "aircraft": adsb_feed.aircraft,
        "summary":  adsb_feed.get_summary(),
    }

@app.get("/api/adsb/status")
def get_adsb_status():
    return adsb_feed.get_summary()

@app.get("/api/assets")
def get_assets():
    return {
        "drones": [{"id":t["name"],"type":"drone","status":"active" if t["armed"] else "standby",
                    "lat":t["lat"],"lon":t["lon"],"alt":t["alt"],"battery":t["battery"],
                    "speed":t["speed"],"heading":t["heading"],"mode":t["mode"]}
                   for t in telemetry_store.values()],
        "ugvs":   [{"id":g["name"],"type":"ugv","status":"active" if g["armed"] else "docked",
                    "lat":g["lat"],"lon":g["lon"],"battery":g["battery"],
                    "speed":g["speed"],"heading":g["heading"],"mode":g["mode"]}
                   for g in ugv_store.values()],
        "static": STATIC_ASSETS,
    }

@app.get("/api/telemetry/{drone_id}")
def get_telemetry(drone_id: int):
    t = telemetry_store.get(drone_id)
    return t if t else {"error": "not found"}

@app.get("/api/log")
def get_log(limit: int = 50):
    return {"entries": list(event_log)[:limit]}

@app.get("/api/missions")
def get_missions():
    return {"missions": missions}

@app.get("/api/threats")
def get_threats():
    return {"pending": list(pending_threats.values())}

@app.post("/api/missions")
async def post_mission(mission: dict):
    mission["id"] = f"MSN-{int(time.time())}"
    mission["created_ts"] = int(time.time()*1000)
    mission["status"] = "uploaded"
    missions.append(mission)
    drone_name = f"ATLAS-{mission.get('drone','D-01')}"
    wps = mission.get('waypoints', [])
    if sim: sim.assign_mission(drone_name, wps)
    push_log("MISSION CTRL", f"{mission.get('name','MSN')} → {drone_name}. {len(wps)} waypoints.", "ok")
    await broadcast({"type": "mission_ack", "mission": mission})
    return mission

@app.post("/api/rtb")
async def rtb_all_ep():
    count = sim.rtb_all() if sim else 0
    push_log("COMMAND", f"RTB ALL — {count} units returning to base.", "warn")
    await broadcast({"type": "rtb", "target": "ALL", "count": count})
    return {"status": "RTB issued", "units_affected": count}

@app.post("/api/rtb/{name}")
async def rtb_single_ep(name: str):
    ok = sim.rtb_single(f"ATLAS-{name}") if sim else False
    push_log("COMMAND", f"RTB → ATLAS-{name}.", "warn")
    await broadcast({"type": "rtb", "target": name})
    return {"status": "RTB issued" if ok else "failed", "target": name}

# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    ws_clients.add(ws)
    push_log("ATLAS CORE", "UI client connected.", "info")

    # Send init payload including ADS-B snapshot
    await ws.send_text(json.dumps({
        "type": "init",
        "assets": {
            "drones": [{"id":t["name"],"lat":t["lat"],"lon":t["lon"],
                        "alt":t["alt"],"battery":t["battery"],"armed":t["armed"]}
                       for t in telemetry_store.values()],
            "ugvs":   [{"id":g["name"],"lat":g["lat"],"lon":g["lon"],
                        "battery":g["battery"],"armed":g["armed"]}
                       for g in ugv_store.values()],
            "static": STATIC_ASSETS,
        },
        "log":              list(event_log)[:30],
        "missions":         missions,
        "pending_threats":  list(pending_threats.values()),
        "adsb": {
            "aircraft": adsb_feed.aircraft,
            "summary":  adsb_feed.get_summary(),
        },
    }))

    try:
        while True:
            raw = await ws.receive_text()
            await handle_ws_message(ws, json.loads(raw))
    except WebSocketDisconnect:
        ws_clients.discard(ws)

async def handle_ws_message(ws: WebSocket, msg: dict):
    mtype = msg.get("type")

    if mtype == "ping":
        await ws.send_text(json.dumps({"type":"pong","ts":int(time.time()*1000)}))

    elif mtype == "get_adsb":
        # Client explicitly requesting latest ADS-B data
        await ws.send_text(json.dumps({
            "type":     "adsb_update",
            "ts":       int(adsb_feed.last_updated * 1000),
            "count":    len(adsb_feed.aircraft),
            "aircraft": adsb_feed.aircraft,
            "status":   adsb_feed.status,
        }))

    elif mtype == "upload_mission":
        mission = msg.get("mission", {})
        mission["id"] = f"MSN-{int(time.time())}"
        mission["created_ts"] = int(time.time()*1000)
        mission["status"] = "uploaded"
        missions.append(mission)
        drone_name = f"ATLAS-{mission.get('drone','D-01')}"
        wps = mission.get("waypoints", [])
        if sim and wps: sim.assign_mission(drone_name, wps)
        push_log("MISSION CTRL",
                 f"{mission.get('name','MSN')} → {drone_name}. {len(wps)} waypoints.", "ok")
        await broadcast({"type": "mission_ack", "mission": mission})

    elif mtype == "deploy_drone":
        threat_id  = msg.get("threat_id") or ""
        drone_name = msg.get("drone_name")
        threat = pending_threats.get(threat_id)
        if not threat:
            await ws.send_text(json.dumps({"type":"error","msg":"Threat not found"}))
            return
        if not drone_name:
            drone_name = sim.get_available_drone() if sim else None
        if not drone_name:
            push_log("COMMAND", "DEPLOY FAILED — no available drones.", "warn")
            await broadcast({"type":"deploy_failed","threat_id":threat_id,"reason":"No available drones"})
            return
        if sim:
            sim.deploy_to_threat(drone_name, threat['threat_lat'], threat['threat_lon'], alt=200)
        if threat_id: pending_threats.pop(threat_id, None)
        push_log("COMMAND",
                 f"DEPLOY → {drone_name} → {threat['threat_class']} "
                 f"@ ({threat['threat_lat']}, {threat['threat_lon']}).", "ok")
        await broadcast({"type":"deploy_confirmed","threat_id":threat_id,
                          "drone_name":drone_name,"threat_lat":threat['threat_lat'],
                          "threat_lon":threat['threat_lon'],"threat_class":threat['threat_class']})

    elif mtype == "dismiss_threat":
        threat_id = msg.get("threat_id", "")
        if threat_id:
            threat = pending_threats.pop(threat_id, None)
            if threat:
                push_log("COMMAND", f"Threat {threat_id} dismissed.", "info")
        await broadcast({"type": "threat_dismissed", "threat_id": threat_id})

    elif mtype == "rtb":
        target = msg.get("target", "ALL")
        if target == "ALL":
            count = sim.rtb_all() if sim else 0
            push_log("COMMAND", f"RTB ALL — {count} units returning to base.", "warn")
            await broadcast({"type":"rtb","target":"ALL","count":count})
        else:
            ok = sim.rtb_single(f"ATLAS-{target}") if sim else False
            push_log("COMMAND", f"RTB → ATLAS-{target}.", "warn")
            await broadcast({"type":"rtb","target":target,"success":ok})

    elif mtype == "redeploy":
        target = msg.get("target", "")
        ok = False
        if sim and target:
            ok = sim.redeploy_ugv(target) or sim.arm_drone(target)
        push_log("COMMAND", f"REDEPLOY → {target}." if ok else f"REDEPLOY FAILED → {target}.", "ok" if ok else "warn")
        await broadcast({"type": "redeploy_ack", "target": target, "success": ok})

    elif mtype == "arm":
        target = msg.get("target", "")
        ok = sim.arm_drone(f"ATLAS-{target}") if sim else False
        push_log("COMMAND", f"ARM → ATLAS-{target}.", "ok" if ok else "warn")
        await broadcast({"type":"arm","target":target,"success":ok})

    elif mtype == "command":
        cmd = msg.get("command"); asset = msg.get("asset")
        push_log("COMMAND", f"CMD [{cmd}] → {asset}", "warn")
        await broadcast({"type":"command_ack","command":cmd,"asset":asset,"ts":int(time.time()*1000)})

# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    global sim
    loop = asyncio.get_event_loop()
    sim  = MAVLinkSimulator(on_packet=on_mavlink_packet,
                             on_ugv=on_ugv_packet,
                             on_detection=on_detection)
    loop.create_task(sim.run(hz=4.0))
    loop.create_task(telemetry_broadcast_loop())
    loop.create_task(log_broadcast_loop())
    loop.create_task(adsb_feed.run())           # Start ADS-B background fetcher
    loop.create_task(adsb_broadcast_loop())     # Broadcast ADS-B to clients
    print("=" * 55)
    print("  ATLAS OS BACKEND — v0.6")
    print("  WebSocket : ws://localhost:8000/ws")
    print("  REST API  : http://localhost:8000/api/")
    print("  ADS-B     : India FIR — OpenSky Network")
    print("=" * 55)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
