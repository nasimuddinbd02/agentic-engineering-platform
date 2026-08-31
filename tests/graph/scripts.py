"""Scripted agent behaviour for graph tests.

These scripts stand in for the model.  They exercise the real tools, the real
worktree, and the real ``dotnet test`` run - only the reasoning is fixed, so the
control plane is what is actually under test.
"""

from __future__ import annotations

from llm.scripted_provider import ScriptedTurn

TARGET_FILE = "src/OrderService/Services/OrderService.cs"
TEST_FILE = "tests/OrderService.Tests/OrderCancellationIdempotencyTests.cs"

REFUND_ANCHOR = "        _paymentService.RefundOrder(order);"

CORRECT_FIX = """        if (order.Status == OrderStatus.Cancelled)
        {
            // Cancellation is idempotent: the order is already cancelled and has
            // already been refunded, so report success instead of refunding twice.
            return CancellationResult.Cancelled(id);
        }

        _paymentService.RefundOrder(order);"""

#: A plausible but wrong first attempt - it returns the wrong outcome, so the
#: regression test fails and the debugging loop has to correct it.
BROKEN_FIX = """        if (order.Status == OrderStatus.Cancelled)
        {
            return CancellationResult.NotCancellable(id, order.Status);
        }

        _paymentService.RefundOrder(order);"""

BROKEN_ANCHOR = """        if (order.Status == OrderStatus.Cancelled)
        {
            return CancellationResult.NotCancellable(id, order.Status);
        }"""

CORRECTED_BLOCK = """        if (order.Status == OrderStatus.Cancelled)
        {
            return CancellationResult.Cancelled(id);
        }"""

REGRESSION_TEST = """using OrderService.Models;
using OrderService.Repositories;
using OrderService.Services;
using Xunit;

namespace OrderService.Tests;

public class OrderCancellationIdempotencyTests
{
    private static (OrderManagementService Service, Order Order) CreateService()
    {
        var order = new Order { CustomerId = "customer-1", Total = 10m, Status = OrderStatus.Pending };
        var repository = new InMemoryOrderRepository(new[] { order });
        return (new OrderManagementService(repository, new PaymentService()), order);
    }

    [Fact]
    public void CancelOrder_AlreadyCancelled_ReturnsSuccess()
    {
        var (service, order) = CreateService();
        service.CancelOrder(order.Id);

        var second = service.CancelOrder(order.Id);

        Assert.Equal(CancellationOutcome.Cancelled, second.Outcome);
        Assert.Equal(OrderStatus.Cancelled, order.Status);
    }

    [Fact]
    public void CancelOrder_CalledThreeTimes_DoesNotThrow()
    {
        var (service, order) = CreateService();

        service.CancelOrder(order.Id);
        service.CancelOrder(order.Id);
        var third = service.CancelOrder(order.Id);

        Assert.Equal(CancellationOutcome.Cancelled, third.Outcome);
    }
}
"""

PLAN_TURN = ScriptedTurn.json(
    {
        "summary": "Make order cancellation idempotent",
        "steps": [
            "Find the cancellation API",
            "Inspect OrderManagementService.CancelOrder",
            "Check how PaymentService handles a repeated refund",
            "Return success when the order is already cancelled",
            "Add a regression test",
        ],
        "acceptance_criteria": [
            "Cancelling an already cancelled order returns success, not HTTP 500",
            "The payment gateway is not asked to refund the same order twice",
            "Existing tests continue to pass",
        ],
    }
)

REPOSITORY_TURNS = [
    ScriptedTurn.call("search_code", pattern="CancelOrder"),
    ScriptedTurn.call("read_file", path=TARGET_FILE),
    ScriptedTurn.json(
        {
            "relevant_files": [
                TARGET_FILE,
                "src/OrderService/Services/PaymentService.cs",
                "src/OrderService/Controllers/OrdersController.cs",
                "tests/OrderService.Tests/OrderServiceTests.cs",
            ],
            "findings": [
                "CancelOrder refunds unconditionally, so a second call throws PaymentGatewayException",
                "PaymentService.RefundOrder rejects a duplicate refund",
                "OrdersController turns the escaping exception into HTTP 500",
            ],
            "entry_point": TARGET_FILE,
        }
    ),
]

RISK_TURN = ScriptedTurn.json(
    {
        "risk_level": "LOW",
        "reasons": ["A guard clause in one service method, covered by tests"],
        "blast_radius": "Only the cancellation path of the order service",
    }
)


def happy_path_script() -> dict[str, list[ScriptedTurn]]:
    """The agent gets it right first time; tests pass on the first run."""
    return {
        "planner": [PLAN_TURN],
        "repository": REPOSITORY_TURNS,
        "risk": [RISK_TURN],
        "implementation": [
            ScriptedTurn.call("read_file", path=TARGET_FILE),
            ScriptedTurn.call(
                "apply_patch",
                path=TARGET_FILE,
                old_text=REFUND_ANCHOR,
                new_text=CORRECT_FIX,
            ),
            ScriptedTurn.json(
                {
                    "summary": "Return success when cancelling an already cancelled order",
                    "changed_files": [TARGET_FILE],
                    "notes_for_tests": ["Cancelling twice must succeed and must not refund twice"],
                }
            ),
        ],
        "testing": [
            ScriptedTurn.call("create_file", path=TEST_FILE, content=REGRESSION_TEST),
            ScriptedTurn.json(
                {
                    "summary": "Added idempotency regression tests",
                    "test_cases": [
                        "Cancelling an already cancelled order returns success",
                        "Cancelling three times does not throw",
                    ],
                    "test_files": [TEST_FILE],
                }
            ),
        ],
    }


def debugging_path_script() -> dict[str, list[ScriptedTurn]]:
    """The first fix is wrong, the tests fail, and the debugger corrects it."""
    script = happy_path_script()
    script["implementation"] = [
        ScriptedTurn.call("read_file", path=TARGET_FILE),
        ScriptedTurn.call(
            "apply_patch", path=TARGET_FILE, old_text=REFUND_ANCHOR, new_text=BROKEN_FIX
        ),
        ScriptedTurn.json(
            {
                "summary": "Reject cancellation when the order is already cancelled",
                "changed_files": [TARGET_FILE],
                "notes_for_tests": ["Cancelling twice must not reach the payment gateway"],
            }
        ),
    ]
    script["debugging"] = [
        ScriptedTurn.call("read_file", path=TARGET_FILE),
        ScriptedTurn.call(
            "apply_patch",
            path=TARGET_FILE,
            old_text=BROKEN_ANCHOR,
            new_text=CORRECTED_BLOCK,
        ),
        ScriptedTurn.json(
            {
                "analysis": (
                    "The guard returned NotCancellable, but cancelling an already "
                    "cancelled order is a successful no-op. Returning Cancelled makes "
                    "the operation idempotent."
                ),
                "fix_applied": True,
                "changed_files": [TARGET_FILE],
                "confidence": "HIGH",
            }
        ),
    ]
    return script


def stuck_script() -> dict[str, list[ScriptedTurn]]:
    """The debugger never fixes anything, so the loop must stop on its own."""
    script = debugging_path_script()
    script["debugging"] = [
        ScriptedTurn.json(
            {
                "analysis": "Still investigating; no change made.",
                "fix_applied": False,
                "changed_files": [],
                "confidence": "LOW",
            }
        )
        for _ in range(6)
    ]
    return script
