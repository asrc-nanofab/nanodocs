# Execute a plan phase by phase

Execute a plan file from `plans/` with a phase-gated workflow.

## Selecting the plan

- If the user named a plan or has one open, use it. Otherwise use the most
  recent non-Complete plan in `plans/` and confirm the choice before starting.

## Workflow — repeat for each phase

1. **Call out the phase.** State the phase name, what it will do, which files
   it touches, and anything destructive or irreversible about it.
2. **Ask for approval.** Wait for an explicit go-ahead before executing.
   Do not batch approvals for multiple phases.
3. **Execute.** Do the work. If reality diverges from the plan (new findings,
   failed assumptions), say so immediately and update the plan file to match
   what is actually true before continuing.
4. **Update the plan.** Check off completed items with brief result notes and
   update the **Status** line.
5. **Summarize.** Report what was done, what was verified (build/lint/test
   results), and anything the user should look at, then present the next phase.

## Review gates

- A phase ending in a review gate means STOP: summarize what to verify, hand
  off to the user, and do not start the next phase until they sign off.

## Hard rules

- Never commit, push, or deploy — the user does those.
- Never skip a phase or reorder destructive steps earlier.
- If a phase fails partway, leave the plan file accurately reflecting the
  partial state and report exactly where it stopped.
