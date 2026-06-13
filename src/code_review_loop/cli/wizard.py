"""Dependency-free command-building wizard for the RevRem CLI."""

from __future__ import annotations

import shlex
import sys
from dataclasses import dataclass
from os import environ
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


@dataclass
class WizardState:
    profile_name: str | None
    profile: profiles.Profile
    base: str
    max_iterations: int
    checks: tuple[str, ...]
    final_review: bool
    triage_enabled: bool
    routing_enabled: bool
    routing_default_route: str
    shared_model: str = ""
    shared_reasoning_effort: str = ""
    timeout_seconds: str = ""
    commit_after_remediation: bool = False
    progress_style: str = "compact"
    summary_format: str = "text"
    max_wall_seconds: str = ""
    pending_review: str = "profile"


@dataclass(frozen=True)
class CheckPreset:
    key: str
    label: str
    checks: tuple[str, ...]


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
    except (KeyboardInterrupt, WizardCancelled):
        print("Cancelled before provider calls.", file=wizard.stderr)
        return None


class _Wizard:
    def __init__(self, *, cwd: Path, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> None:
        self.cwd = cwd
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr
        self.console = _rich_console(stderr)

    def run(self) -> WizardResult:
        self._print_heading("RevRem command wizard")
        choice = self._choose_profile()
        state = _initial_state(choice)

        while True:
            self._print_run_preview(state)
            next_step = self._choice(
                "Next step",
                (
                    ("accept", "accept this run shape"),
                    ("essentials", "edit base, loop count, checks, final review, output, budget"),
                    ("phases", "edit model-calling phases and routing"),
                    ("config", "choose a different starting config"),
                    ("cancel", "exit without doing anything"),
                ),
                default="accept",
                help_text="Model/quota-using phases are shown as harness:model(effort).",
            )
            if next_step == "cancel":
                raise WizardCancelled
            if next_step == "config":
                choice = self._choose_profile()
                state = _initial_state(choice)
                continue
            if next_step == "essentials":
                self._common_options(state)
                continue
            if next_step == "phases":
                self._phase_options(state)
                continue
            break

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
            argv = _argv_for_state(state)
            final_argv = list(argv)
            if action == "dry-run":
                final_argv.append("--dry-run")
            elif action == "save-profile":
                name = self._text("Project profile name", default=state.profile_name or "final-pr")
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
        options: list[tuple[str, str]] = [
            (
                "no-profile",
                self._profile_option_label(None, defaults, "no profile (merged defaults)"),
            )
        ]
        options.extend(
            (profile.name, self._profile_option_label(profile.name, profile, profile.name))
            for profile in resolved_profiles
            if profile.name
        )
        default = resolved_profiles[0].name if resolved_profiles else "no-profile"
        default_argv = _profile_command(default if default != "no-profile" else None)
        self._print_key_value("Default command", shlex.join(default_argv))
        selected = self._choice(
            "Start from which configuration?",
            tuple(options),
            default=default,
            help_text="Enter selects the recommended command; no provider calls run until you confirm.",
        )
        if selected == "no-profile":
            return WizardProfileChoice(profile_name=None, profile=defaults)
        for profile in resolved_profiles:
            if profile.name == selected:
                return WizardProfileChoice(profile_name=selected, profile=profile)
        raise WizardCancelled

    def _common_options(self, state: WizardState) -> None:
        base = self._text("Base branch", default=state.base)
        state.base = base

        max_iterations = self._text(
            "Max remediation iterations",
            default=str(state.max_iterations),
            validator=_positive_int,
        )
        state.max_iterations = int(max_iterations)

        state.checks = self._checks(state.checks)

        final_review = self._yes_no(
            "Run final review after remediation?", state.final_review
        )
        state.final_review = final_review

        progress = self._choice(
            "Progress style",
            tuple((value, value) for value in cli_args.PROGRESS_STYLE_CHOICES),
            default=state.progress_style,
        )
        state.progress_style = progress

        summary = self._choice(
            "Terminal summary format",
            (("text", "text"), ("json", "json"), ("both", "text and json")),
            default=state.summary_format,
        )
        state.summary_format = summary

        wall = self._text(
            "Max wall seconds budget (blank for none/profile)",
            default=state.max_wall_seconds,
            validator=_non_negative_float_or_blank,
        )
        state.max_wall_seconds = wall

    def _phase_options(self, state: WizardState) -> None:
        profile = state.profile
        triage = self._yes_no(
            "Use structured triage step before remediation?", state.triage_enabled
        )
        state.triage_enabled = triage
        if triage:
            route_names = tuple(sorted(profile.triage.routes))
            if route_names:
                routing = self._yes_no(
                    "Use profile routing policy? (triage may choose a remediation route)",
                    state.routing_enabled,
                )
                state.routing_enabled = routing
                if routing:
                    route = self._choice(
                        "Default remediation route",
                        tuple(
                            (name, _route_label(profile.triage.routes[name]))
                            for name in route_names
                        ),
                        default=state.routing_default_route
                        if state.routing_default_route in route_names
                        else route_names[0],
                    )
                    state.routing_default_route = route
            else:
                state.routing_enabled = False
                self._print_dim("No profile routes are defined, so routing stays off.")
        else:
            state.routing_enabled = False

        shared_model = self._text(
            "Override review/remediation model (blank = keep shown models)",
            default=state.shared_model,
        )
        state.shared_model = shared_model
        effort = self._choice(
            "Override review/remediation reasoning effort",
            (("profile", "keep profile/default"),)
            + tuple((value, value) for value in cli_args.REASONING_EFFORT_CHOICES),
            default=state.shared_reasoning_effort or "profile",
        )
        state.shared_reasoning_effort = "" if effort == "profile" else effort

        timeout = self._text(
            "Phase timeout seconds (0 disables, blank keeps profile/default)",
            default=state.timeout_seconds,
            validator=_non_negative_float_or_blank,
        )
        state.timeout_seconds = timeout

        commit = self._yes_no(
            "Commit after verified remediation?", state.commit_after_remediation
        )
        state.commit_after_remediation = commit

        pending = self._choice(
            "Pending review handling",
            (
                ("profile", "interactive default"),
                ("prompt", "prompt when compatible feedback exists"),
                ("auto", "reuse compatible feedback automatically"),
                ("ignore", "always start fresh"),
            ),
            default=state.pending_review,
        )
        state.pending_review = pending

    def _checks(self, current: tuple[str, ...]) -> tuple[str, ...]:
        presets = _detect_check_presets(self.cwd)
        options: list[tuple[str, str]] = []
        if current:
            options.append(("keep", f"keep current checks ({len(current)})"))
        options.extend((preset.key, preset.label) for preset in presets)
        options.extend(
            (
                ("custom", "enter manual shell commands"),
                ("none", "use a shell no-op check"),
            )
        )
        default = "keep" if current else (presets[0].key if presets else "custom")
        mode = self._choice(
            "Verification checks",
            tuple(options),
            default=default,
            help_text="Choose a detected preset or use custom for raw shell commands.",
        )
        if mode == "keep":
            return current
        if mode == "none":
            return ()
        for preset in presets:
            if mode == preset.key:
                return preset.checks
        checks: list[str] = []
        self._print_dim("Enter one manual shell command per line. Leave blank when done.")
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
        help_text: str | None = None,
    ) -> str:
        values = {value for value, _description in options}
        if default not in values:
            default = options[0][0]
        while True:
            self._print_heading(label)
            if help_text:
                self._print_dim(help_text)
            for index, (value, description) in enumerate(options, start=1):
                self._print_option(index, value, description, is_default=value == default)
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
        self._print_prompt(prompt)
        try:
            line = self.stdin.readline()
        except KeyboardInterrupt as exc:
            raise WizardCancelled from exc
        if line == "":
            raise WizardCancelled
        value = line.rstrip("\n")
        if value.strip().lower() in {"cancel", "quit", "q"}:
            raise WizardCancelled
        return value

    def _profile_option_label(
        self,
        profile_name: str | None,
        profile: profiles.Profile,
        display_name: str,
    ) -> str:
        parts = [display_name] if profile_name is None else []
        source = _display_source(profile.source, cwd=self.cwd)
        if source:
            parts.append(f"({source})")
        if profile.description:
            parts.append(_clip(profile.description, 90))
        parts.append(f"command: {shlex.join(_profile_command(profile_name))}")
        return "; ".join(parts)

    def _print_run_preview(self, state: WizardState) -> None:
        self._print_heading("Run shape")
        for line in _run_preview_lines(state):
            print(line, file=self.stderr)

    def _print_heading(self, value: str) -> None:
        print("", file=self.stderr)
        if self.console is not None:
            self.console.print(value, style="bold cyan")
            return
        print(value, file=self.stderr)

    def _print_key_value(self, key: str, value: str) -> None:
        if self.console is not None:
            text = self._rich_text()
            text.append(f"{key}: ", style="bold")
            text.append(value, style="green")
            self.console.print(text)
            return
        print(f"{key}: {value}", file=self.stderr)

    def _print_dim(self, value: str) -> None:
        if self.console is not None:
            self.console.print(value, style="dim")
            return
        print(value, file=self.stderr)

    def _print_option(
        self,
        index: int,
        value: str,
        description: str,
        *,
        is_default: bool,
    ) -> None:
        if self.console is not None:
            text = self._rich_text()
            text.append(f"  {index}. ", style="dim")
            text.append(value, style="bold")
            text.append(": ")
            for segment_index, segment in enumerate(description.split("; ")):
                if segment_index:
                    text.append("; ", style="dim")
                style = "green" if segment.startswith("command: ") else None
                text.append(segment, style=style)
            if is_default:
                text.append(" [default]", style="yellow")
            self.console.print(text)
            return
        marker = " [default]" if is_default else ""
        print(f"  {index}. {value}: {description}{marker}", file=self.stderr)

    def _print_prompt(self, prompt: str) -> None:
        if self.console is not None:
            text = self._rich_text()
            text.append(prompt, style="bold")
            self.console.print(text, end="")
            return
        print(prompt, end="", file=self.stderr, flush=True)

    def _rich_text(self):
        if self.console is None:
            raise RuntimeError("Rich text requested without a Rich console")
        from rich.text import Text  # type: ignore[import-not-found]

        return Text()


