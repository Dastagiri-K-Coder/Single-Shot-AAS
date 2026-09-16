# -*- coding: utf-8 -*-
"""
test_safe_pickle.py — Verification of restricted unpickler security.
"""

import pickle
import numpy as np
import pytest
from aas.core.safe_pickle import safe_load, RestrictedUnpickler


class MaliciousPayload:
    def __reduce__(self):
        import os
        return (os.system, ("echo pwned",))


def test_safe_load_valid_numpy(tmp_path):
    arr = np.random.rand(128).astype(np.float64)
    data = {"encodings": [arr], "gender": "F"}
    pkl_file = tmp_path / "valid.pkl"
    with open(pkl_file, "wb") as f:
        pickle.dump(data, f)

    loaded = safe_load(str(pkl_file))
    assert isinstance(loaded, dict)
    assert loaded["gender"] == "F"
    assert np.allclose(loaded["encodings"][0], arr)


def test_safe_load_blocks_malicious_code(tmp_path):
    evil = MaliciousPayload()
    pkl_file = tmp_path / "evil.pkl"
    with open(pkl_file, "wb") as f:
        pickle.dump(evil, f)

    with pytest.raises(pickle.UnpicklingError) as excinfo:
        safe_load(str(pkl_file))
    assert "Blocked unsafe pickle class" in str(excinfo.value)
