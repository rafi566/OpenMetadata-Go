"""The baseline guard must reject source Maven would compile outside the commit."""

import os
import subprocess
from pathlib import Path

import pytest

BUILD = Path(__file__).resolve().parents[2] / "docker/benchmark/build-java.sh"


@pytest.mark.skipif(os.name == "nt", reason="The builder runs in Linux")
@pytest.mark.parametrize("untracked_source", [True, False])
def test_baseline_rejects_extra_source_before_maven(tmp_path, untracked_source):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True).strip()

    git("init", "-q")
    (tmp_path / ".gitignore").write_text("target/\n")
    git("add", ".gitignore")
    git(
        "-c",
        "user.name=fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-qm",
        "Baseline fixture",
    )
    extra = tmp_path / (
        "openmetadata-service/src/main/java/ExtraResource.java"
        if untracked_source
        else "target/generated-output"
    )
    extra.parent.mkdir(parents=True)
    extra.write_text("class ExtraResource {}\n")
    commands = tmp_path / "target/bin"
    commands.mkdir(parents=True)
    maven = commands / "mvn"
    maven.write_text('#!/usr/bin/env bash\ntouch "$MAVEN_MARKER"\nexit 37\n')
    maven.chmod(0o755)
    marker = tmp_path / "target/maven-started"
    result = subprocess.run(
        ["bash", str(BUILD)],
        check=False,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "BASELINE_SOURCE_SHA": git("rev-parse", "HEAD"),
            "MAVEN_MARKER": str(marker),
            "PATH": str(commands) + os.pathsep + os.environ["PATH"],
        },
    )
    assert marker.exists() is (not untracked_source), result.stderr
    assert result.returncode == (1 if untracked_source else 37), result.stderr
