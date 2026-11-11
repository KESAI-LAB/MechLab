"""新机接入：解析器 / 机器注册 / 通用后端的自测（不联网、不启 COMSOL）。

运行：python tests/test_machine_setup.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import machine_probe, machines  # noqa: E402
from app.backends import Job, get_backend  # noqa: E402
from app.config import MACHINE_BY_LABEL, MACHINES  # noqa: E402

BATCH = r"D:\COMSOL64\Multiphysics\bin\win64\comsolbatch.exe"
COMPILE = r"D:\COMSOL64\Multiphysics\bin\win64\comsolcompile.exe"


def test_parse_and_suggest() -> None:
    fake = {
        "hostname": "TESTPC",
        "user": r"TESTPC\alice",
        "username": "alice",
        "cpu_cores": 8,
        "cpu_logical": 16,
        "ram_gb": 32,
        "ipv4": ["10.1.2.3"],
        "comsol": [{"batch": BATCH, "compile": COMPILE}],
        "writable_dirs": [r"D:\zjz"],
        "sshd": "Running",
        "ssh_port_22_listening": True,
    }
    text = "noise\n" + machine_probe.BEGIN + "\n" + json.dumps(fake) + "\n" + machine_probe.END + "\n"
    data = machine_probe.parse_probe_text(text)
    sug = machine_probe.suggest_config(data)
    assert sug["host"] == "alice@10.1.2.3", sug
    assert sug["cores"] == 16
    assert sug["base_win"] == r"D:\zjz"
    assert sug["batch"] == BATCH
    print("[ok] 解析 + 自动填表建议")


def test_register_and_backend() -> None:
    cm = machines.CustomMachine(
        label="测试新机", host="alice@10.1.2.3", port=2222, key_path="C:/keys/id_test",
        base_win=r"D:\zjz", base_unix="D:/zjz", batch=BATCH, compile=COMPILE, cores=16,
    )
    m = machines.save_machine(cm)
    try:
        assert m.key in MACHINES and m.label in MACHINE_BY_LABEL
        backend = get_backend("GenericRemote", m.key)
        job = Job(model=str(Path(__file__)), spec="SiC_hoop=solid.sphi@2", study="std1",
                  cores=16, tag="t")
        cmd = backend.build_command(job)
        assert "RG_PORT=2222" in cmd and "RG_HOST=alice@10.1.2.3" in cmd
        assert "remote_extract.sh" in cmd and "SiC_hoop=solid.sphi@2" in cmd
        probe = backend.build_probe_command()
        assert "-p 2222" in probe and "LINK_OK" in probe
        print("[ok] 机器注册 + 通用后端命令")
    finally:
        machines.remove_machine(m.key)
        (ROOT / "machines.json").unlink(missing_ok=True)


def test_ssh_enable_script() -> None:
    dummy = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITESTKEY mechlab@test"
    s = machine_probe.build_ssh_enable_script(dummy)
    assert "Add-WindowsCapability" in s and "Start-Service sshd" in s
    assert "New-NetFirewallRule" in s and "administrators_authorized_keys" in s
    assert "SSH_READY" in s and dummy in s
    s2 = machine_probe.build_ssh_enable_script("")
    assert "__PUBKEY__" in s2
    print("[ok] SSH 启动脚本生成")


if __name__ == "__main__":
    test_parse_and_suggest()
    test_register_and_backend()
    test_ssh_enable_script()
    print("ALL TESTS PASSED")
