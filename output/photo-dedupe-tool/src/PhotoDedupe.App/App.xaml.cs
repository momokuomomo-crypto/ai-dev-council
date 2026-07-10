using System.Windows;
using System.Windows.Threading;

namespace PhotoDedupe.App;

/// <summary>
/// Interaction logic for App.xaml. Adds a top-level unhandled exception handler so that
/// non-technical users see a friendly Japanese error dialog instead of a crash.
/// </summary>
public partial class App : System.Windows.Application
{
    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        DispatcherUnhandledException += OnDispatcherUnhandledException;
    }

    private void OnDispatcherUnhandledException(object sender, DispatcherUnhandledExceptionEventArgs e)
    {
        MessageBox.Show(
            "予期しないエラーが発生しました。" + Environment.NewLine + e.Exception.Message,
            "エラー",
            MessageBoxButton.OK,
            MessageBoxImage.Error);
        e.Handled = true;
    }
}