def _profile_command(profile_name: str | None) -> tuple[str, ...]:
    if profile_name:
        return ("revrem", "--profile", profile_name)
    return ("revrem",)


def _initial_state(choice: WizardProfileChoice) -> WizardState:
    profile = choice.profile
    return WizardState(
        profile_name=choice.profile_name,
        profile=profile,
        base=profile.pipeline.base,
        max_iterations=profile.pipeline.max_iterations,
        checks=profile.pipeline.checks,
        final_review=profile.pipeline.final_review,
        triage_enabled=profile.triage.enabled,
        routing_enabled=profile.triage.routing.enabled and bool(profile.triage.routes),
        routing_default_route=profile.triage.routing.default_route,
        commit_after_remediation=profile.commit.enabled,
        progress_style=profile.output.progress_style,
        summary_format=profile.output.summary_format,
    )


def _argv_for_state(state: WizardState) -> list[str]:
    profile = state.profile
    argv: list[str] = []
    if state.profile_name:
        argv.extend(["--profile", state.profile_name])
    if state.base != profile.pipeline.base:
        argv.extend(["--base", state.base])
    if state.max_iterations != profile.pipeline.max_iterations:
        argv.extend(["--max-iterations", str(state.max_iterations)])
    if state.checks != profile.pipeline.checks:
        checks = state.checks or ("true",)
        for command in checks:
            argv.extend(["--check", command])
    if state.final_review != profile.pipeline.final_review:
        argv.append("--final-review" if state.final_review else "--skip-final-review")
    if state.triage_enabled != profile.triage.enabled:
        argv.append("--triage" if state.triage_enabled else "--no-triage")
    if state.triage_enabled:
        if state.routing_enabled != profile.triage.routing.enabled:
            argv.append("--routing" if state.routing_enabled else "--no-routing")
        if state.routing_enabled and profile.triage.contract != "v2":
            argv.extend(["--triage-contract", "v2"])
        if (
            state.routing_enabled
            and state.routing_default_route != profile.triage.routing.default_route
        ):
            argv.extend(["--route", state.routing_default_route])
    if state.shared_model:
        argv.extend(["--model", state.shared_model])
    if state.shared_reasoning_effort:
        argv.extend(["--reasoning-effort", state.shared_reasoning_effort])
    if state.timeout_seconds:
        argv.extend(["--timeout-seconds", state.timeout_seconds])
    if state.commit_after_remediation != profile.commit.enabled:
        argv.append(
            "--commit-after-remediation"
            if state.commit_after_remediation
            else "--no-commit-after-remediation"
        )
    if state.progress_style != profile.output.progress_style:
        argv.extend(["--progress-style", state.progress_style])
    if state.summary_format != profile.output.summary_format:
        argv.extend(["--summary-format", state.summary_format])
    if state.max_wall_seconds:
        argv.extend(["--max-wall-seconds", state.max_wall_seconds])
    if state.pending_review != "profile":
        argv.extend(["--pending-review", state.pending_review])
    return argv


