import unittest

from scripts.s04_authorization_report import analyse
from scripts.test_s02_report import allowed_session, complete_block_session, event


def with_expected_identity(events):
    result = list(events)
    ready_sessions = {
        item["sessionId"]
        for item in result
        if item.get("kind") == "ready"
    }
    for session in ready_sessions:
        result.append(
            event(
                "owner_identity_expected",
                session,
                data={
                    "packageName": "com.jumpterminator.s02",
                    "packageUid": 10_418,
                    "uidSource": "dumpsys_package",
                },
            ),
        )
    return result


class S04AuthorizationReportTest(unittest.TestCase):
    def full_events(self):
        executor = "shizuku_user_service"
        return with_expected_identity(
            complete_block_session(executor=executor)
            + allowed_session(executor=executor),
        )

    def test_complete_security_and_performance_gate_passes(self):
        report = analyse(self.full_events())

        self.assertTrue(report["securityGatePassed"])
        self.assertTrue(report["performanceGatePassed"])
        self.assertEqual(
            "S04_AUTHORIZATION_GATE_PASSED",
            report["provisionalDecision"],
        )

    def test_binder_uid_must_match_runtime_package_uid(self):
        events = self.full_events()
        expectation = next(
            item for item in events if item["kind"] == "owner_identity_expected"
        )
        expectation["data"]["packageUid"] = 10_999

        report = analyse(events)

        self.assertFalse(report["securityGatePassed"])
        self.assertEqual("STOP_S04_AUTHORIZATION", report["provisionalDecision"])

    def test_raw_capability_field_is_forbidden(self):
        events = self.full_events()
        ready = next(item for item in events if item["kind"] == "ready")
        ready["data"]["capability"] = "secret"

        report = analyse(events)

        self.assertFalse(report["securityChecks"]["noRawCapabilityFields"])
        self.assertEqual("STOP_S04_AUTHORIZATION", report["provisionalDecision"])

    def test_action_after_revocation_is_forbidden(self):
        events = self.full_events()
        events.extend(
            [
                event("authorization_revoked", "block", time_ms=500_000),
                event(
                    "back_requested",
                    "block",
                    101,
                    500_001,
                    {"dispatched": True},
                ),
            ],
        )

        report = analyse(events)

        self.assertFalse(report["securityChecks"]["noActionsAfterRevocation"])
        self.assertEqual("STOP_S04_AUTHORIZATION", report["provisionalDecision"])

    def test_small_valid_sample_is_only_a_security_smoke(self):
        executor = "shizuku_user_service"
        events = with_expected_identity(complete_block_session(1, executor=executor))

        report = analyse(events)

        self.assertTrue(report["securityGatePassed"])
        self.assertFalse(report["performanceGatePassed"])
        self.assertEqual("S04_SECURITY_SMOKE_PASSED", report["provisionalDecision"])


if __name__ == "__main__":
    unittest.main()
