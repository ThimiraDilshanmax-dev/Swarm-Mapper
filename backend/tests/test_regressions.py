"""Regressions found while reviewing real motion, replay, and failure handling."""
import asyncio
import math
import struct
import zlib

import numpy as np
import pytest
from fastapi.testclient import TestClient

from mapper.app import create_app, png_bytes
from mapper.estimation import Estimator
from mapper.mapping import Grid
from mapper.models import Profile, RangeSample, Telemetry
from mapper.service import MapperService


def test_slow_quantized_turn_is_not_learned_as_stationary_bias():
    p=Profile()
    e=Estimator(p)
    metres_per_count=math.pi*p.wheel_diameter/p.counts_per_revolution
    rate=.04
    for i in range(1501):
        t=i*.01
        ticks=round(rate*p.wheel_base*t/(2*metres_per_count))
        e.update(t,-ticks,ticks,rate)
    assert abs(e.bias)<.003
    assert abs(e.pose[2]-rate*15)<.025


def test_pose_lookup_before_first_sample_uses_earliest_pose():
    e=Estimator(Profile())
    for i in range(10):
        e.update(1+i*.01,i*10,i*10,0)
    assert e.at(.98)==[0,0,0]
    assert e.at(.8) is None


def test_one_return_counts_as_one_independent_boundary_observation():
    g=Grid(Profile(target_side="all"))
    g.integrate(RangeSample(sensor="front",t=1,distance=.2),[0,0,0],1)
    assert g.hits.max()==1
    assert not g.boundary()


def test_png_retains_uncertain_cells_as_gray():
    g=Grid(Profile())
    g.integrate(RangeSample(sensor="front",t=1,distance=1),[0,0,0],1)
    png=png_bytes(g)
    offset=8
    compressed=b""
    while offset<len(png):
        size=struct.unpack(">I",png[offset:offset+4])[0]
        if png[offset+4:offset+8]==b"IDAT":
            compressed+=png[offset+8:offset+8+size]
        offset+=size+12
    pixels=np.frombuffer(zlib.decompress(compressed),dtype=np.uint8).reshape(g.n,g.n+1)[:,1:]
    row,column=g.cell(.5,0)
    assert pixels[g.n-1-row,column]==222


def test_invalid_source_does_not_change_current_source(tmp_path):
    async def scenario():
        s=MapperService(tmp_path)
        try:
            with pytest.raises(ValueError,match="source"):
                await s.action("source",{"source":"invalid"},"test")
            assert s.source=="simulator" and s.connected
        finally:s.store.close()
    asyncio.run(scenario())


def test_finished_summary_is_not_changed_by_later_motion_or_gaps(tmp_path):
    async def scenario():
        s=MapperService(tmp_path)
        try:
            await s.action("start",{},"test")
            for i in range(3):
                await s.ingest(Telemetry(seq=i,t=1+i*.05,left=i*10,right=i*10,gyro_z=0))
            await s.finish()
            original=s.summary()
            await s.ingest(Telemetry(seq=5,t=1.2,left=100,right=100,gyro_z=0))
            assert s.summary()==original
        finally:s.store.close()
    asyncio.run(scenario())


def test_optimization_disarms_before_starting_the_solver(tmp_path,monkeypatch):
    async def scenario():
        s=MapperService(tmp_path)
        try:
            await s.action("start",{},"test")
            for i in range(12):
                await s.ingest(Telemetry(seq=i,t=1+i*.05,left=i*10,right=i*10,gyro_z=0))
            await s.finish()
            await s.action("arm",{},"test")
            s.input("test",dict(v=.1,omega=0))
            def solver(*args):
                assert not s.armed and s.drive==[0,0]
                raise ValueError("test solver failure")
            monkeypatch.setattr("mapper.service.optimize_path",solver)
            with pytest.raises(ValueError,match="test solver failure"):
                await s.action("optimize",{"closure":{"confirmed":True,"note":"Measured fixture"}},"test")
            assert not s.armed
        finally:s.store.close()
    asyncio.run(scenario())


