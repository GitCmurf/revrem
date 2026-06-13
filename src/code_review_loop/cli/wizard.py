"""Dependency-free command-building wizard for the RevRem CLI."""

from __future__ import annotations

import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from code_review_loop import profiles
from code_review_loop.cli import args as cli_args
from code_review_loop.cli.config_builder import build_loop_config


@dataclass(frozen=True)
class WizardResult:
    argv: tuple[str, ...]
    shell_command: str
    action: str


@dataclass(frozen=True)
class WizardProfileChoice:
    profile_name: str | None
    profile: profiles.Profile


class WizardCancelled(Exception):
    """Raised when the operator cancels before a command is selected."""


def run_wizard(
    *,
    cwd: Path,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> WizardResult | None:
    """Prompt an operator for common RevRem choices and return generated argv.

    The returned ``argv`` deliberately omits the executable name. ``shell_command``
    includes it for display/copying.
    """

    wizard = _Wizard(
        cwd=cwd,
        stdin=stdin or sys.stdin,
        stdout=stdout or sys.stdout,
        stderr=stderr or sys.stderr,
    )
    try:
        return wizard.run()
    except WizardCancelled:
        print("Cancelled before provider calls.", file=wizard.stderr)
        return None


class _Wizard:
    def __init__(self, *, cwd: Path, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> None:
        self.cwd = cwd
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr

    def run(self) -> WizardResult:
        print("RevRem command wizard", file=self.stderr)
        choice = self._choose_profile()
        argv: list[str] = []
        if choice.profile_name:
            argv.extend(["--profile", choice.profile_name])

        self._common_options(argv, choice.profile)
        if self._yes_no("Configure advanced options?", default=False):
            self._advanced_options(argv, choice.profile)

        while True:
            action = self._choice(
                "What should the wizard do?",
                (
                    ("dry-run", "validate and print the loop shape"),
                    ("run", "start the real run"),
                    ("save-profile", "save these choices as a project profile"),
                    ("print", "print the command only"),
                    ("cancel", "exit without doing anything"),
                ),
                default="dry-run",
            )
            if action == "cancel":
                raise WizardCancelled
            final_argv = list(argv)
            if action == "dry-run":
                final_argv.append("--dry-run")
            elif action == "save-profile":
                name = self._text("Project profile name", default=choice.profile_name or "final-pr")
                final_argv.extend(["--dry-run", "--save-profile", name])
            result = self._validate(final_argv, action=action)
            print(f"\nCommand: {result.shell_command}", file=self.stdout)
            if self._yes_no("Use this command?", default=True):
                return result

    def _choose_profile(self) -> WizardProfileChoice:
        resolved_profiles = tuple(
            profiles.resolve_profiles(cwd=self.cwd, require_implemented=False)
        )
        defaults = profiles.resolve_defaults(cwd=self.cwd, require_implemented=False)
        options: list[tuple[str, str]] = [("defaults", "resolved repo/user defaults")]
        options.extend(
            (profile.name, _profile_label(profile))
            for profile in resolved_profiles
            if profile.name
        )
        default = resolved_profiles[0].name if resolved_profiles else "defaults"
        selected = self._choice("Start from which configuration?", tuple(options), default=default)
        if selected == "defaults":
            return WizardProfileChoice(profile_name=None, profile=defaults)
        for profile in resolved_profiles:
            if profile.name == selected:
                return WizardProfileChoice(profile_name=selected, profile=profile)
        raise WizardCancelled

    def _common_options(self, argv: list[str], profile: profiles.Profile) -> None:
        base = self._text("Base branch", default=profile.pipeline.base)
        if base != profile.pipeline.base:
            argv.extend(["--base", base])

        max_iterations = self._text(
            "Max remediation iterations",
            default=str(profile.pipeline.max_iterations),
            validator=_positive_int,
        )
        if int(max_iterations) != profile.pipeline.max_iterations:
            argv.extend(["--max-iterations", max_iterations])

        checks = self._checks(profile.pipeline.checks)
        if checks != profile.pipeline.checks:
            if checks:
                for command in checks:
                    argv.extend(["--check", command])
            else:
                # Empty replacement is represented by a shell no-op so the
                # existing repeatable --check parser can express "no checks"
                # without adding a new top-level flag.
                argv.extend(["--check", "true"])

        final_review = self._yes_no("Run final review after remediation?", profile.pipeline.final_review)
        if final_review != profile.pipeline.final_review:
            argv.append("--final-review" if final_review else "--skip-final-review")

    def _advanced_options(self, argv: list[str], profile: profiles.Profile) -> None:
        triage = self._yes_no("Enable structured triage?", profile.triage.enabled)
        if triage != profile.triage.enabled:
            argv.append("--triage" if triage else "--no-triage")
        if triage:
            routing = self._yes_no("Enable v2 routing?", profile.triage.routing.enabled)
            if routing:
                if profile.triage.contract != "v2":
                    argv.extend(["--triage-contract", "v2"])
                if not profile.triage.routing.enabled:
                    argv.append("--routing")
                route_names = tuple(sorted(profile.triage.routes))
                if route_names:
                    route = self._choice(
                        "Routing default route",
                        tuple((name, _route_label(profile.triage.routes[name])) for name in route_names),
                        default=profile.triage.routing.default_route
                        if profile.triage.routing.default_route in route_names
                        else route_names[0],
                    )
                    if route != profile.triage.routing.default_route:
                        argv.extend(["--route", route])
            elif profile.triage.routing.enabled:
                argv.append("--no-routing")

        shared_model = self._text("Shared review/remediation model override", default="")
        if shared_model:
            argv.extend(["--model", shared_model])
        effort = self._choice(
            "Shared reasoning effort",
            (("profile", "keep profile/default"),)
            + tuple((value, value) for value in cli_args.REASONING_EFFORT_CHOICES),
            default="profile",
        )
        if effort != "profile":
            argv.extend(["--reasoning-effort", effort])

        timeout = self._text(
            "Phase timeout seconds (0 disables, blank keeps profile/default)",
            default="",
            validator=_non_negative_float_or_blank,
        )
        if timeout:
            argv.extend(["--timeout-seconds", timeout])

        commit = self._yes_no("Commit after verified remediation?", profile.commit.enabled)
        if commit != profile.commit.enabled:
            argv.append("--commit-after-remediation" if commit else "--no-commit-after-remediation")

        progress = self._choice(
            "Progress style",
            tuple((value, value) for value in cli_args.PROGRESS_STYLE_CHOICES),
            default=profile.output.progress_style,
        )
        if progress != profile.output.progress_style:
            argv.extend(["--progress-style", progress])

        summary = self._choice(
            "Terminal summary format",
            (("text", "text"), ("json", "json"), ("both", "text and json")),
            default=profile.output.summary_format,
        )
        if summary != profile.output.summary_format:
            argv.extend(["--summary-format", summary])

        wall = self._text(
            "Max wall seconds budget (blank for none/profile)",
            default="",
            validator=_non_negative_float_or_blank,
        )
        if wall:
            argv.extend(["--max-wall-seconds", wall])

        pending = self._choice(
            "Pending review handling",
            (
                ("profile", "interactive default"),
                ("prompt", "prompt when compatible feedback exists"),
                ("auto", "reuse compatible feedback automatically"),
                ("ignore", "always start fresh"),
            ),
            default="profile",
        )
        if pending != "profile":
            argv.extend(["--pending-review", pending])

    def _checks(self, current: tuple[str, ...]) -> tuple[str, ...]:
        default = "keep" if current else "add"
        mode = self._choice(
            "Verification checks",
            (
                ("keep", f"keep current ({len(current)})"),
                ("add", "append checks"),
                ("replace", "replace checks"),
                ("none", "use a shell no-op check"),
            ),
            default=default,
        )
        if mode == "keep":
            return current
        if mode == "none":
            return ()
        checks = list(current) if mode == "add" else []
        print("Enter one check command per line. Leave blank when done.", file=self.stderr)
        while True:
            command = self._text("Check command", default="")
            if not command:
                break
            checks.append(command)
        return tuple(checks)

    def _validate(self, argv: list[str], *, action: str) -> WizardResult:
        validation_argv = list(argv)
        if action in {"run", "print", "save-profile"} and "--dry-run" not in validation_argv:
            # Command-shape validation should not fail just because a provider
            # executable is unavailable before the operator has chosen to run.
            validation_argv.append("--dry-run")
        while True:
            try:
                parsed = cli_args.parse_args(validation_argv)
                build_loop_config(parsed, self.cwd)
                shell_command = shlex.join(("revrem", *argv))
                return WizardResult(argv=tuple(argv), shell_command=shell_command, action=action)
            except SystemExit as exc:
                raise ValueError(f"wizard produced invalid arguments: exit {exc.code}") from exc
            except ValueError as exc:
                print(f"Validation failed: {exc}", file=self.stderr)
                if not self._yes_no("Choose a different action?", default=True):
                    raise WizardCancelled from exc
                action = self._choice(
                    "Fallback action",
                    (("dry-run", "validate without provider execution"), ("print", "print only")),
                    default="dry-run",
                )
                if action == "dry-run" and "--dry-run" not in argv:
                    argv.append("--dry-run")
                validation_argv = list(argv)

    def _choice(
        self,
        label: str,
        options: tuple[tuple[str, str], ...],
        *,
        default: str,
    ) -> str:
        values = {value for value, _description in options}
        if default not in values:
            default = options[0][0]
        while True:
            print(f"\n{label}", file=self.stderr)
            for index, (value, description) in enumerate(options, start=1):
                marker = " [default]" if value == default else ""
                print(f"  {index}. {value}: {description}{marker}", file=self.stderr)
            raw = self._read(f"Choice [{default}]: ").strip()
            if not raw:
                return default
            if raw in values:
                return raw
            if raw.isdigit() and 1 <= int(raw) <= len(options):
                return options[int(raw) - 1][0]
            print("Choose one of the listed values or numbers.", file=self.stderr)

    def _yes_no(self, label: str, default: bool) -> bool:
        suffix = "Y/n" if default else "y/N"
        while True:
            raw = self._read(f"{label} [{suffix}]: ").strip().lower()
            if not raw:
                return default
            if raw in {"y", "yes"}:
                return True
            if raw in {"n", "no"}:
                return False
            print("Choose yes or no.", file=self.stderr)

    def _text(
        self,
        label: str,
        *,
        default: str,
        validator=None,
    ) -> str:
        while True:
            raw = self._read(f"{label} [{default}]: ").strip()
            value = raw if raw else default
            if validator is None:
                return value
            error = validator(value)
            if error is None:
                return value
            print(error, file=self.stderr)

    def _read(self, prompt: str) -> str:
        print(prompt, end="", file=self.stderr, flush=True)
        line = self.stdin.readline()
        if line == "":
            raise WizardCancelled
        value = line.rstrip("\n")
        if value.strip().lower() in {"cancel", "quit", "q"}:
            raise WizardCancelled
        return value


def _profile_label(profile: profiles.Profile) -> str:
    parts = []
    if profile.description:
        parts.append(profile.description)
    parts.append(f"base={profile.pipeline.base}")
    if profile.pipeline.checks:
        parts.append(f"checks={len(profile.pipeline.checks)}")
    if profile.source:
        parts.append(profile.source)
    return ", ".join(parts)


def _route_label(route: profiles.TriageRouteConfig) -> str:
    parts = [f"harness={route.harness}"]
    if route.model:
        parts.append(f"model={route.model}")
    if route.fallback:
        parts.append(f"fallback={route.fallback}")
    return ", ".join(parts)


def _positive_int(value: str) -> str | None:
    try:
        parsed = int(value)
    except ValueError:
        return "Enter a whole number."
    if parsed < 1:
        return "Enter a number greater than zero."
    return None


def _non_negative_float_or_blank(value: str) -> str | None:
    if value == "":
        return None
    try:
        parsed = float(value)
    except ValueError:
        return "Enter a number, 0, or blank."
    if parsed < 0:
        return "Enter 0 or a positive number."
    return None
