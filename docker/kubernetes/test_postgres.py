"""Exercise the shipped SQL with a disposable local PostgreSQL cluster."""

import os
import shutil
import socket
import subprocess
import uuid
from pathlib import Path

import pytest

HERE = Path(__file__).parent


@pytest.fixture(scope="module")
def postgres(tmp_path_factory):
    directory = os.environ.get("POSTGRES_BIN_DIR")
    suffix = ".exe" if os.name == "nt" else ""

    def binary(name):
        return (
            str(Path(directory) / (name + suffix)) if directory else shutil.which(name)
        )

    if not all(binary(name) for name in ("initdb", "pg_ctl", "psql")):
        pytest.skip("Set POSTGRES_BIN_DIR to run disposable PostgreSQL SQL tests")
    work = tmp_path_factory.mktemp("preflight-postgres")
    data = work / "data"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]

    def run(command, **kwargs):
        return subprocess.run(
            command, check=False, capture_output=True, text=True, timeout=45, **kwargs
        )

    initialized = run(
        [
            binary("initdb"),
            "-D",
            str(data),
            "-U",
            "postgres",
            "-A",
            "trust",
            "--no-locale",
            "-E",
            "UTF8",
        ]
    )
    assert initialized.returncode == 0, initialized.stderr
    started = subprocess.run(
        [
            binary("pg_ctl"),
            "-D",
            str(data),
            "-l",
            str(work / "server.log"),
            "-o",
            f"-h 127.0.0.1 -p {port}",
            "-w",
            "start",
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=45,
    )
    assert started.returncode == 0, started.stderr

    def sql(statement, *, database="postgres", user="postgres"):
        return run(
            [
                binary("psql"),
                "-X",
                "--no-password",
                "-v",
                "ON_ERROR_STOP=1",
                "-h",
                "127.0.0.1",
                "-p",
                str(port),
                "-U",
                user,
                "-d",
                database,
            ],
            input=statement,
            env={**os.environ, "PGSSLMODE": "disable", "PGCONNECT_TIMEOUT": "5"},
        )

    try:
        result = sql("CREATE ROLE office_app LOGIN;")
        assert result.returncode == 0, result.stderr
        yield sql
    finally:
        stopped = run(
            [binary("pg_ctl"), "-D", str(data), "-m", "immediate", "-w", "stop"]
        )
        assert stopped.returncode == 0, stopped.stderr


@pytest.mark.parametrize(
    "prepare,expected_error",
    [
        ("", None),
        ("DROP EXTENSION pgcrypto;", "pgcrypto and pg_trgm"),
        ("DROP EXTENSION pg_trgm;", "pgcrypto and pg_trgm"),
        (
            "ALTER DATABASE {database} SET default_transaction_read_only = on;",
            "writable primary",
        ),
        ("REVOKE CREATE ON SCHEMA public FROM pg_database_owner;", "USAGE and CREATE"),
        ("CREATE TABLE public.dba_owned (id integer);", "must own existing tables"),
    ],
)
def test_sql_exits_nonzero_when_a_database_prerequisite_fails(
    postgres, prepare, expected_error
):
    database = "preflight_" + uuid.uuid4().hex
    created = postgres(f"CREATE DATABASE {database} OWNER office_app;")
    assert created.returncode == 0, created.stderr
    setup = postgres(
        "CREATE EXTENSION pgcrypto; CREATE EXTENSION pg_trgm;"
        + prepare.format(database=database),
        database=database,
    )
    assert setup.returncode == 0, setup.stderr
    result = postgres(
        (HERE / "check-postgres.sql").read_text(), database=database, user="office_app"
    )
    if expected_error:
        assert result.returncode != 0, result.stdout + result.stderr
        assert expected_error in result.stderr
        assert "PASS:" not in result.stdout
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "PASS: PostgreSQL" in result.stdout
