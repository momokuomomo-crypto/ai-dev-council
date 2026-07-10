namespace PhotoDedupe.Core;

/// <summary>
/// Similarity thresholds selectable from the UI. The numeric value is the maximum
/// Hamming distance (out of 64 bits) between two dHash values for the images to be
/// considered "similar". Smaller values are stricter (fewer, more confident matches).
/// </summary>
public enum SimilarityThreshold
{
    Strict = 3,
    Moderate = 8,
    Loose = 15,
}

public enum DuplicateGroupType
{
    ExactMatch,
    SimilarImage,
}

/// <summary>
/// A lightweight, already-computed fingerprint of a file. Kept separate from any I/O so
/// that <see cref="DuplicateDetector"/>'s grouping logic can be unit tested without real
/// files or hash computation.
/// </summary>
public class FileFingerprint
{
    public required string FilePath { get; init; }

    public long FileSize { get; init; }

    public string? Sha256 { get; set; }

    /// <summary>Null for videos, or for images whose dHash has not been computed.</summary>
    public ulong? DHash { get; set; }

    public bool IsVideo { get; init; }
}

public class DuplicateGroup
{
    public required DuplicateGroupType Type { get; init; }

    public List<string> FilePaths { get; init; } = new();
}

public class DuplicateDetectionResult
{
    public List<DuplicateGroup> ExactGroups { get; } = new();

    public List<DuplicateGroup> SimilarGroups { get; } = new();
}

/// <summary>
/// Groups a set of files into exact-match duplicates (SHA-256, prefiltered by file size)
/// and near-duplicate image clusters (dHash Hamming distance). Videos only ever
/// participate in exact-match grouping.
/// </summary>
public class DuplicateDetector
{
    /// <summary>
    /// Groups already-computed fingerprints. This is the core, side-effect-free logic.
    /// </summary>
    public DuplicateDetectionResult DetectDuplicates(
        IReadOnlyList<FileFingerprint> fingerprints,
        SimilarityThreshold threshold = SimilarityThreshold.Moderate)
    {
        var result = new DuplicateDetectionResult();

        // Exact match: prefilter by file size, then confirm with SHA-256.
        var sizeGroups = fingerprints.GroupBy(f => f.FileSize).Where(g => g.Count() > 1);
        foreach (var sizeGroup in sizeGroups)
        {
            var hashGroups = sizeGroup
                .Where(f => f.Sha256 is not null)
                .GroupBy(f => f.Sha256, StringComparer.OrdinalIgnoreCase)
                .Where(g => g.Count() > 1);

            foreach (var hashGroup in hashGroups)
            {
                result.ExactGroups.Add(new DuplicateGroup
                {
                    Type = DuplicateGroupType.ExactMatch,
                    FilePaths = hashGroup.Select(f => f.FilePath).ToList(),
                });
            }
        }

        // Similar images: videos are excluded entirely (SHA-256 only, no dHash clustering).
        var imageCandidates = fingerprints.Where(f => !f.IsVideo && f.DHash.HasValue).ToList();
        var clusters = ClusterBySimilarity(imageCandidates, (int)threshold);
        foreach (var cluster in clusters.Where(c => c.Count > 1))
        {
            result.SimilarGroups.Add(new DuplicateGroup
            {
                Type = DuplicateGroupType.SimilarImage,
                FilePaths = cluster.Select(f => f.FilePath).ToList(),
            });
        }

        return result;
    }

    /// <summary>
    /// Convenience overload that computes fingerprints for real files on disk using the
    /// supplied <see cref="IHashService"/>, then delegates to the core grouping logic.
    /// </summary>
    public DuplicateDetectionResult DetectDuplicates(
        IEnumerable<string> filePaths,
        IHashService hashService,
        SimilarityThreshold threshold = SimilarityThreshold.Moderate)
    {
        var fingerprints = new List<FileFingerprint>();
        foreach (var path in filePaths)
        {
            var isVideo = HashService.IsVideoFile(path);
            var isImage = HashService.IsImageFile(path);
            var fileInfo = new FileInfo(path);

            fingerprints.Add(new FileFingerprint
            {
                FilePath = path,
                FileSize = fileInfo.Length,
                IsVideo = isVideo,
                Sha256 = hashService.ComputeSha256(path),
                DHash = isImage ? hashService.ComputeDHash(path) : null,
            });
        }

        return DetectDuplicates(fingerprints, threshold);
    }

    /// <summary>
    /// Clusters fingerprints using union-find: any two images whose dHash Hamming distance
    /// is within the threshold are merged into the same cluster (distance is not
    /// necessarily transitive, so a cluster may include images that are only linked via
    /// one or more intermediate images).
    /// </summary>
    private static List<List<FileFingerprint>> ClusterBySimilarity(
        IReadOnlyList<FileFingerprint> candidates,
        int maxDistance)
    {
        var count = candidates.Count;
        var parent = Enumerable.Range(0, count).ToArray();

        int Find(int x)
        {
            while (parent[x] != x)
            {
                parent[x] = parent[parent[x]];
                x = parent[x];
            }

            return x;
        }

        void Union(int a, int b)
        {
            var rootA = Find(a);
            var rootB = Find(b);
            if (rootA != rootB)
            {
                parent[rootA] = rootB;
            }
        }

        for (var i = 0; i < count; i++)
        {
            for (var j = i + 1; j < count; j++)
            {
                var distance = HashService.HammingDistance(candidates[i].DHash!.Value, candidates[j].DHash!.Value);
                if (distance <= maxDistance)
                {
                    Union(i, j);
                }
            }
        }

        var clusters = new Dictionary<int, List<FileFingerprint>>();
        for (var i = 0; i < count; i++)
        {
            var root = Find(i);
            if (!clusters.TryGetValue(root, out var list))
            {
                list = new List<FileFingerprint>();
                clusters[root] = list;
            }

            list.Add(candidates[i]);
        }

        return clusters.Values.ToList();
    }
}
