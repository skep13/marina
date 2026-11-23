"""Background jobs, restore points and the work log on her machine."""
import re

import pytest

from process.tools import workspace


@pytest.fixture
def mem(monkeypatch):
    store = {}
    from process import state
    monkeypatch.setattr(state, "get", lambda k, d=None: store.get(k, d))
    monkeypatch.setattr(state, "put", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(workspace, "_watch", lambda: None)
    monkeypatch.setattr(workspace, "available", lambda: True)
    return store


def test_risky_commands_get_a_restore_point():
    risky = ["sudo apt upgrade -y", "sudo apt-get -y dist-upgrade", "sudo apt purge foo",
             "sudo apt autoremove", "sudo update-grub", "echo x | sudo tee /etc/fstab",
             "sudo sed -i 's/a/b/' /etc/default/grub", "sudo systemctl disable ssh",
             "sudo rm -rf /etc/foo"]
    safe = ["sudo apt update", "sudo apt install htop", "ls /etc", "cat /etc/fstab",
            "rm -rf ~/projects/tmp", "flatpak update -y", "systemctl status ssh"]
    for c in risky:
        assert workspace._RISKY.search(c), c
    for c in safe:
        assert not workspace._RISKY.search(c), c


def test_restore_point_only_when_due(mem, monkeypatch):
    monkeypatch.setattr(workspace, "THEIRS", True)
    taken = []
    monkeypatch.setattr(workspace, "make_restore_point", lambda c: taken.append(c) or "took one")
    assert workspace._maybe_restore_point("sudo apt install htop") == ""
    assert workspace._maybe_restore_point("sudo apt upgrade -y").startswith("took one")
    import time
    mem[workspace._RP_KEY] = time.time()
    assert workspace._maybe_restore_point("sudo apt upgrade -y") == ""
    assert len(taken) == 1


def test_start_job_and_finish_is_announced(mem, monkeypatch):
    calls = []

    def fake_ssh(command, stdin=None, timeout=None):
        calls.append(command)
        if "JOB" in command:
            return 0, "JOB 1123-101010-42\n"
        return 0, "=== 1123-101010-42 done 0\nUpgraded 12 packages.\n"
    monkeypatch.setattr(workspace, "_ssh", fake_ssh)
    monkeypatch.setattr(workspace, "THEIRS", False)
    said = []
    monkeypatch.setattr(workspace, "on_job_done", said.append)
    out = workspace.start_job("sudo apt update", name="package lists")
    assert "1123-101010-42" in out
    assert workspace.check_jobs() == 0
    assert said and "package lists" in said[0] and "Upgraded 12 packages" in said[0]
    # finished jobs aren't announced twice
    assert workspace.check_jobs() == 0 and len(said) == 1
    assert "job: package lists -> ok" in workspace.recent_note()


def test_failed_job_reports_its_last_line(mem, monkeypatch):
    monkeypatch.setattr(workspace, "_ssh", lambda c, stdin=None, timeout=None:
                        (0, "JOB a1\n") if "JOB" in c else (0, "=== a1 done 100\nE: Unable to locate package nope\n"))
    said = []
    monkeypatch.setattr(workspace, "on_job_done", said.append)
    workspace.start_job("sudo apt install nope", name="install")
    workspace.check_jobs()
    assert "something went wrong" in said[0]
    assert "Unable to locate package" in workspace.recent_note()


def test_recent_note_empty_without_history(mem, monkeypatch):
    monkeypatch.setattr(workspace, "available", lambda: True)
    assert workspace.recent_note() == ""
