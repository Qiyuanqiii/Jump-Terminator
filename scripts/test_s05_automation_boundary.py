import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "s02-shizuku-poc"
SOURCE_MODULE = ROOT / "test-source"
ANDROID = "{http://schemas.android.com/apk/res/android}"


def activities(path):
    root = ET.parse(path).getroot()
    application = root.find("application")
    return {
        item.attrib[f"{ANDROID}name"]: item
        for item in application.findall("activity")
    }


class S05AutomationBoundaryTest(unittest.TestCase):
    def test_public_manifest_contains_only_launcher_entry(self):
        declared = activities(MODULE / "src/main/AndroidManifest.xml")

        self.assertIn(".MainActivity", declared)
        self.assertEqual("true", declared[".MainActivity"].attrib[f"{ANDROID}exported"])
        self.assertNotIn(".AutomationActivity", declared)

    def test_debug_automation_activity_requires_adb_permission(self):
        declared = activities(MODULE / "src/debug/AndroidManifest.xml")

        self.assertEqual(
            "true",
            declared[".AutomationActivity"].attrib[f"{ANDROID}exported"],
        )
        self.assertEqual(
            "android.permission.DUMP",
            declared[".AutomationActivity"].attrib[f"{ANDROID}permission"],
        )
        self.assertEqual(
            "singleTask",
            declared[".AutomationActivity"].attrib[f"{ANDROID}launchMode"],
        )
        self.assertEqual(
            "${applicationId}.automation",
            declared[".AutomationActivity"].attrib[f"{ANDROID}taskAffinity"],
        )

    def test_device_runners_use_adb_only_debug_component(self):
        for relative in ("scripts/s02-shizuku-run.ps1", "scripts/s03-lifecycle.ps1"):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("com.jumpterminator.s02/.AutomationActivity", source)
            self.assertNotIn("$pocComponent = 'com.jumpterminator.s02/.MainActivity'", source)
            self.assertNotIn("'run-as', $pocPackage, 'am', 'start'", source)

    def test_ordinary_uid_probe_is_debug_only_and_never_arms(self):
        public = activities(SOURCE_MODULE / "src/main/AndroidManifest.xml")
        debug = activities(SOURCE_MODULE / "src/debug/AndroidManifest.xml")
        probe_source = (
            SOURCE_MODULE
            / "src/debug/java/com/jumpterminator/testsource/AutomationBoundaryProbeActivity.kt"
        ).read_text(encoding="utf-8")

        self.assertNotIn(".AutomationBoundaryProbeActivity", public)
        self.assertIn(".AutomationBoundaryProbeActivity", debug)
        self.assertIn('putExtra("jt_s02_armed", false)', probe_source)


if __name__ == "__main__":
    unittest.main()
