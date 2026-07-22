"""Validation for the Selenium Grid video sidecar + Allure video attachment.

The user asked to also get a real VIDEO when the Selenium tests run on a headless
Docker Grid (where the Monte in-JVM recorder can't capture a display). The
pipeline now attaches a ``selenium/video`` sidecar that screen-records the Chrome
container, then copies the MP4 out and attaches it to the E2E journey test in the
Allure report.

This smoketest verifies the pure-Python glue WITHOUT Docker:

  1. ``_selenium_grid_video_enabled`` defaults on and respects the
     SELENIUM_GRID_VIDEO=0/false/off toggle.

  2. ``_attach_file_to_allure`` attaches the MP4 to the RIGHT Allure result — the
     E2E journey (not an unrelated test) — copies the file next to the results as
     ``<uuid>-attachment.mp4`` (so ``mvn allure:report`` bundles it), and records a
     ``video/mp4`` attachment entry in that result's JSON.
"""
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
BACKEND = HERE.parents[1]
PIPELINE = BACKEND / "services" / "functional_test_pipeline.py"


def _load_pipeline_module():
    spec = importlib.util.spec_from_file_location("ftp_isolated_grid_video", str(PIPELINE))
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("ftp_isolated_grid_video", mod)
    spec.loader.exec_module(mod)
    return mod


def check(cond: bool, ok_msg: str, fail_msg: str, failures: list) -> None:
    if cond:
        print(f"  PASS: {ok_msg}")
    else:
        print(f"  FAIL: {fail_msg}")
        failures.append(fail_msg)


def main() -> int:
    mod = _load_pipeline_module()

    cls = None
    for name in dir(mod):
        obj = getattr(mod, name)
        if isinstance(obj, type) and hasattr(obj, "_attach_file_to_allure"):
            cls = obj
            break
    if cls is None:
        print("FAIL: could not find class with _attach_file_to_allure")
        return 1
    print(f"Using pipeline class: {cls.__name__}\n")

    inst = cls.__new__(cls)
    failures: list = []

    # ---- 1. env toggle -------------------------------------------------------
    print("[1] _selenium_grid_video_enabled():")
    saved = os.environ.pop("SELENIUM_GRID_VIDEO", None)
    try:
        check(inst._selenium_grid_video_enabled() is True,
              "defaults ON when unset", "should default ON", failures)
        for val in ("0", "false", "off", "no"):
            os.environ["SELENIUM_GRID_VIDEO"] = val
            check(inst._selenium_grid_video_enabled() is False,
                  f"OFF when SELENIUM_GRID_VIDEO={val}", f"should be OFF for {val}", failures)
        for val in ("1", "true", "on"):
            os.environ["SELENIUM_GRID_VIDEO"] = val
            check(inst._selenium_grid_video_enabled() is True,
                  f"ON when SELENIUM_GRID_VIDEO={val}", f"should be ON for {val}", failures)
    finally:
        os.environ.pop("SELENIUM_GRID_VIDEO", None)
        if saved is not None:
            os.environ["SELENIUM_GRID_VIDEO"] = saved

    # ---- 2. attach video to the journey result -------------------------------
    print("\n[2] _attach_file_to_allure(allure_results, video, ...):")
    tmp = Path(tempfile.mkdtemp())
    allure_results = tmp / "allure-results"
    allure_results.mkdir(parents=True, exist_ok=True)

    # An unrelated login test (fewer steps) and the E2E journey (should win).
    (allure_results / "aaaa-result.json").write_text(json.dumps({
        "uuid": "aaaa", "name": "loginWorks",
        "fullName": "GeneratedSeleniumFunctionalTest.loginWorks",
        "status": "passed", "steps": [{"name": "s1"}],
    }), encoding="utf-8")
    (allure_results / "bbbb-result.json").write_text(json.dumps({
        "uuid": "bbbb", "name": "E2E_user_journey_across_4_pages",
        "fullName": "GeneratedSeleniumFunctionalTest.E2E_user_journey_across_4_pages",
        "status": "passed", "steps": [{"name": "n1"}, {"name": "n2"}, {"name": "n3"}],
    }), encoding="utf-8")

    video = tmp / "journey.mp4"
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42FAKE-VIDEO-BYTES")

    ok = inst._attach_file_to_allure(
        allure_results, video, attach_name="E2E journey — screen recording", mime="video/mp4",
    )
    check(ok is True, "returned True (attachment added)", "attach returned False", failures)

    journey = json.loads((allure_results / "bbbb-result.json").read_text(encoding="utf-8"))
    login = json.loads((allure_results / "aaaa-result.json").read_text(encoding="utf-8"))

    j_atts = journey.get("attachments", [])
    check(len(j_atts) == 1 and j_atts[0].get("type") == "video/mp4",
          "video/mp4 attachment added to the E2E journey result",
          f"journey attachments wrong: {j_atts}", failures)
    check(not login.get("attachments"),
          "unrelated login test was NOT touched",
          "attachment leaked onto the wrong test", failures)

    if j_atts:
        source = j_atts[0].get("source", "")
        src_path = allure_results / source
        check(source.endswith("-attachment.mp4") and src_path.exists(),
              f"attachment file copied next to results ({source})",
              f"attachment source missing/misnamed: {source}", failures)
        check(src_path.read_bytes() == video.read_bytes(),
              "copied video bytes match the source", "copied video bytes differ", failures)

    # no results dir → graceful False
    check(inst._attach_file_to_allure(tmp / "nope", video, "x", "video/mp4") is False,
          "returns False when there are no Allure results",
          "should return False without results", failures)

    print()
    if failures:
        print(f"RESULT: FAIL ({len(failures)} problem(s))")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("RESULT: PASS — Grid sidecar video attaches to the Allure journey test")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
