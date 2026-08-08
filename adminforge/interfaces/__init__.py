"""Abstract ports AdminForge's core depends on: persistence (`IStore`),
applying changes to a server (`IDeployer`) and recording operations
(`IAuditor`). `core.nucleo` is written against these interfaces only, so
any concrete implementation (JSON files on disk, SSH vs. a mock, JSONL
vs. some other log) can be swapped in without touching the core logic.
"""

from .store import IStore
from .deployer import IDeployer
from .auditor import IAuditor

__all__ = ["IStore", "IDeployer", "IAuditor"]
