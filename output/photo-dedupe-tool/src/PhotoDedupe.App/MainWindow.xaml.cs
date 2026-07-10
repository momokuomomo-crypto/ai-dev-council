using System.Collections.ObjectModel;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using PhotoDedupe.Core;

namespace PhotoDedupe.App;

/// <summary>
/// Wizard-style main window: (1) choose input folders, (2) choose output folder and
/// settings, (3) run the merge + duplicate-detection pipeline with a progress bar, and
/// (4) show a summary with a link into <see cref="ReviewWindow"/> for final duplicate
/// review/deletion. All actual work is delegated to PhotoDedupe.Core.
/// </summary>
public partial class MainWindow : Window
{
    private enum WizardStep
    {
        InputFolders,
        OutputAndSettings,
        Progress,
        Summary,
    }

    private readonly ObservableCollection<string> _inputFolders = new();
    private WizardStep _currentStep = WizardStep.InputFolders;
    private CancellationTokenSource? _cancellationTokenSource;
    private PipelineSummary? _lastSummary;

    public MainWindow()
    {
        InitializeComponent();
        InputFoldersListBox.ItemsSource = _inputFolders;
        UpdateStepUi();
    }

    // --- Step 1: input folders --------------------------------------------------------

    private void AddGoogleTakeoutButton_Click(object sender, RoutedEventArgs e) =>
        AddInputFolder("取り込むGoogle Takeout展開済みフォルダを選択してください。");

    private void AddAmazonPhotosButton_Click(object sender, RoutedEventArgs e) =>
        AddInputFolder("取り込むAmazon Photos同期フォルダを選択してください。");

    private void AddInputFolder(string description)
    {
        using var dialog = new System.Windows.Forms.FolderBrowserDialog
        {
            Description = description,
            UseDescriptionForTitle = true,
        };

        if (dialog.ShowDialog() == System.Windows.Forms.DialogResult.OK && !_inputFolders.Contains(dialog.SelectedPath))
        {
            _inputFolders.Add(dialog.SelectedPath);
        }
    }

    private void RemoveInputFolderButton_Click(object sender, RoutedEventArgs e)
    {
        if (InputFoldersListBox.SelectedItem is string selected)
        {
            _inputFolders.Remove(selected);
        }
    }

    // --- Step 2: output folder + settings ---------------------------------------------

    private void BrowseOutputFolderButton_Click(object sender, RoutedEventArgs e)
    {
        using var dialog = new System.Windows.Forms.FolderBrowserDialog
        {
            Description = "統合した写真・動画を保存する出力フォルダを選択してください。",
            UseDescriptionForTitle = true,
        };

        if (dialog.ShowDialog() == System.Windows.Forms.DialogResult.OK)
        {
            OutputFolderTextBox.Text = dialog.SelectedPath;
        }
    }

    private DateFolderStrategy SelectedDateStrategy =>
        YearOnlyRadioButton.IsChecked == true ? DateFolderStrategy.YearOnly : DateFolderStrategy.YearMonth;

    private SimilarityThreshold SelectedSimilarityThreshold
    {
        get
        {
            if (StrictRadioButton.IsChecked == true)
            {
                return SimilarityThreshold.Strict;
            }

            if (LooseRadioButton.IsChecked == true)
            {
                return SimilarityThreshold.Loose;
            }

            return SimilarityThreshold.Moderate;
        }
    }

    // --- Wizard navigation --------------------------------------------------------------

    private void BackButton_Click(object sender, RoutedEventArgs e)
    {
        _currentStep = _currentStep switch
        {
            WizardStep.OutputAndSettings => WizardStep.InputFolders,
            _ => _currentStep,
        };
        UpdateStepUi();
    }

    private async void NextButton_Click(object sender, RoutedEventArgs e)
    {
        switch (_currentStep)
        {
            case WizardStep.InputFolders:
                if (_inputFolders.Count == 0)
                {
                    MessageBox.Show(this, "少なくとも1つの入力フォルダを追加してください。", "確認", MessageBoxButton.OK, MessageBoxImage.Warning);
                    return;
                }

                _currentStep = WizardStep.OutputAndSettings;
                UpdateStepUi();
                break;

            case WizardStep.OutputAndSettings:
                if (string.IsNullOrWhiteSpace(OutputFolderTextBox.Text))
                {
                    MessageBox.Show(this, "出力フォルダを選択してください。", "確認", MessageBoxButton.OK, MessageBoxImage.Warning);
                    return;
                }

                var confirmResult = MessageBox.Show(
                    this,
                    "写真・動画の統合と重複検出を開始します。処理には時間がかかる場合があります。よろしいですか？",
                    "確認",
                    MessageBoxButton.YesNo,
                    MessageBoxImage.Question);
                if (confirmResult != MessageBoxResult.Yes)
                {
                    return;
                }

                _currentStep = WizardStep.Progress;
                UpdateStepUi();
                await RunPipelineAsync();
                break;

            case WizardStep.Summary:
                Close();
                break;
        }
    }

