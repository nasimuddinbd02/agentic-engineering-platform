using OrderService.Models;

namespace OrderService.Repositories;

public interface IOrderRepository
{
    Order? GetById(Guid id);

    void Update(Order order);

    IReadOnlyCollection<Order> All();
}

/// <summary>
/// In-memory store. The sample service has no database on purpose - the
/// interesting behaviour is in the service layer.
/// </summary>
public class InMemoryOrderRepository : IOrderRepository
{
    private readonly Dictionary<Guid, Order> _orders = new();

    public InMemoryOrderRepository(IEnumerable<Order>? seed = null)
    {
        foreach (var order in seed ?? Array.Empty<Order>())
        {
            _orders[order.Id] = order;
        }
    }

    public Order? GetById(Guid id) => _orders.TryGetValue(id, out var order) ? order : null;

    public void Update(Order order) => _orders[order.Id] = order;

    public IReadOnlyCollection<Order> All() => _orders.Values.ToList();

    public Order Add(Order order)
    {
        _orders[order.Id] = order;
        return order;
    }
}
