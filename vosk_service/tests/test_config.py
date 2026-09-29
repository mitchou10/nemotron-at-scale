"""Settings: sizing from the CPUs the container may use, and cgroup limit detection."""

from pathlib import Path

import pytest

from app import config
from app.config import Settings, available_cpus, cgroup_cpu_quota


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_cgroup_v2_quota(tmp_path: Path) -> None:
    write(tmp_path / "cpu.max", "150000 100000\n")
    assert cgroup_cpu_quota(tmp_path) == 1.5


def test_cgroup_v2_without_limit(tmp_path: Path) -> None:
    write(tmp_path / "cpu.max", "max 100000\n")
    assert cgroup_cpu_quota(tmp_path) is None


def test_cgroup_v1_quota(tmp_path: Path) -> None:
    write(tmp_path / "cpu" / "cpu.cfs_quota_us", "200000\n")
    write(tmp_path / "cpu" / "cpu.cfs_period_us", "100000\n")
    assert cgroup_cpu_quota(tmp_path) == 2.0


def test_cgroup_v1_without_limit(tmp_path: Path) -> None:
    write(tmp_path / "cpu" / "cpu.cfs_quota_us", "-1\n")
    write(tmp_path / "cpu" / "cpu.cfs_period_us", "100000\n")
    assert cgroup_cpu_quota(tmp_path) is None


def test_no_cgroup_files(tmp_path: Path) -> None:
    assert cgroup_cpu_quota(tmp_path) is None


def test_garbage_cgroup_files(tmp_path: Path) -> None:
    write(tmp_path / "cpu.max", "what")
    write(tmp_path / "cpu" / "cpu.cfs_quota_us", "x")
    assert cgroup_cpu_quota(tmp_path) is None


def test_container_limit_caps_the_available_cpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config.os, "sched_getaffinity", lambda _pid: set(range(64)))
    write(tmp_path / "cpu.max", "200000 100000")
    assert available_cpus(tmp_path) == 2.0  # a 2-CPU container on a 64-core node
    write(tmp_path / "cpu.max", "max 100000")
    assert available_cpus(tmp_path) == 64.0
    write(tmp_path / "cpu.max", "9600000 100000")
    assert available_cpus(tmp_path) == 64.0  # a quota above the cores changes nothing


def test_falls_back_to_cpu_count_without_affinity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(config.os, "sched_getaffinity")
    monkeypatch.setattr(config.os, "cpu_count", lambda: 6)
    assert available_cpus(Path("/nonexistent")) == 6.0


@pytest.fixture
def cpus(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    def set_cpus(value: float) -> None:
        monkeypatch.setattr(config, "available_cpus", lambda: value)

    return set_cpus


def test_limits_are_sized_from_the_cpus(cpus) -> None:  # type: ignore[no-untyped-def]
    cpus(4.0)
    settings = Settings(_env_file=None)
    assert (settings.threads, settings.max_streams, settings.max_requests) == (4, 4, 4)


def test_streams_per_cpu_scales_the_stream_limit(cpus) -> None:  # type: ignore[no-untyped-def]
    cpus(4.0)
    assert Settings(_env_file=None, streams_per_cpu=3).max_streams == 12
    assert Settings(_env_file=None, streams_per_cpu=2.5).max_streams == 10


def test_fractional_cpus_round_safely(cpus) -> None:  # type: ignore[no-untyped-def]
    cpus(0.5)
    settings = Settings(_env_file=None, streams_per_cpu=3)
    assert (settings.threads, settings.max_streams) == (1, 1)  # never zero
    cpus(1.5)
    assert Settings(_env_file=None).threads == 2


def test_explicit_limits_win(cpus) -> None:  # type: ignore[no-untyped-def]
    cpus(8.0)
    settings = Settings(_env_file=None, max_streams=3, threads=2, max_requests=1)
    assert (settings.max_streams, settings.threads, settings.max_requests) == (3, 2, 1)


def test_limits_come_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
    cpus,  # type: ignore[no-untyped-def]
) -> None:
    cpus(8.0)
    monkeypatch.setenv("VOSK_MAX_STREAMS", "5")
    monkeypatch.setenv("VOSK_STREAMS_PER_CPU", "9")
    monkeypatch.setenv("VOSK_IDLE_TIMEOUT_S", "30")
    monkeypatch.setenv("VOSK_MAX_STREAM_SECONDS", "600")
    settings = Settings(_env_file=None)
    assert settings.max_streams == 5  # explicit beats streams_per_cpu
    assert (settings.idle_timeout_s, settings.max_stream_seconds) == (30.0, 600)


@pytest.mark.parametrize(
    "field", ["max_streams", "threads", "max_requests", "max_upload_mb", "max_stream_seconds"]
)
def test_limits_must_be_positive(field: str) -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, **{field: 0})


def test_default_limits() -> None:
    settings = Settings(_env_file=None)
    assert settings.max_upload_mb == 64
    assert settings.max_stream_seconds == 3600
    assert settings.idle_timeout_s == 120.0
    assert settings.streams_per_cpu == 1.0


def test_empty_environment_values_mean_unset(
    monkeypatch: pytest.MonkeyPatch,
    cpus,  # type: ignore[no-untyped-def]
) -> None:
    cpus(4.0)
    monkeypatch.setenv("VOSK_MAX_STREAMS", "")
    assert Settings(_env_file=None).max_streams == 4
