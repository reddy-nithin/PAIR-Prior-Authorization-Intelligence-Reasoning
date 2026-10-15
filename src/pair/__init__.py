"""PAIR: patient-side appeal copilot for Medicare Advantage prior authorization denials.

Pipeline: parse denial, select checklist, extract evidence, rule engine and gaps,
draft letter, verify claims, score strength, show in the UI.
"""

__version__: str = "0.1.0"
