using PhotoDedupe.Core;

namespace PhotoDedupe.Core.Tests;

/// <summary>
/// Test double that returns a pre-programmed date (or null) for each source file path,
/// so <see cref="FileOrganizer"/> can be tested without depending on real EXIF/JSON/file
/// system date resolution.
/// </summary>
internal class FakeDateResolver : IExifDateResolver
{
    private readonly Dictionary<string, DateTime?> _datesByPath;

    public FakeDateResolver(Dictionary<string, DateTime?> datesByPath)
    {
        _datesByPath = datesByPath;
    }

    public DateTime? ResolveDate(string filePath, string? jsonSidecarPath = null)
    {
        return _datesByPath.TryGetValue(filePath, out var date) ? date : null;
    }
}

public class FileOrganizerTests : IDisposable
{
    private readonly string _tempDirectory;
    private readonly string _sourceDirectory;
    private readonly string _outputDirectory;

    public FileOrganizerTests()
    {
        _tempDirectory = Path.Combine(Path.GetTempPath(), "PhotoDedupeTests_" + Guid.NewGuid().ToString("N"));
        _sourceDirectory = Path.Combine(_tempDirectory, "source");
        _outputDirectory = Path.Combine(_tempDirectory, "output");
        Directory.CreateDirectory(_sourceDirectory);
        Directory.CreateDirectory(_outputDirectory);
    }

    public void Dispose()
    {
        if (Directory.Exists(_tempDirectory))
        {
            Directory.Delete(_tempDirectory, recursive: true);
        }
    }

    [Fact]
    public void BuildRelativeFolder_YearMonth_CombinesYearAndMonth()
    {
        var date = new DateTime(2022, 3, 7);

        var folder = FileOrganizer.BuildRelativeFolder(date, DateFolderStrategy.YearMonth);

        Assert.Equal(Path.Combine("2022", "03"), folder);
    }

    [Fact]
    public void BuildRelativeFolder_YearOnly_ReturnsJustTheYear()
    {
        var date = new DateTime(2022, 3, 7);

        var folder = FileOrganizer.BuildRelativeFolder(date, DateFolderStrategy.YearOnly);

        Assert.Equal("2022", folder);
    }

    [Fact]
    public void BuildRelativeFolder_NullDate_ReturnsUnknownDateFolder()
    {
        var folder = FileOrganizer.BuildRelativeFolder(null, DateFolderStrategy.YearMonth);

        Assert.Equal(FileOrganizer.UnknownDateFolderName, folder);
    }

    [Fact]
    public void Organize_CopiesFileIntoYearMonthFolder_BasedOnResolvedDate()
    {
        var sourcePath = CreateSourceFile("photo1.jpg", "content-1");
        var resolver = new FakeDateResolver(new Dictionary<string, DateTime?>
        {
            [sourcePath] = new DateTime(2023, 6, 15),
        });
        var organizer = new FileOrganizer(resolver);

        var results = organizer.Organize(new[] { sourcePath }, _outputDirectory, DateFolderStrategy.YearMonth);

        var result = Assert.Single(results);
        var expectedFolder = Path.Combine(_outputDirectory, "2023", "06");
        Assert.Equal(Path.Combine(expectedFolder, "photo1.jpg"), result.DestinationPath);
        Assert.False(result.IsUnknownDate);
        Assert.True(File.Exists(result.DestinationPath));
    }

    [Fact]
    public void Organize_CopiesFileIntoYearOnlyFolder_WhenStrategyIsYearOnly()
    {
        var sourcePath = CreateSourceFile("photo2.jpg", "content-2");
        var resolver = new FakeDateResolver(new Dictionary<string, DateTime?>
        {
            [sourcePath] = new DateTime(2023, 6, 15),
        });
        var organizer = new FileOrganizer(resolver);

        var results = organizer.Organize(new[] { sourcePath }, _outputDirectory, DateFolderStrategy.YearOnly);

        var result = Assert.Single(results);
        var expectedFolder = Path.Combine(_outputDirectory, "2023");
        Assert.Equal(Path.Combine(expectedFolder, "photo2.jpg"), result.DestinationPath);
    }

    [Fact]
    public void Organize_LeavesSourceFileInPlace_AfterCopying()
    {
        var sourcePath = CreateSourceFile("photo3.jpg", "content-3");
        var resolver = new FakeDateResolver(new Dictionary<string, DateTime?>
        {
            [sourcePath] = new DateTime(2023, 6, 15),
        });
        var organizer = new FileOrganizer(resolver);

        organizer.Organize(new[] { sourcePath }, _outputDirectory, DateFolderStrategy.YearMonth);

        Assert.True(File.Exists(sourcePath), "The original source file must not be deleted or moved.");
    }

    [Fact]
    public void Organize_RoutesFileToUnknownDateFolder_WhenDateCannotBeResolved()
    {
        var sourcePath = CreateSourceFile("mystery.jpg", "content-4");
        var resolver = new FakeDateResolver(new Dictionary<string, DateTime?>
        {
            [sourcePath] = null,
        });
        var organizer = new FileOrganizer(resolver);

        var results = organizer.Organize(new[] { sourcePath }, _outputDirectory, DateFolderStrategy.YearMonth);

        var result = Assert.Single(results);
        Assert.True(result.IsUnknownDate);
        var expectedFolder = Path.Combine(_outputDirectory, FileOrganizer.UnknownDateFolderName);
        Assert.Equal(Path.Combine(expectedFolder, "mystery.jpg"), result.DestinationPath);
        Assert.True(File.Exists(result.DestinationPath));
    }

    [Fact]
    public void Organize_RenamesFile_WhenDestinationNameAlreadyExists()
    {
        var sourceSubDirA = Path.Combine(_sourceDirectory, "a");
        var sourceSubDirB = Path.Combine(_sourceDirectory, "b");
        Directory.CreateDirectory(sourceSubDirA);
        Directory.CreateDirectory(sourceSubDirB);

        var sourcePathA = Path.Combine(sourceSubDirA, "duplicate-name.jpg");
        var sourcePathB = Path.Combine(sourceSubDirB, "duplicate-name.jpg");
        File.WriteAllText(sourcePathA, "from-a");
        File.WriteAllText(sourcePathB, "from-b");

        var sameDate = new DateTime(2023, 6, 15);
        var resolver = new FakeDateResolver(new Dictionary<string, DateTime?>
        {
            [sourcePathA] = sameDate,
            [sourcePathB] = sameDate,
        });
        var organizer = new FileOrganizer(resolver);

        var results = organizer.Organize(new[] { sourcePathA, sourcePathB }, _outputDirectory, DateFolderStrategy.YearMonth);

        Assert.Equal(2, results.Count);
        var destinations = results.Select(r => r.DestinationPath).ToList();
        Assert.Equal(2, destinations.Distinct().Count());
        Assert.Contains(destinations, d => Path.GetFileName(d) == "duplicate-name.jpg");
        Assert.Contains(destinations, d => Path.GetFileName(d) == "duplicate-name_1.jpg");

        // Both files' content must be preserved, not overwritten.
        var contents = destinations.Select(File.ReadAllText).OrderBy(c => c).ToList();
        Assert.Equal(new[] { "from-a", "from-b" }, contents);
    }

    private string CreateSourceFile(string fileName, string content)
    {
        var path = Path.Combine(_sourceDirectory, fileName);
        File.WriteAllText(path, content);
        return path;
    }
}
