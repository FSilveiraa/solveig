"""Provider abstraction.

Deliberately empty: `types` sits below config (APIType is a config field type)
while `client` sits above it, so the package spans two layers and must not be
importable as one node. Import from the real module.
"""
