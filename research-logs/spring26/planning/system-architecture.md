# System Architecture Overview

## System Architecture Layer

```txt
Streamlit UI Layer
  ├── Stakeholder Dashboard
  └── Moderator Dashboard

Application Service Layer
  ├── Scenario Registry Service
  ├── Session Management Service
  ├── Stakeholder Access Service
  ├── Preference Submission Service
  ├── Voting Power Service
  ├── Preprocessing Orchestration Service
  └── Export / Handoff Service

Domain Layer
  ├── Scenario
  ├── PollingSession
  ├── Stakeholder
  ├── SessionParticipant
  ├── PreferenceSubmission
  ├── VotingPowerAssignment
  ├── PreprocessingRun
  └── ExportRecord

Infrastructure Layer
  ├── Scenario File Loader
  ├── Config Validator
  ├── Database Repository
  ├── Preprocessing Step Registry
  ├── Approved Function Loader
  ├── Logger / Audit Trail
  └── File Export Writer

Downstream MCDM Layers
  ├── Data Acquisition and Policy Modeling
  ├── AHP / Fuzzy AHP Weight Derivation
  ├── TOPSIS / Fuzzy TOPSIS Ranking
  ├── AI Interpretation
  └── Verification
```

## System Directory Structure

```txt
policy_mcdm/
│
├── app/
│   ├── main.py
│   ├── pages/
│   │   ├── stakeholder_dashboard.py
│   │   └── moderator_dashboard.py
│   │
│   ├── services/
│   │   ├── scenario_registry_service.py
│   │   ├── session_service.py
│   │   ├── stakeholder_service.py
│   │   ├── preference_service.py
│   │   ├── voting_power_service.py
│   │   ├── preprocessing_service.py
│   │   └── export_service.py
│   │
│   ├── domain/
│   │   ├── scenario.py
│   │   ├── session.py
│   │   ├── stakeholder.py
│   │   ├── preference.py
│   │   ├── preprocessing.py
│   │   └── export_contracts.py
│   │
│   ├── infrastructure/
│   │   ├── db.py
│   │   ├── repositories.py
│   │   ├── config_loader.py
│   │   ├── config_validator.py
│   │   ├── preprocessing_executor.py
│   │   ├── function_loader.py
│   │   └── audit_logger.py
│   │
│   ├── schemas/
│   │   ├── scenario_schema.py
│   │   ├── preprocessing_schema.py
│   │   ├── data_sources_schema.py
│   │   └── submission_schema.py
│   │
│   └── utils/
│       ├── ids.py
│       ├── hashing.py
│       └── time.py
│
├── scenarios/
│   ├── seattle_school_closure/
│   │   ├── scenario.json
│   │   ├── criteria.json
│   │   ├── data_sources.json
│   │   ├── preprocessing.json
│   │   ├── session_rules.json
│   │   ├── ui_config.json
│   │   ├── functions.py
│   │   ├── README.md
│   │   └── data/
│   │       ├── population.csv
│   │       └── budget.csv
│   │
│   └── smart_energy_priority/
│       ├── scenario.json
│       ├── data_sources.json
│       ├── preprocessing.json
│       ├── ui_config.json
│       └── data/
│
├── exports/
│   ├── submissions/
│   ├── session_handoffs/
│   └── preprocessing_metadata/
│
├── logs/
│   ├── app.log
│   └── preprocessing.log
│
├── tests/
│   ├── test_config_validation.py
│   ├── test_preprocessing_pipeline.py
│   ├── test_submission_validation.py
│   └── test_voting_power.py
│
├── database/
│   └── prototype.sqlite
│
├── requirements.txt
└── README.md
```

## System Architecture Components

### Scenario Registry Service

This service is responsible for loading scenarios as read-only definitions.

