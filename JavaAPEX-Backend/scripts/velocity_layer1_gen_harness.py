"""Scratch harness: drive the real Velocity Layer-1 generators to emit a
compilable Maven project so we can `mvn test` the generated Java.

Usage:
    python scripts/velocity_layer1_gen_harness.py <out_dir>
"""
from __future__ import annotations

import sys
from pathlib import Path

# Import the real generators (root-cause fixes must live here, not in output).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import velocity_test_templates as V  # noqa: E402


SAMPLE_VM = """<html>
<head><title>$title</title></head>
<body>
  <h1>$title</h1>
  #if($flag)
    <p class="on">Enabled</p>
  #else
    <p class="off">Disabled</p>
  #end
  <table>
    #foreach($row in $rows)
      <tr><td>$row.name</td><td>$row.value</td></tr>
    #end
  </table>
</body>
</html>
"""


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "_velocity_layer1_out").resolve()
    tpl_dir = out / "templates"
    tpl_dir.mkdir(parents=True, exist_ok=True)

    (tpl_dir / "ReportPage.vm").write_text(SAMPLE_VM, encoding="utf-8")

    analysis = V.analyze_template(SAMPLE_VM)
    templates = [{"template": "ReportPage.vm", "name": "ReportPage", "analysis": analysis}]

    pkg_path = out / "src" / "test" / "java" / "functionaltests" / "velocity"
    pkg_path.mkdir(parents=True, exist_ok=True)
    (pkg_path / "GeneratedVelocityRenderTest.java").write_text(
        V.render_layer1_junit(templates), encoding="utf-8"
    )
    (out / "pom.xml").write_text(V.render_layer1_pom(), encoding="utf-8")

    print("analysis:", analysis)
    print("generated project at:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
