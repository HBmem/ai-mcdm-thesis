# Streamlit Foundation

## Runtime configuration

The application selects one authentication adapter at startup. It defaults to
the Streamlit OIDC adapter and fails closed for every admin route. Configure the
provider in `.streamlit/secrets.toml` using
`.streamlit/secrets.toml.example` as a guide.

The verified user must contain a stable `sub` claim and the configured admin
role in a role claim. Runtime settings are:

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `POLI_INSIGHT_AUTH_BACKEND` | `streamlit_oidc` | Select authentication adapter |
| `POLI_INSIGHT_ENVIRONMENT` | `production` | Gates development authentication |
| `POLI_INSIGHT_ADMIN_ROLE` | `admin` | Role required for every admin page |
| `POLI_INSIGHT_AUTH_ROLE_CLAIMS` | `roles,groups` | Role claim names |

`POLI_INSIGHT_AUTH_MODE` remains a temporary compatibility alias when
`POLI_INSIGHT_AUTH_BACKEND` is absent. New configuration should use
`POLI_INSIGHT_AUTH_BACKEND`.

Development password authentication is available only when both development
environment variables are set and `DEV_ADMIN_PASSWORD` exists in the untracked
Streamlit secrets file. It must not be used for a deployment.

Navigation visibility is only a convenience. Every bound admin renderer calls
the authorization policy again before executing.

## Adapter boundary

Navigation and pages depend on the `AuthenticationAdapter` protocol. The
development and Streamlit OIDC implementations return the same minimized
`Principal` and are selected only by `create_authentication_adapter()`.

- `DevelopmentAuthAdapter` uses namespaced Streamlit session state and the
  local development password.
- `StreamlitOidcAuthAdapter` delegates to `st.user`, `st.login()`, and
  `st.logout()` and requires a stable OIDC `sub` claim.
- `AuthorizationPolicy` remains independent of both adapters.
- Invalid production configuration never falls back to development auth.

The login page renders a password form or OIDC redirect button from the
adapter's `login_method`; it never checks a concrete adapter class.

## Page architecture

- `ApplicationContainer` supplies command use cases and the read-only
  `PageQueries` interface.
- Page renderers receive a `PageContext`; they do not create database sessions
  or import ORM rows.
- `SqlAlchemyPageQueries` uses short-lived read sessions and maps rows into
  immutable page DTOs.
- Shared layout and status components keep workflow states visually consistent.
- The final page error boundary logs an opaque reference and renders no stack
  trace or database error to the browser.

The first adapter supports the public open-session catalog and operational
admin session counts. Processing, report, and publication pages intentionally
show capability notices until their independent backend models exist.

## Routes

Streamlit does not allow subdirectories in `st.Page.url_path`, so the admin
routes are flat but namespaced:

- `/` — Home
- `/participate`
- `/results`
- `/about`
- `/admin-login`
- `/admin`
- `/admin-sessions`
- `/admin-processing`
- `/admin-reports`

Only routes available to the current principal are registered for a run.
