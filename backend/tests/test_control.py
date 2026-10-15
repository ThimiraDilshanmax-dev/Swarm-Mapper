import asyncio
import time
import pytest
from mapper.models import Profile, RangeSample, Telemetry
from mapper.service import Conflict, MapperService


def frame(seq,t,left=0,right=0,**kwargs):
    return Telemetry(seq=seq,t=t,left=left,right=right,gyro_z=0,**kwargs)


def test_stale_operator_heartbeat_disarms(tmp_path):
    async def scenario():
        s=MapperService(tmp_path)
        try:
            await s.action("arm",{},"test")
            s.last_input=time.monotonic()-1
            task=asyncio.create_task(s.loop())
            await asyncio.sleep(.12)
            s.running=False
            await task
            assert not s.armed
            assert s.drive==[0,0]
            assert any("heartbeat" in e["message"] for e in s.events)
        finally:s.store.close()
    asyncio.run(scenario())


def test_second_controller_cannot_take_armed_lease(tmp_path):
    async def scenario():
        s=MapperService(tmp_path)
        try:
            await s.action("arm",{},"first")
            with pytest.raises(Conflict,match="owns"):
                await s.action("arm",{},"second")
            s.input("second",dict(v=.1,omega=.2))
            assert s.drive==[0,0]
        finally:s.store.close()
    asyncio.run(scenario())


def test_software_stop_clears_but_physical_contact_blocks_clear(tmp_path):
    async def scenario():
        s=MapperService(tmp_path)
        try:
            await s.action("estop",{},"test")
            assert s.stop_latched and not s.armed
            await s.action("clear_stop",{},"test")
            assert not s.stop_latched and not s.armed
            s.source="robot";s.robot_info["physical_stop"]=True
            await s.action("estop",{},"test")
            with pytest.raises(Conflict,match="physical"):
                await s.action("clear_stop",{},"test")
        finally:s.store.close()
    asyncio.run(scenario())


def test_discontinuity_pauses_and_requires_new_segment(tmp_path):
    async def scenario():
        s=MapperService(tmp_path)
        try:
            await s.action("start",{},"test")
            await s.ingest(frame(0,1,10000,10000))
            await s.ingest(frame(1,1.05,0,0))
            assert s.needs_segment and s.mapping=="paused"
            with pytest.raises(Conflict,match="continuity"):
                await s.action("resume",{},"test")
            await s.action("finish",{},"test")
            await s.action("start",{},"test")
            assert not s.needs_segment
        finally:s.store.close()
    asyncio.run(scenario())


def test_finish_freezes_recorded_path_while_idle_telemetry_continues(tmp_path):
    async def scenario():
        s=MapperService(tmp_path)
        try:
            await s.action("start",{},"test")
            await s.ingest(frame(0,1))
            await s.ingest(frame(1,1.05,10,10))
            await s.action("finish",{},"test")
            count=len(s.path)
            duration=s.summary()["duration"]
            await s.ingest(frame(2,1.1,10,10))
            assert len(s.path)==count
            assert s.summary()["duration"]==duration
        finally:s.store.close()
    asyncio.run(scenario())


def test_stationary_bias_is_saved_as_session_initial_condition(tmp_path):
    async def scenario():
        s=MapperService(tmp_path)
        try:
            for i in range(100):
                s.estimator.update(i*.01,0,0,.015)
            learned=s.estimator.bias
            assert abs(learned-.015)<.002
            await s.action("start",{},"test")
            assert s.estimator.bias==learned
            saved=s.store.get(s.session_id)
            assert saved["profile"]["gyro_bias"]==learned
        finally:s.store.close()
    asyncio.run(scenario())
