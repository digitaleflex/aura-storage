# Autonomous Agent Workflow

## 1. Initialize
1. Read `AGENTS.md` and applicable nested instructions.
2. Check `git status --short --branch`, recent commits and the current diff.
3. Read relevant architecture, security, API, runbook and data-model docs.
4. Inspect the implementation and existing tests. Verify the current branch and target environment.
5. Convert the task into acceptance criteria. Identify risk level, dependencies and files likely to change.

## 2. Plan proportionally
For a small, low-risk fix, use a short internal checklist and proceed. For cross-cutting or high-risk work, record a plan with ordered steps, tests, rollback and approval gates. Do not ask for confirmation for ordinary reversible choices.

## 3. Execute autonomously
- Create a dedicated branch for a coherent task.
- Make minimal changes and preserve unrelated work.
- Add regression tests with behavior changes.
- Use synthetic data and isolated services.
- Run independent work in parallel only when agents have distinct file ownership and interfaces.
- Reconcile conflicting findings rather than silently choosing an unsupported assumption.
- If documentation conflicts, prefer the newest dated evidence for observed state, verify against the live code/config where possible, and record unresolved discrepancies.

## 4. Validate
Run the narrowest relevant tests first, then broader regression tests. Review security implications, authorization paths, failure modes and compatibility. Inspect the full diff and run `git diff --check`. Never report an unexecuted test as passing.

For infrastructure tasks, separate local Compose validation from live-host verification. Never infer production acceptance from a build, unit test or Compose parse.

## 5. Deliver
Create a commit on the task branch when authorized by repository policy, push the branch if permitted, and open a PR when the integration is ready. Do not merge protected branches or deploy without the required authority.

Provide a report with:
- Goal and outcome.
- Files changed and important decisions.
- Commands/tests executed and actual results.
- Tests not executed and reasons.
- Security/data/operational risks.
- Open approval gates.
- Recommended next action.

## 6. Recovery from failure
Investigate the root cause. Do not delete tests, disable checks or weaken permissions to force success. If blocked by missing access, external dependencies or unsafe state, finish safe work, document evidence and state exactly what is required to proceed.