def _run_preview_lines(state: WizardState) -> tuple[str, ...]:
    profile = state.profile
    command = shlex.join(("revrem", *_argv_for_state(state)))
    lines = [
        f"command: {command}",
        f"base: {state.base}",
        f"review: {_phase_call(profile.review, state)}",
    ]
    if state.triage_enabled:
        triage_bits = [
            _phase_call(profile.triage, state, shared_override=False),
            f"contract={profile.triage.contract}",
        ]
        lines.append("  -> triage: " + ", ".join(bit for bit in triage_bits if bit))
        if state.routing_enabled:
            route = profile.triage.routes.get(state.routing_default_route)
            route_text = _route_call(state.routing_default_route, route)
            lines.append(f"     routing policy: default {route_text}")
            route_names = ", ".join(
                _route_call(name, route_cfg) for name, route_cfg in sorted(profile.triage.routes.items())
            )
            lines.append(f"     routes: {route_names}")
        else:
            lines.append("     routing policy: off")
    else:
        lines.append("  -> triage: off")
    lines.append(f"  -> loop: up to {state.max_iterations} remediation iteration(s)")
    lines.append(f"     remediate: {_phase_call(profile.remediation, state)}")
    lines.extend(_check_preview_lines(state.checks))
    if state.final_review:
        lines.append(f"  -> final review: {_phase_call(profile.review, state)}")
    else:
        lines.append("  -> final review: off")
    if state.commit_after_remediation:
        lines.append(
            "  -> commit message: "
            f"{_phase_call(profile.commit, state, shared_override=False, model_attr='message_model')}"
        )
    else:
        lines.append("  -> commit: off")
    lines.append(f"output: {state.summary_format}, {state.progress_style} progress")
    if state.max_wall_seconds:
        lines.append(f"budget: max wall {state.max_wall_seconds}s")
    if state.pending_review != "profile":
        lines.append(f"pending review: {state.pending_review}")
    return tuple(lines)


