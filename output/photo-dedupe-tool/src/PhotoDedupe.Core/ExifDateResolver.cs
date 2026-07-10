using MetadataExtractor;
using MetadataExtractor.Formats.Exif;

namespace PhotoDedupe.Core;

/// <summary>
/// Resolves the "capture date" of a media file using a defined priority order:
/// 1. EXIF DateTimeOriginal (falls back to DateTimeDigitized)
/// 2. Google Takeout JSON sidecar "photoTakenTime.timestamp"
/// 3. File system date (earliest of creation / last write time)
/// If none of the above are available, null is returned so the caller can route the
/// file to an "unknown date" quarantine folder.
/// </summary>
public interface IExifDateResolver
{
    DateTime? ResolveDate(string filePath, string? jsonSidecarPath = null);
}

public class ExifDateResolver : IExifDateResolver
{
    private readonly GoogleTakeoutJsonReader _jsonReader;

    public ExifDateResolver(GoogleTakeoutJsonReader? jsonReader = null)
    {
        _jsonReader = jsonReader ?? new GoogleTakeoutJsonReader();
    }

    /// <summary>
    /// Pure priority-merge logic, independent of any I/O. EXIF wins over JSON, which wins
    /// over the file system date. Returns null only when all three inputs are null.
    /// </summary>
    public static DateTime? Resolve(DateTime? exifDate, DateTime? jsonDate, DateTime? fileSystemDate)
    {
        return exifDate ?? jsonDate ?? fileSystemDate;
    }

    /// <summary>
    /// Reads EXIF DateTimeOriginal (preferred) or DateTimeDigitized from the given image
    /// file. Returns null for videos, files without EXIF data, or unreadable files.
    /// </summary>
    public virtual DateTime? ResolveExifDate(string filePath)
    {
        if (string.IsNullOrWhiteSpace(filePath) || !File.Exists(filePath))
        {
            return null;
        }

        try
        {
            var directories = ImageMetadataReader.ReadMetadata(filePath);
            var subIfd = directories.OfType<ExifSubIfdDirectory>().FirstOrDefault();
            if (subIfd is not null)
            {
                if (subIfd.TryGetDateTime(ExifDirectoryBase.TagDateTimeOriginal, out var original))
                {
                    return original;
                }

                if (subIfd.TryGetDateTime(ExifDirectoryBase.TagDateTimeDigitized, out var digitized))
                {
                    return digitized;
                }
            }
        }
        catch
        {
            // Unsupported format, corrupt file, or no metadata: treat as "no EXIF date".
            return null;
        }

        return null;
    }

    /// <summary>
    /// Returns the earlier of the file's creation and last-write UTC timestamps, which is
    /// used as the last-resort date source. Returns null if the file does not exist.
    /// </summary>
    public static DateTime? GetFileSystemDate(string filePath)
    {
        if (string.IsNullOrWhiteSpace(filePath) || !File.Exists(filePath))
        {
            return null;
        }

        var created = File.GetCreationTimeUtc(filePath);
        var modified = File.GetLastWriteTimeUtc(filePath);
        return created < modified ? created : modified;
    }

    /// <summary>
    /// Resolves the capture date for a real file on disk, applying the full
    /// EXIF &gt; JSON sidecar &gt; file system priority chain.
    /// </summary>
    public DateTime? ResolveDate(string filePath, string? jsonSidecarPath = null)
    {
        var exifDate = ResolveExifDate(filePath);

        DateTime? jsonDate = null;
        var jsonPath = jsonSidecarPath ?? GoogleTakeoutJsonReader.FindSidecarPath(filePath);
        if (!string.IsNullOrEmpty(jsonPath))
        {
            jsonDate = _jsonReader.ReadPhotoTakenTime(jsonPath);
        }

        var fsDate = GetFileSystemDate(filePath);

        return Resolve(exifDate, jsonDate, fsDate);
    }
}
