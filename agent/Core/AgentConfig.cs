using System.Text.Json;
using System.Text.Json.Serialization;

namespace SinavAjan.Core;

/// <summary>
/// agent.json, read from the folder that contains the agent executable.
/// It deliberately has NO server address: the server is discovered on every start.
/// </summary>
public sealed class AgentConfig
{
    [JsonPropertyName("discovery_port")] public int DiscoveryPort { get; set; } = 47000;
    [JsonPropertyName("stream")] public StreamConfig Stream { get; set; } = new();

    public static AgentConfig Load(string directory)
    {
        var path = Path.Combine(directory, "agent.json");
        try
        {
            if (File.Exists(path))
            {
                var options = new JsonSerializerOptions
                {
                    ReadCommentHandling = JsonCommentHandling.Skip,
                    AllowTrailingCommas = true,
                };
                var config = JsonSerializer.Deserialize<AgentConfig>(File.ReadAllText(path), options);
                if (config != null)
                {
                    config.Normalise();
                    return config;
                }
            }
        }
        catch (Exception ex) when (ex is IOException or JsonException or UnauthorizedAccessException)
        {
            LocalLog.Write($"agent.json okunamadı, varsayılanlar kullanılıyor: {ex.Message}");
        }
        return new AgentConfig();
    }

    private void Normalise()
    {
        if (DiscoveryPort is < 1 or > 65535) DiscoveryPort = 47000;
        Stream ??= new StreamConfig();
        Stream.Fps = Math.Clamp(Stream.Fps, 1, 30);
        Stream.Width = Math.Clamp(Stream.Width, 320, 3840);
        Stream.BitrateKbps = Math.Clamp(Stream.BitrateKbps, 50, 8000);
    }
}

public sealed class StreamConfig
{
    [JsonPropertyName("user")] public string User { get; set; } = "sinavajan";
    [JsonPropertyName("pass")] public string Pass { get; set; } = "sinav-yayin-2026";
    [JsonPropertyName("fps")] public int Fps { get; set; } = 5;
    [JsonPropertyName("width")] public int Width { get; set; } = 1280;
    [JsonPropertyName("bitrate_kbps")] public int BitrateKbps { get; set; } = 500;
}
