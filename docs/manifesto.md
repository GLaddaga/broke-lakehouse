# Manifesto

I am a data engineer still learning the ropes. My researcher friends asked me to help them manage the data behind their
ML experiments, and I am taking the chance to learn something along the way. The outcome is a lightweight, inexpensive
data platform covering ingestion, transformation and visualization.

## As-is
Where things stand today:
* Data lives on local machines or a shared drive;
* ETL and feature engineering run in Jupyter notebooks;
* Data is refreshed by hand;
* All compute is local.

## To-be
Where I want to land:
* Centralized cloud storage as the single source of truth;
* ACID guarantees;
* ELT and feature engineering pipelines running on a schedule in the cloud;
* Data analysis and ML workflows still running on the researchers' machines;
* Everything as code, so that AI agents with the right skills can help maintain the platform.

## Philosophy
The problem is a common one, and I am not trying to reinvent the wheel.
Still, I believe this work could be useful to anyone looking to host a data and analytics project on an open-source,
inexpensive yet production-grade platform: from individuals with a personal project to small and medium-sized companies
starting their analytics journey on a tight budget.
Once the project is stable enough, I plan to distill a scaffolding tool from it (along the lines of `dbt init`), to make
running a data platform simpler and accessible to more people. The project it generates ships with a TPC-H sample
pipeline, the same one this project is built against, to show the platform end to end before any real source exists.
I hope people will find it valuable and contribute.

That goal shaped the choice of building blocks: a core of tools is fixed, while other pieces are deliberately left open
so that users can plug in whatever they prefer. For my own implementation, I will eventually have to pick one for each.

## Lakehouse
The to-be state points straight at a lakehouse architecture: it provides ACID guarantees and lets storage and compute
scale independently.
Since data must live remotely while researchers keep working locally, with an eye on performance, DuckDB is the right
engine for the job: it is built for in-process analytics, reads efficiently from cloud storage and has a good Python
client.
Picking DuckLake as the lakehouse format follows naturally.
[This deep dive](https://motherduck.com/blog/ducklake-architecture-deep-dive/) explains why the idea behind DuckLake is
so compelling.

## Backbone
The platform's building blocks, split into the core every implementation shares and the pieces left open. Items marked
*(later)* are part of the design but not yet on the roadmap.

**Core:**
* **Lakehouse:** [DuckLake](https://ducklake.select/docs/stable/)
    * **DBMS:** [DuckDB](https://duckdb.org/docs/current/)
    * **Catalog:** [Postgres](https://www.postgresql.org/docs/)
* **Ingestion:** [dlt](https://dlthub.com/docs/intro)
* **Transformation:** [dbt Core](https://docs.getdbt.com/)
* **Visualization:** [Evidence Core](https://docs.evidence.dev/) *(later)*
* **IaC:** [OpenTofu](https://opentofu.org/docs/)

**Pluggable:**
* **Secret manager:** any, behind a thin wrapper exposing the same function
* **Cloud storage:** any S3-compatible service with free egress
* **Postgres hosting:** any
* **Orchestrator:** any Python-based orchestrator
* **Compute:** local machines for exploratory analytics and ML work, any cloud compute service for scheduled pipelines
* **CI/CD:** any *(later)*

## Starting choices
What I picked to get started:
* Infisical as the secret manager;
* Tigris as cloud storage (S3-compatible, free egress, generous free tier);
* Neon to host Postgres (serverless, generous free tier);
* Prefect as the orchestrator (generous free tier with serverless compute included);
* GitHub Actions for CI/CD (easy to use) *(later)*.
