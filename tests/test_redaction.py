"""A connect failure inside dlt must not print the catalog password.

Offline: fake secrets, a catalog on a dead port, and the attach guard bypassed,
because the guard would otherwise fail first and dlt would never connect.

    python -m pytest tests/test_redaction.py -v
"""

import traceback
from unittest import mock

import pytest

import broke_lakehouse.ops as lakehouse
from ingest.pipelines import tpch

SECRETS = {
    "DUCKLAKE_CATALOG_URI": "postgresql://user:hunter2%40secret@127.0.0.1:1/db?sslmode=disable",
    "DUCKLAKE_DATA_PATH": "s3://bucket/prod/",
    "AWS_ACCESS_KEY_ID": "key",
    "AWS_SECRET_ACCESS_KEY": "storage-secret",
    "AWS_ENDPOINT_URL_S3": "https://127.0.0.1:1",
    "AWS_REGION": "auto",
}


def test_dlt_connect_failure_hides_the_password(capfd):
    with (mock.patch.object(lakehouse, "get_secrets", lambda names, *, environment: SECRETS),
          mock.patch.object(lakehouse, "attach")):
        with pytest.raises(RuntimeError) as failure:
            tpch.load("prod", 0.001)

    output = "".join(traceback.format_exception(failure.value)) + "".join(capfd.readouterr())
    assert "127.0.0.1" in output  # the failure itself is still readable
    for secret in ("hunter2", "storage-secret"):
        assert secret not in output
