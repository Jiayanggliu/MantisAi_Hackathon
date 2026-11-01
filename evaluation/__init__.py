"""Evaluation framework for the Track-2 cluster-efficiency project.

See evaluation/README.md for the implementation brief and AGENTS.md for the
repository ground rules. Three execution modes are exposed via ``python -m
evaluation <mode>`` (mirrored by ``make eval`` targets):

- ``eval``       offline deterministic checks on synthetic fixtures
- ``eval-data``  telemetry data-quality report over ``data/prepped/*.parquet``
- ``eval-live``  run the real system against reviewed benchmark cases

Exit codes (contract): 0 = completed with no configured acceptance failures,
1 = evaluation failure / invalid input / failed acceptance criterion,
2 = missing prerequisites.
"""

__version__ = "0.1.0"

# Exit-code contract shared by all modes.
EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_MISSING_PREREQUISITES = 2
