using PhotoDedupe.Core;

namespace PhotoDedupe.Core.Tests;

public class DuplicateDetectorTests
{
    private readonly DuplicateDetector _detector = new();

    [Fact]
    public void DetectDuplicates_GroupsFilesWithMatchingSizeAndSha256()
    {
        var fingerprints = new List<FileFingerprint>
        {
            new() { FilePath = "a1.jpg", FileSize = 1000, Sha256 = "hash-a", IsVideo = false },
            new() { FilePath = "a2.jpg", FileSize = 1000, Sha256 = "hash-a", IsVideo = false },
            new() { FilePath = "b.jpg", FileSize = 1000, Sha256 = "hash-b", IsVideo = false },
        };

        var result = _detector.DetectDuplicates(fingerprints);

        var group = Assert.Single(result.ExactGroups);
        Assert.Equal(DuplicateGroupType.ExactMatch, group.Type);
        Assert.Equal(new[] { "a1.jpg", "a2.jpg" }, group.FilePaths.OrderBy(p => p));
    }

    [Fact]
    public void DetectDuplicates_DoesNotGroup_WhenSha256DiffersEvenIfSizeMatches()
    {
        var fingerprints = new List<FileFingerprint>
        {
            new() { FilePath = "a.jpg", FileSize = 1000, Sha256 = "hash-a", IsVideo = false },
            new() { FilePath = "b.jpg", FileSize = 1000, Sha256 = "hash-b", IsVideo = false },
        };

        var result = _detector.DetectDuplicates(fingerprints);

        Assert.Empty(result.ExactGroups);
    }

    [Fact]
    public void DetectDuplicates_UsesSizeAsPrefilter_SoIdenticalHashButDifferentSizeIsNotGrouped()
    {
        // In practice identical content implies identical size; this test proves the
        // detector explicitly gates exact-match comparison on file size before it will
        // even consider comparing SHA-256 values (the prefilter step in the design).
        var fingerprints = new List<FileFingerprint>
        {
            new() { FilePath = "a.jpg", FileSize = 1000, Sha256 = "same-hash", IsVideo = false },
            new() { FilePath = "b.jpg", FileSize = 2000, Sha256 = "same-hash", IsVideo = false },
        };

        var result = _detector.DetectDuplicates(fingerprints);

        Assert.Empty(result.ExactGroups);
    }

    [Fact]
    public void DetectDuplicates_GroupsSingleFiles_AreNotReportedAsDuplicates()
    {
        var fingerprints = new List<FileFingerprint>
        {
            new() { FilePath = "unique-a.jpg", FileSize = 500, Sha256 = "hash-a", IsVideo = false },
            new() { FilePath = "unique-b.jpg", FileSize = 600, Sha256 = "hash-b", IsVideo = false },
        };

        var result = _detector.DetectDuplicates(fingerprints);

        Assert.Empty(result.ExactGroups);
        Assert.Empty(result.SimilarGroups);
    }

    [Theory]
    [InlineData(SimilarityThreshold.Strict, 2, true)]
    [InlineData(SimilarityThreshold.Strict, 10, false)]
    [InlineData(SimilarityThreshold.Moderate, 8, true)]
    [InlineData(SimilarityThreshold.Moderate, 9, false)]
    [InlineData(SimilarityThreshold.Loose, 15, true)]
    [InlineData(SimilarityThreshold.Loose, 16, false)]
    public void DetectDuplicates_GroupsSimilarImages_BasedOnHammingDistanceThreshold(
        SimilarityThreshold threshold,
        int bitDifference,
        bool expectGrouped)
    {
        const ulong baseHash = 0UL;
        var otherHash = bitDifference == 64 ? ulong.MaxValue : (1UL << bitDifference) - 1; // sets `bitDifference` low bits

        var fingerprints = new List<FileFingerprint>
        {
            new() { FilePath = "img1.jpg", FileSize = 100, Sha256 = "h1", DHash = baseHash, IsVideo = false },
            new() { FilePath = "img2.jpg", FileSize = 200, Sha256 = "h2", DHash = otherHash, IsVideo = false },
        };

        var result = _detector.DetectDuplicates(fingerprints, threshold);

        if (expectGrouped)
        {
            var group = Assert.Single(result.SimilarGroups);
            Assert.Equal(DuplicateGroupType.SimilarImage, group.Type);
            Assert.Equal(2, group.FilePaths.Count);
        }
        else
        {
            Assert.Empty(result.SimilarGroups);
        }
    }

    [Fact]
    public void DetectDuplicates_Videos_AreOnlyComparedByExactSha256_NeverClusteredBySimilarity()
    {
        var fingerprints = new List<FileFingerprint>
        {
            new() { FilePath = "clip1.mp4", FileSize = 5000, Sha256 = "video-hash", DHash = null, IsVideo = true },
            new() { FilePath = "clip2.mp4", FileSize = 5000, Sha256 = "video-hash", DHash = null, IsVideo = true },
        };

        var result = _detector.DetectDuplicates(fingerprints, SimilarityThreshold.Loose);

        var exactGroup = Assert.Single(result.ExactGroups);
        Assert.Equal(2, exactGroup.FilePaths.Count);
        Assert.Empty(result.SimilarGroups);
    }

    [Fact]
    public void DetectDuplicates_VideosWithDifferentContent_AreNotGrouped()
    {
        var fingerprints = new List<FileFingerprint>
        {
            new() { FilePath = "clip1.mp4", FileSize = 5000, Sha256 = "hash-1", IsVideo = true },
            new() { FilePath = "clip2.mp4", FileSize = 5000, Sha256 = "hash-2", IsVideo = true },
        };

        var result = _detector.DetectDuplicates(fingerprints, SimilarityThreshold.Loose);

        Assert.Empty(result.ExactGroups);
        Assert.Empty(result.SimilarGroups);
    }

    [Fact]
    public void DetectDuplicates_ExactAndSimilarGroups_CanCoexistIndependently()
    {
        var fingerprints = new List<FileFingerprint>
        {
            // Exact duplicate pair. Uses a dHash far away (in Hamming distance) from the
            // similar-image pair below so the two clusters do not merge.
            new() { FilePath = "exact1.jpg", FileSize = 1000, Sha256 = "exact-hash", DHash = ulong.MaxValue, IsVideo = false },
            new() { FilePath = "exact2.jpg", FileSize = 1000, Sha256 = "exact-hash", DHash = ulong.MaxValue, IsVideo = false },

            // Separate similar-image pair (different size/hash from the exact pair and from
            // each other, but close dHash).
            new() { FilePath = "similarA.jpg", FileSize = 2000, Sha256 = "hash-a", DHash = 0b1111UL, IsVideo = false },
            new() { FilePath = "similarB.jpg", FileSize = 3000, Sha256 = "hash-b", DHash = 0b1110UL, IsVideo = false },
        };

        var result = _detector.DetectDuplicates(fingerprints, SimilarityThreshold.Moderate);

        Assert.Single(result.ExactGroups);
        Assert.Contains(result.SimilarGroups, g => g.FilePaths.Contains("similarA.jpg") && g.FilePaths.Contains("similarB.jpg"));
    }
}
