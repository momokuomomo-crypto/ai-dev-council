namespace PhotoDedupe.Core;

/// <summary>Progress update reported from the background pipeline to the UI thread.</summary>
public record PipelineProgress(string StageDescription, int Current, int Total);

/// <summary>
/// One duplicate group after the "move to duplicate-candidates folder" step: the file
/// that was left in place (the presumed original) and the files that were moved into the
/// duplicate-candidates folder awaiting human review.
/// </summary>
public record MovedDuplicateGroup(DuplicateGroupType Type, string KeptFilePath, List<string> MovedFilePaths);

/// <summary>Result of a full merge + duplicate-detection run, shown on the summary step.</summary>
public class PipelineSummary
{
    public PipelineSummary(
        int totalSourceFiles,
        int organizedFileCount,
        int unknownDateFileCount,
        int exactDuplicateGroupCount,
        int similarDuplicateGroupCount,
        string duplicateCandidatesFolder,
        List<MovedDuplicateGroup> duplicateGroups)
    {
        TotalSourceFiles = totalSourceFiles;
        OrganizedFileCount = organizedFileCount;
        UnknownDateFileCount = unknownDateFileCount;
        ExactDuplicateGroupCount = exactDuplicateGroupCount;
        SimilarDuplicateGroupCount = similarDuplicateGroupCount;
        DuplicateCandidatesFolder = duplicateCandidatesFolder;
        DuplicateGroups = duplicateGroups;
    }

    public int TotalSourceFiles { get; }

    public int OrganizedFileCount { get; }

    public int UnknownDateFileCount { get; }

    public int ExactDuplicateGroupCount { get; }

    public int SimilarDuplicateGroupCount { get; }

    public string DuplicateCandidatesFolder { get; }

    public List<MovedDuplicateGroup> DuplicateGroups { get; }
}

/// <summary>
/// Orchestrates the rest of PhotoDedupe.Core to (1) copy input files into the organized
/// output folder, (2) detect exact and similar duplicates among the organized files —
/// reusing cached SHA-256/dHash values from a previous run via <see cref="HashCacheStore"/>
/// whenever a file's size and last-write time have not changed, so rescanning a large,
/// mostly-unchanged library does not require rehashing everything — and (3) move all but
/// one file of each duplicate group into the "重複候補" folder so a human can review them
/// before anything is deleted. Lives in Core (not the WPF project) so it can be unit
/// tested without any UI dependency.
/// </summary>
public static class PipelineRunner
{
    private const string DuplicateCandidatesFolderName = "重複候補";

    /// <summary>
    /// File name of the SQLite cache database created inside each output folder.
    /// Leading dot keeps it out of the way in the organized photo folder listing.
    /// </summary>
    public const string CacheDatabaseFileName = ".photodedupe-cache.sqlite";

    public static PipelineSummary Run(
        IReadOnlyList<string> inputFolders,
        string outputFolder,
        DateFolderStrategy dateStrategy,
        SimilarityThreshold threshold,
        IProgress<PipelineProgress> progress,
        CancellationToken token)
    {
        var dateResolver = new ExifDateResolver();
        var organizer = new FileOrganizer(dateResolver);
        var hashService = new HashService();
        using var cache = new HashCacheStore(Path.Combine(outputFolder, CacheDatabaseFileName));

        return Run(inputFolders, outputFolder, dateStrategy, threshold, progress, token, organizer, hashService, cache);
    }

