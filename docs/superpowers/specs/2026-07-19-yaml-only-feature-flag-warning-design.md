# YAML-only feature flag warning design

## Context

NEOS runtime behavior is configured through validated YAML. Secrets and bootstrap
controls remain environment variables, while a limited set of legacy non-secret
environment overrides is temporarily supported with a warning.

Seven feature flags do not belong to that legacy compatibility set:

| Ignored environment variable | Authoritative YAML path |
| --- | --- |
| `DEEP_ANALYSIS_ENABLED` | `deep_analysis.enabled` |
| `RECURSIVE_AGENT_ENABLED` | `recursive_agent.enabled` |
| `HYPER_DEEP_AGENT_ENABLED` | `hyper_deep_agent.enabled` |
| `A2UI_ENABLED` | `a2ui.enabled` |
| `RAY_ENABLED` | `ray.enabled` |
| `EXECUTION_APPROVAL_ENABLED` | `execution_approval.enabled` |
| `CELERY_ENABLED` | `celery.enabled` |

When one of these names is present in the repository `.env` file or process
environment, the current loader silently ignores it. This can make an operator
believe a feature is enabled while the application continues to use its YAML
value.

## Decision

The loader will emit a `UserWarning` in every application environment when it
finds one of the seven known YAML-only feature flag environment variables.

Each warning will:

- name the ignored environment variable;
- state that it is ignored;
- identify the authoritative dotted YAML path; and
- leave the merged YAML value unchanged.

Example:

```text
DEEP_ANALYSIS_ENABLED is ignored; configure deep_analysis.enabled in YAML.
```

Warnings are advisory. They will not prevent startup in development, test,
staging, or production.

## Loader structure

`neos/config/loader.py` will define an explicit mapping from the seven variable
names to their YAML paths. A focused warning function will inspect the merged
bootstrap `.env` and process environment once during `load_app_config()`.

The mapping will not be added to `LEGACY_ENV_KEYS`. That collection applies an
override, while these variables must remain non-authoritative.

`validate_env_allowlist()` will keep its existing responsibility of identifying
unknown `NEOS_*` variables. Generalizing the new behavior to every
`*_ENABLED` name is deliberately avoided because deployment platforms and
third-party services can supply unrelated variables with that suffix.

## Precedence and duplicate handling

The warning scan operates on `{**bootstrap_env, **process_env}`. Therefore:

- a name present in either source is detected;
- a name present in both sources produces one warning; and
- process values still win in the temporary merged mapping, although the value
  is never applied to application configuration.

Secrets loading and legacy override precedence are unchanged.

## Tests

Loader tests will establish these contracts:

1. Each known YAML-only feature flag produces a warning naming both the
   environment variable and its YAML path.
2. A warned environment variable does not override an explicit YAML value.
3. An unrelated `*_ENABLED` variable does not produce this warning.
4. A flag present in both the bootstrap `.env` and process environment produces
   one warning.
5. Existing secret, bootstrap, legacy override, and unknown `NEOS_*` behavior
   remains unchanged.

## Documentation reconciliation

`docs/TODO_260729.md` will be reconciled with the already merged loop work before
recording this implementation:

- mark the bounded terminal failure work in section 1 complete;
- mark backend CI and pytest collection isolation in section 3 complete;
- update the priority summary so completed work is not presented as upcoming;
- after verification, mark section 2 complete and record the warning-only policy.

The existing `.env.template` already directs non-secret runtime settings to
YAML and currently contains unrelated user changes, so it is outside this
change's edit scope.

## Non-goals

- Restoring the seven environment variables as supported overrides.
- Failing startup because a YAML-only flag is present.
- Warning for every environment variable ending in `*_ENABLED`.
- Redesigning the complete configuration inventory or legacy migration policy.
