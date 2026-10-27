import argparse
import json
from pathlib import Path
import sys

from .evaluate import evaluate


def main(argv=None):
    parser = argparse.ArgumentParser(description="Evaluate evidence, plan/run experiments or continuations, report or browse results")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--case", help="Version 1 or 2 case JSON")
    selection.add_argument("--batch", help="Version 1 sequential batch manifest")
    selection.add_argument("--experiment", help="Version 1 repeated-trial experiment manifest")
    selection.add_argument("--resume-batch", help="Preview or continue provably unstarted entries from a coordinated batch result")
    selection.add_argument("--resume-experiment", help="Preview or continue provably unstarted samples from a bound experiment result")
    selection.add_argument("--report", help="Recheck a terminal experiment-result.json or experiment-resume-result.json without model calls")
    selection.add_argument("--browse", action="store_true", help="Serve a read-only local viewer; never executes tasks")
    parser.add_argument("--evidence", help="Version 1 or 2 offline evidence manifest")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run", action="store_true", help="Execute isolated headless tasks; may call configured models")
    mode.add_argument("--plan", action="store_true", help="Preview an experiment or continuation without executing tasks")
    parser.add_argument("--max-samples", type=int, help="Positive task-count cap for experiments or new continuation tasks")
    parser.add_argument("--expected-plan-sha256", help="Require a matching preview fingerprint; mandatory for continuation --run")
    parser.add_argument("--runs-root", help="Run output parent; --browse reads existing results from this directory")
    parser.add_argument("--reports-root", help="Parent directory for new JSON/Markdown comparison reports")
    parser.add_argument("--cases-root", help="Case library directory for --browse")
    parser.add_argument("--port", type=int, help="Loopback port for --browse; default selects a free port")
    parser.add_argument("--host-modules", help="Explicit installed Harness node_modules directory")
    parser.add_argument("--cancel-after-stream", action="store_true", help="Exercise cancellation after the first real model stream chunk")
    parser.add_argument("--output", help="Create a new result JSON; existing files are never overwritten")
    args = parser.parse_args(argv)
    if args.expected_plan_sha256 is not None and not ((args.experiment or args.resume_batch or args.resume_experiment) and args.run):
        parser.error("--expected-plan-sha256 requires --experiment, --resume-batch or --resume-experiment with --run")
    if args.max_samples is not None:
        if not (args.experiment or args.resume_batch or args.resume_experiment) or not (args.plan or args.run):
            parser.error("--max-samples requires an experiment or continuation plan/run")
        if args.max_samples <= 0:
            parser.error("--max-samples must be a positive integer")
    if args.plan and not (args.experiment or args.resume_batch or args.resume_experiment):
        parser.error("--plan requires --experiment, --resume-batch or --resume-experiment")
    if args.plan and (args.cancel_after_stream or any(value is not None for value in
                     (args.evidence, args.output, args.runs_root, args.host_modules, args.reports_root, args.cases_root, args.port))):
        parser.error("--plan cannot use execution, evidence, browse, report, or output controls; the plan is printed to stdout")
    if args.browse and (args.run or args.evidence or args.output or args.reports_root or args.host_modules or args.cancel_after_stream):
        parser.error("--browse is read-only and cannot use execution, evidence, report, or output controls")
    if not args.browse and (args.cases_root or args.port is not None):
        parser.error("--cases-root and --port require --browse")
    if args.report and (args.run or args.evidence or args.output or args.runs_root or args.host_modules or args.cancel_after_stream):
        parser.error("--report cannot use execution, evidence, or output controls; use --reports-root")
    if args.reports_root and not args.report:
        parser.error("--reports-root requires --report")
    if (args.batch or args.experiment or args.resume_batch or args.resume_experiment) and (not (args.run or args.plan) or args.evidence or args.output):
        parser.error("--batch requires --run; experiments and continuations require --run or --plan; none accepts --evidence or --output")
    if not (args.batch or args.experiment or args.resume_batch or args.resume_experiment or args.report or args.browse) and args.run == bool(args.evidence):
        parser.error("Choose --run or --evidence")
    if args.run and args.output:
        parser.error("--run saves evaluation.json in its new run directory; omit --output")
    if not args.run and not args.browse and (args.runs_root or args.host_modules or args.cancel_after_stream):
        parser.error("Run controls require --run")
    try:
        if args.browse:
            from .browser import serve
            serve(args.cases_root, args.runs_root, args.port if args.port is not None else 0)
            return 0
        if args.output and Path(args.output).resolve() in (Path(args.case).resolve(), Path(args.evidence).resolve()):
            raise ValueError("Output must differ from input paths")
        if args.report:
            from .report import generate_report
            result = generate_report(args.report, args.reports_root)
        elif args.resume_experiment:
            from .experiment_resume import plan_experiment_resume, resume_experiment
            result = (plan_experiment_resume(args.resume_experiment, max_samples=args.max_samples) if args.plan else
                      resume_experiment(args.resume_experiment, args.runs_root, args.host_modules, args.cancel_after_stream,
                                        max_samples=args.max_samples, expected_plan_sha256=args.expected_plan_sha256))
        elif args.resume_batch:
            from .resume import plan_batch_resume, resume_batch
            result = (plan_batch_resume(args.resume_batch, max_samples=args.max_samples) if args.plan else
                      resume_batch(args.resume_batch, args.runs_root, args.host_modules, args.cancel_after_stream,
                                   max_samples=args.max_samples, expected_plan_sha256=args.expected_plan_sha256))
        elif args.experiment:
            from .experiment import plan_experiment, run_experiment
            result = (plan_experiment(args.experiment, max_samples=args.max_samples) if args.plan else
                      run_experiment(args.experiment, args.runs_root, args.host_modules, args.cancel_after_stream,
                                     max_samples=args.max_samples, expected_plan_sha256=args.expected_plan_sha256))
        elif args.batch:
            from .batch import run_batch
            result = run_batch(args.batch, args.runs_root, args.host_modules, args.cancel_after_stream)
        elif args.run:
            from .runner import run_case
            result = run_case(args.case, args.runs_root, args.host_modules, args.cancel_after_stream)
        else:
            result = evaluate(args.case, args.evidence)
        text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            with Path(args.output).open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(text)
        print(text, end="")
        if args.plan:
            if args.resume_experiment:
                return 0 if result["eligibleForResume"] else 2
            return 2 if args.resume_batch and not result["canResume"] else 0
        return 0 if args.report else {"passed": 0, "failed": 1, "unevaluable": 2}[result["outcome"]]
    except (OSError, ValueError, KeyError, TypeError) as error:
        version_key = ("experimentResumePlanFormatVersion" if args.plan and args.resume_experiment else "experimentResumeResultFormatVersion" if args.resume_experiment else
                       "batchResumePlanFormatVersion" if args.plan and args.resume_batch else "experimentPlanFormatVersion" if args.plan else
                       "batchResumeResultFormatVersion" if args.resume_batch else "browserFormatVersion" if args.browse else "comparisonReportFormatVersion" if args.report else "experimentResultFormatVersion" if args.experiment else
                       "batchResultFormatVersion" if args.batch else "evaluationFormatVersion")
        state = {"valid": False, "modelCalled": False} if args.plan else {"outcome": "unevaluable"}
        print(json.dumps({version_key: 1, **state, "error": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