    /// <summary>
    /// Overload accepting pre-built dependencies (including the hash cache and, via
    /// <see cref="IHashService"/>, a fake in tests) so callers can inject test doubles
    /// without touching the SQLite-backed convenience overload above.
    /// </summary>
    public static PipelineSummary Run(
        IReadOnlyList<string> inputFolders,
        string outputFolder,
        DateFolderStrategy dateStrategy,
        SimilarityThreshold threshold,
        IProgress<PipelineProgress> progress,
        CancellationToken token,
        FileOrganizer organizer,
        IHashService hashService,
        HashCacheStore cache)
    {
        var detector = new DuplicateDetector();

        progress.Report(new PipelineProgress("入力フォルダをスキャンしています...", 0, 0));

        var sourceFiles = inputFolders
            .Where(Directory.Exists)
            .SelectMany(folder => Directory.EnumerateFiles(folder, "*", SearchOption.AllDirectories))
            .Where(f => HashService.IsImageFile(f) || HashService.IsVideoFile(f))
            .Distinct()
            .ToList();

        token.ThrowIfCancellationRequested();

        var organizedPaths = new List<string>();
        var unknownDateCount = 0;
        for (var i = 0; i < sourceFiles.Count; i++)
        {
            token.ThrowIfCancellationRequested();

            foreach (var organizedResult in organizer.Organize(new[] { sourceFiles[i] }, outputFolder, dateStrategy))
            {
                organizedPaths.Add(organizedResult.DestinationPath);
                if (organizedResult.IsUnknownDate)
                {
                    unknownDateCount++;
                }
            }

            progress.Report(new PipelineProgress("写真・動画を統合しています...", i + 1, sourceFiles.Count));
        }

        token.ThrowIfCancellationRequested();

        var fingerprints = BuildFingerprints(organizedPaths, hashService, cache, progress, token);
        cache.RemoveMissingFiles(organizedPaths);

        var detection = detector.DetectDuplicates(fingerprints, threshold);

        var duplicateFolder = Path.Combine(outputFolder, DuplicateCandidatesFolderName);
        Directory.CreateDirectory(duplicateFolder);

        var allGroups = detection.ExactGroups.Concat(detection.SimilarGroups).ToList();
        var movedGroups = new List<MovedDuplicateGroup>();

        for (var i = 0; i < allGroups.Count; i++)
        {
            token.ThrowIfCancellationRequested();
            var group = allGroups[i];

            // Keep the first file where it is (treated as the "original"); move the rest
            // into the duplicate-candidates folder for human review before deletion.
            var keptFile = group.FilePaths[0];
            var movedFiles = new List<string>();
            foreach (var filePath in group.FilePaths.Skip(1))
            {
                var destination = GetUniqueDestination(duplicateFolder, Path.GetFileName(filePath));
                File.Move(filePath, destination);
                movedFiles.Add(destination);
            }

            if (movedFiles.Count > 0)
            {
                movedGroups.Add(new MovedDuplicateGroup(group.Type, keptFile, movedFiles));
            }

            progress.Report(new PipelineProgress("重複候補フォルダへ移動しています...", i + 1, allGroups.Count));
        }

        return new PipelineSummary(
            sourceFiles.Count,
            organizedPaths.Count,
            unknownDateCount,
            detection.ExactGroups.Count,
            detection.SimilarGroups.Count,
            duplicateFolder,
            movedGroups);
    }

    /// <summary>
    /// Builds a fingerprint for each organized file, reusing a cached SHA-256/dHash when
    /// the file's size and last-write time still match what was recorded on a previous
    /// run (incremental scan), and computing + caching fresh values otherwise.
    /// Public (rather than the more encapsulated `private`) specifically so tests can
    /// call it directly across two separate invocations sharing one <see cref="HashCacheStore"/>
    /// and assert that the second invocation does not recompute hashes for unchanged files.
    /// </summary>
    public static List<FileFingerprint> BuildFingerprints(
        IReadOnlyList<string> filePaths,
        IHashService hashService,
        HashCacheStore cache,
        IProgress<PipelineProgress> progress,
        CancellationToken token)
    {
        var fingerprints = new List<FileFingerprint>();
        for (var i = 0; i < filePaths.Count; i++)
        {
            token.ThrowIfCancellationRequested();

            var path = filePaths[i];
            var isVideo = HashService.IsVideoFile(path);
            var isImage = HashService.IsImageFile(path);
            var fileInfo = new FileInfo(path);
            var lastWriteUtc = fileInfo.LastWriteTimeUtc;

            var cached = cache.TryGet(path);
            string sha256;
            ulong? dHash;
            if (cached is not null
                && cached.Sha256 is not null
                && HashCacheStore.IsUpToDate(cached, fileInfo.Length, lastWriteUtc))
            {
                sha256 = cached.Sha256;
                dHash = cached.DHash;
            }
            else
            {
                sha256 = hashService.ComputeSha256(path);
                dHash = isImage ? hashService.ComputeDHash(path) : null;
                cache.Upsert(new FileHashCacheEntry
                {
                    FilePath = path,
                    FileSize = fileInfo.Length,
                    LastWriteTimeUtc = lastWriteUtc,
                    Sha256 = sha256,
                    DHash = dHash,
                });
            }

            fingerprints.Add(new FileFingerprint
            {
                FilePath = path,
                FileSize = fileInfo.Length,
                IsVideo = isVideo,
                Sha256 = sha256,
                DHash = dHash,
            });

            progress.Report(new PipelineProgress("重複判定用のハッシュを計算しています...", i + 1, filePaths.Count));
        }

        return fingerprints;
    }

    private static string GetUniqueDestination(string folder, string fileName)
    {
        var destination = Path.Combine(folder, fileName);
        if (!File.Exists(destination))
        {
            return destination;
        }

        var nameWithoutExtension = Path.GetFileNameWithoutExtension(fileName);
        var extension = Path.GetExtension(fileName);
        var counter = 1;
        string candidate;
        do
        {
            candidate = Path.Combine(folder, $"{nameWithoutExtension}_{counter}{extension}");
            counter++;
        }
        while (File.Exists(candidate));

        return candidate;
    }
}
