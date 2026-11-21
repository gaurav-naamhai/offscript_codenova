# Review job storage requirements

The in-memory repository uses a lock to claim a job and to commit its results only while the submission retains the same version, running state and job ID. This only coordinates threads in one process; its data is not shared between workers and is lost at restart.

Submission updates also compare an internal storage revision under that lock. Revisions and decisions loaded before a competing mutation receive a conflict rather than overwriting it. This internal revision is excluded from API responses. The checked-in Render configuration selects `REPO_BACKEND=memory` and starts one Uvicorn process; hosting environment overrides must be checked separately.

The Supabase submission repository is currently a placeholder. Before enabling persistent or multi-worker submission storage, implement transactional compare-and-set operations for job claim, completion and failure. Completion must atomically verify the current version and job ID, then write the status, findings and snapshot together. Revision, decisions and job cancellation must use the same transactional concurrency control, including approval invalidation. Add recovery for abandoned jobs and concurrent integration tests against a disposable database. Do not assume a process-local lock protects separate workers.
