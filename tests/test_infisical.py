"""Integration check for utils/secrets/infisical.py.

Hits the real Infisical API. Two tests, split so the failure tells you where
to look: the first covers Universal Auth login, the second covers the project
grant, the environment slug and the secret path.

Needs a mock secret at the root path of whichever environment is under test
(`--lakehouse-env`, default `prod`):

    TEST_SECRET = it-works

Skipped when the bootstrap credentials are absent, so a clone without a
`.env` does not fail.
"""

import os
import pytest
from utils.secrets.infisical import _client, get_secret

EXPECTED = "it-works"

pytestmark = pytest.mark.skipif(
    not os.environ.get("INFISICAL_CLIENT_ID"), reason="no bootstrap credentials"
)


def test_login_succeeds():
    # Bad client ID/secret or no network fail here.
    _client.cache_clear()  # a client cached by another test would prove nothing
    assert _client() is not None


def test_returns_known_value(environment):
    # Green above and red here means auth worked but the read did not —
    # usually the identity is missing the project grant.
    assert get_secret("TEST_SECRET", environment=environment) == EXPECTED