def _phase_call(
    phase: profiles.PhaseConfig | profiles.TriageConfig | profiles.CommitConfig,
    state: WizardState,
    *,
    shared_override: bool = True,
    model_attr: str = "model",
) -> str:
    harness = phase.harness
    model_value = getattr(phase, model_attr)
    model = state.shared_model if shared_override and state.shared_model else model_value
    effort = (
        state.shared_reasoning_effort
        if shared_override and state.shared_reasoning_effort
        else phase.reasoning_effort
    )
    timeout = state.timeout_seconds if shared_override and state.timeout_seconds else None
    if timeout == "":
        timeout = None
    timeout_display = timeout if timeout is not None else phase.timeout_seconds
    call = f"{harness}:{model or 'default'}"
    if effort:
        call += f"({effort})"
    if timeout_display is not None:
        call += f" timeout={_timeout_text(timeout_display)}"
    return call


def _route_call(name: str, route: profiles.TriageRouteConfig | None) -> str:
    if route is None:
        return f"{name} (missing)"
    text = f"{name}->{route.harness}:{route.model or 'default'}"
    if route.reasoning_effort:
        text += f"({route.reasoning_effort})"
    if route.fallback:
        text += f" fallback={route.fallback}"
    return text


def _check_preview_lines(checks: tuple[str, ...]) -> list[str]:
    if not checks:
        return ["     checks: shell no-op"]
    lines = [f"     checks: {len(checks)} command(s)"]
    for index, command in enumerate(checks[:5], start=1):
        lines.append(f"       {index}. {command}")
    if len(checks) > 5:
        lines.append(f"       ... {len(checks) - 5} more")
    return lines


def _timeout_text(value: str | int | float) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number == 0:
        return "none"
    return f"{number:g}s"


