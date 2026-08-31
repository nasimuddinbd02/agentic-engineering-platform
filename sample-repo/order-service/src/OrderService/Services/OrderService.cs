using OrderService.Models;
using OrderService.Repositories;

namespace OrderService.Services;

public enum CancellationOutcome
{
    Cancelled,
    NotFound,
    NotCancellable
}

public record CancellationResult(CancellationOutcome Outcome, string Message)
{
    public static CancellationResult Cancelled(Guid id) =>
        new(CancellationOutcome.Cancelled, $"Order {id} cancelled.");

    public static CancellationResult NotFound(Guid id) =>
        new(CancellationOutcome.NotFound, $"Order {id} was not found.");

    public static CancellationResult NotCancellable(Guid id, OrderStatus status) =>
        new(CancellationOutcome.NotCancellable, $"Order {id} cannot be cancelled while it is {status}.");
}

public interface IOrderService
{
    Order? GetOrder(Guid id);

    CancellationResult CancelOrder(Guid id, string? reason = null);
}

public class OrderManagementService : IOrderService
{
    private readonly IOrderRepository _repository;
    private readonly IPaymentService _paymentService;

    public OrderManagementService(IOrderRepository repository, IPaymentService paymentService)
    {
        _repository = repository;
        _paymentService = paymentService;
    }

    public Order? GetOrder(Guid id) => _repository.GetById(id);

    public CancellationResult CancelOrder(Guid id, string? reason = null)
    {
        var order = _repository.GetById(id);
        if (order is null)
        {
            return CancellationResult.NotFound(id);
        }

        if (order.Status == OrderStatus.Completed || order.Status == OrderStatus.Shipped)
        {
            return CancellationResult.NotCancellable(id, order.Status);
        }

        _paymentService.RefundOrder(order);

        order.Status = OrderStatus.Cancelled;
        order.CancelledAt = DateTimeOffset.UtcNow;
        order.CancellationReason = reason;
        _repository.Update(order);

        return CancellationResult.Cancelled(id);
    }
}