| Responsibility | Description |
| -------------- | ----------- |
| Discover scenarios | Scan `./scenarios/*/scenario.json` |
| Validate configs | Validate `scenario.json`, `criteria.json`, `data_sources.json`, and `preprocessing.json` |
| Build scenario catalog | Return only valid, enabled scenarios |
| Version configs | Compute config hash and store scenario snapshot |
| Resolve file paths | Ensure all paths remain inside the scenario folder |
| Surface config errors | Show moderator-friendly validation reports |

### Session Management Service

This service is responsible for managing polling sessions.

| Responsibility | Description |
| -------------- | ----------- |
| Create polling session | Select scenario and session mode |
| Manage lifecycle | `draft → open → locked → processing → completed` |
| Track participants | Maintain invited, started, submitted, excluded states |
| Enforce rules | Single-stakeholder, multi-stakeholder, required groups |
| Lock session | Prevent further submissions |
| Trigger handoff | Create export once ready |

### Preference Submission Service

This service is responsible for managing stakeholder preferences submission.

| Responsibility | Description |
| -------------- | ----------- |
| Validate stakeholder access | Check invitation code, type, session status |
| Render configured preference method | Linguistic ratings by default |
| Validate completeness | Require one preference per required criterion |
| Transform preferences | Convert linguistic ratings to numeric and/or fuzzy values |
| Store raw and transformed forms | Preserve research traceability |
| Prevent duplicates | Unless session allows revisions |

### Voting Power Service

This service is responsible for managing stakeholder voting power influence.

| Responsibility | Description |
| -------------- | ----------- |
| Read default group powers | From scenario/session config |
| Apply moderator overrides | Participant-level or group-level |
| Normalize effective weights | Ensure submitted stakeholder power sums to 1 |
| Export voting metadata | Preserve raw, effective, and normalized power |
| Support later aggregation | Produce stakeholder influence values for AHP/Fuzzy AHP aggregation |

### Preprocessing Service

This service is responsible for applying and managing necessary preprocessing steps.

| Responsibility | Description |
| -------------- | ----------- |
| Validate preprocessing config | Check step types, input references, output names |
| Execute safe built-in steps | CSV load, join, rename, select, aggregate, etc. |
| Execute approved custom functions | Only explicitly whitelisted functions |
| Log each step | Start time, end time, status, output shape |
| Produce decision matrix candidate | Final dataframe for downstream TOPSIS/Fuzzy TOPSIS |
| Export metadata | Data provenance, config hash, row count, column list |

### Handoff Service

This services handles the packaging and handoff of polling session data such as weights, voting power, etc.

## Dashboard Flow Design

### Stakeholder Dashboard

#### Stakeholder Identification

##### **User View**

- Scenario Title
- Short Summary
- Minimal Instruction
- Access Form

##### **User Inputs**

| Field             |   Required? | Notes                                 |
| ----------------- | ----------: | ------------------------------------- |
| Stakeholder ID    |    Optional | Useful for invited participants       |
| Name or alias     |         Yes | Can be pseudonymous                   |
| Stakeholder type  |         Yes | Must match session-allowed type       |
| Access code       | Conditional | Required if session uses invitations  |
| Session selection | Conditional | Hidden if access code maps to session |

##### **Validation**

- Is the session open?
- Is the stakeholder type allowed?
- Is the access code valid and unused?
- Has this participant already submitted?

#### Full Scenario Review

##### **User View**

- Scenario description
- Policy question
- Alternatives
- Criteria
- Criteria descriptions
- Criterion type: benefit or cost
- Voting instructions
- Estimated completion time

#### Preference Submission

##### **Default Scale**

- Very Low
- Low
- Medium
- High
- Very High

##### **Validation**

- Every required criterion must have a rating.
- Rating must be in configured scale.
- Optional comment length limit.
- Submission blocked if session is locked.

#### Result State

After preference submission the user is left in one of the following states.

