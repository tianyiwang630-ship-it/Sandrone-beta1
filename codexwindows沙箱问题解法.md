# 补丁参考
$codexExe = (Get-Command codex.exe -ErrorAction Stop).Source

$patch = @'
*** Begin Patch
*** Update File: path/to/file
@@
-old
+new
*** End Patch
'@

& $codexExe --codex-run-as-apply-patch $patch

if ($LASTEXITCODE -ne 0) {
    throw "apply_patch failed with exit code $LASTEXITCODE"
}