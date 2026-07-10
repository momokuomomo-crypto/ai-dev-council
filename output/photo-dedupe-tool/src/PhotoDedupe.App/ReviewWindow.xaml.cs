using System.IO;
using System.Windows;
using System.Windows.Media.Imaging;
using Microsoft.VisualBasic.FileIO;
using PhotoDedupe.Core;

namespace PhotoDedupe.App;

/// <summary>
/// Lets the user review each duplicate group's thumbnails, choose which candidate files to
/// discard, and finally move only the selected files to the Recycle Bin. Nothing is ever
/// permanently deleted from here; files are just moved to Windows' Recycle Bin so the user
/// can restore them if a decision was wrong.
/// </summary>
public partial class ReviewWindow : Window
{
    private readonly List<DuplicateGroupViewModel> _groups;

    public ReviewWindow(IReadOnlyList<MovedDuplicateGroup> duplicateGroups)
    {
        InitializeComponent();

        _groups = duplicateGroups.Select(BuildGroupViewModel).ToList();
        GroupsItemsControl.ItemsSource = _groups;
    }

    private static DuplicateGroupViewModel BuildGroupViewModel(MovedDuplicateGroup group)
    {
        return new DuplicateGroupViewModel
        {
            GroupTypeLabel = group.Type == DuplicateGroupType.ExactMatch ? "完全一致の重複" : "類似画像の重複候補",
            KeptFilePath = group.KeptFilePath,
            KeptThumbnail = TryCreateThumbnail(group.KeptFilePath),
            Candidates = group.MovedFilePaths
                .Select(path => new DuplicateFileItem
                {
                    FilePath = path,
                    Thumbnail = TryCreateThumbnail(path),
                })
                .ToList(),
        };
    }

    private static BitmapImage? TryCreateThumbnail(string filePath)
    {
        if (!HashService.IsImageFile(filePath) || !File.Exists(filePath))
        {
            return null;
        }

        try
        {
            var bitmap = new BitmapImage();
            bitmap.BeginInit();
            bitmap.CacheOption = BitmapCacheOption.OnLoad;
            bitmap.DecodePixelWidth = 160;
            bitmap.UriSource = new Uri(filePath);
            bitmap.EndInit();
            bitmap.Freeze();
            return bitmap;
        }
        catch
        {
            // Corrupt or unreadable image: fall back to the "no preview" placeholder.
            return null;
        }
    }

    private void SelectAllButton_Click(object sender, RoutedEventArgs e)
    {
        foreach (var candidate in _groups.SelectMany(g => g.Candidates))
        {
            candidate.IsSelected = true;
        }

        RefreshList();
    }

    private void DeleteSelectedButton_Click(object sender, RoutedEventArgs e)
    {
        var selectedFiles = _groups
            .SelectMany(g => g.Candidates)
            .Where(c => c.IsSelected)
            .ToList();

        if (selectedFiles.Count == 0)
        {
            MessageBox.Show(this, "削除するファイルが選択されていません。", "確認", MessageBoxButton.OK, MessageBoxImage.Information);
            return;
        }

        var confirmResult = MessageBox.Show(
            this,
            $"選択した{selectedFiles.Count}件のファイルをごみ箱へ移動します。よろしいですか？",
            "確認",
            MessageBoxButton.YesNo,
            MessageBoxImage.Warning);
        if (confirmResult != MessageBoxResult.Yes)
        {
            return;
        }

        var failures = new List<string>();
        foreach (var file in selectedFiles)
        {
            try
            {
                if (File.Exists(file.FilePath))
                {
                    FileSystem.DeleteFile(file.FilePath, UIOption.OnlyErrorDialogs, RecycleOption.SendToRecycleBin);
                }
            }
            catch (Exception ex)
            {
                failures.Add($"{file.FileName}: {ex.Message}");
            }
        }

        foreach (var group in _groups)
        {
            group.Candidates.RemoveAll(c => c.IsSelected && !File.Exists(c.FilePath));
        }

        RefreshList();

        if (failures.Count > 0)
        {
            MessageBox.Show(
                this,
                "一部のファイルを削除できませんでした:" + Environment.NewLine + string.Join(Environment.NewLine, failures),
                "エラー",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
        }
        else
        {
            MessageBox.Show(this, "選択したファイルをごみ箱へ移動しました。", "完了", MessageBoxButton.OK, MessageBoxImage.Information);
        }
    }

    private void CloseButton_Click(object sender, RoutedEventArgs e)
    {
        Close();
    }

    /// <summary>
    /// DuplicateFileItem/DuplicateGroupViewModel are plain data holders without
    /// INotifyPropertyChanged, so after mutating state in code we re-bind ItemsSource to
    /// force the ItemsControl to refresh what it displays.
    /// </summary>
    private void RefreshList()
    {
        var itemsSource = GroupsItemsControl.ItemsSource;
        GroupsItemsControl.ItemsSource = null;
        GroupsItemsControl.ItemsSource = itemsSource;
    }
}

public class DuplicateGroupViewModel
{
    public required string GroupTypeLabel { get; init; }

    public required string KeptFilePath { get; init; }

    public BitmapImage? KeptThumbnail { get; init; }

    public List<DuplicateFileItem> Candidates { get; init; } = new();
}

public class DuplicateFileItem
{
    public required string FilePath { get; init; }

    public bool IsSelected { get; set; }

    public BitmapImage? Thumbnail { get; init; }

    public string FileName => Path.GetFileName(FilePath);

    public Visibility ThumbnailVisibility => Thumbnail is not null ? Visibility.Visible : Visibility.Collapsed;

    public Visibility VideoLabelVisibility => Thumbnail is null ? Visibility.Visible : Visibility.Collapsed;
}
