"""Textual materialization of `SolveigInterface`.

Deliberately empty: a re-exporting `__init__` merges everything it touches into
a single node in the import graph, which is how a one-name annotation turns
into a multi-module cycle. Import from the real module.
"""
