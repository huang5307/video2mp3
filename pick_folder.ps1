param(
    [string]$InitialDir = ""
)

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32Window {
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")]
    public static extern bool BringWindowToTop(IntPtr hWnd);
}
"@

Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Application]::EnableVisualStyles()

$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = "【Video2MP3】請選擇儲存資料夾"
if ($InitialDir -and (Test-Path $InitialDir)) {
    $dialog.SelectedPath = $InitialDir
}
$dialog.ShowNewFolderButton = $true

$form = New-Object System.Windows.Forms.Form
$form.TopMost = $true
$form.Width = 1
$form.Height = 1
$form.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen
$form.Show()
[Win32Window]::SetForegroundWindow($form.Handle) | Out-Null
[Win32Window]::BringWindowToTop($form.Handle) | Out-Null

$result = $dialog.ShowDialog($form)
$form.Close()
$form.Dispose()

if ($result -eq [System.Windows.Forms.DialogResult]::OK) {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    Write-Output $dialog.SelectedPath
} else {
    Write-Output "CANCELLED"
}
