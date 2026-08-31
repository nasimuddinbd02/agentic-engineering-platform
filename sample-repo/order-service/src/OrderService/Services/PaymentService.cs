using OrderService.Models;

namespace OrderService.Services;

public interface IPaymentService
{
    void RefundOrder(Order order);
}

public class PaymentGatewayException : Exception
{
    public PaymentGatewayException(string message) : base(message)
    {
    }
}

/// <summary>
/// Stand-in for a real payment gateway. Refunding an order that was already
/// refunded is an error on the provider side - the gateway has no record of a
/// second charge to reverse.
/// </summary>
public class PaymentService : IPaymentService
{
    private readonly HashSet<Guid> _refunded = new();

    public void RefundOrder(Order order)
    {
        if (!_refunded.Add(order.Id))
        {
            throw new PaymentGatewayException(
                $"Order {order.Id} has already been refunded; the gateway rejected the duplicate refund.");
        }
    }
}
