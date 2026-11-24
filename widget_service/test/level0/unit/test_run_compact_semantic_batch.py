"""语义批跑工具的预览产物及 Windows 进程清理回归。"""

import argparse
import asyncio
import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from tools import run_compact_semantic_batch as batch


def test_prepare_preview_uses_run_directory(tmp_path):
    meta = {"index": 1, "traceDirectory": "trace"}
    source = tmp_path / "md" / "q1_artifact.md"
    source.parent.mkdir()
    source.write_text("card", encoding="utf-8")

    batch.prepare_preview(tmp_path, meta)

    preview = tmp_path / "preview"
    assert (preview / "md/q1_artifact.md").read_text(encoding="utf-8") == "card"
    assert json.loads((preview / "q1_meta.json").read_text(encoding="utf-8")) == meta


@pytest.mark.skipif(os.name != "nt", reason="Windows 专属的进程树清理")
def test_windows_cleanup_uses_system_taskkill(tmp_path, monkeypatch):
    (tmp_path / "runner.py").touch()
    cases = tmp_path / "cardSpec24"
    cases.mkdir()
    (cases / "Q1.json").touch()
    runner = MagicMock()
    runner.is_port_in_use.return_value = False
    proc = runner.start_server.return_value
    proc.poll.return_value = None
    proc.pid = 123
    runner.run_single.side_effect = ValueError("case failed")
    monkeypatch.setattr(batch.importlib.util, "module_from_spec", lambda spec: runner)
    # 空 runner 文件无需执行，避免加载器修改模拟对象。
    monkeypatch.setattr("importlib.machinery.SourceFileLoader.exec_module", lambda self, mod: None)
    command = MagicMock()
    monkeypatch.setattr(batch.subprocess, "run", command)
    monkeypatch.setattr(batch.os, "environ", dict(os.environ, SystemRoot=os.environ["SystemRoot"]))
    args = argparse.Namespace(
        native=tmp_path, output=tmp_path / "out", cases=[], port=9009, repairs=1
    )

    with pytest.raises(ValueError, match="case failed"):
        asyncio.run(batch.run(args))

    executable = Path(os.environ["SystemRoot"]) / "System32" / "taskkill.exe"
    command.assert_called_once_with(
        [executable, "/PID", "123", "/T", "/F"], capture_output=True, check=False
    )
