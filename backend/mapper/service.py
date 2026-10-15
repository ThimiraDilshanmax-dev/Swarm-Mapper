from __future__ import annotations
import asyncio
import json
import math
import secrets
import time
from collections import deque
from pathlib import Path
from uuid import uuid4
from fastapi import WebSocket
from .estimation import Estimator, interpolate_pose
from .graph import optimize_path
from .mapping import Grid
from .models import Closure, Profile, Telemetry
from .simulation import Simulator
from .storage import Store


class Conflict(ValueError):
    pass


class MapperService:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        profile_path = directory / "profile.json"
        self.profile = Profile.model_validate_json(profile_path.read_text(encoding="utf-8")) if profile_path.exists() else Profile()
        self.store = Store(directory)
        self.source = "simulator"
        self.sim = Simulator(self.profile)
        self.robot: WebSocket | None = None
        self.robot_info: dict = {}
        self.connected = True
        self.armed = False
        self.stop_latched = False
        self.mapping = "idle"
        self.estimator = Estimator(self.profile)
        self.grid = Grid(self.profile)
        self.path: list[list[float]] = []
        self.odom_path: list[list[float]] = []
        self.original_path: list[list[float]] = []
        self.optimization: dict | None = None
        self.session_id: str | None = None
        self.session_name = "Untitled survey"
        self.sample_index = 0
        self.recorded_distance = 0.0
        self.reading_id = 0
        self.last_frame: Telemetry | None = None
        self.latest_ranges: dict = {}
        self.sim_origin = self.sim.pose.tolist()
        self.needs_segment = False
        self.last_received = time.monotonic()
        self.last_seq = -1
        self.seq = 0
        self.state_seq = 0
        self.owner: str | None = None
        self.arm_token = ""
        self.last_input = 0.0
        self.drive = [0.0, 0.0]
        self.events = deque(maxlen=40)
        self.clients: dict[str, WebSocket] = {}
        self.replay: dict | None = None
        self.replay_samples: list[dict] = []
        self.replay_ranges: dict = {}
        self.replay_cursor = 0
        self.replay_profile: Profile | None = None
        self.replay_playing = False
        self.replay_speed = 1.0
        self.replay_clock = 0.0
        self.sim_speed = 1.0
        self.running = True
        self.working = False
        self.gaps = 0
        self.robot_token = self._token("robot-token")
        self.operator_token = self._token("operator-token")
        self.event("system", "Console ready. Simulator measurements are explicitly synthetic.")

    def _token(self, name: str) -> str:
        path = self.directory / name
        if not path.exists():
            path.write_text(secrets.token_urlsafe(30), encoding="utf-8")
        return path.read_text(encoding="utf-8").strip()

    def event(self, kind: str, message: str):
        self.events.appendleft(dict(t=time.time(), kind=kind, message=message))
        self.store.event(self.session_id, kind, message)

    def _free_to_change(self):
        if self.mapping in ("mapping", "paused") and self.session_id:
            raise Conflict("Finish the current session first")
        if self.working:
            raise Conflict("Wait for the current rebuild")

    def _reset_map(self, profile: Profile | None = None):
        p = profile or self.profile
        self.estimator, self.grid = Estimator(p), Grid(p)
        self.path, self.odom_path, self.original_path = [], [], []
        self.reading_id = 0
        self.optimization = None
        self.sample_index = 0
        self.recorded_distance = 0.0
        self.gaps = 0
        self.needs_segment = False

    async def command(self, state_change: bool = False):
        self.seq += 1
        if state_change:
            self.state_seq = self.seq
        if self.source != "robot" or not self.robot:
            return
        now = time.monotonic()
        robot_now = (self.last_frame.t if self.last_frame else 0) + max(0, now - self.last_received)
        payload = dict(type="command", seq=self.seq, boot_id=self.robot_info.get("boot_id"),
            deadline=robot_now + 0.18, armed=self.armed, stop_latched=self.stop_latched,
            arm_token=self.arm_token,
            mapping=self.mapping, v=self.drive[0] if self.armed else 0,
            omega=self.drive[1] if self.armed else 0,
            wheel_diameter=self.profile.wheel_diameter, wheel_base=self.profile.wheel_base,
            counts_per_revolution=self.profile.counts_per_revolution,
            left_scale=self.profile.left_scale, right_scale=self.profile.right_scale)
        try:
            await asyncio.wait_for(self.robot.send_json(payload), timeout=0.1)
        except (TimeoutError, RuntimeError, OSError):
            self.armed = False
            self.drive = [0, 0]

    async def stop(self, reason: str = "Motion stopped", latch: bool = False):
        self.armed = False
        self.drive = [0.0, 0.0]
        self.sim.demo = False
        self.sim_speed = 1.0
        if latch:
            self.stop_latched = True
        self.owner = None
        await self.command(True)
        self.event("stop", reason)

    def input(self, client: str, message: dict):
        if self.owner != client or not self.armed or self.replay:
            return
        try:
            v, w = float(message.get("v", 0)), float(message.get("omega", 0))
        except (ValueError, TypeError):
            return
        if not math.isfinite(v) or not math.isfinite(w):
            return
        self.drive = [max(-self.profile.max_speed, min(self.profile.max_speed, v)),
                      max(-self.profile.max_turn, min(self.profile.max_turn, w))]
        self.last_input = time.monotonic()

    async def action(self, kind: str, data: dict, client: str) -> dict:
        if self.working and kind not in ("stop", "estop"):
            raise Conflict("Map processing is in progress")
        if kind in ("stop", "estop"):
            await self.stop("Emergency stop latched" if kind == "estop" else "Operator stopped motion",
                            latch=kind == "estop")
        elif kind == "clear_stop":
            if self.source == "robot" and self.robot_info.get("physical_stop", False):
                raise Conflict("Release the physical stop first")
            self.stop_latched = False
            await self.command(True)
            self.event("system", "Stop cleared. Drive remains disarmed.")
        elif kind == "arm":
            if self.replay:
                raise Conflict("Robot control is disabled in replay")
            if self.optimization:
                raise Conflict("Start a new session before driving after map optimization")
            if not self.connected or self.stop_latched:
                raise Conflict("Connect a source and clear the stop before arming")
            if self.owner and self.owner != client:
                raise Conflict("Another console owns robot control")
            if self.source == "robot":
                if not self.profile.verified:
                    raise Conflict("Verify and save the hardware calibration first")
                if self.profile.tof_model == "unconfirmed":
                    raise Conflict("Confirm the ToF model in Calibration before hardware arming")
                if not self.last_frame or not self.last_frame.motor_enabled:
                    raise Conflict("Firmware inhibits motors; verify wiring and firmware configuration")
                if time.monotonic() - self.last_received > 0.4:
                    raise Conflict("Robot telemetry is stale")
            self.owner, self.armed, self.last_input = client, True, time.monotonic()
            self.arm_token = uuid4().hex
            self.drive = [0, 0]
            await self.command(True)
            self.event("control", "Drive armed for this console")
        elif kind == "source":
            self._free_to_change()
            source = data.get("source", "simulator")
            if source not in ("simulator", "robot"):
                raise ValueError("Unknown source")
            await self.stop("Source changed")
            if self.robot:
                previous_robot = self.robot
                self.robot = None
                await previous_robot.close(code=1000)
            self.source = source
            self.connected = self.source == "simulator"
            self.sim = Simulator(self.profile)
            if data.get("shape") in ("irregular", "box", "circle"):
                self.sim.shape = data["shape"]
                self.sim.polygon = self.sim.make_polygon()
            self.last_frame, self.last_seq = None, -1
            self.latest_ranges = {}
            self.sim_origin = [0,0,0]
            self.needs_segment = False
            self.mapping, self.session_id, self.replay = "idle", None, None
            self._reset_map()
            self.sim_origin = self.sim.pose.tolist()
            self.needs_segment = False
            self.event("source", "Simulator connected" if self.connected else "Waiting for authenticated ESP32")
        elif kind in ("start", "demo"):
            self._free_to_change()
            if self.replay:
                raise Conflict("Return to Live before starting a session")
            if not self.connected:
                raise Conflict("Connect the robot first")
            if kind == "demo" and self.source != "simulator":
                raise Conflict("Sample surveys are available only in simulation")
            initial_profile = self.profile.model_copy(deep=True)
            if self.estimator.stationary_samples >= 30:
                initial_profile.gyro_bias = self.estimator.bias
            await self.stop("Preparing a new survey")
            if kind == "demo":
                self.sim = Simulator(self.profile)
                self.last_frame, self.last_seq = None, -1
            self._reset_map(initial_profile)
            self.mapping = "mapping"
            self.sim_origin = self.sim.pose.tolist()
            self.needs_segment = False
            self.session_id = uuid4().hex[:12]
            self.session_name = str(data.get("name", "Survey " + time.strftime("%H:%M")))[:100] or "Untitled survey"
            self.store.create(self.session_id, self.session_name, self.source, initial_profile.model_dump())
            self.event("mapping", "Mapping started; original samples are being recorded")
            if kind == "demo":
                self.sim.demo = True
                self.sim_speed = 4
                self.armed, self.owner, self.last_input = True, client, time.monotonic()
                self.event("simulation", "Synthetic sample survey running at 4× simulation time")
            await self.command(True)
        elif kind == "pause":
            if self.mapping != "mapping":
                raise Conflict("No active map to pause")
            await self.stop("Mapping paused and motion stopped")
            self.mapping = "paused"
            await self.command(True)
            self.store.finish(self.session_id, "paused", self.summary())
        elif kind == "resume":
            if self.needs_segment:
                raise Conflict("Robot pose continuity was lost; finish and start a new session")
            if self.mapping != "paused" or not self.connected or self.replay:
                raise Conflict("No connected paused session to resume")
            self.mapping = "mapping"
            await self.command(True)
            self.store.finish(self.session_id, "mapping", self.summary())
            self.event("mapping", "Mapping resumed; drive remains disarmed")
        elif kind == "finish":
            await self.finish()
        elif kind == "profile":
            self._free_to_change()
            profile = Profile.model_validate(data["profile"])
            await self.stop("Calibration changed; drive disarmed")
            self.profile = profile
            (self.directory / "profile.json").write_text(self.profile.model_dump_json(indent=2), encoding="utf-8")
            self.sim = Simulator(self.profile)
            self.mapping, self.session_id, self.replay = "idle", None, None
            self.last_frame, self.last_seq = None, -1
            self.latest_ranges = {}
            self.sim_origin = self.sim.pose.tolist()
            self._reset_map()
            self.event("calibration", "Calibration profile saved")
        elif kind == "replay":
            self._free_to_change()
            session = self.store.get(data["id"])
            profile = Profile.model_validate(data.get("profile", session["profile"]))
            await self.stop("Replay opened; motion output disabled")
            self.replay = {k: v for k, v in session.items() if k != "samples_data"}
            self.replay["override"] = "profile" in data
            self.replay_samples = session["samples_data"]
            self.replay_profile = profile
            self.session_id = None
            await self.seek(len(self.replay_samples))
            self.event("replay", "Recorded session opened. Replay cannot command the robot.")
        elif kind == "seek":
            if not self.replay:
                raise Conflict("Open a recording first")
            await self.seek(int(data.get("index", 0)))
        elif kind == "play":
            if not self.replay:
                raise Conflict("Open a recording first")
            self.replay_speed = max(0.25, min(4, float(data.get("speed", self.replay_speed))))
            if self.replay_cursor >= len(self.replay_samples):
                await self.seek(0)
            if self.replay_samples:
                self.replay_clock = self.replay_samples[max(0,self.replay_cursor-1)]["frame"]["t"]
            self.replay_playing = not self.replay_playing
        elif kind == "replay_speed":
            if not self.replay:
                raise Conflict("Open a recording first")
            self.replay_speed = max(0.25,min(4,float(data.get("speed",1))))
        elif kind == "live":
            self._free_to_change()
            await self.stop("Returned to Live")
            self.replay, self.replay_samples, self.replay_playing = None, [], False
            self.session_id, self.mapping = None, "idle"
            self._reset_map()
            self.last_frame, self.last_seq = None, -1
            self.sim_origin = self.sim.pose.tolist()
        elif kind == "optimize":
            if self.mapping in ("mapping", "paused"):
                raise Conflict("Finish the session before optimization")
            if len(self.path) < 10:
                raise Conflict("Record or open a session first")
            closure = Closure.model_validate(data.get("closure", {}))
            if not closure.confirmed or not closure.note.strip():
                raise ValueError("A confirmed, documented physical endpoint reference is required")
            await self.stop("Pose graph correction started; drive disarmed")
            self.working = True
            try:
                original = self.original_path or self.path
                corrected, result = await asyncio.to_thread(optimize_path, original, closure)
                session = self.replay if self.replay else self.store.get(self.session_id)
                samples = self.replay_samples if self.replay else session["samples_data"]
                p = self.grid.profile
                rebuilt = await asyncio.to_thread(self._rebuild_corrected, p, samples, original, corrected)
                self.original_path, self.path, self.grid, self.optimization = original, corrected, rebuilt, result
                sid = self.replay["id"] if self.replay else self.session_id
                if sid:
                    self.store.result(sid, dict(**result, profile=p.model_dump()))
                self.event("optimization", "Map rebuilt using a documented surveyed endpoint; global accuracy remains to be validated")
            finally:
                self.working = False
        elif kind == "annotate":
            sid = self.replay["id"] if self.replay else self.session_id
            if not sid:
                raise Conflict("Record or open a session first")
            note = str(data.get("note", "")).strip()[:2000]
            self.store.note(sid, note)
            if self.replay:
                self.replay["note"] = note
            self.event("annotation", note or "Session note cleared")
        else:
            raise ValueError("Unknown action")
        return {"ok": True}

    async def finish(self):
        if self.mapping not in ("mapping", "paused") or not self.session_id:
            raise Conflict("There is no active session to finish")
        await self.stop("Survey finished; motors disarmed")
        self.mapping = "finished"
        self.sim_speed = 1
        await self.command(True)
        self.store.finish(self.session_id, "finished", self.summary())
        self.event("mapping", "Session saved")

    def process(self, frame: Telemetry, integrate: bool, record: bool = True):
        if not self.estimator.update(frame.t, frame.left, frame.right, frame.gyro_z):
            return
        pose = self.estimator.pose.tolist()
        if self.mapping in ("mapping", "paused") or not record:
            self.path.append([frame.t, *pose])
            self.odom_path.append([frame.t, *self.estimator.odom.tolist()])
            self.recorded_distance = self.estimator.distance
        if not record:
            for sample in frame.ranges:
                self.replay_ranges[sample.sensor] = sample.model_dump()
        if integrate:
            for sample in frame.ranges:
                self.reading_id += 1
                self.grid.integrate(sample, self.estimator.at(sample.t), self.reading_id)
        if record and self.session_id and self.mapping in ("mapping", "paused"):
            self.store.sample(self.session_id, self.sample_index,
                              dict(frame=frame.model_dump(), integrate=integrate))
            self.sample_index += 1

    async def ingest(self, frame: Telemetry):
        if frame.seq <= self.last_seq:
            return
        if self.last_seq >= 0 and frame.seq > self.last_seq + 1:
            if not self.replay and self.mapping in ("mapping", "paused"):
                self.gaps += frame.seq - self.last_seq - 1
            self.event("gap", "Missing telemetry frames: " + str(frame.seq - self.last_seq - 1))
        self.last_received, self.last_seq, self.last_frame = time.monotonic(), frame.seq, frame
        for sample in frame.ranges:
            self.latest_ranges[sample.sensor] = sample.model_dump()
        if self.replay or self.working:
            return
        self.robot_info["physical_stop"] = frame.physical_stop
        if self.source=="robot" and self.armed and not frame.motor_enabled:
            await self.stop("Robot reports hardware inhibition; inspect sensors and firmware")
        if self.source=="robot" and self.armed and frame.ack >= self.state_seq and not frame.armed:
            await self.stop("Robot stopped locally; explicit operator rearming required")
        if self.source == "robot" and frame.stop_latched and not self.stop_latched:
            await self.stop("Robot reported a latched stop", latch=True)
        if self.needs_segment:
            return
        integrate = self.mapping == "mapping" and (self.source != "robot" or frame.mapping == "mapping")
        try:
            self.process(frame, integrate)
        except ValueError as exc:
            self.needs_segment = True
            await self.stop(str(exc))
            if self.mapping == "mapping":
                self.mapping = "paused"
                await self.command(True)

    async def seek(self, index: int):
        self.working = True
        self.replay_playing = False
        try:
            count = max(0, min(index, len(self.replay_samples)))
            profile = self.replay_profile or self.profile
            estimator, grid, path, odom, reading_id = await asyncio.to_thread(self._rebuild_replay, profile, self.replay_samples[:count])
            self.estimator, self.grid, self.path, self.odom_path = estimator, grid, path, odom
            self.original_path, self.optimization = [], None
            self.reading_id, self.replay_cursor = reading_id, count
            self.sample_index = count
            self.recorded_distance = estimator.distance
            self.replay_ranges = {}
            for entry in self.replay_samples[:count]:
                for sample in entry["frame"]["ranges"]:
                    self.replay_ranges[sample["sensor"]] = sample
            self.gaps = sum(max(0,b["frame"]["seq"]-a["frame"]["seq"]-1)
                            for a,b in zip(self.replay_samples[:count],self.replay_samples[1:count]))
            self.mapping = "finished"
        finally:
            self.working = False

    @staticmethod
    def _rebuild_replay(profile, samples):
        estimator, grid = Estimator(profile), Grid(profile)
        path, odom, rid = [], [], 0
        for entry in samples:
            frame = Telemetry.model_validate(entry["frame"])
            if not estimator.update(frame.t, frame.left, frame.right, frame.gyro_z):
                continue
            path.append([frame.t, *estimator.pose.tolist()])
            odom.append([frame.t, *estimator.odom.tolist()])
            if entry["integrate"]:
                for r in frame.ranges:
                    rid += 1
                    grid.integrate(r, estimator.at(r.t), rid)
        return estimator, grid, path, odom, rid

    @staticmethod
    def _rebuild_corrected(profile, samples, original, corrected):
        grid, rid, index = Grid(profile), 0, 0
        for entry in samples:
            frame = entry["frame"]
            if not entry["integrate"]:
                continue
            for raw in frame["ranges"]:
                from .models import RangeSample
                r = RangeSample.model_validate(raw)
                while index < len(corrected)-2 and corrected[index+1][0] < r.t:
                    index += 1
                a, b = corrected[index], corrected[min(index+1, len(corrected)-1)]
                pose = interpolate_pose(a[1:4], b[1:4], (r.t-a[0])/max(1e-9,b[0]-a[0]))
                rid += 1
                grid.integrate(r, pose, rid)
        return grid

    def summary(self):
        return dict(distance=round(self.recorded_distance, 3), readings=self.grid.accepted+self.grid.rejected,
                    accepted=self.grid.accepted, rejected=self.grid.rejected, frames=self.sample_index,
                    duration=self.path[-1][0]-self.path[0][0] if len(self.path)>1 else 0, gaps=self.gaps)

    def snapshot(self):
        age = max(0, time.monotonic() - self.last_received)
        frame = self.last_frame
        led = "red" if self.stop_latched else ("blue" if not self.connected else (
            "cyan" if self.mapping == "mapping" else "amber" if self.mapping == "paused" else "green"))
        p = self.replay_profile if self.replay else self.profile
        return dict(type="state", source=self.source, connected=self.connected, armed=self.armed,
            owner=self.owner, stop_latched=self.stop_latched, mapping=self.mapping, led=led,
            age=round(age,3), robot=self.robot_info, ack=frame.ack if frame else -1,
            pending_ack=self.source=="robot" and (not frame or frame.ack<self.state_seq),
            pose=(self.path[-1][1:4] if self.path else [0,0,0]) if self.replay or self.optimization else self.estimator.pose.tolist(),
            velocity=self.estimator.velocity,
            covariance=np_diag(self.estimator.cov), gyro_bias=self.estimator.bias,
            kalman=dict(innovation=getattr(self.estimator,"innovation",0),
                        bias_gain=getattr(self.estimator,"kalman_gain",0),
                        bias_variance=float(self.estimator.cov[3,3])),
            disagreement=self.estimator.disagreement, path=self.path[::max(1,len(self.path)//1800)],
            odom_path=self.odom_path[::max(1,len(self.odom_path)//1800)],
            original_path=self.original_path[::max(1,len(self.original_path)//1800)],
            grid=self.grid.payload(), readings=self.grid.readings[-120:], events=list(self.events)[:15],
            summary=self.summary(), profile=(p or self.profile).model_dump(), robot_profile=self.profile.model_dump(), session_id=self.session_id,
            session_name=self.replay["name"] if self.replay else self.session_name,
            replay=dict(id=self.replay["id"], note=self.replay.get("note",""), override=self.replay.get("override",False),
                        cursor=self.replay_cursor, total=len(self.replay_samples),
                        playing=self.replay_playing, speed=self.replay_speed) if self.replay else None,
            optimization=self.optimization, working=self.working,
            reference=self.reference_polygon() if self.source=="simulator" and not self.replay else None,
            demo=self.sim.demo, sim_speed=self.sim_speed,
            measurement_source=self.replay["source"] if self.replay else self.source,
            range_time=(self.replay_samples[self.replay_cursor-1]["frame"]["t"] if self.replay_cursor else 0)
                if self.replay else (frame.t if frame else 0),
            live_ranges=list((self.replay_ranges if self.replay else self.latest_ranges).values()), needs_segment=self.needs_segment)

    def reference_polygon(self):
        x,y,t = self.sim_origin
        c,s = math.cos(t), math.sin(t)
        return [[c*(px-x)+s*(py-y), -s*(px-x)+c*(py-y)] for px,py in self.sim.polygon]

    async def loop(self):
        broadcast_at = time.monotonic()
        previous_tick = broadcast_at
        while self.running:
            started = time.monotonic()
            elapsed = max(0,min(.25,started-previous_tick))
            previous_tick = started
            if self.armed and started-self.last_input > 0.3 and not (self.source=="simulator" and self.sim.demo):
                await self.stop("Control heartbeat expired; drive disarmed")
            if self.source == "robot" and self.connected and started-self.last_received > 0.5:
                self.connected = False
                await self.stop("Robot telemetry lost; local firmware watchdog also stops motion")
                if self.mapping=="mapping":
                    self.mapping="paused"
            if self.source == "simulator" and not self.replay and not self.working:
                frame = self.sim.step(0.05*self.sim_speed, *self.drive, self.armed,
                                      self.mapping, self.stop_latched, self.seq)
                await self.ingest(frame)
                if self.sim.demo_done and self.mapping=="mapping":
                    await self.finish()
            if self.replay and self.replay_playing and not self.working:
                self.replay_clock += elapsed*self.replay_speed
                for _ in range(30):
                    if self.replay_cursor >= len(self.replay_samples):
                        self.replay_playing = False
                        break
                    entry = self.replay_samples[self.replay_cursor]
                    if entry["frame"]["t"]>self.replay_clock:
                        break
                    self.process(Telemetry.model_validate(entry["frame"]), entry["integrate"], False)
                    if self.replay_cursor:
                        self.gaps += max(0,entry["frame"]["seq"]-self.replay_samples[self.replay_cursor-1]["frame"]["seq"]-1)
                    self.replay_cursor += 1
                    self.sample_index = self.replay_cursor
            if self.source=="robot" and self.connected:
                await self.command()
            if started >= broadcast_at:
                broadcast_at = started + 0.2
                payload = self.snapshot()
                for cid, ws in list(self.clients.items()):
                    try:
                        await asyncio.wait_for(ws.send_json(payload), timeout=0.12)
                    except (TimeoutError, RuntimeError, OSError):
                        self.clients.pop(cid, None)
                        if self.owner==cid:
                            await self.stop("Controller disconnected")
            await asyncio.sleep(max(0.005, 0.05-(time.monotonic()-started)))


def np_diag(cov):
    return [float(cov[i,i]) for i in range(3)]
