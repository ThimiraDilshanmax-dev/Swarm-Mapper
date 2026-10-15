import asyncio
import io
import json
import time
import zipfile
import pytest
from fastapi.testclient import TestClient
from mapper.app import create_app
from mapper.models import Profile
from mapper.service import Conflict, MapperService


def test_auth_record_replay_and_export_bundle(tmp_path):
    app=create_app(tmp_path)
    with TestClient(app) as client:
        assert client.get("/api/state").status_code==401
        assert client.get("/api/bootstrap").status_code==200
        with client.websocket_connect("/ws/ui") as ws:
            message=ws.receive_json()
            while message["type"]!="welcome":
                message=ws.receive_json()
            cid=message["client_id"]
            def action(kind,**data):
                return client.post("/api/action",json=dict(action=kind,client_id=cid,**data))
            assert action("start",name="Integration survey").status_code==200
            time.sleep(.25)
            assert action("finish").status_code==200
            sessions=client.get("/api/sessions").json()
            assert sessions[0]["samples"]>=2
            sid=sessions[0]["id"]
            result=client.get("/api/export/"+sid+"/zip")
            assert result.status_code==200
            with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
                assert {"session.json","measurements.csv","map.png","map.pgm","map.yaml","boundary.svg"}<=set(archive.namelist())
                assert archive.read("map.png").startswith(b"\x89PNG")
                assert json.loads(archive.read("session.json"))["profile"]["counts_per_revolution"]==1440
            assert action("replay",id=sid).status_code==200
            assert action("arm").status_code==409
            assert action("seek",index=1).status_code==200
            assert client.get("/api/state").json()["replay"]["cursor"]==1
            assert action("replay_speed",speed=4).status_code==200
            assert action("play").status_code==200
            assert client.get("/api/state").json()["replay"]["speed"]==4
            assert action("live").status_code==200


def test_controller_disconnect_disarms(tmp_path):
    app=create_app(tmp_path)
    with TestClient(app) as client:
        client.get("/api/bootstrap")
        with client.websocket_connect("/ws/ui") as ws:
            message=ws.receive_json()
            while message["type"]!="welcome":
                message=ws.receive_json()
            assert client.post("/api/action",json={"action":"arm","client_id":message["client_id"]}).status_code==200
        time.sleep(.08)
        assert not client.get("/api/state").json()["armed"]


def test_hardware_requires_verified_calibration_and_motor_permission(tmp_path):
    async def scenario():
        s=MapperService(tmp_path)
        try:
            s.source="robot";s.connected=True
            with pytest.raises(Conflict,match="calibration"):
                await s.action("arm",{},"operator")
            s.profile=Profile(verified=True,tof_model="VL53L1X")
            with pytest.raises(Conflict,match="inhibits"):
                await s.action("arm",{},"operator")
        finally:
            s.store.close()
    asyncio.run(scenario())


def test_websocket_robot_requires_pairing_token(tmp_path):
    app=create_app(tmp_path)
    with TestClient(app) as client:
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/robot"):
                pass
