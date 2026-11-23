import subprocess
import sys
from typing import Any

import boto3  # type: ignore[import-untyped]
import manage_foundation
import pytest


@pytest.mark.parametrize(
    "caller,cell,hub,message",
    [
        ("111111111111", "b", "", "another tenant"),
        ("222222222222", "a", "", "do not match"),
        ("111111111111", "a", "111111111111", "must be different"),
    ],
)
def test_wrong_tenant_or_account_never_reaches_destructive_cdk(
    monkeypatch: pytest.MonkeyPatch,
    caller: str,
    cell: str,
    hub: str,
    message: str,
) -> None:
    class Session:
        def client(self, name: str) -> "Session":
            return self

        def get_caller_identity(self) -> dict[str, str]:
            return {"Account": caller}

        def describe_stacks(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "Stacks": [
                    {
                        "Tags": [
                            {"Key": k, "Value": v}
                            for k, v in {
                                "Project": "verimed",
                                "Env": "dev",
                                "Tenant": "a",
                            }.items()
                        ]
                    }
                ]
            }

    def fail(*args: Any, **kwargs: Any) -> None:
        pytest.fail("A wrong-tenant/account command reached the CDK mutation")

    monkeypatch.setenv("VERIMED_CELL_ACCOUNT", "111111111111")
    monkeypatch.setenv("VERIMED_HUB_ACCOUNT", hub)
    monkeypatch.setattr(
        sys, "argv", ["manage_foundation", "destroy", "--env", "dev", "--cell", cell]
    )
    monkeypatch.setattr(boto3, "Session", lambda **kwargs: Session())
    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(ValueError, match=message):
        manage_foundation.main()
