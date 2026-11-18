using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;

namespace SinavAjan.Core;

/// <summary>An API call failed. <see cref="IsNetwork"/> means the server could not be reached.</summary>
public sealed class ApiException : Exception
{
    public int Status { get; }
    public bool IsNetwork => Status == 0;

    public ApiException(int status, string message, Exception? inner = null) : base(message, inner)
    {
        Status = status;
    }
}

/// <summary>HTTP client for the teacher server (student API).</summary>
public sealed class ApiClient : IDisposable
{
    private static readonly TimeSpan ShortTimeout = TimeSpan.FromSeconds(4);
    private static readonly TimeSpan TransferTimeout = TimeSpan.FromSeconds(120);

    private readonly HttpClient _http;

    public string Host { get; }
    public int Port { get; }
    public string Token { get; set; } = "";

    public ApiClient(string host, int port)
    {
        Host = host;
        Port = port;
        var handler = new SocketsHttpHandler
        {
            // The server is on the classroom LAN: never go through a system proxy.
            UseProxy = false,
            ConnectTimeout = TimeSpan.FromSeconds(4),
            PooledConnectionLifetime = TimeSpan.FromMinutes(2),
            PooledConnectionIdleTimeout = TimeSpan.FromSeconds(30),
        };
        _http = new HttpClient(handler)
        {
            BaseAddress = new Uri($"http://{host}:{port}/"),
            Timeout = Timeout.InfiniteTimeSpan, // each call has its own timeout
        };
    }

    public Task<InfoResponse> GetInfoAsync(CancellationToken ct = default) =>
        SendJsonAsync<InfoResponse>(HttpMethod.Get, "api/info", null, ShortTimeout, auth: false, ct);

    public Task<LoginResponse> LoginAsync(LoginRequest request, CancellationToken ct = default) =>
        SendJsonAsync<LoginResponse>(HttpMethod.Post, "api/login", request, TimeSpan.FromSeconds(8), auth: false, ct);

    public Task<ExamStatus> HeartbeatAsync(HeartbeatRequest request, CancellationToken ct = default) =>
        SendJsonAsync<ExamStatus>(HttpMethod.Post, "api/heartbeat", request, ShortTimeout, auth: true, ct);

    public async Task SendEventAsync(EventRequest request, CancellationToken ct = default) =>
        await SendJsonAsync<JsonElement>(HttpMethod.Post, "api/event", request, ShortTimeout, auth: true, ct)
            .ConfigureAwait(false);

    public Task<ConfigResponse> GetConfigAsync(CancellationToken ct = default) =>
        SendJsonAsync<ConfigResponse>(HttpMethod.Get, "api/config", null, ShortTimeout, auth: true, ct);

    public async Task<byte[]> DownloadExamFileAsync(CancellationToken ct = default)
    {
        using var message = new HttpRequestMessage(HttpMethod.Get, "api/exam-file");
        using var response = await SendAsync(message, TransferTimeout, auth: true, ct).ConfigureAwait(false);
        return await ReadBytesAsync(response, ct).ConfigureAwait(false);
    }

    /// <summary>
    /// Uploads a file as this student's submission. <paramref name="sha256"/> is the hash of the
    /// bytes as read on this computer; the server refuses the upload if what arrives differs.
    /// </summary>
    public async Task<SubmitResponse> SubmitAsync(byte[] content, string sha256,
        string originalName = "", bool stale = false, CancellationToken ct = default)
    {
        using var form = new MultipartFormDataContent();
        form.Add(new StringContent(sha256), "sha256");
        // Sent as a text field: file names with Turkish letters do not survive every
        // multipart "filename" encoding.
        if (originalName.Length > 0) form.Add(new StringContent(originalName), "original_name");
        if (stale) form.Add(new StringContent("true"), "stale");
        var file = new ByteArrayContent(content);
        file.Headers.ContentType = new MediaTypeHeaderValue("application/octet-stream");
        form.Add(file, "file", "sinav.pka");

        using var message = new HttpRequestMessage(HttpMethod.Post, "api/submit") { Content = form };
        using var response = await SendAsync(message, TransferTimeout, auth: true, ct).ConfigureAwait(false);
        return await ReadJsonAsync<SubmitResponse>(response, ct).ConfigureAwait(false);
    }

    private async Task<T> SendJsonAsync<T>(HttpMethod method, string path, object? body, TimeSpan timeout,
        bool auth, CancellationToken ct)
    {
        using var message = new HttpRequestMessage(method, path);
        if (body != null) message.Content = JsonContent.Create(body, body.GetType());
        using var response = await SendAsync(message, timeout, auth, ct).ConfigureAwait(false);
        return await ReadJsonAsync<T>(response, ct).ConfigureAwait(false);
    }

    private async Task<HttpResponseMessage> SendAsync(HttpRequestMessage message, TimeSpan timeout, bool auth,
        CancellationToken ct)
    {
        if (auth) message.Headers.Authorization = new AuthenticationHeaderValue("Bearer", Token);
        using var timeoutSource = CancellationTokenSource.CreateLinkedTokenSource(ct);
        timeoutSource.CancelAfter(timeout);

        HttpResponseMessage response;
        try
        {
            // The content is buffered before the timeout source is disposed.
            response = await _http.SendAsync(message, HttpCompletionOption.ResponseContentRead, timeoutSource.Token)
                .ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (!ct.IsCancellationRequested)
        {
            throw new ApiException(0, "Sunucu yanıt vermedi (zaman aşımı).");
        }
        catch (HttpRequestException ex)
        {
            throw new ApiException(0, "Sunucuya ulaşılamıyor.", ex);
        }
        catch (IOException ex)
        {
            throw new ApiException(0, "Sunucu bağlantısı kesildi.", ex);
        }

        if (response.IsSuccessStatusCode) return response;

        var status = (int)response.StatusCode;
        var text = "";
        try
        {
            var error = await response.Content.ReadFromJsonAsync<ErrorResponse>(ct).ConfigureAwait(false);
            text = error?.Error ?? "";
        }
        catch (Exception ex) when (ex is JsonException or HttpRequestException or IOException or NotSupportedException)
        {
            // Not our JSON error format; fall through to the generic message.
        }
        response.Dispose();
        throw new ApiException(status, string.IsNullOrWhiteSpace(text) ? $"Sunucu hatası ({status})." : text);
    }

    private static async Task<T> ReadJsonAsync<T>(HttpResponseMessage response, CancellationToken ct)
    {
        try
        {
            var value = await response.Content.ReadFromJsonAsync<T>(ct).ConfigureAwait(false);
            return value ?? throw new ApiException(502, "Sunucudan boş yanıt geldi.");
        }
        catch (JsonException ex)
        {
            throw new ApiException(502, "Sunucu yanıtı anlaşılamadı.", ex);
        }
    }

    private static async Task<byte[]> ReadBytesAsync(HttpResponseMessage response, CancellationToken ct)
    {
        try
        {
            return await response.Content.ReadAsByteArrayAsync(ct).ConfigureAwait(false);
        }
        catch (Exception ex) when (ex is HttpRequestException or IOException)
        {
            throw new ApiException(0, "Dosya indirilirken bağlantı kesildi.", ex);
        }
    }

    public void Dispose() => _http.Dispose();
}
