using PhotoDedupe.Core;

namespace PhotoDedupe.Core.Tests;

/// <summary>
/// Verifies that <see cref="PipelineRunner.BuildFingerprints"/> actually reuses cached
/// hashes on a rescan (rather than recomputing every file every time), which is the
/// requirement flagged as missing in the initial implementation's review.
/// </summary>
public class PipelineRunnerCacheTests : IDisposable
{
    private readonly string _tempDirectory;
    private readonly string _cacheDbPath;

    public PipelineRunnerCacheTests()
    {
        _tempDirectory = Path.Combine(Path.GetTempPath(), "PhotoDedupeCacheTests_" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_tempDirectory);
        _cacheDbPath = Path.Combine(_tempDirectory, "cache.sqlite");
    }

    public void Dispose()
    {
        // Microsoft.Data.Sqlite pools connections by default, which can keep a file handle
        // open briefly after HashCacheStore.Dispose() returns; clear the pool so the temp
        // directory can actually be deleted below.
        Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();

        if (Directory.Exists(_tempDirectory))
        {
            Directory.Delete(_tempDirectory, recursive: true);
        }
    }

    [Fact]
    public void BuildFingerprints_SecondRunWithUnchangedFiles_DoesNotRecomputeHashes()
    {
        var fileA = Path.Combine(_tempDirectory, "a.jpg");
        var fileB = Path.Combine(_tempDirectory, "b.jpg");
        File.WriteAllBytes(fileA, new byte[] { 1, 2, 3 });
        File.WriteAllBytes(fileB, new byte[] { 4, 5, 6 });
        var files = new[] { fileA, fileB };

        var fakeHashService = new CountingFakeHashService();
        using var cache = new HashCacheStore(_cacheDbPath);
        var noopProgress = new Progress<PipelineProgress>();

        var firstRun = PipelineRunner.BuildFingerprints(files, fakeHashService, cache, noopProgress, CancellationToken.None);
        Assert.Equal(2, firstRun.Count);
        Assert.Equal(1, fakeHashService.Sha256CallCount(fileA));
        Assert.Equal(1, fakeHashService.Sha256CallCount(fileB));

        // Second scan over the same, unchanged files: cached values should be reused, so
        // the hash service must not be invoked again for either file.
        var secondRun = PipelineRunner.BuildFingerprints(files, fakeHashService, cache, noopProgress, CancellationToken.None);
        Assert.Equal(2, secondRun.Count);
        Assert.Equal(1, fakeHashService.Sha256CallCount(fileA));
        Assert.Equal(1, fakeHashService.Sha256CallCount(fileB));

        // The reused fingerprint's hash value should still match what was originally computed.
        Assert.Equal(firstRun[0].Sha256, secondRun[0].Sha256);
        Assert.Equal(firstRun[1].Sha256, secondRun[1].Sha256);
    }

    [Fact]
    public void BuildFingerprints_ModifiedFile_RecomputesOnlyThatFile()
    {
        var fileA = Path.Combine(_tempDirectory, "a.jpg");
        var fileB = Path.Combine(_tempDirectory, "b.jpg");
        File.WriteAllBytes(fileA, new byte[] { 1, 2, 3 });
        File.WriteAllBytes(fileB, new byte[] { 4, 5, 6 });
        var files = new[] { fileA, fileB };

        var fakeHashService = new CountingFakeHashService();
        using var cache = new HashCacheStore(_cacheDbPath);
        var noopProgress = new Progress<PipelineProgress>();

        PipelineRunner.BuildFingerprints(files, fakeHashService, cache, noopProgress, CancellationToken.None);

        // Modify only fileA's content (changes size and last-write time).
        Thread.Sleep(10);
        File.WriteAllBytes(fileA, new byte[] { 9, 9, 9, 9 });

        PipelineRunner.BuildFingerprints(files, fakeHashService, cache, noopProgress, CancellationToken.None);

        Assert.Equal(2, fakeHashService.Sha256CallCount(fileA)); // recomputed
        Assert.Equal(1, fakeHashService.Sha256CallCount(fileB)); // still cached
    }

    /// <summary>Fake <see cref="IHashService"/> that counts calls per file path instead of
    /// doing real (and, for dHash, image-decoding-dependent) work.</summary>
    private class CountingFakeHashService : IHashService
    {
        private readonly Dictionary<string, int> _sha256Calls = new();

        public int Sha256CallCount(string path) => _sha256Calls.GetValueOrDefault(path, 0);

        public string ComputeSha256(string filePath)
        {
            _sha256Calls[filePath] = _sha256Calls.GetValueOrDefault(filePath, 0) + 1;
            using var stream = File.OpenRead(filePath);
            return Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(stream)).ToLowerInvariant();
        }

        public ulong ComputeDHash(string imagePath) => 0UL;
    }
}
