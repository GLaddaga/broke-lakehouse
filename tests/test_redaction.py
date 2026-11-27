"""A connect failure inside dlt must not print the catalog password.

Offline: fake secrets, a catalog on a dead port, and the attach guard bypassed,
because the guard would otherwise fail first and dlt would never connect. The
pipeline is a one-row toy run through the pattern every pipeline uses,
`destination()` inside `redacted()`, so the test does not depend on the sample.

    python -m pytest tests/test_redaction.py -v
"""

import traceback
from unittest import mock

import dlt
import pytest

import broke_lakehouse.ops as lakehouse

SECRETS = {
    "DUCKLAKE_CATALOG_URI": "postgresql://user:hunter2%40secret@127.0.0.1:1/db?sslmode=disable",
    "DUCKLAKE_DATA_PATH": "s3://bucket/prod/",
    "AWS_ACCESS_KEY_ID": "key",
    "AWS_SECRET_ACCESS_KEY": "storage-secret",
    "AWS_ENDPOINT_URL_S3": "https://127.0.0.1:1",
    "AWS_REGION": "auto",
}


def test_dlt_connect_failure_hides_the_password(capfd, tmp_path):
    with (mock.patch.object(lakehouse, "get_secrets", lambda names, *, environment: SECRETS),
          mock.patch.object(lakehouse, "attach")):
        pipeline = dlt.pipeline(pipeline_name="redaction",
                                destination=lakehouse.destination("prod"),
                                dataset_name="raw", pipelines_dir=str(tmp_path))
        with pytest.raises(RuntimeError) as failure, lakehouse.redacted("prod"):
            pipeline.run([{"x": 1}], table_name="probe")

    output = "".join(traceback.format_exception(failure.value)) + "".join(capfd.readouterr())
    assert "127.0.0.1" in output  # the failure itself is still readable
    for secret in ("hunter2", "storage-secret"):
        assert secret not in output
