using System.Net;
using System.Net.NetworkInformation;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;

namespace SinavAjan.Core;

/// <summary>
/// Finds the teacher server with a UDP broadcast ("SINAV_DISCOVER v1" on port 47000).
/// A broadcast never leaves the modem's own network, so every agent finds the
/// server of the classroom it is actually connected to.
/// </summary>
public static class Discovery
{
    public const string RequestText = "SINAV_DISCOVER v1";

    private static readonly TimeSpan ResendInterval = TimeSpan.FromSeconds(1);
    private static readonly TimeSpan SettleTime = TimeSpan.FromMilliseconds(800);

    public static async Task<List<ServerInfo>> FindAsync(int port, TimeSpan timeout, CancellationToken ct = default)
    {
        var found = new Dictionary<string, ServerInfo>(StringComparer.OrdinalIgnoreCase);
        var gate = new object();
        var payload = Encoding.ASCII.GetBytes(RequestText);

        var sockets = new List<(UdpClient Client, List<IPEndPoint> Targets)>();
        foreach (var (local, broadcast) in LocalAddresses())
        {
            try
            {
                var client = new UdpClient(new IPEndPoint(local, 0)) { EnableBroadcast = true };
                IgnoreConnectionReset(client.Client);
                var targets = new List<IPEndPoint> { new(IPAddress.Broadcast, port) };
                if (broadcast != null && !broadcast.Equals(IPAddress.Broadcast)) targets.Add(new IPEndPoint(broadcast, port));
                sockets.Add((client, targets));
            }
            catch (SocketException)
            {
                // Interface went away between enumeration and bind; skip it.
            }
        }
        try
        {
            // Same machine (teacher trying the agent on the server PC).
            var loopback = new UdpClient(new IPEndPoint(IPAddress.Loopback, 0));
            IgnoreConnectionReset(loopback.Client);
            sockets.Add((loopback, new List<IPEndPoint> { new(IPAddress.Loopback, port) }));
        }
        catch (SocketException)
        {
        }

        using var stop = CancellationTokenSource.CreateLinkedTokenSource(ct);
        var receivers = sockets.Select(s => ReceiveLoopAsync(s.Client, found, gate, stop.Token)).ToList();

        var deadline = DateTime.UtcNow + timeout;
        DateTime? firstSeen = null;
        var nextSend = DateTime.MinValue;
        try
        {
            while (DateTime.UtcNow < deadline && !ct.IsCancellationRequested)
            {
                if (DateTime.UtcNow >= nextSend)
                {
                    foreach (var (client, targets) in sockets)
                    {
                        foreach (var target in targets)
                        {
                            try
                            {
                                await client.SendAsync(payload, payload.Length, target).ConfigureAwait(false);
                            }
                            catch (Exception ex) when (ex is SocketException or ObjectDisposedException)
                            {
                                // e.g. no route for broadcast on this interface
                            }
                        }
                    }
                    nextSend = DateTime.UtcNow + ResendInterval;
                }

                lock (gate)
                {
                    if (found.Count > 0) firstSeen ??= DateTime.UtcNow;
                }
                // After the first answer wait a little for other servers, then stop early.
                if (firstSeen != null && DateTime.UtcNow - firstSeen >= SettleTime) break;

                try
                {
                    await Task.Delay(100, ct).ConfigureAwait(false);
                }
                catch (OperationCanceledException)
                {
                    break;
                }
            }
        }
        finally
        {
            stop.Cancel();
            foreach (var (client, _) in sockets) client.Dispose();
            try
            {
                await Task.WhenAll(receivers).ConfigureAwait(false);
            }
            catch (Exception ex) when (ex is OperationCanceledException or ObjectDisposedException or SocketException)
            {
            }
        }

        lock (gate)
        {
            return Distinct(found.Values);
        }
    }

    /// <summary>
    /// One entry per server. A server that is reachable over several network adapters (or over
    /// loopback when the agent runs on the teacher PC) answers once per adapter; those answers
    /// carry the same instance id and are merged, preferring a real LAN address.
    /// </summary>
    public static List<ServerInfo> Distinct(IEnumerable<ServerInfo> answers)
    {
        var servers = answers
            .GroupBy(s => s.InstanceId.Length > 0 ? "id:" + s.InstanceId : "host:" + s.Key, StringComparer.Ordinal)
            .Select(group => group
                .OrderBy(s => IsLoopbackHost(s.Host) ? 1 : 0)
                .ThenBy(s => s.Host, StringComparer.Ordinal)
                .First())
            .ToList();
        // Answers without an id: drop a loopback duplicate of a LAN entry.
        servers.RemoveAll(s => IsLoopbackHost(s.Host) && servers.Any(o =>
            !IsLoopbackHost(o.Host) && o.Port == s.Port && o.SinifAdi == s.SinifAdi && o.OgretmenAdi == s.OgretmenAdi));
        return servers.OrderBy(s => s.SinifAdi, StringComparer.Ordinal).ThenBy(s => s.Host, StringComparer.Ordinal).ToList();
    }

