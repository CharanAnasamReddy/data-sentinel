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

### Mapping document validation and transformations

Provide a structured mapping document to define expected source and target columns, per-column transformations, target types/lengths, nullability, and defaults. DataSentinel validates the mapping document before using it to build deterministic, executable rules. Rules only use supported operations; mapping text is never evaluated as Python or SQL.

Supported file formats:

- JSON and CSV using the Python standard library.
- YAML (`.yaml`, `.yml`) and Excel workbooks (`.xlsx`) with the optional mapping dependencies: `pip install -e ".[mappings]"`.

PDFs and Word documents are not treated as executable mappings: their free-form content must first be reviewed and converted into a structured mapping document.

See [mapping.example.json](./mapping.example.json). The same mapping model can be loaded in Python and used to generate target records:

```python
from datasentinel import load_mapping_document

mapping = load_mapping_document("mapping.example.json")
print(mapping.summary())
target_record = mapping.transform_record({
    "first_name": "Ada",
    "last_name": "Lovelace",
    "gross_amount": "100.00",
    "tax_amount": "10.00",
})
```

The CLI can validate a mapping file and print the generated rules without connecting to an ETL platform:

```bash
python -m datasentinel.cli --validate-mapping mapping.example.json
```

Built-in operations are `copy`, `trim`, `upper`, `lower`, `concat`, `coalesce`, `add`, `subtract`, `multiply`, `divide`, `replace`, `substring`, `round`, and `if_else`. Supported target types are `string`, `integer`, `number`, `decimal`, `boolean`, and ISO-formatted `date`, including common SQL type aliases. Unsupported transformations, missing inputs, invalid conversions, nulls for required targets, and target-length overflow produce explicit errors; values are not silently truncated.

### Connection string configuration

Configure source and target data connection strings with environment variables. Configure zero or more ETL integrations separately in `datasentinel.integrations.json`. Each integration has a unique name, a provider identifier, provider-specific non-secret settings, and references to credentials stored in environment variables. A configuration can contain ADF, SSIS, AWS Glue, and other or custom ETL providers together. Never put credentials directly in the JSON file or commit real secrets:

- `DATASENTINEL_SOURCE_CONNECTION_STRING`
- `DATASENTINEL_TARGET_CONNECTION_STRING`

For local development, copy `.env.example` to `.env` and `datasentinel.integrations.json.example` to `datasentinel.integrations.json`. Fill in the provider settings and configure only the environment variables referenced by the integrations you enable. DataSentinel does not load `.env` files automatically; load them with your development environment or export them before starting the application.

Load the configuration in Python:

```python
from datasentinel import ConnectionSettings

connections = ConnectionSettings.from_environment(
    integrations_path="datasentinel.integrations.json"
)
source_connection, target_connection = connections.require_source_and_target()
for integration in connections.enabled_etl_integrations:
    print(integration.name, integration.provider, integration.settings)
    # Use integration.credentials in that provider's integration adapter.
```

Credential values are resolved from the environment using each integration's `credentials_env` mapping and excluded from object representations. Provider identifiers are extensible; this provides configuration for multiple integrations but does not itself implement their clients or trigger pipelines. Core data validation remains independent of ETL integrations.

### Deterministic results remain authoritative

The deterministic testing engine is the source of truth for objective checks such as row counts, schemas, nulls, duplicates, and reconciliation. Events capture execution state; AI interprets results and suggests impact analysis or regression checks; visualizations present the results. AI may explain or enrich a result but must never override a deterministic failure.

AI reasoning focuses on changes across the data ecosystem—tables, columns, mappings, schemas, transformations, and downstream dependencies—rather than assuming a specific ETL vendor.

## Core modules

- `datasentinel.deterministic_engine`: row count, schema, null, and duplicate validation logic.
- `datasentinel.mappings`: mapping-document parsing, validation, and deterministic transformation rule generation.
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