| State      | Stakeholder Message                                      |
| ---------- | -------------------------------------------------------- |
| Submitted  | “Your preferences were submitted successfully.”          |
| Waiting    | “The session is waiting for other required submissions.” |
| Locked     | “The moderator has locked this session.”                 |
| Processing | “Results are being prepared.”                            |
| Complete   | “Results are available.”                                 |
| Rejected   | “Your submission could not be used. Contact moderator.”  |

For a single stakeholder session, the user is immediately sent downstream after submission. For a multi-stakeholder session, the stakeholder should wait for moderator.

### Moderator Dashboard

#### Create Session

##### **Inputs**

- Session name
- Scenario
- Session mode: single-stakeholder or multi-stakeholder
- Weighting method: AHP or Fuzzy AHP
- Ranking method: TOPSIS or Fuzzy TOPSIS
- Allow resubmission: yes/no
- Require access codes: yes/no
- Require moderator lock before processing: yes/no

#### Configure Participants

Moderator defines the following:

| Setting                     | Description                               |
| --------------------------- | ----------------------------------------- |
| Eligible stakeholder groups | Example: parents, educators, planners     |
| Required groups             | Groups that must submit before processing |
| Minimum submissions         | Example: at least 1 educator and 1 parent |
| Access codes                | Generated per participant or group        |
| Voting power                | Default or override                       |

#### Track Status

##### **View**

| Participant | Type      | Status    | Voting Power | Submitted At |
| ----------- | --------- | --------- | -----------: | ------------ |
| Parent A    | parents   | Submitted |        0.125 | timestamp    |
| Educator B  | educators | Pending   |        0.250 | —            |
| Planner C   | planners  | Started   |        0.125 | —            |

##### **Summary Card**

- Total invited: 8
- Submitted: 5
- Required groups complete: No
- Voting power submitted: 62.5%
- Session status: Open

#### Lock Session

- Prevent new submissions
- Freeze voting power
- Freeze scenario config snapshot
- Freeze preprocessing config snapshot
- Create an audit record

#### Trigger Downstream Processes

## Voting Power Multi-Stakeholder Design

### Voting Power Model

#### Scenario Default

```json
{
  "stakeholder_groups": [
    {
      "id": "parents",
      "label": "Parents",
      "default_group_voting_power": 0.20
    },
    {
      "id": "educators",
      "label": "Educators",
      "default_group_voting_power": 0.25
    },
    {
      "id": "policy_makers",
      "label": "Policy Makers",
      "default_group_voting_power": 0.30
    }
  ]
}
```

#### Moderator Override

```json
{
  "participant_id": "part_001",
  "stakeholder_group_id": "educators",
  "default_voting_power": 0.25,
  "override_voting_power": 0.35,
  "effective_voting_power": 0.35,
  "override_reason": "Domain expert for school budgeting"
}
```

#### Aggregation Logic

1. Each stakeholder submits criterion ratings.
2. Ratings are transformed into a stakeholder-level preference vector
3. Each stakeholder vector is multiplied by normalized effective voting power.
4. Weighted stakeholder vectors are aggregated into a group-level weight vector.
5. The aggregate vector is passed to AHP/Fuzzy AHP-compatible weight derivation or directly to TOPSIS depending on experiment mode.

## Scenario Config File Responsibility

### `scenario.json`

#### Purpose

Main policy scenario descriptor. Defines identity, domain, alternatives, supported methods, stakeholder groups, and file references.

#### Should Include

- scenario_id
- schema_version
- scenario_version
- title
- domain
- summary
- description
- policy_question
- alternatives
- criteria reference
- stakeholder groups
- supported methods
- preference collection defaults
- file references
- export contract version

#### Example

