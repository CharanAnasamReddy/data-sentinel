# DataSentinel

DataSentinel is a universal ETL/ELT data validation and quality platform. It validates data based on configured sources, targets, schemas, mappings, and business rules—not on the technology used to build or orchestrate the pipeline.

Supported pipeline technologies may include Azure Data Factory, Azure Databricks, AWS Glue, Informatica, Talend, SSIS, IBM DataStage, Snowflake, dbt, Apache Airflow, Matillion, Fivetran, Spark, SQL-based ETL, and custom Python or Java pipelines. This list is illustrative, not restrictive.

## Architecture

```text
                 ┌─────────────────────┐
                 │    ETL / ELT Tools  │
                 │ ADF, Databricks,    │
                 │ Glue, Informatica,  │
                 │ dbt, Airflow, etc.  │
                 └──────────┬──────────┘
                            │
                            ▼
              ┌─────────────────────────┐
              │     DATA ENVIRONMENT    │
              │ Sources, stages, and    │
              │ targets; any layers     │
              └────────────┬────────────┘
                           │
                           ▼
                 ┌──────────────────┐
                 │   DataSentinel   │
                 │ Deterministic    │
                 │ validation      │
                 │ Events & lineage │
                 │ AI intelligence │
                 └────────┬─────────┘
                          │
                          ▼
              ┌────────────────────────┐
              │ Dashboards, reports,   │
              │ alerts, and insights  │
              └────────────────────────┘
```

### Non-negotiable principle: ETL-tool agnostic

DataSentinel validates the data pipeline, not the technology that built it. The deterministic engine operates independently of pipeline orchestration and transformation tools. Core validation must be runnable from configured data sources, targets, metadata, schemas, mappings, and business rules—even when no ETL integration is configured.

DataSentinel does not require Databricks or any other specific ETL/ELT platform. Databricks is one potential integration among many, not the foundation of the product. Source, processing, and target layers are configurable rather than fixed to names such as Bronze, Silver, and Gold.

### Data connectors and ETL integrations

These are separate extension points with distinct responsibilities:

- **Data connectors** access the data and metadata DataSentinel validates. Connector families include databases (such as SQL Server, Oracle, PostgreSQL, Snowflake, and MySQL), files (CSV, Excel, JSON, XML, and Parquet), cloud storage (Azure Blob, ADLS, S3, and GCS), and data platforms (such as Databricks, BigQuery, and Synapse).
- **Optional ETL integrations** provide orchestration-related capabilities such as triggering a validation, reporting pipeline execution status, and retrieving job metadata or lineage. Integrations may include ADF, Databricks, Informatica, Talend, SSIS, AWS Glue, Airflow, dbt, or generic REST APIs.

An ETL integration is never a prerequisite for validating accessible source and target data. For example, DataSentinel can independently validate Oracle-to-SQL Server data without knowing whether Informatica performed the transformation; an Informatica integration may optionally trigger validation after a workflow completes.

### Deterministic results remain authoritative

The deterministic testing engine is the source of truth for objective checks such as row counts, schemas, nulls, duplicates, and reconciliation. Events capture execution state; AI interprets results and suggests impact analysis or regression checks; visualizations present the results. AI may explain or enrich a result but must never override a deterministic failure.

AI reasoning focuses on changes across the data ecosystem—tables, columns, mappings, schemas, transformations, and downstream dependencies—rather than assuming a specific ETL vendor.

## Core modules

- `datasentinel.deterministic_engine`: row count, schema, null, and duplicate validation logic.
- `datasentinel.events`: execution event ordering and state history.
- `datasentinel.ai_agent`: business-friendly AI analysis that never overrides deterministic pass/fail outcomes.
- `datasentinel.visualization`: executive dashboard summaries.
- `datasentinel.cli`: runnable example command.

## Example

```bash
python -m datasentinel.cli --example
```

Example output includes:

- deterministic result with `status`, `expected`, `actual`, and `difference`
- AI explanation of business impact
- event history for the execution state
- dashboard summary with pass/fail counts

## Why this matters

The engine enforces the rule that objective validation is authoritative. AI is allowed to add recommendations, root-cause context, and explanations, but it cannot make a failing deterministic check pass.
