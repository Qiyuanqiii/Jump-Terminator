import unittest

from scripts.s0_report import analyse, make_samples, metric


def event(time_ms, kind, package=None, data=None):
    payload = dict(data or {})
    if kind == "accessibility_signal":
        payload.setdefault("receiptDelayMs", 0)
    elif kind == "usage_signal":
        payload.setdefault("eventWallClockMs", time_ms)
    elif kind == "transition_candidate":
        payload.setdefault("targetEnteredElapsedMs", time_ms)
        payload.setdefault("signalAgeMs", 0)
    return {
        "eventId": f"{kind}-{time_ms}",
        "elapsedRealtimeMs": time_ms,
        "wallClockMs": time_ms,
        "_time": time_ms,
        "kind": kind,
        "packageName": package,
        "data": payload,
    }


def issued(time_ms, run_id, sequence, expected, target, trigger_type):
    return event(
        time_ms,
        "ground_truth",
        "com.jumpterminator.testsource",
        {
            "phase": "trigger_issued",
            "runId": run_id,
            "sequence": sequence,
            "expected": expected,
            "targetPackage": target,
            "triggerType": trigger_type,
            "originElapsedMs": time_ms,
        },
    )


def target_entered(time_ms, run_id, sequence, target):
    return event(
        time_ms,
        "ground_truth",
        target,
        {
            "phase": "target_entered",
            "runId": run_id,
            "sequence": sequence,
            "expected": "block",
            "targetPackage": target,
            "triggerType": "automatic_batch",
            "originElapsedMs": time_ms,
        },
    )