```json
{
  "schema_version": "1.0",
  "scenario_id": "seattle_school_closure",
  "scenario_version": "2026.04",
  "status": "active",

  "title": "Seattle Public School Closure for Budget Recovery",
  "domain": "education",
  "tags": ["school_planning", "budget", "public_policy", "smart_city"],

  "summary": "This scenario evaluates which school would be least harmful to close under a hypothetical budget recovery plan.",
  "description_file": "README.md",

  "policy_question": "Which school closure option produces the least negative impact while helping address district budget constraints?",

  "alternatives": [
    {
      "id": "ballard_high",
      "name": "Ballard High School",
      "description": "A high school located in the Ballard neighborhood."
    },
    {
      "id": "center_school",
      "name": "Center School",
      "description": "A school located near downtown Seattle."
    },
    {
      "id": "cleveland_stem_high",
      "name": "Cleveland STEM High School",
      "description": "A high school with a STEM-focused academic program."
    }
  ],

  "criteria_file": "criteria.json",
  "data_sources_file": "data_sources.json",
  "preprocessing_file": "preprocessing.json",
  "session_rules_file": "session_rules.json",
  "ui_config_file": "ui_config.json",

  "stakeholder_groups": [
    {
      "id": "students",
      "label": "Students",
      "description": "Students directly or indirectly affected by school closure decisions.",
      "default_group_voting_power": 0.125
    },
    {
      "id": "parents",
      "label": "Parents",
      "description": "Parents or guardians of students affected by school planning decisions.",
      "default_group_voting_power": 0.125
    },
    {
      "id": "residents",
      "label": "Residents",
      "description": "Community residents affected by neighborhood school changes.",
      "default_group_voting_power": 0.125
    },
    {
      "id": "planners",
      "label": "Urban and Education Planners",
      "description": "Planning professionals evaluating long-term service impacts.",
      "default_group_voting_power": 0.125
    },
    {
      "id": "policy_makers",
      "label": "Policy Makers",
      "description": "Decision-makers responsible for public budget and school system policy.",
      "default_group_voting_power": 0.25
    },
    {
      "id": "educators",
      "label": "Educators",
      "description": "Teachers, administrators, or education professionals.",
      "default_group_voting_power": 0.25
    }
  ],

  "preference_collection": {
    "default_method": "criterion_linguistic_rating",
    "supported_methods": [
      "criterion_linguistic_rating",
      "pairwise_comparison"
    ],
    "default_scale_id": "five_level_importance"
  },

  "scales": {
    "five_level_importance": {
      "type": "linguistic",
      "ordered": true,
      "values": [
        {
          "label": "Very Low",
          "numeric_value": 1,
          "fuzzy_value": [0.0, 0.1, 0.25]
        },
        {
          "label": "Low",
          "numeric_value": 2,
          "fuzzy_value": [0.15, 0.3, 0.45]
        },
        {
          "label": "Medium",
          "numeric_value": 3,
          "fuzzy_value": [0.35, 0.5, 0.65]
        },
        {
          "label": "High",
          "numeric_value": 4,
          "fuzzy_value": [0.55, 0.7, 0.85]
        },
        {
          "label": "Very High",
          "numeric_value": 5,
          "fuzzy_value": [0.75, 0.9, 1.0]
        }
      ]
    }
  },

  "mcdm_methods": {
    "weighting_supported": ["AHP", "FUZZY_AHP"],
    "ranking_supported": ["TOPSIS", "FUZZY_TOPSIS"],
    "default_weighting": "AHP",
    "default_ranking": "TOPSIS"
  },

  "handoff": {
    "contract_version": "1.0",
    "expected_exports": [
      "stakeholder_submission_export",
      "session_approved_export",
      "preprocessing_metadata_export"
    ]
  }
}
```

### `criteria.json`

#### Purpose

Detailed criteria definitions. Useful when criteria list becomes large or reused.

#### Should Include

- criteria id
- name
- description
- criteria_type: benefit/cost
- data type
- unit
- required
- source column
- display order

#### Example

