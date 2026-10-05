from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True)
class ETLIntegration:
    """Named ETL integration configuration with credentials hidden from repr."""

    name: str
    provider: str
    settings: Mapping[str, Any] = field(default_factory=dict)
    credentials: Mapping[str, str] = field(default_factory=dict, repr=False)
    enabled: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "settings", MappingProxyType(dict(self.settings)))
        object.__setattr__(self, "credentials", MappingProxyType(dict(self.credentials)))


@dataclass(frozen=True)
class ConnectionSettings:
    """Data endpoint strings and independently configured ETL integrations."""

    source_connection_string: str | None = field(default=None, repr=False)
    target_connection_string: str | None = field(default=None, repr=False)
    etl_integrations: tuple[ETLIntegration, ...] = ()

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
        integrations_path: str | Path | None = None,
    ) -> ConnectionSettings:
        values = os.environ if environ is None else environ
        integrations = (
            load_etl_integrations(integrations_path, values)
            if integrations_path is not None
            else ()
        )
        return cls(
            source_connection_string=values.get("DATASENTINEL_SOURCE_CONNECTION_STRING"),
            target_connection_string=values.get("DATASENTINEL_TARGET_CONNECTION_STRING"),
            etl_integrations=integrations,
        )

    def require_source_and_target(self) -> tuple[str, str]:
        source = self.source_connection_string or ""
        target = self.target_connection_string or ""
        missing = []
        if not source.strip():
            missing.append("DATASENTINEL_SOURCE_CONNECTION_STRING")
        if not target.strip():
            missing.append("DATASENTINEL_TARGET_CONNECTION_STRING")
        if missing:
            names = ", ".join(missing)
            raise ValueError(f"Missing required connection string environment variable(s): {names}")

        return source, target

    def get_etl_integration(self, name: str) -> ETLIntegration:
        for integration in self.etl_integrations:
            if integration.name == name:
                return integration
        raise KeyError(f"ETL integration '{name}' is not configured.")

    @property
    def enabled_etl_integrations(self) -> tuple[ETLIntegration, ...]:
        return tuple(integration for integration in self.etl_integrations if integration.enabled)


def load_etl_integrations(
    path: str | Path,
    environ: Mapping[str, str] | None = None,
) -> tuple[ETLIntegration, ...]:
    """Load named integrations from JSON, resolving credential references via env vars."""
    values = os.environ if environ is None else environ
    config_path = Path(path)
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON in ETL integration configuration '{config_path}'.") from error

    if not isinstance(config, dict):
        raise ValueError("ETL integration configuration must be a JSON object.")
    entries = config.get("etl_integrations", [])
    if not isinstance(entries, list):
        raise ValueError("'etl_integrations' must be a JSON array.")

    integrations: list[ETLIntegration] = []
    names: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"ETL integration at index {index} must be a JSON object.")

        name = entry.get("name")
        provider = entry.get("provider")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"ETL integration at index {index} must have a non-empty name.")
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError(f"ETL integration '{name}' must have a non-empty provider.")
        name = name.strip()
        provider = provider.strip()
        if name in names:
            raise ValueError(f"Duplicate ETL integration name '{name}'.")
        names.add(name)

        enabled = entry.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError(f"'enabled' for ETL integration '{name}' must be a boolean.")

        settings = entry.get("settings", {})
        credentials_env = entry.get("credentials_env", {})
        if not isinstance(settings, dict):
            raise ValueError(f"'settings' for ETL integration '{name}' must be a JSON object.")
        if not isinstance(credentials_env, dict):
            raise ValueError(f"'credentials_env' for ETL integration '{name}' must be a JSON object.")

        credentials: dict[str, str] = {}
        for credential_name, environment_name in credentials_env.items():
            if not isinstance(credential_name, str) or not isinstance(environment_name, str):
                raise ValueError(f"Credential references for ETL integration '{name}' must be strings.")
            if not credential_name.strip():
                raise ValueError(f"Credential names for ETL integration '{name}' cannot be empty.")
            if not environment_name.strip():
                raise ValueError(f"Credential reference '{credential_name}' for integration '{name}' is empty.")
            if not enabled:
                continue
            secret = values.get(environment_name)
            if not secret or not secret.strip():
                raise ValueError(
                    f"Missing environment variable '{environment_name}' for ETL integration '{name}'."
                )
            credentials[credential_name] = secret

        integrations.append(
            ETLIntegration(
                name=name,
                provider=provider,
                settings=settings,
                credentials=credentials,
                enabled=enabled,
            )
        )

    return tuple(integrations)
