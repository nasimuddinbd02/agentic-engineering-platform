using OrderService.Models;
using OrderService.Repositories;
using OrderService.Services;

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddControllers();
builder.Services.AddSingleton<IOrderRepository>(_ => new InMemoryOrderRepository(new[]
{
    new Order { CustomerId = "demo-customer", Total = 42.00m, Status = OrderStatus.Pending }
}));
builder.Services.AddSingleton<IPaymentService, PaymentService>();
builder.Services.AddScoped<IOrderService, OrderManagementService>();

var app = builder.Build();

app.MapControllers();
app.MapGet("/health", () => Results.Ok(new { status = "ok" }));

app.Run();

/// <summary>Exposed so integration tests can reference the entry-point assembly.</summary>
public partial class Program;