```json
{
  "schema_version": "1.0",
  "criteria": [
    {
      "id": "total_population",
      "name": "Total Student Population",
      "description": "Total number of students currently enrolled in the school.",
      "criteria_type": "cost",
      "data_type": "numeric",
      "unit": "students",
      "required": true,
      "source_column": "total_population",
      "display_order": 1
    },
    {
      "id": "total_budget",
      "name": "Total Budget Allocation",
      "description": "Total budget allocated to the school for the current fiscal year.",
      "criteria_type": "benefit",
      "data_type": "numeric",
      "unit": "usd",
      "required": true,
      "source_column": "total_budget",
      "display_order": 2
    },
    {
      "id": "budget_per_student",
      "name": "Budget Per Student",
      "description": "Budget allocation divided by total enrollment.",
      "criteria_type": "benefit",
      "data_type": "numeric",
      "unit": "usd_per_student",
      "required": true,
      "source_column": "budget_per_student",
      "display_order": 3
    },
    {
      "id": "grade_9_share",
      "name": "Grade 9 Student Share",
      "description": "Share of grade 9 students relative to total enrollment.",
      "criteria_type": "cost",
      "data_type": "numeric",
      "unit": "ratio",
      "required": true,
      "source_column": "grade_9_share",
      "display_order": 4
    },
    {
      "id": "retention_rate",
      "name": "Student Retention Rate",
      "description": "Ratio of grade 12 enrollment to grade 9 enrollment.",
      "criteria_type": "cost",
      "data_type": "numeric",
      "unit": "ratio",
      "required": true,
      "source_column": "retention_rate",
      "display_order": 5
    },
    {
      "id": "grade_imbalance",
      "name": "Grade Imbalance",
      "description": "Degree of imbalance in the distribution of students across grade levels.",
      "criteria_type": "benefit",
      "data_type": "numeric",
      "unit": "index",
      "required": true,
      "source_column": "grade_imbalance",
      "display_order": 6
    }
  ]
}
```

### `data_sources.json`

#### Purpose

Defines where raw data originated from.

### Should Support

- csv
- excel
- sql
- mongodb
- api
- manual/simulated

**NOTE:** Do not store raw passwords or API keys. Use environment variable references.

#### Example

```json
{
  "schema_version": "1.0",
  "data_sources": [
    {
      "id": "population_csv",
      "type": "csv",
      "path": "data/school_population.csv",
      "description": "School enrollment by grade level.",
      "required": true
    },
    {
      "id": "budget_csv",
      "type": "csv",
      "path": "data/school_budget.csv",
      "description": "School-level budget allocation.",
      "required": true
    }
  ]
}
```

#### Other Examples

API

```json
{
  "id": "traffic_sensor_api",
  "type": "api",
  "method": "GET",
  "url_env": "TRAFFIC_API_URL",
  "api_key_env": "TRAFFIC_API_KEY",
  "response_format": "json",
  "required": true
}
```

Mongodb

```json
{
  "id": "district_energy_mongodb",
  "type": "mongodb",
  "uri_env": "MONGODB_URI",
  "database": "smart_city",
  "collection": "district_energy_metrics",
  "query_template": {
    "scenario_id": "smart_energy_priority"
  },
  "required": true
}
```

SQL

```json
{
    "id": "water_quality_sql",
    "type": "sql",
    "database": "water_quality",
    "query": "SELECT * FROM water_quality"
    "required": true
}
```

### `preprocessing.json`

#### Purpose

Defines the pipeline that turns raw data into a final decision matrix.

#### Should Include

- pipeline id
- input datasets
- ordered steps
- approved custom function references
- final output table
- expected columns
- validation checks

#### Example 

