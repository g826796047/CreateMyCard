"""用实际渲染器表达式解析器验证连续高度、空值保护与刷新边界。"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from services.countdown_pattern import (
    GEOMETRY,
    CountdownPattern,
    pattern_fill_height,
    pattern_fill_visibility,
)


def test_actual_runtime_evaluates_continuous_pattern_fill(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.fail("未找到 Node.js；需要安装 Node.js 24 执行实际表达式解析器")
    root = Path(__file__).resolve().parents[4]
    runtime = root / "render/genui-sdk/interactions/src/expression.ts"
    requests = []
    expected = []
    states = [
        (4, 6, "还剩"), (12, 91, "还剩"), (26, 91, "还剩"),
        (6, 6, "还剩"), (99, 6, "还剩"), (1, 91, "还剩"),
        (0, 6, "就是今天"), (3, 6, "已过"), (4, 0, "还剩"),
        (0, 6, "还剩"), (4, None, "还剩"), (None, 6, "还剩"),
    ]
    for size in ("2x2", "2x4"):
        for kind in ("bars", "dots"):
            geometry = GEOMETRY.get((size, kind))
            assert geometry is not None
            count = 7 if kind == "bars" else (48 if size == "2x2" else 100)
            pattern = CountdownPattern(kind, "/data/counter/days")
            for days, total, relation in states:
                data = {pattern.relation_path: relation}
                if total is not None:
                    data[pattern.total_path] = total
                if days is not None:
                    data[pattern.days_path] = days
                ratio = 0.0
                if relation == "还剩" and days and total:
                    ratio = min(max(days / total, 0.0), 1.0)
                for index in range(count):
                    height = min(max(ratio * count - index, 0.0), 1.0) * geometry.height
                    requests.append({
                        "data": data,
                        "height": pattern_fill_height(pattern, index, geometry),
                        "visibility": pattern_fill_visibility(pattern, index, geometry),
                    })
                    expected.append((height, "visible" if height > 0 else "none"))
    payload = tmp_path / "requests.json"
    payload.write_text(json.dumps(requests, ensure_ascii=False), encoding="utf-8")
    runner = tmp_path / "evaluate.mjs"
    runner.write_text(
        "import fs from 'node:fs';\n"
        "import {pathToFileURL} from 'node:url';\n"
        "const [runtime,payload]=process.argv.slice(2);\n"
        "const {evaluateExpression}=await import(pathToFileURL(runtime).href);\n"
        "const result=JSON.parse(fs.readFileSync(payload,'utf8')).map(item=>{\n"
        " const evaluate=value=>evaluateExpression(value.slice(2,-2).trim(),p=>item.data[p]);\n"
        " return [evaluate(item.height),evaluate(item.visibility)];\n"
        "});\n"
        "process.stdout.write(JSON.stringify(result));\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [node, str(runner), str(runtime), str(payload)],
        capture_output=True, text=True, encoding="utf-8", check=True,
    )
    actual = json.loads(result.stdout)
    assert len(actual) == len(expected)
    for observed, wanted in zip(actual, expected, strict=True):
        assert observed[0] == pytest.approx(wanted[0], abs=1e-8)
        assert observed[1] == wanted[1]
