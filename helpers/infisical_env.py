"""Pull secrets from Infisical into the process environment.

The one bootstrap credential (a Universal Auth machine identity) comes from the
environment or from Prefect secrets; everything else comes from here. See docs/secrets.md.

    In a flow:  from helpers import infisical_env; infisical_env.load()
    For CLIs:   python -m helpers.infisical_env dbt run

The SDK rather than the Infisical CLI: the managed work pool installs pip
packages only, so a Go binary is not an option there.
"""
import os
import sys
from infisical_sdk import InfisicalSDKClient


def load():
    c = InfisicalSDKClient(host=os.environ.get("INFISICAL_HOST", "https://app.infisical.com"))
    c.auth.universal_auth.login(os.environ["INFISICAL_CLIENT_ID"],
                                os.environ["INFISICAL_CLIENT_SECRET"])
    # recursive from / — one call gets every path, so folder layout stays a
    # documentation concern instead of a code branch.
    for s in c.secrets.list_secrets(project_id=os.environ["INFISICAL_PROJECT_ID"],
                                    environment_slug=os.environ.get("INFISICAL_ENV", "dev"),
                                    secret_path="/", recursive=True).secrets:
        # setdefault, not update: an already-exported variable wins, which is
        # how you override one secret locally without touching Infisical.
        os.environ.setdefault(s.secretKey, s.secretValue)


if __name__ == "__main__":
    load()
    os.execvp(sys.argv[1], sys.argv[1:])
