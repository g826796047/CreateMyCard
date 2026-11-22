"""在线卡片校验命令的退出码约定。"""

import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

SCRIPTS = Path(__file__).resolve().parents[4] / "skills/harmony-card-generation-online/scripts"


@pytest.mark.parametrize("fail_on_error", [False, True])
@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("errors,warnings", [(0, 0), (0, 1), (1, 0), (1, 1)])
def test_online_validator_exit_code(monkeypatch, fail_on_error, strict, errors, warnings):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    import validate_card

    reporter = Mock(error_count=errors, warning_count=warnings)
    monkeypatch.setattr(validate_card, "validate_card", Mock(return_value=reporter))
    arguments = ["validate_card"]
    if fail_on_error:
        arguments.append("--fail-on-error")
    if strict:
        arguments.append("--strict")
    monkeypatch.setattr(sys, "argv", arguments)

    expected = int(fail_on_error and (errors > 0 or (strict and warnings > 0)))
    assert validate_card.main() == expected
