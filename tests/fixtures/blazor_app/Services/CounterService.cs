namespace BlazorApp.Services;

/// <summary>Service that manages the counter state.</summary>
public class CounterService
{
    private int _count = 0;

    /// <summary>Gets the current count.</summary>
    public int GetCount() => _count;

    /// <summary>Increments the counter.</summary>
    public void Increment() => _count++;
}
