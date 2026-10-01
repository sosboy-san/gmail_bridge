"""Resolve runtime paths without changing the code working directory."""

import os
from pathlib import Path


def runtime_path(value):
    """Legacy paths remain unchanged; explicit config roots never fall back."""
    path = Path(value)
    if 'BRIDGE_CONFIG_DIR' not in os.environ:
        return path
    root_value = os.environ['BRIDGE_CONFIG_DIR']
    if not root_value.strip():
        raise ValueError('[CONFIG_ERROR] BRIDGE_CONFIG_DIR must not be empty.')
    try:
        root = Path(root_value).resolve(strict=True)
        if not root.is_dir():
            raise ValueError
        resolved = (root / path).resolve()
        if not resolved.is_relative_to(root):
            raise ValueError
        return resolved
    except (OSError, RuntimeError, ValueError):
        raise ValueError('[CONFIG_ERROR] Invalid runtime directory or path outside it.') from None
