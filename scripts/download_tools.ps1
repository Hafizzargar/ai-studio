# Downloads FFmpeg and Piper (+ one English voice) into vendor\. URLs can change: if a download fails,
# get the files by hand (see README). Check each tool's and voice's licence before you distribute anything.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$vendor = Join-Path $root "vendor"
$tmp = Join-Path $env:TEMP "aistudio_dl"
New-Item -ItemType Directory -Force -Path $tmp, $vendor, (Join-Path $vendor "voices") | Out-Null

function Get-File($url, $out) {
  Write-Host "Downloading $url"
  Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing
}
try {
  Get-File "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" "$tmp\ffmpeg.zip"
  Expand-Archive "$tmp\ffmpeg.zip" -DestinationPath "$tmp\ffmpeg" -Force
  Get-ChildItem "$tmp\ffmpeg" -Recurse -Include ffmpeg.exe, ffprobe.exe | Copy-Item -Destination $vendor -Force
} catch { Write-Warning "FFmpeg download failed: $_  -> download manually and copy ffmpeg.exe/ffprobe.exe into vendor\" }
try {
  Get-File "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_windows_amd64.zip" "$tmp\piper.zip"
  Expand-Archive "$tmp\piper.zip" -DestinationPath $vendor -Force
  $v = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"
  Get-File "$v/en_US-lessac-medium.onnx" "$vendor\voices\en_US-lessac-medium.onnx"
  Get-File "$v/en_US-lessac-medium.onnx.json" "$vendor\voices\en_US-lessac-medium.onnx.json"
} catch { Write-Warning "Piper download failed: $_  -> optional; Windows built-in voices will be used instead." }
Write-Host "Finished. Run: python -m engine.cli doctor"