    private static bool IsLoopbackHost(string host) =>
        IPAddress.TryParse(host, out var address) && IPAddress.IsLoopback(address);

    private static async Task ReceiveLoopAsync(UdpClient client, Dictionary<string, ServerInfo> found, object gate,
        CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            UdpReceiveResult result;
            try
            {
                result = await client.ReceiveAsync(ct).ConfigureAwait(false);
            }
            catch (SocketException ex) when (ex.SocketErrorCode == SocketError.ConnectionReset)
            {
                continue; // ICMP "port unreachable" from some host; keep listening
            }
            catch (Exception ex) when (ex is OperationCanceledException or ObjectDisposedException or SocketException)
            {
                return;
            }

            var server = Parse(result.Buffer, result.RemoteEndPoint);
            if (server == null) continue;
            lock (gate) found[server.Key] = server;
        }
    }

    /// <summary>Parses a discovery answer. The sender address is used as the host.</summary>
    public static ServerInfo? Parse(byte[] data, IPEndPoint sender)
    {
        try
        {
            var reply = JsonSerializer.Deserialize<DiscoveryReply>(data);
            if (reply == null || reply.Port is < 1 or > 65535) return null;
            if (string.IsNullOrWhiteSpace(reply.SinifAdi) && string.IsNullOrWhiteSpace(reply.OgretmenAdi)) return null;
            return new ServerInfo
            {
                // The address the answer really came from is always reachable from here.
                Host = sender.Address.ToString(),
                Port = reply.Port,
                InstanceId = (reply.Id ?? "").Trim(),
                SinifAdi = reply.SinifAdi.Trim(),
                OgretmenAdi = reply.OgretmenAdi.Trim(),
            };
        }
        catch (JsonException)
        {
            return null;
        }
    }

    /// <summary>IPv4 addresses of all active interfaces with their directed broadcast address.</summary>
    private static IEnumerable<(IPAddress Local, IPAddress? Broadcast)> LocalAddresses()
    {
        NetworkInterface[] interfaces;
        try
        {
            interfaces = NetworkInterface.GetAllNetworkInterfaces();
        }
        catch (NetworkInformationException)
        {
            yield break;
        }

        foreach (var nic in interfaces)
        {
            if (nic.OperationalStatus != OperationalStatus.Up) continue;
            if (nic.NetworkInterfaceType is NetworkInterfaceType.Loopback or NetworkInterfaceType.Tunnel) continue;

            UnicastIPAddressInformationCollection addresses;
            try
            {
                addresses = nic.GetIPProperties().UnicastAddresses;
            }
            catch (NetworkInformationException)
            {
                continue;
            }

            foreach (var address in addresses)
            {
                if (address.Address.AddressFamily != AddressFamily.InterNetwork) continue;
                if (IPAddress.IsLoopback(address.Address)) continue;
                yield return (address.Address, DirectedBroadcast(address));
            }
        }
    }

    private static IPAddress? DirectedBroadcast(UnicastIPAddressInformation info)
    {
        try
        {
            var ip = info.Address.GetAddressBytes();
            var mask = info.IPv4Mask?.GetAddressBytes();
            if (mask == null || mask.Length != 4 || mask.All(b => b == 0)) return null;
            var result = new byte[4];
            for (var i = 0; i < 4; i++) result[i] = (byte)(ip[i] | ~mask[i]);
            return new IPAddress(result);
        }
        catch (Exception ex) when (ex is PlatformNotSupportedException or NotImplementedException)
        {
            return null;
        }
    }

    /// <summary>
    /// Windows reports an ICMP "port unreachable" as a ConnectionReset on the next receive.
    /// Turn that off so one unreachable host cannot disturb discovery.
    /// </summary>
    private static void IgnoreConnectionReset(Socket socket)
    {
        if (!OperatingSystem.IsWindows()) return;
        try
        {
            const int SIO_UDP_CONNRESET = unchecked((int)0x9800000C);
            socket.IOControl(SIO_UDP_CONNRESET, new byte[] { 0, 0, 0, 0 }, null);
        }
        catch (Exception ex) when (ex is SocketException or NotSupportedException or InvalidOperationException)
        {
        }
    }
}
