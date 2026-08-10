import json
import re
from pathlib import Path


def test_release_version_uses_calendar_increment_scheme():
    manifest = json.loads(Path("custom_components/antplus/manifest.json").read_text())
    version = manifest["version"]
    assert re.fullmatch(r"20\d{2}\.\d{1,2}\.\d+", version)
    assert version == "2026.8.1"
