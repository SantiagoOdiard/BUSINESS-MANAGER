# push_to_github.ps1
# Script para instalar git/gh si faltan, inicializar repo y hacer push a GitHub
$repoUrl = "https://github.com/SantiagoOdiard/BUSINESS-MANAGER.git"

function Ensure-Command($name, $wingetId) {
  $cmd = Get-Command $name -ErrorAction SilentlyContinue
  if (-not $cmd) {
    Write-Host "$name no encontrado. Intentando instalar via winget..."
    winget install --id $wingetId -e --source winget
  } else {
    Write-Host "$name ya está instalado."
  }
}

Ensure-Command -name git -wingetId "Git.Git"
Ensure-Command -name gh -wingetId "GitHub.cli"

Set-Location (Resolve-Path .)

if (-not (Test-Path .git)) {
  git init
  git checkout -b main
}

if (-not (Test-Path .gitignore)) {
@"
venv/
__pycache__/
*.pyc
instance/
.env
uploads/
backups/
*.sqlite3
"@ | Out-File -Encoding UTF8 .gitignore
  git add .gitignore
}

git add -A
$porcelain = git status --porcelain
if ($porcelain) {
  git commit -m "Initial commit - upload project"
} else {
  Write-Host "No hay cambios nuevos para commitear."
}

$remoteExists = (git remote) -contains "origin"
if (-not $remoteExists) {
  git remote add origin $repoUrl
} else {
  Write-Host "Remote 'origin' ya existe."
}

git branch -M main

# Intentar usar gh para autenticación; si falla, instruir manualmente
$ghAuthExit = 0
try {
  gh auth status > $null 2>&1
  $ghAuthExit = $LASTEXITCODE
} catch {
  $ghAuthExit = 1
}
if ($ghAuthExit -ne 0) {
  Write-Host "Autentícate en GitHub CLI ahora (se abrirá el navegador)."
  gh auth login --web
}

Write-Host "Empujando a $repoUrl ..."
git push -u origin main
Write-Host "Hecho. Verifica el repositorio en GitHub."
