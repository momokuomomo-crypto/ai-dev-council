using PhotoDedupe.Core;
using SixLabors.ImageSharp;
using SixLabors.ImageSharp.PixelFormats;

namespace PhotoDedupe.Core.Tests;

public class HashServiceTests : IDisposable
{
    private readonly string _tempDirectory;
    private readonly HashService _hashService = new();

    public HashServiceTests()
    {
        _tempDirectory = Path.Combine(Path.GetTempPath(), "PhotoDedupeTests_" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_tempDirectory);
    }

    public void Dispose()
    {
        if (Directory.Exists(_tempDirectory))
        {
            Directory.Delete(_tempDirectory, recursive: true);
        }
    }

    // --- SHA-256 --------------------------------------------------------------------------

    [Fact]
    public void ComputeSha256_SameContent_ProducesSameHash()
    {
        var path1 = Path.Combine(_tempDirectory, "a.bin");
        var path2 = Path.Combine(_tempDirectory, "b.bin");
        var content = new byte[] { 1, 2, 3, 4, 5, 6, 7, 8 };
        File.WriteAllBytes(path1, content);
        File.WriteAllBytes(path2, content);

        var hash1 = _hashService.ComputeSha256(path1);
        var hash2 = _hashService.ComputeSha256(path2);

        Assert.Equal(hash1, hash2);
    }

    [Fact]
    public void ComputeSha256_DifferentContent_ProducesDifferentHash()
    {
        var path1 = Path.Combine(_tempDirectory, "a.bin");
        var path2 = Path.Combine(_tempDirectory, "b.bin");
        File.WriteAllBytes(path1, new byte[] { 1, 2, 3 });
        File.WriteAllBytes(path2, new byte[] { 9, 9, 9 });

        var hash1 = _hashService.ComputeSha256(path1);
        var hash2 = _hashService.ComputeSha256(path2);

        Assert.NotEqual(hash1, hash2);
    }

    [Fact]
    public void ComputeSha256_KnownContent_MatchesExpectedDigest()
    {
        // SHA-256("hello world") is a well-known value, used as a sanity check that the
        // implementation is a standard, unmodified SHA-256.
        var path = Path.Combine(_tempDirectory, "hello.txt");
        File.WriteAllText(path, "hello world");

        var hash = _hashService.ComputeSha256(path);

        Assert.Equal("b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9", hash);
    }

    // --- dHash -----------------------------------------------------------------------------

    [Fact]
    public void ComputeDHash_IdenticalImages_ProduceSameHash()
    {
        var path1 = Path.Combine(_tempDirectory, "gradient1.png");
        var path2 = Path.Combine(_tempDirectory, "gradient2.png");
        CreateHorizontalGradient(path1, darkToLight: true);
        CreateHorizontalGradient(path2, darkToLight: true);

        var hash1 = _hashService.ComputeDHash(path1);
        var hash2 = _hashService.ComputeDHash(path2);

        Assert.Equal(hash1, hash2);
    }

    [Fact]
    public void ComputeDHash_VisuallyDifferentImages_ProduceDifferentHash()
    {
        var lightIncreasing = Path.Combine(_tempDirectory, "increasing.png");
        var lightDecreasing = Path.Combine(_tempDirectory, "decreasing.png");
        CreateHorizontalGradient(lightIncreasing, darkToLight: true);
        CreateHorizontalGradient(lightDecreasing, darkToLight: false);

        var hash1 = _hashService.ComputeDHash(lightIncreasing);
        var hash2 = _hashService.ComputeDHash(lightDecreasing);

        Assert.NotEqual(hash1, hash2);
        // The two gradients run in opposite directions, so essentially every bit should flip.
        Assert.True(HashService.HammingDistance(hash1, hash2) > 32);
    }

    // --- Hamming distance -------------------------------------------------------------------

    [Fact]
    public void HammingDistance_IdenticalHashes_IsZero()
    {
        const ulong value = 0xABCD1234_5678EF01;

        Assert.Equal(0, HashService.HammingDistance(value, value));
    }

    [Theory]
    [InlineData(0UL, 0b1UL, 1)]
    [InlineData(0UL, 0b1011UL, 3)]
    [InlineData(0xFFFF_FFFF_FFFF_FFFFUL, 0UL, 64)]
    public void HammingDistance_CountsDifferingBits(ulong a, ulong b, int expectedDistance)
    {
        Assert.Equal(expectedDistance, HashService.HammingDistance(a, b));
    }

    [Fact]
    public void HammingDistance_RespectsSimilarityThresholdBoundaries()
    {
        const ulong baseHash = 0UL;
        var closeHash = 0b111UL; // 3 bits different
        var farHash = 0xFFFFUL; // 16 bits different

        var closeDistance = HashService.HammingDistance(baseHash, closeHash);
        var farDistance = HashService.HammingDistance(baseHash, farHash);

        Assert.True(closeDistance <= (int)SimilarityThreshold.Strict);
        Assert.True(farDistance > (int)SimilarityThreshold.Loose);
    }

    // --- File-type classification ------------------------------------------------------------

    [Theory]
    [InlineData("photo.jpg", true)]
    [InlineData("photo.JPEG", true)]
    [InlineData("photo.png", true)]
    [InlineData("photo.heic", true)]
    [InlineData("video.mp4", false)]
    [InlineData("notes.txt", false)]
    public void IsImageFile_ClassifiesByExtension(string fileName, bool expected)
    {
        Assert.Equal(expected, HashService.IsImageFile(fileName));
    }

    [Theory]
    [InlineData("video.mp4", true)]
    [InlineData("video.MOV", true)]
    [InlineData("clip.avi", true)]
    [InlineData("photo.jpg", false)]
    [InlineData("notes.txt", false)]
    public void IsVideoFile_ClassifiesByExtension(string fileName, bool expected)
    {
        Assert.Equal(expected, HashService.IsVideoFile(fileName));
    }

    private static void CreateHorizontalGradient(string path, bool darkToLight)
    {
        const int width = 32;
        const int height = 32;
        using var image = new Image<L8>(width, height);

        for (var y = 0; y < height; y++)
        {
            for (var x = 0; x < width; x++)
            {
                var ratio = (double)x / (width - 1);
                if (!darkToLight)
                {
                    ratio = 1 - ratio;
                }

                var value = (byte)Math.Round(ratio * 255);
                image[x, y] = new L8(value);
            }
        }

        image.SaveAsPng(path);
    }
}
