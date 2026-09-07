"""DELIBERATE FAILURE -- red-proof for the CI gate (model_performance-j1e6).

This file exists on a scratch branch only, to prove .github/workflows/ci.yml
can actually go red *from inside the test job*, with the real suite collected
and executing around it. It is deleted with its branch.
"""


def test_red_proof_this_must_fail():
    assert 1 == 2, "deliberate red-proof failure -- the CI test job is executing the real suite"
