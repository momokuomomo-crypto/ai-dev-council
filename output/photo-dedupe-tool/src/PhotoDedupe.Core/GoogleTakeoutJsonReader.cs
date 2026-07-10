using System.Text.Json;

namespace PhotoDedupe.Core;

/// <summary>
/// Reads Google Takeout JSON sidecar files (e.g. "IMG_0001.jpg.json") and extracts
/// the "photoTakenTime.timestamp" value which represents the original capture time
/// as recorded by Google Photos.
/// </summary>
public class GoogleTakeoutJsonReader
{
    /// <summary>
    /// Attempts to locate the Google Takeout JSON sidecar file for a given media file.
    /// Takeout historically names sidecars "&lt;original file name&gt;.json" and, in newer
    /// exports, "&lt;original file name&gt;.supplemental-metadata.json". Both are checked.
    /// </summary>
    public static string? FindSidecarPath(string mediaFilePath)
    {
        if (string.IsNullOrWhiteSpace(mediaFilePath))
        {
            return null;
        }

        var candidates = new[]
        {
            mediaFilePath + ".json",
            mediaFilePath + ".supplemental-metadata.json",
        };

        foreach (var candidate in candidates)
        {
            if (File.Exists(candidate))
            {
                return candidate;
            }
        }

        return null;
    }

    /// <summary>
    /// Reads the photoTakenTime.timestamp field (Unix epoch seconds, UTC) from a Google
    /// Takeout JSON sidecar file and returns it as a UTC <see cref="DateTime"/>.
    /// Returns null if the file does not exist, is not valid JSON, or does not contain
    /// a usable photoTakenTime value.
    /// </summary>
    public DateTime? ReadPhotoTakenTime(string jsonFilePath)
    {
        if (string.IsNullOrWhiteSpace(jsonFilePath) || !File.Exists(jsonFilePath))
        {
            return null;
        }

        try
        {
            using var stream = File.OpenRead(jsonFilePath);
            return ReadPhotoTakenTime(stream);
        }
        catch (JsonException)
        {
            return null;
        }
        catch (IOException)
        {
            return null;
        }
    }

    /// <summary>
    /// Reads the photoTakenTime.timestamp field from a JSON stream. Exposed for testing
    /// without requiring a file on disk.
    /// </summary>
    public DateTime? ReadPhotoTakenTime(Stream jsonStream)
    {
        using var document = JsonDocument.Parse(jsonStream);
        return ReadPhotoTakenTime(document.RootElement);
    }

    /// <summary>
    /// Extracts the photoTakenTime timestamp from an already-parsed JSON root element.
    /// </summary>
    public DateTime? ReadPhotoTakenTime(JsonElement root)
    {
        if (root.ValueKind != JsonValueKind.Object)
        {
            return null;
        }

        if (!root.TryGetProperty("photoTakenTime", out var photoTakenTime) ||
            photoTakenTime.ValueKind != JsonValueKind.Object)
        {
            return null;
        }

        if (!photoTakenTime.TryGetProperty("timestamp", out var timestampElement))
        {
            return null;
        }

        long timestampSeconds;
        if (timestampElement.ValueKind == JsonValueKind.String)
        {
            if (!long.TryParse(timestampElement.GetString(), out timestampSeconds))
            {
                return null;
            }
        }
        else if (timestampElement.ValueKind == JsonValueKind.Number)
        {
            if (!timestampElement.TryGetInt64(out timestampSeconds))
            {
                return null;
            }
        }
        else
        {
            return null;
        }

        return DateTimeOffset.FromUnixTimeSeconds(timestampSeconds).UtcDateTime;
    }
}
