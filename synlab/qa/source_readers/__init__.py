"""Bounded, source-backed readers used by QA audits.

Readers in this package verify producer bytes before reporting what those bytes
support. A source reader does not qualify physics or infer missing capabilities.
"""

from .pgfrag_result import read_pgfrag_result

__all__ = ["read_pgfrag_result"]
