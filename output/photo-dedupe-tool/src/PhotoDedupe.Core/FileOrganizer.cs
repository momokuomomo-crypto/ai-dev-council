namespace PhotoDedupe.Core;

/// <summary>
/// Folder layout strategy used when files are copied into the unified output folder.
/// </summary>
public enum DateFolderStrategy
{
    YearOnly,
    YearMonth,
}

public class OrganizedFileResult
{
    public required string SourcePath { get; init; }

    public required string DestinationPath { get; init; }

    public bool IsUnknownDate { get; init; }
}

/// <summary>
/// Resolves each source file's capture date, decides which year / year-month folder it
/// belongs in (or quarantines it to an "unknown date" folder), and copies it into the
/// unified output folder. Source files are never modified or deleted.
/// </summary>
public class FileOrganizer
{
    public const string UnknownDateFolderName = "不明な日付";

    private readonly IExifDateResolver _dateResolver;

    public FileOrganizer(IExifDateResolver dateResolver)
    {
        _dateResolver = dateResolver;
    }

    /// <summary>
    /// Builds the folder name (relative to the output root) for a given resolved date and
    /// strategy. A null date always maps to the unknown-date quarantine folder.
    /// </summary>
    public static string BuildRelativeFolder(DateTime? date, DateFolderStrategy strategy)
    {
        if (date is null)
        {
            return UnknownDateFolderName;
        }

        return strategy switch
        {
            DateFolderStrategy.YearOnly => date.Value.Year.ToString("D4"),
            DateFolderStrategy.YearMonth => Path.Combine(date.Value.Year.ToString("D4"), date.Value.Month.ToString("D2")),
            _ => UnknownDateFolderName,
        };
    }

    /// <summary>
    /// Copies each source file into <paramref name="outputRoot"/>, organized into
    /// year/year-month subfolders (or the unknown-date folder). Existing source files are
    /// left untouched. Filename collisions in the destination folder are resolved by
    /// appending a numeric suffix.
    /// </summary>
    public List<OrganizedFileResult> Organize(
        IEnumerable<string> sourceFiles,
        string outputRoot,
        DateFolderStrategy strategy = DateFolderStrategy.YearMonth)
    {
        var results = new List<OrganizedFileResult>();

        foreach (var sourcePath in sourceFiles)
        {
            var date = _dateResolver.ResolveDate(sourcePath);
            var relativeFolder = BuildRelativeFolder(date, strategy);
            var targetFolder = Path.Combine(outputRoot, relativeFolder);
            Directory.CreateDirectory(targetFolder);

            var destinationPath = GetUniqueDestinationPath(targetFolder, Path.GetFileName(sourcePath));
            File.Copy(sourcePath, destinationPath, overwrite: false);

            results.Add(new OrganizedFileResult
            {
                SourcePath = sourcePath,
                DestinationPath = destinationPath,
                IsUnknownDate = date is null,
            });
        }

        return results;
    }

    /// <summary>
    /// Finds a destination path that does not already exist, appending "_1", "_2", etc.
    /// before the extension when the preferred file name is already taken.
    /// </summary>
    private static string GetUniqueDestinationPath(string folder, string fileName)
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
