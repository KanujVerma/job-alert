from src.adapters.base import BaseAdapter

# Registry populated by each adapter module when imported.
# Phase 1: empty. Phase 2+ adds entries.
ADAPTER_REGISTRY: dict[str, type[BaseAdapter]] = {}

from src.adapters.workday import WorkdayAdapter  # noqa: E402

ADAPTER_REGISTRY["workday"] = WorkdayAdapter

from src.adapters.lever import LeverAdapter  # noqa: E402
from src.adapters.smartrecruiters import SmartRecruitersAdapter  # noqa: E402

ADAPTER_REGISTRY["lever"] = LeverAdapter
ADAPTER_REGISTRY["smartrecruiters"] = SmartRecruitersAdapter

from src.adapters.oracle_careers import OracleAdapter  # noqa: E402
from src.adapters.amazon_jobs import AmazonJobsAdapter  # noqa: E402
from src.adapters.apple_jobs import AppleJobsAdapter  # noqa: E402

ADAPTER_REGISTRY["oracle_careers"] = OracleAdapter
ADAPTER_REGISTRY["amazon_jobs"] = AmazonJobsAdapter
ADAPTER_REGISTRY["apple_jobs"] = AppleJobsAdapter