```json
{
  "schema_version": "1.0",
  "pipeline_id": "school_closure_baseline_pipeline",
  "description": "Loads school population and budget data, joins records, creates derived criteria, and outputs the decision matrix.",

  "inputs": [
    {
      "ref": "population_csv",
      "output_table": "population"
    },
    {
      "ref": "budget_csv",
      "output_table": "budget"
    }
  ],

  "steps": [
    {
      "id": "load_population",
      "type": "load_csv",
      "source_ref": "population_csv",
      "output": "population_raw",
      "options": {
        "encoding": "utf-8"
      }
    },
    {
      "id": "load_budget",
      "type": "load_csv",
      "source_ref": "budget_csv",
      "output": "budget_raw",
      "options": {
        "encoding": "utf-8"
      }
    },
    {
      "id": "standardize_population_columns",
      "type": "rename_columns",
      "input": "population_raw",
      "output": "population",
      "columns": {
        "High Schools": "school_name",
        "Grade 9": "grade_9",
        "Grade 10": "grade_10",
        "Grade 11": "grade_11",
        "Grade 12": "grade_12",
        "Total Population": "total_population"
      }
    },
    {
      "id": "standardize_budget_columns",
      "type": "rename_columns",
      "input": "budget_raw",
      "output": "budget",
      "columns": {
        "High Schools": "school_name",
        "Total Budget": "total_budget"
      }
    },
    {
      "id": "join_population_budget",
      "type": "join",
      "left": "population",
      "right": "budget",
      "output": "school_joined",
      "how": "inner",
      "on": ["school_name"]
    },
    {
      "id": "convert_numeric_columns",
      "type": "convert_types",
      "input": "school_joined",
      "output": "school_typed",
      "columns": {
        "grade_9": "float",
        "grade_10": "float",
        "grade_11": "float",
        "grade_12": "float",
        "total_population": "float",
        "total_budget": "float"
      }
    },
    {
      "id": "handle_missing_values",
      "type": "missing_values",
      "input": "school_typed",
      "output": "school_clean",
      "strategy": {
        "default": "error",
        "columns": {
          "total_budget": "median",
          "total_population": "error"
        }
      }
    },
    {
      "id": "derive_budget_per_student",
      "type": "derive_column",
      "input": "school_clean",
      "output": "school_with_budget_per_student",
      "new_column": "budget_per_student",
      "operation": "divide",
      "operands": ["total_budget", "total_population"],
      "on_zero": "null"
    },
    {
      "id": "derive_grade_9_share",
      "type": "derive_column",
      "input": "school_with_budget_per_student",
      "output": "school_with_grade_9_share",
      "new_column": "grade_9_share",
      "operation": "divide",
      "operands": ["grade_9", "total_population"],
      "on_zero": "null"
    },
    {
      "id": "custom_school_metrics",
      "type": "approved_function",
      "input": "school_with_grade_9_share",
      "output": "school_with_metrics",
      "function_ref": "compute_school_closure_metrics"
    },
    {
      "id": "select_decision_matrix_columns",
      "type": "select_columns",
      "input": "school_with_metrics",
      "output": "decision_matrix",
      "columns": [
        "school_name",
        "total_population",
        "total_budget",
        "budget_per_student",
        "grade_9_share",
        "retention_rate",
        "grade_imbalance"
      ]
    }
  ],

  "approved_functions": [
    {
      "id": "compute_school_closure_metrics",
      "file": "functions.py",
      "callable": "compute_school_closure_metrics",
      "input_type": "dataframe",
      "output_type": "dataframe",
      "allowed_imports": ["pandas", "numpy", "math"],
      "sha256": "optional_hash_for_reproducibility"
    }
  ],

  "final_output": {
    "table": "decision_matrix",
    "alternative_id_column": "school_name",
    "criteria_columns": [
      "total_population",
      "total_budget",
      "budget_per_student",
      "grade_9_share",
      "retention_rate",
      "grade_imbalance"
    ]
  },

  "validation": {
    "required_columns": [
      "school_name",
      "total_population",
      "total_budget",
      "budget_per_student",
      "grade_9_share",
      "retention_rate",
      "grade_imbalance"
    ],
    "no_nulls_in": [
      "school_name",
      "total_population",
      "total_budget"
    ],
    "minimum_rows": 2
  }
}
```

### `session_rules.json`

#### Purpose

Default rules for polling sessions created from this scenario.

#### Should Include

- single vs multi stakeholder defaults
- access code requirement
- minimum required submissions
- required stakeholder groups
- resubmission policy
- auto-lock policy
- processing trigger policy

