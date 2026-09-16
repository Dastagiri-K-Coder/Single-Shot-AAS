# -*- coding: utf-8 -*-
"""
safe_pickle.py — Restricted pickle deserialization for Single Shot AAS.

Prevents arbitrary code execution from malicious .pkl files by only
allowing numpy arrays and basic Python types to be unpickled.

Usage:
    from aas.core.safe_pickle import safe_load
    payload = safe_load("/path/to/encodings/student.pkl")
"""

import pickle
import io


# Allowlisted modules and classes for unpickling face encodings
_SAFE_CLASSES = {
    ("numpy", "ndarray"),
    ("numpy", "dtype"),
    ("numpy.core.multiarray", "_reconstruct"),
    ("numpy.core.multiarray", "scalar"),
    ("numpy", "core.multiarray._reconstruct"),
    ("builtins", "dict"),
    ("builtins", "list"),
    ("builtins", "tuple"),
    ("builtins", "set"),
    ("builtins", "frozenset"),
    ("builtins", "str"),
    ("builtins", "int"),
    ("builtins", "float"),
    ("builtins", "bool"),
    ("builtins", "bytes"),
    ("builtins", "type"),
    ("builtins", "complex"),
    ("collections", "OrderedDict"),
    # numpy internals used by encoding serialization
    ("numpy", "float64"),
    ("numpy", "int64"),
    ("numpy", "int32"),
    ("numpy", "float32"),
}


class RestrictedUnpickler(pickle.Unpickler):
    """Unpickler that only allows safe, known classes."""

    def find_class(self, module: str, name: str):
        if (module, name) in _SAFE_CLASSES:
            return super().find_class(module, name)
        raise pickle.UnpicklingError(
            f"Blocked unsafe pickle class: {module}.{name}. "
            f"Only numpy arrays and basic types are allowed."
        )


def safe_load(filepath: str):
    """
    Safely load a pickle file, blocking arbitrary code execution.

    Only allows numpy arrays and basic Python types (dict, list, str, etc.).
    Raises pickle.UnpicklingError if the file contains unsafe classes.

    Args:
        filepath: Absolute or relative path to the .pkl file.

    Returns:
        The deserialized Python object.
    """
    with open(filepath, 'rb') as fp:
        data = fp.read()
    return RestrictedUnpickler(io.BytesIO(data)).load()
