using System.Net;
using System.Net.NetworkInformation;
using System.Net.Sockets;
using System.Security.Cryptography;

namespace SinavAjan.Core;

public static class NetInfo
{
    /// <summary>
    /// MAC address (AA:BB:CC:DD:EE:FF) of the network adapter that is used to reach the
    /// server; on a student laptop that is the Wi-Fi adapter. Empty when unknown.
    /// </summary>
    public static string MacAddressFor(string serverHost)
    {
        try
        {
            if (!IPAddress.TryParse(serverHost, out var server)) return "";
            IPAddress local;
            using (var probe = new Socket(server.AddressFamily, SocketType.Dgram, ProtocolType.Udp))
            {
                probe.Connect(server, 9); // UDP connect sends nothing; it only selects the route
                local = ((IPEndPoint)probe.LocalEndPoint!).Address;
            }

            foreach (var nic in NetworkInterface.GetAllNetworkInterfaces())
            {
                if (!nic.GetIPProperties().UnicastAddresses.Any(a => a.Address.Equals(local))) continue;
                var bytes = nic.GetPhysicalAddress().GetAddressBytes();
                if (bytes.Length != 6 || bytes.All(b => b == 0)) return "";
                return string.Join(':', bytes.Select(b => b.ToString("X2")));
            }
        }
        catch (Exception ex) when (ex is SocketException or NetworkInformationException or InvalidOperationException)
        {
            LocalLog.Write($"MAC adresi okunamadı: {ex.Message}");
        }
        return "";
    }

    public static string Sha256Hex(byte[] data) => Convert.ToHexString(SHA256.HashData(data)).ToLowerInvariant();

    public static double UnixNow() => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0;
}
