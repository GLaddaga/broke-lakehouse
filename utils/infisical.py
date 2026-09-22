"""
Thin wrapper around the Infisical SDK.

Auth (machine identity) is bootstrapped from environment variables:
    INFISICAL_CLIENT_ID
    INFISICAL_CLIENT_SECRET
    INFISICAL_PROJECT_ID
These are the *only* secrets that should ever be placed manually
(local .env, Prefect deployment env, k8s secret, etc).
Everything else is fetched from Infisical on demand.
"""

import os
from functools import lru_cache
from infisical_sdk import InfisicalSDKClient


@lru_cache(maxsize=1)
def _client() -> InfisicalSDKClient:
    # ponytail: token cached for the process lifetime, no refresh — if a run ever
    # outlives the UA token TTL, catch the auth error, _client.cache_clear(), retry once.
    # A project in the EU region answers on eu.infisical.com. The wrong host
    # still authenticates and then returns nothing, so this is an override
    # rather than a constant.
    client = InfisicalSDKClient(
        host=os.environ.get("INFISICAL_HOST", "https://app.infisical.com")
    )
    client.auth.universal_auth.login(
        os.environ["INFISICAL_CLIENT_ID"],
        os.environ["INFISICAL_CLIENT_SECRET"],
    )
    return client


@lru_cache(maxsize=None)
def get_secret(name: str, *, environment: str) -> str:
    """Fetch a single secret value. Never log or print the result.

    Cached per (name, environment) for the process lifetime: one `attach()` costs
    six API calls, and `initialise --force` attaches three times over. A value
    rotated mid-process is not picked up — call `get_secret.cache_clear()`, as the
    tests do for `_client`.
    """
    client = _client()
    return client.secrets.get_secret_by_name(
        secret_name=name,
        environment_slug=environment,
        project_id=os.environ["INFISICAL_PROJECT_ID"],
        secret_path="/"
    ).secretValue


def get_secrets(names: list[str], *, environment: str) -> dict[str, str]:
    """Fetch several secrets at once — still explicit, still per-call scoped."""
    return {n: get_secret(n, environment=environment) for n in names}