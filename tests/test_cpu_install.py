"""The CPU install must omit GPU wheels, keep CUDA available, and skip cuDNN."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

from packaging.markers import default_environment
from packaging.requirements import Requirement
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("group", ["cpu", "cuda"])
def test_frozen_torch_graph_on_supported_platforms(group, tmp_path):
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv required to validate its frozen dependency selection")
    args = [uv, "export", "--frozen", "--no-dev", "--no-hashes", "--no-emit-project"]
    if group == "cpu":
        args += ["--no-group", "cuda", "--group", "cpu"]
    result = subprocess.run(
        args, cwd=ROOT, text=True, capture_output=True, check=True, timeout=30,
        env={**os.environ, "UV_CACHE_DIR": str(tmp_path / "uv"), "UV_OFFLINE": "1"},
    )
    requirements = [
        Requirement(line) for line in result.stdout.splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "-"))
    ]
    for platform, machine in [("linux", "x86_64"), ("win32", "AMD64"), ("darwin", "arm64"), ("linux", "aarch64")]:
        env = {**default_environment(), "sys_platform": platform, "platform_machine": machine,
               "python_full_version": "3.11.16", "python_version": "3.11"}
        selected = {req.name: str(req.specifier) for req in requirements
                    if req.marker is None or req.marker.evaluate(env)}
        native = platform == "darwin" or machine == "aarch64"
        suffix = "" if native else "+cpu" if group == "cpu" else "+cu128"
        assert selected["torch"] == f"==2.8.0{suffix}"
        assert selected["torchaudio"] == f"==2.8.0{suffix}"
        assert selected["torchvision"] == f"==0.23.0{suffix}"
        gpu_libs = {name for name in selected if name == "triton" or
                    (name.startswith("nvidia-") and "-cu" in name)}
        if group == "cpu" or native:
            assert not gpu_libs, gpu_libs
        elif platform == "linux":
            assert "nvidia-cudnn-cu12" in gpu_libs
            assert "triton" in gpu_libs


@pytest.mark.parametrize("probe", ["cpu", "cuda", "rocm", "failed", "timeout"])
def test_post_setup_installs_cudnn_only_after_positive_cuda_probe(monkeypatch, tmp_path, probe):
    spec = importlib.util.spec_from_file_location("cpu_install_setup", ROOT / "scripts/setup.py")
    setup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup)
    monkeypatch.setattr(setup.sys, "platform", "linux")
    monkeypatch.setattr(setup, "_ensure_vcredist_windows", lambda: None)
    monkeypatch.setattr(setup, "_ensure_rocm_torch", lambda: None)
    monkeypatch.setattr(setup, "_find_compat_dir", lambda: str(tmp_path / "compat"))
    monkeypatch.setattr(setup, "_count_cudnn8_libs", lambda _: 5)
    commands = []
    fake_torch = SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: probe != "cpu"),
        version=SimpleNamespace(hip="6.4" if probe == "rocm" else None),
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    def run(args, **kwargs):
        commands.append(args)
        if args[0] == setup.sys.executable:
            if probe == "timeout":
                raise subprocess.TimeoutExpired(args, 30)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exec(args[2], {})
            return SimpleNamespace(stdout=output.getvalue(), returncode=1 if probe == "failed" else 0)
        return SimpleNamespace(stdout="", returncode=0)

    monkeypatch.setattr(setup.subprocess, "run", run)
    setup.main()
    installs = [cmd for cmd in commands if cmd[:2] == ["uv", "pip"]]
    assert len(installs) == (1 if probe == "cuda" else 0)