class S0ReportTest(unittest.TestCase):
    def test_zero_of_two_hundred_wilson_upper_is_under_two_percent(self):
        result = metric(0, 200)
        self.assertLess(result["wilson95"][1], 0.02)

    def test_correlates_block_and_allow_samples(self):
        target = "com.jumpterminator.testtarget"
        events = [
            issued(1_000, "block-run", 1, "block", target, "manual_click"),
            target_entered(1_040, "block-run", 1, target),
            event(1_050, "accessibility_signal", target),
            event(1_060, "usage_signal", target, {"signal": "FOREGROUND"}),
            event(1_070, "transition_candidate", target),
            event(1_080, "policy_decision", target, {"shouldAct": True}),
            event(1_100, "action_attempt", target, {"stage": "back"}),
            event(1_200, "action_verification", target, {"stage": "back", "leftTarget": True}),
            issued(3_000, "allow-run", 1, "allow", "com.android.settings", "allowed_settings"),
            event(3_100, "accessibility_signal", "com.android.settings"),
        ]
        events.sort(key=lambda item: item["_time"])

        report = analyse(events, make_samples(events))

        self.assertEqual(1.0, report["metrics"]["targetEventAcquisitionCombined"]["pointEstimate"])
        self.assertEqual(1.0, report["metrics"]["blockCandidateIdentification"]["pointEstimate"])
        self.assertEqual(0.0, report["metrics"]["allowedFlowFalseBlock"]["pointEstimate"])
        self.assertEqual(1.0, report["metrics"]["finalLeaveTarget"]["pointEstimate"])
        self.assertEqual(30, report["latencyMs"]["candidateP95"])
        self.assertEqual("NOT_READY", report["provisionalDecision"])

    def test_flags_repeated_global_action(self):
        target = "com.jumpterminator.testtarget"
        events = [
            issued(1_000, "unsafe", 1, "block", target, "automatic_batch"),
            event(1_050, "policy_decision", target, {"shouldAct": True}),
            event(1_100, "action_attempt", target, {"stage": "back"}),
            event(1_150, "action_attempt", target, {"stage": "back"}),
        ]

        report = analyse(events, make_samples(events))

        self.assertEqual(1, len(report["safetyViolations"]))

    def test_stale_candidate_signal_is_not_matched_to_next_trigger(self):
        target = "com.jumpterminator.testtarget"
        events = [
            issued(1_000, "fresh", 1, "block", target, "automatic_batch"),
            event(
                1_100,
                "transition_candidate",
                target,
                {"targetEnteredElapsedMs": 500, "evidence": "usage_stats"},
            ),
        ]

        report = analyse(events, make_samples(events))

        self.assertEqual(0.0, report["metrics"]["blockCandidateIdentification"]["pointEstimate"])

    def test_delayed_delivery_is_eventual_but_not_realtime(self):
        target = "com.jumpterminator.testtarget"
        events = [
            issued(1_000, "frozen", 1, "block", target, "automatic_batch"),
            target_entered(1_040, "frozen", 1, target),
            event(1_050, "accessibility_signal", target, {"receiptDelayMs": 60_000}),
            event(
                1_060,
                "usage_signal",
                target,
                {"signal": "FOREGROUND", "eventWallClockMs": -58_940},
            ),
            event(
                61_070,
                "transition_candidate",
                target,
                {"targetEnteredElapsedMs": 1_050, "signalAgeMs": 60_020},
            ),
        ]
        events.sort(key=lambda item: item["_time"])

        report = analyse(events, make_samples(events))

        self.assertEqual(0.0, report["metrics"]["targetEventAcquisitionCombined"]["pointEstimate"])
        self.assertEqual(
            1.0,
            report["metrics"]["targetEventAcquisitionCombinedEventually"]["pointEstimate"],
        )
        self.assertEqual(0.0, report["metrics"]["blockCandidateIdentification"]["pointEstimate"])
        self.assertEqual(
            1.0,
            report["metrics"]["blockCandidateIdentificationEventually"]["pointEstimate"],
        )
        self.assertEqual(60_000, report["latencyMs"]["accessibilityReceiptP95"])

    def test_candidate_must_match_the_truth_target_entry(self):
        target = "com.jumpterminator.testtarget"
        events = [
            issued(1_000, "mismatch", 1, "block", target, "automatic_batch"),
            target_entered(1_050, "mismatch", 1, target),
            event(
                1_100,
                "transition_candidate",
                target,
                {"targetEnteredElapsedMs": 1_800, "signalAgeMs": 0},
            ),
        ]
        events.sort(key=lambda item: item["_time"])

        report = analyse(events, make_samples(events))

        self.assertEqual(
            0.0,
            report["metrics"]["blockCandidateIdentificationEventually"]["pointEstimate"],
        )

    def test_delayed_verification_stays_with_its_original_action_chain(self):
        target = "com.jumpterminator.testtarget"
        events = [
            issued(1_000, "delayed", 1, "block", target, "automatic_batch"),
            target_entered(1_050, "delayed", 1, target),
            event(1_080, "transition_candidate", target, {"targetEnteredElapsedMs": 1_050}),
            event(1_090, "policy_decision", target, {"shouldAct": True, "targetEnteredElapsedMs": 1_050}),
            event(1_100, "action_attempt", target, {"stage": "back", "targetEnteredElapsedMs": 1_050}),
            issued(7_000, "delayed", 2, "block", target, "automatic_batch"),
            event(
                7_010,
                "action_verification",
                target,
                {"stage": "back", "leftTarget": True, "totalLatencyMs": 5_960},
            ),
            target_entered(7_050, "delayed", 2, target),
            event(7_080, "transition_candidate", target, {"targetEnteredElapsedMs": 7_050}),
            event(7_090, "policy_decision", target, {"shouldAct": True, "targetEnteredElapsedMs": 7_050}),
            event(7_100, "action_attempt", target, {"stage": "back", "targetEnteredElapsedMs": 7_050}),
            event(
                7_200,
                "action_verification",
                target,
                {"stage": "back", "leftTarget": True, "targetEnteredElapsedMs": 7_050},
            ),
        ]
        events.sort(key=lambda item: item["_time"])

        report = analyse(events, make_samples(events))

        self.assertEqual(2, report["metrics"]["finalLeaveTarget"]["successes"])
        self.assertEqual(2, report["metrics"]["finalLeaveTarget"]["total"])
        self.assertEqual(5_960, report["latencyMs"]["leaveTargetP95"])


if __name__ == "__main__":
    unittest.main()