    private void UpdateStepUi()
    {
        Step1Panel.Visibility = _currentStep == WizardStep.InputFolders ? Visibility.Visible : Visibility.Collapsed;
        Step2Panel.Visibility = _currentStep == WizardStep.OutputAndSettings ? Visibility.Visible : Visibility.Collapsed;
        Step3Panel.Visibility = _currentStep == WizardStep.Progress ? Visibility.Visible : Visibility.Collapsed;
        Step4Panel.Visibility = _currentStep == WizardStep.Summary ? Visibility.Visible : Visibility.Collapsed;

        StepTitleText.Text = _currentStep switch
        {
            WizardStep.InputFolders => "手順 1/4: 入力フォルダの選択",
            WizardStep.OutputAndSettings => "手順 2/4: 出力フォルダと設定",
            WizardStep.Progress => "手順 3/4: 処理中",
            WizardStep.Summary => "手順 4/4: 完了",
            _ => string.Empty,
        };

        BackButton.IsEnabled = _currentStep == WizardStep.OutputAndSettings;
        NextButton.IsEnabled = _currentStep != WizardStep.Progress;
        NextButton.Content = _currentStep == WizardStep.Summary ? "閉じる" : "次へ";
    }

    // --- Cancellation ---------------------------------------------------------------------

    private void CancelButton_Click(object sender, RoutedEventArgs e)
    {
        _cancellationTokenSource?.Cancel();
    }

    // --- Pipeline execution -----------------------------------------------------------------

    private async Task RunPipelineAsync()
    {
        _cancellationTokenSource = new CancellationTokenSource();
        var token = _cancellationTokenSource.Token;

        var inputFolders = _inputFolders.ToList();
        var outputFolder = OutputFolderTextBox.Text;
        var dateStrategy = SelectedDateStrategy;
        var threshold = SelectedSimilarityThreshold;

        var progress = new Progress<PipelineProgress>(UpdateProgressUi);

        try
        {
            _lastSummary = await Task.Run(
                () => PipelineRunner.Run(inputFolders, outputFolder, dateStrategy, threshold, progress, token),
                token);

            SummaryText.Text = BuildSummaryText(_lastSummary);
            OpenReviewButton.IsEnabled = _lastSummary.DuplicateGroups.Count > 0;
            _currentStep = WizardStep.Summary;
        }
        catch (OperationCanceledException)
        {
            MessageBox.Show(this, "処理はキャンセルされました。", "キャンセル", MessageBoxButton.OK, MessageBoxImage.Information);
            _currentStep = WizardStep.OutputAndSettings;
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, "処理中にエラーが発生しました: " + ex.Message, "エラー", MessageBoxButton.OK, MessageBoxImage.Error);
            _currentStep = WizardStep.OutputAndSettings;
        }
        finally
        {
            UpdateStepUi();
        }
    }

    private void UpdateProgressUi(PipelineProgress progressInfo)
    {
        ProgressStageText.Text = progressInfo.StageDescription;
        if (progressInfo.Total > 0)
        {
            MainProgressBar.IsIndeterminate = false;
            MainProgressBar.Maximum = progressInfo.Total;
            MainProgressBar.Value = progressInfo.Current;
            ProgressDetailText.Text = $"{progressInfo.Current} / {progressInfo.Total}";
        }
        else
        {
            MainProgressBar.IsIndeterminate = true;
            ProgressDetailText.Text = string.Empty;
        }
    }

    private static string BuildSummaryText(PipelineSummary summary)
    {
        return
            $"入力ファイル数: {summary.TotalSourceFiles}" + Environment.NewLine +
            $"統合されたファイル数: {summary.OrganizedFileCount}" + Environment.NewLine +
            $"撮影日が不明で「{FileOrganizer.UnknownDateFolderName}」フォルダに保存されたファイル数: {summary.UnknownDateFileCount}" + Environment.NewLine +
            $"完全一致の重複グループ数: {summary.ExactDuplicateGroupCount}" + Environment.NewLine +
            $"類似画像の重複候補グループ数: {summary.SimilarDuplicateGroupCount}" + Environment.NewLine +
            $"重複候補フォルダ: {summary.DuplicateCandidatesFolder}";
    }

    private void OpenReviewButton_Click(object sender, RoutedEventArgs e)
    {
        if (_lastSummary is null || _lastSummary.DuplicateGroups.Count == 0)
        {
            return;
        }

        var reviewWindow = new ReviewWindow(_lastSummary.DuplicateGroups)
        {
            Owner = this,
        };
        reviewWindow.ShowDialog();
    }
}
