using System.Numerics;
using System.Security.Cryptography;
using SixLabors.ImageSharp;
using SixLabors.ImageSharp.PixelFormats;
using SixLabors.ImageSharp.Processing;

namespace PhotoDedupe.Core;

/// <summary>
/// Computes content hashes used for duplicate detection:
/// - SHA-256 for exact-match comparison (images and videos)
/// - dHash (difference hash) for near-duplicate image comparison
/// </summary>
public interface IHashService
{
    string ComputeSha256(string filePath);

    ulong ComputeDHash(string imagePath);
}

public class HashService : IHashService
{
    /// <summary>
    /// Width/height used to build the dHash: the image is shrunk to 9x8 grayscale pixels
    /// so that each of the 8 rows yields 8 "is left pixel brighter than right" bits,
    /// producing a 64-bit hash.
    /// </summary>
    private const int DHashWidth = 9;
    private const int DHashHeight = 8;

    private static readonly HashSet<string> ImageExtensions = new(StringComparer.OrdinalIgnoreCase)
    {
        ".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff", ".heic", ".heif",
    };

    private static readonly HashSet<string> VideoExtensions = new(StringComparer.OrdinalIgnoreCase)
    {
        ".mp4", ".mov", ".avi", ".mkv", ".m4v", ".3gp", ".wmv", ".mpg", ".mpeg",
    };

    public static bool IsImageFile(string filePath) => ImageExtensions.Contains(Path.GetExtension(filePath));

    public static bool IsVideoFile(string filePath) => VideoExtensions.Contains(Path.GetExtension(filePath));

    /// <summary>
    /// Computes the SHA-256 hash of the file content, returned as a lowercase hex string.
    /// Used for exact-match detection for both images and videos.
    /// </summary>
    public string ComputeSha256(string filePath)
    {
        using var stream = File.OpenRead(filePath);
        return ComputeSha256(stream);
    }

    /// <summary>
    /// Computes the SHA-256 hash of a stream's content. Exposed to allow testing without
    /// requiring a file on disk.
    /// </summary>
    public string ComputeSha256(Stream content)
    {
        var hashBytes = SHA256.HashData(content);
        return Convert.ToHexString(hashBytes).ToLowerInvariant();
    }

    /// <summary>
    /// Computes the 64-bit dHash of an image file. Not applicable to videos.
    /// </summary>
    public ulong ComputeDHash(string imagePath)
    {
        using var image = Image.Load<L8>(imagePath);
        return ComputeDHash(image);
    }

    /// <summary>
    /// Computes the 64-bit dHash directly from a loaded grayscale image. Exposed to allow
    /// testing without requiring a file on disk.
    /// </summary>
    public ulong ComputeDHash(Image<L8> image)
    {
        using var resized = image.Clone(ctx => ctx.Resize(new ResizeOptions
        {
            Size = new Size(DHashWidth, DHashHeight),
            Mode = ResizeMode.Stretch,
            Sampler = KnownResamplers.Bicubic,
        }));

        ulong hash = 0;
        var bitIndex = 0;
        for (var y = 0; y < DHashHeight; y++)
        {
            for (var x = 0; x < DHashWidth - 1; x++)
            {
                var left = resized[x, y].PackedValue;
                var right = resized[x + 1, y].PackedValue;
                if (left > right)
                {
                    hash |= 1UL << bitIndex;
                }

                bitIndex++;
            }
        }

        return hash;
    }

    /// <summary>
    /// Computes the Hamming distance (number of differing bits) between two dHash values.
    /// A smaller distance means the images are more visually similar.
    /// </summary>
    public static int HammingDistance(ulong a, ulong b)
    {
        return BitOperations.PopCount(a ^ b);
    }
}
