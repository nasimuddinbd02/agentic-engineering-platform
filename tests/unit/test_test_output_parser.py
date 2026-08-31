"""Test-output parsing (sections 21 and 23).

The fixtures are verbatim ``dotnet test`` output from the sample repository, so
the parser is tested against reality rather than against an idea of the format.
"""

from __future__ import annotations

from pathlib import Path

from graph.fingerprint import signatures_for
from tools.runner import CommandResult
from tools.testing.test import detect_project_kind, parse_dotnet_output

FIXTURES = Path(__file__).parent / "fixtures"

PASSING = (
    "  Determining projects to restore...\n"
    "  OrderService -> D:\\repo\\src\\OrderService\\bin\\Debug\\net10.0\\OrderService.dll\n"
    "Test run for D:\\repo\\tests\\OrderService.Tests.dll (.NETCoreApp,Version=v10.0)\n"
    "Passed!  - Failed:     0, Passed:     7, Skipped:     0, Total:     7, "
    "Duration: 272 ms - OrderService.Tests.dll (net10.0)\n"
)


def result_of(output: str, exit_code: int) -> CommandResult:
    return CommandResult(
        command=["dotnet", "test"],
        cwd=".",
        exit_code=exit_code,
        stdout=output,
        stderr="",
        duration_ms=1000,
    )


def test_passing_run_is_parsed() -> None:
    outcome = parse_dotnet_output(result_of(PASSING, 0))
    assert outcome.ok
    assert outcome.passed == 7
    assert outcome.failed == 0
    assert outcome.failures == []


def test_failing_run_is_parsed() -> None:
    output = (FIXTURES / "dotnet_failure.txt").read_text(encoding="utf-8")
    outcome = parse_dotnet_output(result_of(output, 1))

    assert not outcome.ok
    assert outcome.passed == 7
    assert outcome.failed == 1
    assert len(outcome.failures) == 1

    failure = outcome.failures[0]
    assert failure.test_name.endswith("CancelOrder_AlreadyCancelled_IsIdempotent")
    assert failure.exception_type == "OrderService.Services.PaymentGatewayException"
    assert "already been refunded" in failure.message


def test_failing_run_produces_a_stable_signature() -> None:
    output = (FIXTURES / "dotnet_failure.txt").read_text(encoding="utf-8")
    outcome = parse_dotnet_output(result_of(output, 1))
    rendered = [failure.render() for failure in outcome.failures]

    # A rerun with a different order GUID must fingerprint identically.
    rerun = output.replace(
        "20ae256e-efa9-4f85-881a-e606877d40cd", "9a1b2c3d-4e5f-6071-8293-a4b5c6d7e8f9"
    )
    rerun_rendered = [
        failure.render() for failure in parse_dotnet_output(result_of(rerun, 1)).failures
    ]
    assert signatures_for(rendered) == signatures_for(rerun_rendered)


def test_build_failure_becomes_one_synthetic_failure() -> None:
    output = "error CS1002: ; expected\nBuild FAILED.\n"
    outcome = parse_dotnet_output(result_of(output, 1))
    assert not outcome.ok
    assert outcome.failed == 1
    assert outcome.failures[0].exception_type == "RunFailure"


def test_timeout_is_not_ok() -> None:
    timed_out = CommandResult(
        command=["dotnet", "test"],
        cwd=".",
        exit_code=0,
        stdout=PASSING,
        stderr="",
        duration_ms=600_000,
        timed_out=True,
    )
    assert not parse_dotnet_output(timed_out).ok


def test_project_kind_detection(tmp_path: Path) -> None:
    assert detect_project_kind(tmp_path) == "unknown"
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "App.csproj").write_text("<Project/>", encoding="utf-8")
    assert detect_project_kind(tmp_path) == "dotnet"
