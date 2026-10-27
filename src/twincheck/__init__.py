"""TwinCheck: evidence-first differential testing for command-line programs."""

__version__ = "0.12.0a1"

from .api import (
    API_VERSION,
    CONTRACT_SCHEMA_VERSION,
    CompatibilityContract,
    OutputContract,
    compare_commands,
    contract_from_dict,
    load_contract,
    report_as_json,
    write_json_report,
    write_junit_report,
)

__all__ = [
    "__version__",
    "API_VERSION",
    "CONTRACT_SCHEMA_VERSION",
    "CompatibilityContract",
    "OutputContract",
    "compare_commands",
    "contract_from_dict",
    "load_contract",
    "report_as_json",
    "write_json_report",
    "write_junit_report",
]
