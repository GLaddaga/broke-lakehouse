"""The whole pipeline: dlt into `raw`, then dbt from `raw` to `gold`.

    python -m orchestrate.flows.pipeline prod --sf 1

Stages pass data only through the warehouse. A failed stage fails the flow, so
dbt never builds on a load that did not finish. @docs/orchestration.md
"""

import argparse
import os
from pathlib import Path

from dbt.cli.main import dbtRunner
from prefect import flow, task
from prefect.blocks.system import Secret

from ingest.pipelines.tpch import load

TRANSFORM = str(Path(__file__).parents[2] / "transform")
BOOTSTRAP = ("INFISICAL_CLIENT_ID", "INFISICAL_CLIENT_SECRET", "INFISICAL_PROJECT_ID")


def _bootstrap() -> None:
    """
    The Infisical credential from Prefect Secret blocks (`infisical-client-id`
    and so on), for the managed pool. Locally the `.env.runner` already set them, so no
    block is read. Loaded here rather than through `job_variables.env`, because
    `prefect deploy` would resolve the block references into the deployment.
    """
    for name in BOOTSTRAP:
        if name not in os.environ:
            os.environ[name] = Secret.load(name.lower().replace("_", "-")).get()


@task
def ingest(environment: str, sf: float) -> None:
    load(environment, sf)


@task
def transform(environment: str) -> None:
    # invoke() reports failure in its result rather than raising.
    result = dbtRunner().invoke(["run", "--target", environment,
                                 "--project-dir", TRANSFORM, "--profiles-dir", TRANSFORM])
    if not result.success:
        raise RuntimeError(f"dbt run failed: {result.exception or 'see the model errors above'}")


@flow(log_prints=True)
def pipeline_flow(environment: str, sf: float = 1.0) -> None:
    _bootstrap()
    ingest(environment, sf)
    transform(environment)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="python -m orchestrate.flows.pipeline")
    parser.add_argument("environment", help="the lakehouse to build, never defaulted")
    parser.add_argument("--sf", type=float, default=1.0,
                        help="TPC-H scale factor; ~1 GB per unit (default: 1)")
    args = parser.parse_args()
    pipeline_flow(args.environment, args.sf)