### `ui_config.json`

#### Purpose

Controls labels, help text, layout, and stakeholder-facing UI behavior.

#### Should Include

- intro text
- criterion card display
- rating scale labels
- step order
- whether to show alternatives before criteria
- whether to show benefit/cost direction

## Safe Preprocessing Execution

### Operation Registry

Create a registry of supported operations:

```python
STEP_REGISTRY = {
    "load_csv": LoadCsvStep,
    "load_excel": LoadExcelStep,
    "load_sql": LoadSqlStep,
    "load_mongodb": LoadMongoStep,
    "load_api": LoadApiStep,
    "join": JoinStep,
    "rename_columns": RenameColumnsStep,
    "select_columns": SelectColumnsStep,
    "filter_rows": FilterRowsStep,
    "missing_values": MissingValuesStep,
    "convert_types": ConvertTypesStep,
    "derive_column": DeriveColumnStep,
    "aggregate": AggregateStep,
    "normalize": NormalizeStep,
    "approved_function": ApprovedFunctionStep
}
```

### Approved Function Rules

For `functions.py` files:

- Must live inside the scenario folder.
- Must be explicitly listed in preprocessing.json.
- Function name must match the allowlist.
- Optional but recommended: verify file hash.
- Do not allow arbitrary module paths.
- Do not allow raw code strings in JSON.
- Execute with timeout and structured logging.
- Function receives a dataframe and returns a dataframe.

## Database Schema

### Scenario

```sql
CREATE TABLE scenarios (
    scenario_id TEXT NOT NULL,
    scenario_version TEXT NOT NULL,
    title TEXT NOT NULL,
    domain TEXT NOT NULL,
    folder_path TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    config_snapshot_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (scenario_id, scenario_version)
);
```

### Polling Session

```sql
CREATE TABLE polling_sessions (
    session_id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL,
    scenario_version TEXT NOT NULL,
    session_name TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    selected_weighting_method TEXT NOT NULL,
    selected_ranking_method TEXT NOT NULL,
    require_access_code INTEGER NOT NULL DEFAULT 1,
    allow_resubmission INTEGER NOT NULL DEFAULT 0,
    require_moderator_lock INTEGER NOT NULL DEFAULT 1,
    created_by TEXT,
    created_at TEXT NOT NULL,
    opened_at TEXT,
    locked_at TEXT,
    completed_at TEXT,
    updated_at TEXT NOT NULL
);
```

Statuses:

- draft
- open
- locked
- preprocessing
- processing_ready
- processing
- completed
- archived
- cancelled

### Stakeholders

```sql
CREATE TABLE stakeholders (
    stakeholder_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    alias TEXT,
    external_ref TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

### Session Participants

```sql
CREATE TABLE session_participants (
    participant_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    stakeholder_id TEXT,
    stakeholder_group_id TEXT NOT NULL,
    access_code_hash TEXT,
    access_code_expires_at TEXT,
    status TEXT NOT NULL DEFAULT 'invited',
    default_voting_power REAL NOT NULL,
    override_voting_power REAL,
    effective_voting_power REAL NOT NULL,
    normalized_voting_power REAL,
    invited_at TEXT,
    started_at TEXT,
    submitted_at TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES polling_sessions(session_id),
    FOREIGN KEY (stakeholder_id) REFERENCES stakeholders(stakeholder_id)
);
```

Participant Status

- invited
- started
- submitted
- excluded
- expired

### Voting Power

```sql
CREATE TABLE voting_power_assignments (
    assignment_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    participant_id TEXT,
    stakeholder_group_id TEXT,
    assignment_scope TEXT NOT NULL,
    source TEXT NOT NULL,
    voting_power REAL NOT NULL,
    reason TEXT,
    assigned_by TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES polling_sessions(session_id),
    FOREIGN KEY (participant_id) REFERENCES session_participants(participant_id)
);
```