def _profile_summary(profile: profiles.Profile) -> str:
    parts = [
        f"base={profile.pipeline.base}",
        f"max={profile.pipeline.max_iterations}",
        f"checks={len(profile.pipeline.checks)}",
        f"review={_phase_summary(profile.review)}",
        f"triage={_triage_summary(profile)}",
        f"remediate={_phase_summary(profile.remediation)}",
        f"commit={'on' if profile.commit.enabled else 'off'}",
        f"output={profile.output.summary_format}/{profile.output.progress_style}",
    ]
    return "; ".join(parts)


def _phase_summary(phase: profiles.PhaseConfig) -> str:
    parts = [phase.harness]
    if phase.model:
        parts.append(phase.model)
    if phase.reasoning_effort:
        parts.append(f"effort={phase.reasoning_effort}")
    if phase.timeout_seconds is not None:
        parts.append(f"timeout={phase.timeout_seconds:g}s")
    return ",".join(parts)


def _triage_summary(profile: profiles.Profile) -> str:
    if not profile.triage.enabled:
        return "off"
    parts = [profile.triage.contract, profile.triage.harness]
    if profile.triage.model:
        parts.append(profile.triage.model)
    if profile.triage.routing.enabled:
        parts.append(f"routing={profile.triage.routing.default_route}")
    return ",".join(parts)


def _display_source(source: str | None, *, cwd: Path) -> str:
    if not source:
        return ""
    path = Path(source)
    try:
        if path == profiles.project_config_path(cwd):
            return "./.revrem.toml"
        if path == profiles.user_config_path():
            return "~/.config/revrem/profiles.toml"
        if path.is_absolute():
            try:
                return f"./{path.relative_to(cwd)}"
            except ValueError:
                home = Path.home()
                try:
                    return f"~/{path.relative_to(home)}"
                except ValueError:
                    return str(path)
    except OSError:
        return source
    return str(path)


def _clip(value: str, max_chars: int) -> str:
    value = " ".join(value.split())
    if len(value) <= max_chars:
        return value
    return f"{value[: max_chars - 1]}…"


def _rich_console(stderr: TextIO):
    if not getattr(stderr, "isatty", lambda: False)() or environ.get("NO_COLOR"):
        return None
    try:
        from rich.console import Console  # type: ignore[import-not-found]
    except ImportError:
        return None
    return Console(file=stderr, force_terminal=True)


def _route_label(route: profiles.TriageRouteConfig) -> str:
    parts = [f"harness={route.harness}"]
    if route.model:
        parts.append(f"model={route.model}")
    if route.fallback:
        parts.append(f"fallback={route.fallback}")
    return ", ".join(parts)


def _detect_check_presets(cwd: Path) -> tuple[CheckPreset, ...]:
    presets: list[CheckPreset] = []
    if (cwd / "scripts" / "dev-check").is_file():
        presets.append(CheckPreset("repo-gate", "repo gate: ./scripts/dev-check", ("./scripts/dev-check",)))

    pyproject = cwd / "pyproject.toml"
    tests_dir = cwd / "tests"
    if pyproject.is_file() or tests_dir.is_dir():
        presets.append(CheckPreset("python-fast", "Python fast: pytest -q", ("pytest -q",)))

    static_checks: list[str] = []
    if pyproject.is_file():
        text = _read_text_best_effort(pyproject)
        if "[tool.ruff" in text or "ruff" in text:
            static_checks.append("ruff check .")
        if "[tool.mypy" in text or "mypy" in text:
            static_checks.append("mypy src")
    if static_checks:
        presets.append(CheckPreset("python-static", "Python static: " + " && ".join(static_checks), tuple(static_checks)))

    if _meminit_detected(cwd):
        presets.append(
            CheckPreset(
                "meminit",
                "Meminit DocOps: uv run --locked meminit check --format json",
                ("uv run --locked meminit check --format json",),
            )
        )
    presets.append(CheckPreset("diff-check", "Git whitespace: git diff --check", ("git diff --check",)))
    return tuple(presets)


def _read_text_best_effort(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _meminit_detected(cwd: Path) -> bool:
    agents = cwd / "AGENTS.md"
    if agents.is_file() and "MEMINIT_PROTOCOL" in _read_text_best_effort(agents):
        return True
    return (cwd / "docs").is_dir()


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
