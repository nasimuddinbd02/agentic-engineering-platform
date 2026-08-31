using Microsoft.AspNetCore.Mvc;
using OrderService.Models;
using OrderService.Services;

namespace OrderService.Controllers;

public record CancelOrderRequest(string? Reason);

[ApiController]
[Route("api/orders")]
public class OrdersController : ControllerBase
{
    private readonly IOrderService _orderService;

    public OrdersController(IOrderService orderService)
    {
        _orderService = orderService;
    }

    [HttpGet("{id:guid}")]
    public ActionResult<Order> GetOrder(Guid id)
    {
        var order = _orderService.GetOrder(id);
        return order is null ? NotFound() : Ok(order);
    }

    /// <summary>
    /// Cancels an order. Any exception escaping the service layer becomes a 500,
    /// which is how the duplicate-cancellation defect surfaces to callers.
    /// </summary>
    [HttpPost("{id:guid}/cancel")]
    public IActionResult CancelOrder(Guid id, [FromBody] CancelOrderRequest? request)
    {
        var result = _orderService.CancelOrder(id, request?.Reason);

        return result.Outcome switch
        {
            CancellationOutcome.Cancelled => Ok(new { message = result.Message }),
            CancellationOutcome.NotFound => NotFound(new { message = result.Message }),
            CancellationOutcome.NotCancellable => Conflict(new { message = result.Message }),
            _ => StatusCode(500, new { message = "Unexpected cancellation outcome." })
        };
    }
}
