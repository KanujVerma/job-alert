from collections.abc import Iterable, Mapping

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

from src.adapters.eightfold import EightfoldAdapter  # noqa: E402
from src.adapters.microsoft_research import MicrosoftResearchAdapter  # noqa: E402
from src.adapters.generic_html import GenericHTMLAdapter  # noqa: E402

ADAPTER_REGISTRY["eightfold"] = EightfoldAdapter
ADAPTER_REGISTRY["microsoft_research"] = MicrosoftResearchAdapter
ADAPTER_REGISTRY["generic_html"] = GenericHTMLAdapter

from src.adapters.eightfold_playwright import EightfoldPlaywrightAdapter  # noqa: E402
from src.adapters.phenom_people import PhenomPeopleAdapter  # noqa: E402

ADAPTER_REGISTRY["eightfold_playwright"] = EightfoldPlaywrightAdapter
ADAPTER_REGISTRY["phenom_people"] = PhenomPeopleAdapter

# Plain HTTP, no session cookie — deliberately NOT requires_browser. See
# eightfold.py for the older /api/apply/v2/jobs route this one supersedes.
from src.adapters.eightfold_pcsx import EightfoldPCSXAdapter  # noqa: E402

ADAPTER_REGISTRY["eightfold_pcsx"] = EightfoldPCSXAdapter


def browser_required(
    companies: Iterable[Mapping], registry: Mapping[str, type[BaseAdapter]]
) -> bool:
    """Does any *enabled* company need a real browser?

    Two sources, because one of them is not trustworthy on its own:
      1. The adapter class declares `requires_browser = True`. Authoritative —
         an adapter that touches self.browser says so once, in its own class.
      2. The company config sets `use_playwright`. Kept for backward
         compatibility; it is opt-in per company and easy to omit.

    A company whose adapter key is not registered is not an error here — do_run
    already skips it — so it simply does not require a browser.
    """
    for company in companies:
        if not company.get("enabled", True):
            continue
        if (company.get("config") or {}).get("use_playwright", False):
            return True
        adapter_cls = registry.get(company.get("adapter"))
        if adapter_cls is not None and getattr(adapter_cls, "requires_browser", False):
            return True
    return False
