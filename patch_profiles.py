import re

with open("src/code_review_loop/profiles.py", "r") as f:
    content = f.read()

# Add _optional_bool helper if not present
if "def _optional_bool" not in content:
    content = content.replace("def _bool", "def _optional_bool(value: Any, field: str) -> bool | None:\n    if value is None:\n        return None\n    return _bool(value, field)\n\n\ndef _bool")

# Update keys
content = content.replace(
    "ROUTING_KEYS = (\"enabled\", \"mode\", \"default_route\", \"strict_on_unavailable_route\", \"rule\")",
    "ROUTING_KEYS = (\"enabled\", \"mode\", \"default_route\", \"strict_on_unavailable_route\", \"rule\", \"allow_model_escalation\")"
)
content = content.replace(
    "ROUTING_WHEN_KEYS = (\n    \"domain_tags_any\",\n    \"risk_level_any\",\n    \"risk_level_max\",\n    \"refactor_depth_any\",\n    \"module_count_gte\",\n    \"module_count_lt\",\n)",
    "ROUTING_WHEN_KEYS = (\n    \"domain_tags_any\",\n    \"risk_level_any\",\n    \"risk_level_max\",\n    \"refactor_depth_any\",\n    \"module_count_gte\",\n    \"module_count_lt\",\n    \"safety_signals_any\",\n    \"failed_checks_any\",\n)"
)
content = content.replace(
    "ROUTING_THEN_KEYS = (\"route\", \"prompt_fragments\", \"allow_model_deescalation\")",
    "ROUTING_THEN_KEYS = (\"route\", \"prompt_fragments\", \"allow_model_deescalation\", \"allow_model_escalation\")"
)

# Update dataclasses
content = content.replace(
    "    module_count_lt: int | None = None",
    "    module_count_lt: int | None = None\n    safety_signals_any: tuple[str, ...] = field(default_factory=tuple)\n    failed_checks_any: tuple[str, ...] = field(default_factory=tuple)"
)
content = content.replace(
    "    allow_model_deescalation: bool = True",
    "    allow_model_deescalation: bool = True\n    allow_model_escalation: bool | None = None"
)
content = content.replace(
    "    rule: tuple[TriageRoutingRule, ...] = field(default_factory=tuple)",
    "    rule: tuple[TriageRoutingRule, ...] = field(default_factory=tuple)\n    allow_model_escalation: bool = False"
)

# Update parsers
content = content.replace(
    "        module_count_lt=_optional_int(raw.get(\"module_count_lt\"), f\"{field}.module_count_lt\"),\n    )",
    "        module_count_lt=_optional_int(raw.get(\"module_count_lt\"), f\"{field}.module_count_lt\"),\n        safety_signals_any=tuple(_str_list(raw.get(\"safety_signals_any\", []), f\"{field}.safety_signals_any\")),\n        failed_checks_any=tuple(_str_list(raw.get(\"failed_checks_any\", []), f\"{field}.failed_checks_any\")),\n    )"
)
content = content.replace(
    "        allow_model_deescalation=_bool(\n            raw.get(\"allow_model_deescalation\", True), f\"{field}.allow_model_deescalation\"\n        ),\n    )",
    "        allow_model_deescalation=_bool(\n            raw.get(\"allow_model_deescalation\", True), f\"{field}.allow_model_deescalation\"\n        ),\n        allow_model_escalation=_optional_bool(\n            raw.get(\"allow_model_escalation\"), f\"{field}.allow_model_escalation\"\n        ),\n    )"
)
content = content.replace(
    "        rule=rules,\n    )",
    "        rule=rules,\n        allow_model_escalation=_bool(raw.get(\"allow_model_escalation\", False), f\"{field}.allow_model_escalation\"),\n    )"
)

# Add validate_policy
validator = """
def validate_policy(profile: Profile) -> list[str]:
    issues = []
    triage = profile.triage
    if not triage.routing.enabled:
        return []

    # Check routes
    for name, route in triage.routes.items():
        try:
            validate_harness_name(route.harness)
            spec = HARNESS_REGISTRY.get(route.harness)
            if spec and not spec.implemented:
                 issues.append(f"route {name!r} uses unimplemented harness {route.harness!r}")
        except ValueError as exc:
            issues.append(f"route {name!r} has invalid harness: {exc}")

        if route.fallback and route.fallback not in triage.routes:
            issues.append(f"route {name!r} has unknown fallback: {route.fallback!r}")

    # Check rules
    for i, rule in enumerate(triage.routing.rule):
        if rule.then.route and rule.then.route not in triage.routes:
            issues.append(f"rule {rule.id or i!r} refers to unknown route {rule.then.route!r}")

    if triage.routing.default_route not in triage.routes:
        issues.append(f"default_route {triage.routing.default_route!r} is unknown")

    return issues
"""
if "def validate_policy" not in content:
    content = content.replace("def validate_profile", validator + "\n\ndef validate_profile")

with open("src/code_review_loop/profiles.py", "w") as f:
    f.write(content)
