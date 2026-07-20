"""Root conftest — add source root to sys.path for all tests."""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
