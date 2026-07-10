using System.Text;
using PhotoDedupe.Core;
using SixLabors.ImageSharp;
using SixLabors.ImageSharp.Formats.Jpeg;
using SixLabors.ImageSharp.Metadata.Profiles.Exif;
using SixLabors.ImageSharp.PixelFormats;

namespace PhotoDedupe.Core.Tests;

public class ExifDateResolverTests : IDisposable
{
    private readonly string _tempDirectory;

    public ExifDateResolverTests()
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

    // --- Pure priority-merge logic -----------------------------------------------------

    [Fact]
    public void Resolve_PrefersExifOverJsonAndFileSystem()
    {
        var exif = new DateTime(2020, 1, 1, 0, 0, 0, DateTimeKind.Utc);
        var json = new DateTime(2019, 1, 1, 0, 0, 0, DateTimeKind.Utc);
        var fs = new DateTime(2018, 1, 1, 0, 0, 0, DateTimeKind.Utc);

        var result = ExifDateResolver.Resolve(exif, json, fs);

        Assert.Equal(exif, result);
    }

    [Fact]
    public void Resolve_PrefersJsonOverFileSystem_WhenExifMissing()
    {
        var json = new DateTime(2019, 1, 1, 0, 0, 0, DateTimeKind.Utc);
        var fs = new DateTime(2018, 1, 1, 0, 0, 0, DateTimeKind.Utc);

        var result = ExifDateResolver.Resolve(null, json, fs);

        Assert.Equal(json, result);
    }

    [Fact]
    public void Resolve_FallsBackToFileSystem_WhenExifAndJsonMissing()
    {
        var fs = new DateTime(2018, 1, 1, 0, 0, 0, DateTimeKind.Utc);

        var result = ExifDateResolver.Resolve(null, null, fs);

        Assert.Equal(fs, result);
    }

    [Fact]
    public void Resolve_ReturnsNull_WhenAllSourcesMissing()
    {
        var result = ExifDateResolver.Resolve(null, null, null);

        Assert.Null(result);
    }

    // --- Real EXIF extraction -------------------------------------------------------------

    [Fact]
    public void ResolveExifDate_ReadsDateTimeOriginal_FromJpeg()
    {
        var expected = new DateTime(2021, 5, 17, 10, 20, 30);
        var filePath = Path.Combine(_tempDirectory, "with-exif.jpg");
        CreateJpegWithExifDate(filePath, expected);

        var resolver = new ExifDateResolver();
        var result = resolver.ResolveExifDate(filePath);

        Assert.NotNull(result);
        Assert.Equal(expected, result!.Value);
    }

    [Fact]
    public void ResolveDate_PrefersExifDate_OverJsonSidecarAndFileSystem()
    {
        var exifDate = new DateTime(2021, 5, 17, 10, 20, 30);
        var filePath = Path.Combine(_tempDirectory, "photo.jpg");
        CreateJpegWithExifDate(filePath, exifDate);

        // A JSON sidecar with a different date is present, but EXIF should win.
        var jsonPath = filePath + ".json";
        File.WriteAllText(jsonPath, """{"photoTakenTime":{"timestamp":"1000000000"}}""");

        var resolver = new ExifDateResolver();
        var result = resolver.ResolveDate(filePath);

        Assert.NotNull(result);
        Assert.Equal(exifDate, result!.Value);
    }

    // --- Google Takeout JSON sidecar fallback -------------------------------------------

    [Fact]
    public void ResolveDate_UsesJsonSidecar_WhenNoExifDataPresent()
    {
        // A file with no EXIF metadata at all (plain bytes, non-image extension so
        // MetadataExtractor cannot find any tags).
        var filePath = Path.Combine(_tempDirectory, "clip.mp4");
        File.WriteAllBytes(filePath, Encoding.UTF8.GetBytes("not a real video, just bytes"));

        var jsonPath = filePath + ".json";
        const long timestampSeconds = 1621247000; // fixed point in time
        File.WriteAllText(jsonPath, "{\"photoTakenTime\":{\"timestamp\":\"" + timestampSeconds + "\"}}");

        var resolver = new ExifDateResolver();
        var result = resolver.ResolveDate(filePath);

        var expected = DateTimeOffset.FromUnixTimeSeconds(timestampSeconds).UtcDateTime;
        Assert.NotNull(result);
        Assert.Equal(expected, result!.Value);
    }

    [Fact]
    public void ResolveDate_UsesSupplementalMetadataSidecarNaming()
    {
        var filePath = Path.Combine(_tempDirectory, "clip2.mp4");
        File.WriteAllBytes(filePath, Encoding.UTF8.GetBytes("not a real video"));

        var jsonPath = filePath + ".supplemental-metadata.json";
        const long timestampSeconds = 1600000000;
        File.WriteAllText(jsonPath, "{\"photoTakenTime\":{\"timestamp\":\"" + timestampSeconds + "\"}}");

        var found = GoogleTakeoutJsonReader.FindSidecarPath(filePath);
        Assert.Equal(jsonPath, found);
    }

    // --- File system fallback -----------------------------------------------------------

    [Fact]
    public void ResolveDate_FallsBackToFileSystemDate_WhenNoExifAndNoJson()
    {
        var filePath = Path.Combine(_tempDirectory, "plain.bin");
        File.WriteAllBytes(filePath, new byte[] { 1, 2, 3 });

        var fixedDate = new DateTime(2015, 3, 4, 5, 6, 7, DateTimeKind.Utc);
        File.SetCreationTimeUtc(filePath, fixedDate);
        File.SetLastWriteTimeUtc(filePath, fixedDate);

        var resolver = new ExifDateResolver();
        var result = resolver.ResolveDate(filePath);

        Assert.NotNull(result);
        Assert.Equal(fixedDate, result!.Value);
    }

    // --- Unknown date (quarantine trigger) ----------------------------------------------

    [Fact]
    public void ResolveDate_ReturnsNull_WhenFileDoesNotExistAndNoSidecar()
    {
        var missingPath = Path.Combine(_tempDirectory, "does-not-exist.jpg");

        var resolver = new ExifDateResolver();
        var result = resolver.ResolveDate(missingPath);

        Assert.Null(result);
    }

    private static void CreateJpegWithExifDate(string filePath, DateTime dateTime)
    {
        using var image = new Image<Rgba32>(4, 4);
        var exifProfile = new ExifProfile();
        var formatted = dateTime.ToString("yyyy:MM:dd HH:mm:ss");
        exifProfile.SetValue(ExifTag.DateTimeOriginal, formatted);
        image.Metadata.ExifProfile = exifProfile;
        image.Save(filePath, new JpegEncoder());
    }
}
