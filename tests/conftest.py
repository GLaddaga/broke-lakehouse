"""Which lakehouse the tests run against, chosen per run on the command line.

    python -m pytest tests/ -v --lakehouse-env dev

One word names the Infisical slug, the Neon branch and the bucket prefix, so
this single option selects the catalog, the credentials and the data path at
once. It is not in `.env`: which lake a run touches is a decision per run, and
one that should be visible in the command that makes it.
"""

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--lakehouse-env", default="prod", metavar="SLUG",
        help="environment to run against: Infisical slug, Neon branch and bucket "
             "prefix, all the same word (default: prod)")


@pytest.fixture(scope="session")
def environment(request) -> str:
    return request.config.getoption("--lakehouse-env")
