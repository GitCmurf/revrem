import re

with open("src/code_review_loop/triage.py", "r") as f:
    content = f.read()

validator = """
def validate_routing_payload(payload: dict[str, Any]) -> None:
    schema = json.loads(files("code_review_loop").joinpath("schemas/routing-v1.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    errors = list(validator.iter_errors(payload))
    if errors:
        raise TriageValidationError(str(errors[0]))
"""

if "def validate_routing_payload" not in content:
    content += validator

with open("src/code_review_loop/triage.py", "w") as f:
    f.write(content)