def test_replay_sensor_panel_uses_recorded_ranges_and_saves_notes(tmp_path):
    async def scenario():
        s=MapperService(tmp_path)
        try:
            await s.action("start",{},"test")
            await s.ingest(Telemetry(seq=0,t=1,left=0,right=0,gyro_z=0,
                ranges=[RangeSample(sensor="left",t=1,distance=.7)]))
            await s.finish()
            sid=s.session_id
            s.profile=s.profile.model_copy(update={"name":"Current physical robot"})
            s.latest_ranges={"left":RangeSample(sensor="left",t=2,distance=1.8).model_dump()}
            await s.action("replay",{"id":sid},"test")
            assert s.snapshot()["robot_profile"]["name"]=="Current physical robot"
            assert s.snapshot()["profile"]["name"]!="Current physical robot"
            assert s.snapshot()["live_ranges"][0]["distance"]==.7
            await s.action("annotate",{"note":"Low light"},"test")
            assert s.snapshot()["replay"]["note"]=="Low light"
            await s.action("seek",{"index":0},"test")
            assert not s.snapshot()["live_ranges"]
        finally:s.store.close()
    asyncio.run(scenario())


def test_robot_reported_watchdog_disarm_requires_operator_rearming(tmp_path):
    async def scenario():
        s=MapperService(tmp_path)
        try:
            s.source="robot";s.connected=True
            s.profile=Profile(verified=True,tof_model="VL53L1X")
            await s.ingest(Telemetry(seq=0,t=1,left=0,right=0,gyro_z=0,motor_enabled=True))
            await s.action("arm",{},"test")
            token=s.arm_token
            ack=s.state_seq
            await s.ingest(Telemetry(seq=1,t=1.01,left=0,right=0,gyro_z=0,
                motor_enabled=True,armed=False,ack=ack))
            assert not s.armed and s.drive==[0,0]
            await s.action("arm",{},"test")
            assert s.armed and s.arm_token!=token
        finally:s.store.close()
    asyncio.run(scenario())


def test_regressing_acquisition_time_pauses_mapping_and_disarms(tmp_path):
    async def scenario():
        s=MapperService(tmp_path)
        try:
            await s.action("start",{},"test")
            await s.ingest(Telemetry(seq=0,t=2,left=0,right=0,gyro_z=0))
            await s.action("arm",{},"test")
            await s.ingest(Telemetry(seq=1,t=1,left=0,right=0,gyro_z=0))
            assert s.needs_segment and s.mapping=="paused" and not s.armed
            assert s.sample_index==1
            await s.finish()
            await s.action("profile",{"profile":s.profile.model_dump()},"test")
            assert not s.needs_segment
        finally:s.store.close()
    asyncio.run(scenario())


def test_malformed_action_body_returns_validation_error(tmp_path):
    with TestClient(create_app(tmp_path),raise_server_exceptions=False) as client:
        client.get("/api/bootstrap")
        assert client.post("/api/action",json=[]).status_code==422


def test_imported_profile_is_validated_without_changing_saved_profile(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        client.get("/api/bootstrap")
        original=client.get("/api/profile").json()
        assert client.post("/api/profile/validate",json={"sensors":[None]*3}).status_code==422
        valid=Profile(name="Imported robot").model_dump()
        result=client.post("/api/profile/validate",json=valid)
        assert result.status_code==200 and result.json()["name"]=="Imported robot"
        assert client.get("/api/profile").json()==original


def test_unicode_profile_survives_windows_save_and_restart(tmp_path):
    name="Robot · පරීක්ෂණ"
    first=MapperService(tmp_path)
    try:
        asyncio.run(first.action("profile",{"profile":Profile(name=name).model_dump()},"test"))
    finally:first.store.close()
    second=MapperService(tmp_path)
    try:assert second.profile.name==name
    finally:second.store.close()
