import time
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from mapper.app import create_app
from mapper.models import Profile


def test_paired_robot_batch_and_velocity_protocol(tmp_path):
    app=create_app(tmp_path)
    service=app.state.mapper
    with TestClient(app) as client:
        client.get("/api/bootstrap")
        with client.websocket_connect("/ws/ui") as ui:
            welcome=ui.receive_json()
            while welcome["type"]!="welcome":
                welcome=ui.receive_json()
            cid=welcome["client_id"]
            def action(kind,**data):
                return client.post("/api/action",json=dict(action=kind,client_id=cid,**data))
            assert action("profile",profile=Profile(verified=True,tof_model="VL53L1X").model_dump()).status_code==200
            assert action("source",source="robot").status_code==200
            with client.websocket_connect("/ws/robot",headers={"Authorization":"Bearer "+service.robot_token}) as robot:
                robot.send_json(dict(type="hello",protocol=2,robot_id="master",boot_id="test-boot",
                                     firmware="test",tof_models=["VL53L1X"]*3,motors_enabled=True))
                received=robot.receive_json()
                while received.get("type")!="welcome":
                    received=robot.receive_json()
                frames=[dict(type="telemetry",seq=i,t=10+i*.01,left=0,right=0,gyro_z=0,
                             motor_enabled=True,ranges=[]) for i in range(5)]
                # A malformed packet must not end an otherwise authenticated link.
                robot.send_json([])
                robot.send_json(dict(type="batch",frames=[]))
                robot.send_json(dict(type="batch",frames=frames))
                time.sleep(.025)
                assert action("arm").status_code==200
                ui.send_json(dict(type="drive",v=.1,omega=.2))
                received=robot.receive_json()
                for _ in range(20):
                    if received.get("armed") and received.get("v")==.1:
                        break
                    received=robot.receive_json()
                assert received["v"]==.1 and received["omega"]==.2
                assert received["boot_id"]=="test-boot"
                assert 10 < received["deadline"] < 10.6
                assert received["counts_per_revolution"]==1440
                assert len(received["arm_token"])==32
                assert service.last_seq==4
                ui.send_json(dict(type="stop"))
                for _ in range(20):
                    received=robot.receive_json()
                    if received.get("type")=="command" and not received["armed"]:
                        break
                assert not received["armed"] and received["v"]==0
            assert not service.armed


def test_unauthenticated_robot_close_code(tmp_path):
    app=create_app(tmp_path)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as caught:
            with client.websocket_connect("/ws/robot"):
                pass
        assert caught.value.code==4401


def test_old_firmware_protocol_is_rejected_with_explanation(tmp_path):
    app=create_app(tmp_path)
    service=app.state.mapper
    service.source="robot"
    with TestClient(app) as client:
        with client.websocket_connect("/ws/robot",headers={"Authorization":"Bearer "+service.robot_token}) as robot:
            robot.send_json(dict(type="hello",protocol=1,robot_id="master",boot_id="old-firmware"))
            with pytest.raises(WebSocketDisconnect) as caught:
                robot.receive_json()
            assert caught.value.code==4400
        assert any("protocol 2" in event["message"] for event in service.events)
