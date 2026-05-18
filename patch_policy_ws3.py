import re

with open("src/code_review_loop/policy.py", "r") as f:
    content = f.read()

# 1. Update resolve_routing logic
content = re.sub(
    r"if matched_rule:.*?allow_model_deescalation = True",
    """if matched_rule:
        route_tier = matched_rule.then.route or routing.default_route
        rule_id = matched_rule.id
        prompt_fragments = matched_rule.then.prompt_fragments
        allow_model_deescalation = matched_rule.then.allow_model_deescalation
        allow_model_escalation = (
            matched_rule.then.allow_model_escalation
            if matched_rule.then.allow_model_escalation is not None
            else routing.allow_model_escalation
        )
    else:
        route_tier = routing.default_route
        rule_id = "default"
        prompt_fragments = ()
        allow_model_deescalation = True
        allow_model_escalation = routing.allow_model_escalation""",
    content,
    flags=re.DOTALL
)

content = re.sub(
    r"if model_proposal_tier and model_proposal_tier != route_tier:.*?effective_tier = model_proposal_tier",
    """if model_proposal_tier and model_proposal_tier != route_tier:
        if _is_higher_tier(model_proposal_tier, route_tier):
            if allow_model_escalation:
                effective_tier = model_proposal_tier
            else:
                effective_tier = route_tier
        elif not allow_model_deescalation:
            effective_tier = route_tier
        else:
            effective_tier = model_proposal_tier""",
    content,
    flags=re.DOTALL
)

# 2. Update _matches logic
content = content.replace(
    "    if w.module_count_lt is not None and context.module_count >= w.module_count_lt:\n        return False\n    return True",
    "    if w.module_count_lt is not None and context.module_count >= w.module_count_lt:\n        return False\n    if w.safety_signals_any and not any(s in context.safety_signals for s in w.safety_signals_any):\n        return False\n    if w.failed_checks_any and not any(c in context.failed_checks for c in w.failed_checks_any):\n        return False\n    return True"
)

with open("src/code_review_loop/policy.py", "w") as f:
    f.write(content)
