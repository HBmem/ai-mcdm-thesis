# Application Redesign

## Sidebar Navigation

### Public

The public section wil contain pages dedicated to providing information about the system and guiding users to where they can participate in active policy scenario sessions.

**Pages**:

- **Home**: Introduces the user to the application and guides them to where they can participate in an ongoing policy scenario session or view results of a session they participated in.
- **Active Sessions**: The user can view the active sessions and choose to participate in them if they wish to do so.
- **Closed Sessions**: The user can see the results of previous sessions and if possible view the input their session identifier to see their personal results along with the session results
  - **View Session Results**: View closed sessions results
  - **View Participant Results**: view personal session results and summary
- **About**: Speak about the thesis research and project.

### Admin

The admin section will contain pages dedicated to managing sessions, processing session results, etc

**Pages**:

- **Manage Sessions**: The admin manages sessions
  - **Create Session**: Create a new session
  - **View Sessions**: View session participants, create new participants, regenerate participant access code, import submissions, etc.
- **Session Processing**: The admin is able to process the sessions, view metrics and prepare the session for AI analysis.
  - **Process Session**: Process the sessions, view failed and passed processed sessions. This could also be used to handle the pipleine where the user process the session and then send sessions for AI analysis.
  - **View Processed Sessions**: View the details of the processed session, aggregate, group and individual stakeholder metrics, sensitivity tests, 
  - **Manage AI Analysis**: Used the manage ai analysis of processed sessions.
  
## Session Attributes

- **Scenario**: The selected policy scenario that will be evaluated
- **Scenario Type**: Whether the scenario will be evaluated as a standard or hierarchical MCDM problem.
- **Session Title**: The name of the evaluation session.
- **Session Description**: A brief description of the evaluation session.
- **Session Mode**: Whether the session will be a single or multiple participant session.
- **Session Weighting Method**: The method used to weight the criteria in the evaluation session. eg. AHP, Fuzzy AHP
- **Session Ranking Method**: The method used to rank the alternatives in the evaluation session. eg. TOPSIS, Fuzzy TOPSIS
- **Session Duration**: The duration of the evaluation session.

**Session Options**:

- **Aggregation Method**: Whether the session will be aggregated using stakeholder grouped responses or individual responses.
  - Stakeholder Grouped
  - Individual
- **Allow Resubmission**: Whether participants are allowed to resubmit their responses.
  - Yes
  - No
- **Require Access Code**: Whether participants are required to enter an access code to join the session.
  - Yes
  - No
- **Enable Notifications**: **(Stretch Goal)** Whether participants will receive notifications about the session.
  - Yes
  - No
