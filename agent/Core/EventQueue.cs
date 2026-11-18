namespace SinavAjan.Core;

/// <summary>
/// Events for the server, delivered in order. While the server is unreachable they are
/// kept (up to a limit) and sent after the connection returns.
/// </summary>
public sealed class EventQueue
{
    private const int MaxPending = 500;
    private readonly Queue<EventRequest> _pending = new();
    private readonly object _gate = new();
    private readonly ApiClient _api;

    public EventQueue(ApiClient api) => _api = api;

    public void Enqueue(string type, Dictionary<string, object?>? details = null)
    {
        var request = new EventRequest
        {
            Type = type,
            Details = details ?? new Dictionary<string, object?>(),
            Ts = NetInfo.UnixNow(),
        };
        lock (_gate)
        {
            if (_pending.Count >= MaxPending) _pending.Dequeue(); // drop the oldest
            _pending.Enqueue(request);
        }
        LocalLog.Write($"olay: {type} {string.Join(", ", request.Details.Select(p => $"{p.Key}={p.Value}"))}");
    }

    public async Task RunAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            EventRequest? next;
            lock (_gate) next = _pending.Count > 0 ? _pending.Peek() : null;
            try
            {
                if (next == null)
                {
                    await Task.Delay(250, ct).ConfigureAwait(false);
                    continue;
                }
                await _api.SendEventAsync(next, ct).ConfigureAwait(false);
                Remove(next);
            }
            catch (OperationCanceledException)
            {
                return;
            }
            catch (ApiException ex) when (ex.IsNetwork || ex.Status == 401)
            {
                // Offline or session being re-established: keep the event and retry.
                try
                {
                    await Task.Delay(2000, ct).ConfigureAwait(false);
                }
                catch (OperationCanceledException)
                {
                    return;
                }
            }
            catch (ApiException ex)
            {
                LocalLog.Write($"olay gönderilemedi ({next?.Type}): {ex.Message}");
                if (next != null) Remove(next); // rejected by the server: do not retry forever
            }
        }
    }

    /// <summary>Waits until everything queued so far has been sent, or the timeout passes.</summary>
    public async Task DrainAsync(TimeSpan timeout)
    {
        var deadline = DateTime.UtcNow + timeout;
        while (DateTime.UtcNow < deadline)
        {
            lock (_gate)
            {
                if (_pending.Count == 0) return;
            }
            await Task.Delay(100).ConfigureAwait(false);
        }
    }

    /// <summary>Try to send one event right now (used when the agent is closing).</summary>
    public async Task<bool> SendNowAsync(string type, Dictionary<string, object?>? details, TimeSpan timeout)
    {
        using var cts = new CancellationTokenSource(timeout);
        try
        {
            await _api.SendEventAsync(new EventRequest
            {
                Type = type,
                Details = details ?? new Dictionary<string, object?>(),
                Ts = NetInfo.UnixNow(),
            }, cts.Token).ConfigureAwait(false);
            return true;
        }
        catch (Exception ex) when (ex is ApiException or OperationCanceledException)
        {
            return false;
        }
    }

    private void Remove(EventRequest sent)
    {
        lock (_gate)
        {
            if (_pending.Count > 0 && ReferenceEquals(_pending.Peek(), sent)) _pending.Dequeue();
        }
    }
}
