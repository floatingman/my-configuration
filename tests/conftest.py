"""
Shared fixtures and configuration for profile_dispatcher tests.
"""

import sys
from pathlib import Path

import pytest

# Add scripts directory to path so profile_dispatcher can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

# Path to the real profiles directory used in integration-style tests
_PROFILES_DIR = str(Path(__file__).resolve().parent.parent / "profiles")
