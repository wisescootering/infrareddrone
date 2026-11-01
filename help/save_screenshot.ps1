# Saves the image currently in the Windows clipboard (Alt+PrintScreen) as a PNG
# in help\images. A dialog asks for the file name (e.g. step1_load_takeoff).
# Launched by the desktop shortcut "Enregistrer capture ecran".
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName Microsoft.VisualBasic

$dir = Join-Path $PSScriptRoot 'images'
if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }

$img = [Windows.Forms.Clipboard]::GetImage()
if (-not $img) {
    [Windows.Forms.MessageBox]::Show('No image in the clipboard. Select the window, press Alt+PrintScreen, then retry.', 'Screenshot') | Out-Null
    exit 1
}

$default = 'capture_' + (Get-Date -Format 'yyyyMMdd_HHmmss')
while ($true) {
    $name = [Microsoft.VisualBasic.Interaction]::InputBox("File name (without extension), saved in:`n$dir", 'Save screenshot', $default)
    if ([string]::IsNullOrWhiteSpace($name)) { exit 0 }   # cancelled
    $name = ($name.Trim() -replace '\.png$', '') -replace '[\\/:*?"<>|]', '_'
    $path = Join-Path $dir ($name + '.png')
    if (Test-Path $path) {
        $answer = [Windows.Forms.MessageBox]::Show("$name.png already exists. Replace it?", 'Screenshot', 'YesNoCancel', 'Question')
        if ($answer -eq 'Cancel') { exit 0 }
        if ($answer -eq 'No') { $default = $name; continue }
    }
    break
}
$img.Save($path, [Drawing.Imaging.ImageFormat]::Png)
$img.Dispose()
