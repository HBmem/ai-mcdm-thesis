# Database Config

## ScenarioSnapshot

scenario_id 
scenario_version
scenario_type
title
domain
status
config_hash
config_snapshot_json
created_at

sessions

## Session

session_id 
scenario_id
scenario_version
title
description
admin_notes
visibility
participation_method
preference_scale
weighting_method
ranking_method
preference_elicitation_method
require_access_code
access_code_type
allow_resubmissions
start_at
end_at
status
opened_at
closed_at
archived_at
created_at
created_by
updated_at

snapshot
stakeholder_groups
participants

## SessionStakeholderGroup

session_id
stakeholder_group_id
stakeholder_group_name
default_voting_power
current_voting_power
normalized_voting_power
is_active
created_at
updated_at
updated_by

session
participants

## Participant

participant_id
session_id
user_id
stakeholder_group_id
name
alias
access_status
joined_at
disabled_at
disabled_by
created_at
created_by
updated_at
updated_by

session
stakeholder_group
submissions

## Submission

submission_id
participant_id
attempt_number
previous_submission_id
status
answers_json
started_at
last_saved_at
submitted_at
submitted_by
superseded_at
withdrawn_at
withdrawn_by
created_at
created_by
updated_at
updated_by

participant
previous_submission
replacement_attempts

## SubmissionValidation

validation_id           primary_key
submission_id
answers_hash
weighting_method
validator_version
completion_ratio
weights_json
consistency_ratio
is_valid
errors_json
validated_at
validated_by

## ProcessingRuns

processing_run_id           primary key
session_id                  foreign key → sessions
run_number                  sequential within session
status                      pending/running/succeeded/failed/cancelled
weighting_method
ranking_method
aggregation_method
processor_version
input_hash
configuration_json
criteria_order_json
started_at
started_by
completed_at
failed_at
error_json
created_at
created_by

Constraints and indexes:
- Unique (session_id, run_number).
- Index (session_id, status).
- Index (session_id, completed_at).
- Only one running processing run per session, preferably enforced by a partial unique index.
- completed_at required for a successful run.
- Failure metadata required for a failed run.
- input_hash should represent all inputs that affect the result:
- Scenario snapshot hash.
- Session method configuration.
- Selected submission-validation IDs.
- Stakeholder voting power.
- Algorithm and processor versions

## ProcessingRunInputs

processing_run_id          foreign key → processing_runs
submission_validation_id   foreign key → submission_validations
participant_id
stakeholder_group_id
included                   boolean
participant_weight
group_weight
exclusion_reason
created_at

This table is important for reproducibility. Without it, you may know that a session was processed, but not which revisions of participant submissions were included.

## AnalysisResults

analysis_result_id
processing_run_id          foreign key → processing_runs
result_type
schema_version
algorithm
algorithm_version
result_json
created_at
created_by

- unique(processing_run_id, result_type, schema_version)

## Audit_Events

audit_event_id
occurred_at
actor_type
actor_id
action
entity_type
entity_id
session_id                 nullable, indexed
correlation_id             nullable
before_json                nullable
after_json                 nullable
metadata_json

### Example actions:

session.created
session.opened
session.closed
session.archived
participant.enrolled
participant.disabled
submission.started
submission.saved
submission.submitted
submission.withdrawn
submission.superseded
submission.validated
processing.started
processing.completed
processing.failed
analysis.created


### Indexes:

(session_id, occurred_at)
(entity_type, entity_id, occurred_at)
(actor_id, occurred_at)
(correlation_id)

Audit events should be written in the same unit-of-work transaction as the action they describe. For example:
Update submission
→ Add submission.submitted audit event
→ Commit both together

If the transaction fails, neither the submission change nor its audit event should remain.
Avoid storing:
Plaintext access codes.
Authentication secrets.
Full prompts containing sensitive participant information.
Unnecessary personal data.
Duplicate raw submissions when an entity ID and change summary are sufficient.

## AI reports later

Do not add a placeholder ai_reports table to the current baseline unless you already need it.
When AI reporting begins, add a new Alembic revision:
0004_add_ai_reports.py

A likely future relationship is:
processing_run
    └── analysis_results
            └── ai_report generation

Likely fields eventually include:
ai_report_id
session_id
processing_run_id
status
report_type
model_provider
model_name
prompt_template_version
input_hash
report_markdown
structured_report_json
citations_json
started_at
completed_at
failed_at
error_json
created_by
But those fields should be driven by actual reporting requirements.

Service and repository boundaries

domain/
    processing.py
    analysis.py
    audit.py

application/services/
    processing_service.py
    analysis_service.py
    audit_service.py

application/ports/
    repositories.py
    unit_of_work.py

infrastructure/database/repositories/
    processing_run_repository.py
    analysis_result_repository.py
    audit_repository.py

```Python
class UnitOfWork(Protocol):
    sessions: SessionRepository
    participants: ParticipantRepository
    submissions: SubmissionRepository
    submission_validations: SubmissionValidationRepository
    processing_runs: ProcessingRunRepository
    analysis_results: AnalysisResultRepository
    audit_events: AuditEventRepository
```

## Processing service responsibilities

ProcessingService should:

1. Load the session.
2. Confirm the session can be processed.
3. Find current effective submissions.
4. Find matching valid submission validations.
5. Apply required-participation rules.
Create a processing run.
Record exact processing inputs.
Aggregate the pairwise matrices.
Generate criterion weights.
Run TOPSIS/Fuzzy TOPSIS.
Store analysis results.
Complete or fail the processing run.
Add audit events.
Commit the complete result atomically where practical.


