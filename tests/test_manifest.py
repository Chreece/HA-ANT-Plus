import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "custom_components" / "antplus" / "manifest.json"


def test_manifest_identity():
    data = json.loads(MANIFEST.read_text())
    assert data["domain"] == "antplus"
    assert data["name"] == "HA ANT+"
    assert data["config_flow"] is True
    assert data["single_config_entry"] is True


def test_usb_discovery_ids_are_specific():
    data = json.loads(MANIFEST.read_text())
    pairs = {(item["vid"], item["pid"]) for item in data["usb"]}
    assert ("0FCF", "1008") in pairs
    assert ("0FCF", "1009") in pairs
