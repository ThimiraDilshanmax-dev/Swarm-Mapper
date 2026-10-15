import shutil
import subprocess
from pathlib import Path

import pytest


def test_actual_firmware_arm_guard_on_host(tmp_path):
    compiler=shutil.which("g++")
    if not compiler:
        pytest.skip("Optional host C++ compiler not installed")
    root=Path(__file__).resolve().parents[2]
    executable=tmp_path/"arm_guard.exe"
    subprocess.run([compiler,"-std=c++17","-I",str(root/"firmware/include"),
                    str(root/"firmware/test/test_arm_guard.cpp"),"-o",str(executable)],
                   check=True,capture_output=True,timeout=30)
    subprocess.run([str(executable)],check=True,capture_output=True,timeout=10)
