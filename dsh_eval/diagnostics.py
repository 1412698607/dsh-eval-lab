"""Summarize diagnostic assertions from freshly evaluated report samples."""

OUTCOMES = ("passed", "failed", "insufficient_evidence", "not_run")


def diagnostic_sample(evaluation):
    rows = [row for row in evaluation["assertions"]["results"] if row.get("role") == "diagnostic"]
    return {"declaredAssertions": len(rows),
            "outcomes": {outcome: sum(row["outcome"] == outcome for row in rows) for outcome in OUTCOMES},
            "failedAssertionIds": [row["id"] for row in rows if row["outcome"] == "failed"],
            "insufficientAssertionIds": [row["id"] for row in rows if row["outcome"] == "insufficient_evidence"],
            "notRunAssertionIds": [row["id"] for row in rows if row["outcome"] == "not_run"]}


def diagnostic_summary(samples):
    observed = [row for row in samples if row.get("diagnosticSummary") is not None]
    failed = [row for row in observed if row["diagnosticSummary"]["outcomes"]["failed"] > 0]
    return {"observedSamples": len(observed), "missingSamples": len(samples) - len(observed),
            "samplesWithDiagnostics": sum(row["diagnosticSummary"]["declaredAssertions"] > 0 for row in observed),
            "samplesWithFailures": len(failed),
            "passedSamplesWithFailures": sum(row["outcome"] == "passed" for row in failed),
            "assertionCounts": {outcome: sum(row["diagnosticSummary"]["outcomes"][outcome] for row in observed)
                                for outcome in OUTCOMES}}
