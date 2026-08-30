# path: app/agents/experimental/__init__.py
"""Experimental ablations that are not part of the frozen protocol.

This package holds the "removed experiment" required by the ТЗ Improvement Changelog: an
implemented, measurable alternative to a shipped component, kept only if real evaluation
numbers justify it. Nothing here is wired into the default pipeline; it is only reachable via
the `it5_subagents` ablation.
"""
