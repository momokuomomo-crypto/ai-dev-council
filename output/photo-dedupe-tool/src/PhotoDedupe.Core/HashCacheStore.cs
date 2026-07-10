using System.Globalization;
using Microsoft.Data.Sqlite;

namespace PhotoDedupe.Core;

/// <summary>
/// A single cached record describing a previously scanned file: its size/last-write time
/// (used to detect changes on incremental rescans) plus the expensive-to-compute values
/// (hashes, resolved capture date).
/// </summary>
public class FileHashCacheEntry
{
    public required string FilePath { get; init; }

    public long FileSize { get; init; }

    public DateTime LastWriteTimeUtc { get; init; }

    public string? Sha256 { get; set; }

    public ulong? DHash { get; set; }

    public DateTime? CapturedDate { get; set; }
}

/// <summary>
/// Persists file hash/metadata results in a local SQLite database so that rescanning a
/// large library (tens of thousands of files) does not require recomputing hashes for
/// files that have not changed since the last scan.
/// </summary>
public class HashCacheStore : IDisposable
{
    private const string DateFormat = "o";

    private readonly SqliteConnection _connection;

    public HashCacheStore(string databaseFilePath)
    {
        var directory = Path.GetDirectoryName(databaseFilePath);
        if (!string.IsNullOrEmpty(directory))
        {
            Directory.CreateDirectory(directory);
        }

        var connectionString = new SqliteConnectionStringBuilder { DataSource = databaseFilePath }.ToString();
        _connection = new SqliteConnection(connectionString);
        _connection.Open();
        Initialize();
    }

    private void Initialize()
    {
        using var command = _connection.CreateCommand();
        command.CommandText =
            """
            CREATE TABLE IF NOT EXISTS FileHashCache (
                FilePath TEXT PRIMARY KEY,
                FileSize INTEGER NOT NULL,
                LastWriteTimeUtc TEXT NOT NULL,
                Sha256 TEXT NULL,
                DHash INTEGER NULL,
                CapturedDate TEXT NULL
            );
            """;
        command.ExecuteNonQuery();
    }

    /// <summary>
    /// Looks up the cached entry for a file path, or null if it has never been scanned.
    /// </summary>
    public FileHashCacheEntry? TryGet(string filePath)
    {
        using var command = _connection.CreateCommand();
        command.CommandText =
            "SELECT FileSize, LastWriteTimeUtc, Sha256, DHash, CapturedDate " +
            "FROM FileHashCache WHERE FilePath = $path";
        command.Parameters.AddWithValue("$path", filePath);

        using var reader = command.ExecuteReader();
        if (!reader.Read())
        {
            return null;
        }

        return new FileHashCacheEntry
        {
            FilePath = filePath,
            FileSize = reader.GetInt64(0),
            LastWriteTimeUtc = DateTime.Parse(reader.GetString(1), CultureInfo.InvariantCulture, DateTimeStyles.RoundtripKind),
            Sha256 = reader.IsDBNull(2) ? null : reader.GetString(2),
            DHash = reader.IsDBNull(3) ? null : unchecked((ulong)reader.GetInt64(3)),
            CapturedDate = reader.IsDBNull(4)
                ? null
                : DateTime.Parse(reader.GetString(4), CultureInfo.InvariantCulture, DateTimeStyles.RoundtripKind),
        };
    }

    /// <summary>
    /// Inserts or updates the cached entry for a file.
    /// </summary>
    public void Upsert(FileHashCacheEntry entry)
    {
        using var command = _connection.CreateCommand();
        command.CommandText =
            """
            INSERT INTO FileHashCache (FilePath, FileSize, LastWriteTimeUtc, Sha256, DHash, CapturedDate)
            VALUES ($path, $size, $lastWrite, $sha256, $dhash, $captured)
            ON CONFLICT(FilePath) DO UPDATE SET
                FileSize = excluded.FileSize,
                LastWriteTimeUtc = excluded.LastWriteTimeUtc,
                Sha256 = excluded.Sha256,
                DHash = excluded.DHash,
                CapturedDate = excluded.CapturedDate;
            """;

        command.Parameters.AddWithValue("$path", entry.FilePath);
        command.Parameters.AddWithValue("$size", entry.FileSize);
        command.Parameters.AddWithValue("$lastWrite", entry.LastWriteTimeUtc.ToString(DateFormat, CultureInfo.InvariantCulture));
        command.Parameters.AddWithValue("$sha256", (object?)entry.Sha256 ?? DBNull.Value);
        command.Parameters.AddWithValue("$dhash", entry.DHash.HasValue ? unchecked((long)entry.DHash.Value) : DBNull.Value);
        command.Parameters.AddWithValue(
            "$captured",
            entry.CapturedDate.HasValue ? entry.CapturedDate.Value.ToString(DateFormat, CultureInfo.InvariantCulture) : DBNull.Value);

        command.ExecuteNonQuery();
    }

    /// <summary>
    /// Returns true when a cached entry's recorded size and last-write time still match the
    /// file's current state, meaning its cached hash values can be reused as-is during an
    /// incremental rescan instead of being recomputed.
    /// </summary>
    public static bool IsUpToDate(FileHashCacheEntry cached, long currentFileSize, DateTime currentLastWriteTimeUtc)
    {
        return cached.FileSize == currentFileSize && cached.LastWriteTimeUtc == currentLastWriteTimeUtc;
    }

    /// <summary>
    /// Removes cache entries for files that no longer exist under any of the given root
    /// folders, keeping the cache from growing unbounded across many rescans.
    /// </summary>
    public int RemoveMissingFiles(IEnumerable<string> knownExistingPaths)
    {
        var existing = new HashSet<string>(knownExistingPaths, StringComparer.OrdinalIgnoreCase);
        var toRemove = new List<string>();

        using (var selectCommand = _connection.CreateCommand())
        {
            selectCommand.CommandText = "SELECT FilePath FROM FileHashCache";
            using var reader = selectCommand.ExecuteReader();
            while (reader.Read())
            {
                var path = reader.GetString(0);
                if (!existing.Contains(path))
                {
                    toRemove.Add(path);
                }
            }
        }

        foreach (var path in toRemove)
        {
            using var deleteCommand = _connection.CreateCommand();
            deleteCommand.CommandText = "DELETE FROM FileHashCache WHERE FilePath = $path";
            deleteCommand.Parameters.AddWithValue("$path", path);
            deleteCommand.ExecuteNonQuery();
        }

        return toRemove.Count;
    }

    public void Dispose()
    {
        _connection.Dispose();
        GC.SuppressFinalize(this);
    }
}
