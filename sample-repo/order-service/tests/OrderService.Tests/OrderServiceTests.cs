using OrderService.Models;
using OrderService.Repositories;
using OrderService.Services;
using Xunit;

namespace OrderService.Tests;

public class OrderServiceTests
{
    private static (OrderManagementService Service, Order Order) CreateService(
        OrderStatus status = OrderStatus.Pending)
    {
        var order = new Order { CustomerId = "customer-1", Total = 25.50m, Status = status };
        var repository = new InMemoryOrderRepository(new[] { order });
        var service = new OrderManagementService(repository, new PaymentService());
        return (service, order);
    }

    [Fact]
    public void CancelOrder_PendingOrder_IsCancelled()
    {
        var (service, order) = CreateService();

        var result = service.CancelOrder(order.Id);

        Assert.Equal(CancellationOutcome.Cancelled, result.Outcome);
        Assert.Equal(OrderStatus.Cancelled, order.Status);
        Assert.NotNull(order.CancelledAt);
    }

    [Fact]
    public void CancelOrder_PaidOrder_IsCancelled()
    {
        var (service, order) = CreateService(OrderStatus.Paid);

        var result = service.CancelOrder(order.Id, "customer changed their mind");

        Assert.Equal(CancellationOutcome.Cancelled, result.Outcome);
        Assert.Equal("customer changed their mind", order.CancellationReason);
    }

    [Fact]
    public void CancelOrder_MissingOrder_ReturnsNotFound()
    {
        var (service, _) = CreateService();

        var result = service.CancelOrder(Guid.NewGuid());

        Assert.Equal(CancellationOutcome.NotFound, result.Outcome);
    }

    [Fact]
    public void CancelOrder_ShippedOrder_IsRejected()
    {
        var (service, order) = CreateService(OrderStatus.Shipped);

        var result = service.CancelOrder(order.Id);

        Assert.Equal(CancellationOutcome.NotCancellable, result.Outcome);
        Assert.Equal(OrderStatus.Shipped, order.Status);
    }

    [Fact]
    public void CancelOrder_CompletedOrder_IsRejected()
    {
        var (service, order) = CreateService(OrderStatus.Completed);

        var result = service.CancelOrder(order.Id);

        Assert.Equal(CancellationOutcome.NotCancellable, result.Outcome);
    }

    [Fact]
    public void GetOrder_ReturnsSeededOrder()
    {
        var (service, order) = CreateService();

        Assert.Same(order, service.GetOrder(order.Id));
    }

    [Fact]
    public void GetOrder_UnknownId_ReturnsNull()
    {
        var (service, _) = CreateService();

        Assert.Null(service.GetOrder(Guid.NewGuid()));
    }
}
