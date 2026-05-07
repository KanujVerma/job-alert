from __future__ import annotations
import os
import logging
from dataclasses import dataclass, field

import yaml
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


@dataclass
class Config:
    defaults: dict
    filters: dict
    companies: list[dict]
    user_agent: str = ""

    def __post_init__(self):
        # Ensure all companies have 'enabled' defaulting to True
        for company in self.companies:
            if "enabled" not in company:
                company["enabled"] = True


def load_config(yaml_path: str = "companies.yaml") -> Config:
    load_dotenv()

    with open(yaml_path, "r") as f:
        data = yaml.safe_load(f)

    defaults = data.get("defaults", {})
    filters = data.get("filters", {})
    companies = data.get("companies", [])

    contact = os.getenv("USER_AGENT_CONTACT_EMAIL", "")
    user_agent = defaults.get("user_agent_base", "job-alert-bot/0.1")
    if contact:
        user_agent = f"{user_agent} (+contact: {contact})"

    config = Config(
        defaults=defaults,
        filters=filters,
        companies=companies,
        user_agent=user_agent,
    )
    return config


def validate_config(
    config: Config,
    adapter_registry: dict,
    dry_run: bool = False,
) -> list[str]:
    errors = []

    # 1. No duplicate company names
    names = [c.get("name") for c in config.companies]
    seen_names = set()
    for name in names:
        if name in seen_names:
            errors.append(f"Duplicate company name: {name}")
        seen_names.add(name)

    # 2. Adapter registry check
    if not adapter_registry:
        if config.companies:
            # Phase 1: registry empty — adapter check skipped. Will validate once adapters are registered.
            logger.warning(
                "ADAPTER_REGISTRY is empty — adapter validation skipped for %d defined "
                "company/companies. This is expected in Phase 1; adapters will be "
                "validated once they are registered.", len(config.companies)
            )
    else:
        for company in config.companies:
            adapter = company.get("adapter")
            if adapter and adapter not in adapter_registry:
                errors.append(
                    f"Company '{company.get('name')}': unknown adapter '{adapter}'"
                )

    # 3. Required fields per company
    for company in config.companies:
        cname = company.get("name", "<unnamed>")
        if not company.get("name"):
            errors.append(f"Company missing 'name' field: {company}")
        if not company.get("adapter"):
            errors.append(f"Company '{cname}' missing 'adapter' field")
        if "config" not in company:
            errors.append(f"Company '{cname}' missing 'config' field")

    # 4. DISCORD_WEBHOOK_URL must be set (unless dry_run)
    if not dry_run:
        webhook = os.getenv("DISCORD_WEBHOOK_URL", "")
        if not webhook:
            errors.append(
                "DISCORD_WEBHOOK_URL env var is not set. "
                "Set it in .env or export it. Use --dry-run to skip this check."
            )

    return errors
