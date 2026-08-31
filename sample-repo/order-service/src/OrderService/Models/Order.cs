namespace OrderService.Models;

public enum OrderStatus
{
    Pending,
    Paid,
    Shipped,
    Completed,
    Cancelled
}

public class Order
{
    public Guid Id { get; init; } = Guid.NewGuid();

    public string CustomerId { get; init; } = string.Empty;

    public decimal Total { get; init; }

    public OrderStatus Status { get; set; } = OrderStatus.Pending;

    public DateTimeOffset CreatedAt { get; init; } = DateTimeOffset.UtcNow;

    public DateTimeOffset? CancelledAt { get; set; }

    public string? CancellationReason { get; set; }
}
