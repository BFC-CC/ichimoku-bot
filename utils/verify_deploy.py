#!/usr/bin/env python3
"""Screenshot verification for the IchiBot v3 dashboard deployment."""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import requests
from PIL import Image

DEFAULT_URL = "https://forex-bot-r5o7.onrender.com"
DEFAULT_OUTPUT = "logs/dashboard_screenshot.png"


def check_health(url: str) -> tuple[bool, str]:
    """GET /api/health and verify response."""
    try:
        resp = requests.get(f"{url.rstrip('/')}/api/health", timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "ok":
            return True, "API responding (status=ok)"
        return False, f"Unexpected response: {data}"
    except Exception as e:
        return False, str(e)


def take_screenshot(url: str, output: str) -> tuple[bool, str]:
    """Capture a headless Firefox screenshot."""
    # Snap Firefox can't write to /tmp; use snap-writable area
    snap_dir = Path.home() / "snap" / "firefox" / "common"
    if snap_dir.exists():
        tmp_path = str(snap_dir / "dashboard_shot.png")
        profile_dir = str(snap_dir / "verify_profile")
    else:
        tmp_path = "/tmp/dashboard_screenshot.png"
        profile_dir = tempfile.mkdtemp(prefix="ff_verify_")

    # Clean up stale files
    Path(tmp_path).unlink(missing_ok=True)
    if Path(profile_dir).exists():
        shutil.rmtree(profile_dir, ignore_errors=True)
    Path(profile_dir).mkdir(parents=True, exist_ok=True)

    try:
        result = subprocess.run(
            [
                "firefox", "--headless", "--no-remote",
                "-profile", profile_dir,
                f"--screenshot={tmp_path}",
                "--window-size=1280,720",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=45,
        )
        if not Path(tmp_path).exists():
            return False, f"Screenshot file not created. stderr: {result.stderr[:200]}"

        size_kb = Path(tmp_path).stat().st_size / 1024
        img = Image.open(tmp_path)
        w, h = img.size
        img.close()

        Path(output).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(tmp_path, output)
        return True, f"{w}x{h}, {size_kb:.1f} KB"
    except subprocess.TimeoutExpired:
        return False, "Firefox timed out after 45s"
    except Exception as e:
        return False, str(e)
    finally:
        shutil.rmtree(profile_dir, ignore_errors=True)
        Path(tmp_path).unlink(missing_ok=True)


def validate_image(path: str) -> tuple[bool, str]:
    """Check the screenshot has real content (not blank)."""
    if not Path(path).exists():
        return False, "Screenshot file not found"
    if Path(path).stat().st_size == 0:
        return False, "Screenshot file is empty"

    img = Image.open(path)
    w, h = img.size
    if w < 800 or h < 600:
        img.close()
        return False, f"Image too small: {w}x{h}"

    # Sample pixels to detect all-white or all-black
    rgb = img.convert("RGB")
    pixels = list(rgb.get_flattened_data() if hasattr(rgb, "get_flattened_data") else rgb.getdata())
    img.close()
    sample = pixels[:: max(1, len(pixels) // 1000)]  # ~1000 evenly spaced pixels
    unique = set(sample)
    if len(unique) <= 2:
        return False, f"Image appears blank (only {len(unique)} unique colors)"
    return True, "content rendered (not blank)"


def main():
    parser = argparse.ArgumentParser(description="Verify dashboard deployment")
    parser.add_argument("--url", default=DEFAULT_URL, help="Dashboard URL")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Screenshot output path")
    args = parser.parse_args()

    checks = [
        ("Health check", check_health(args.url)),
        ("Screenshot captured", take_screenshot(args.url, args.output)),
        ("Image validation", validate_image(args.output)),
    ]

    print("\nDashboard Deployment Verification")
    print("=" * 38)
    all_passed = True
    for name, (ok, detail) in checks:
        tag = "PASS" if ok else "FAIL"
        if not ok:
            all_passed = False
        print(f"[{tag}] {name}: {detail}")

    print(f"\nScreenshot saved: {args.output}")
    result = "ALL CHECKS PASSED" if all_passed else "SOME CHECKS FAILED"
    print(f"Result: {result}")
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
