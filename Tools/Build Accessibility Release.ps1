[CmdletBinding()]
param(
    [string]$Version = (Get-Date -Format 'yyyy-MM-dd-HHmm'),

    # Skips staging the bundled interpreter. For a fast check of the code
    # side of a build only -- the archive it produces is NOT the one to
    # give anyone, because Setup would then fall back to hunting for a
    # Python on the recipient's machine, which is the whole problem the
    # bundled runtime exists to remove.
    [switch]$NoRuntime
)

$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$workspace = Split-Path -Parent $project
$releaseRoot = Join-Path $workspace 'Accessibility Releases'
# Outside the project, beside the releases: a ~10 MB download that would
# otherwise be re-fetched on every build, and that must never be committed.
$runtimeCache = Join-Path $workspace 'RuntimeCache'
$packageName = "Pokemon-XG-Accessibility-$Version"
$stage = Join-Path $releaseRoot $packageName
$archive = Join-Path $releaseRoot "$packageName.zip"

New-Item -ItemType Directory -Path $releaseRoot -Force | Out-Null
$resolvedReleaseRoot = [IO.Path]::GetFullPath($releaseRoot)
$resolvedStage = [IO.Path]::GetFullPath($stage)
if (-not $resolvedStage.StartsWith($resolvedReleaseRoot + [IO.Path]::DirectorySeparatorChar)) {
    throw 'Refusing to use a staging path outside the release directory.'
}
if (Test-Path -LiteralPath $stage) {
    Remove-Item -LiteralPath $stage -Recurse -Force
}
if (Test-Path -LiteralPath $archive) {
    Remove-Item -LiteralPath $archive -Force
}
New-Item -ItemType Directory -Path $stage | Out-Null

function Copy-ApprovedFile([string]$RelativePath) {
    $source = Join-Path $project $RelativePath
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Approved release file is missing: $RelativePath"
    }
    $destination = Join-Path $stage $RelativePath
    New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
    Copy-Item -LiteralPath $source -Destination $destination
}


$approvedFiles = @(
    'Companion/run_accessible_pokemon_xd.py',
    'Companion/run_battle_narrator.py',
    'Companion/run_battle_narrator_phase1b.py',
    'Companion/dolphin_input.py',
    'Companion/dolphin_keyboard_driver.py',
    'Companion/_dialogue_extraction_tool.py',
    # First-run flow. Without these the archive is code with no way in:
    # the companion cannot start until the copyrighted tables it reads
    # have been generated from the recipient's own disc image, and the
    # only launcher this project had hardcoded one machine's Dolphin,
    # game image and interpreter.
    'Companion/bootstrap_game_data.py',
    'Companion/extract_warp_collision_data.py',
    'Companion/setup_companion.py',
    # Finds Dolphin and the player's disc image, so setup can ask them to
    # confirm rather than to type an absolute path into a console. Setup
    # imports it unconditionally, so omitting it here would be a traceback
    # on the recipient's very first action -- the staged import check below
    # is what catches that.
    'Companion/setup_discovery.py',
    'Companion/launch_accessible.py',
    'Companion/check_game_compatibility.py',
    # The static counterpart: answers the same compatibility question from a
    # disc FILE, before the game is ever booted. Worth shipping precisely
    # because a recipient can run it when Setup rejects their image, without
    # having to get as far as a running Dolphin first.
    'Companion/check_image_compatibility.py',
    'Setup.cmd',
    'Launch Accessible XD.cmd',
    'Companion/requirements.txt',
    'Companion/assets/room_ids.json',
    # Generated classification assets. Both are DERIVED from the extracted
    # game scripts by build_npc_role_table.py / build_interactable_table.py
    # and contain no copyrighted game text -- only handler names, record
    # indices and this project's own class ids. Without them the role
    # resolver and the entire Interactables/Hazards categories disable
    # themselves silently, which is how npc_roles.json shipped missing
    # since Phase 2.
    'Companion/assets/npc_roles.json',
    'Companion/assets/interactables.json',
    'Companion/assets/room_services.json',
    # README.txt, not README.md. The recipient's guide is plain ASCII text
    # with no Markdown syntax and no tables: it opens in Notepad on a
    # double-click and reads cleanly through a screen reader, where `#`,
    # backticks and pipe-delimited tables are just noise to sit through.
    # README.md is the repository landing page -- aimed at someone
    # browsing the code on GitHub, not at someone who already has the zip
    # -- and is left out for the same reason as README-DISTRIBUTION.md,
    # which documents how to BUILD a release.
    'README.txt',
    'THIRD-PARTY-NOTICES.md',
    'LICENSE'
)
foreach ($relative in $approvedFiles) {
    Copy-ApprovedFile $relative
}

Get-ChildItem -LiteralPath (Join-Path $project 'Companion/battle_narrator') -File -Filter '*.py' |
    Sort-Object Name |
    ForEach-Object { Copy-ApprovedFile ("Companion/battle_narrator/" + $_.Name) }

$approvedSounds = @(
    '263123__mossy4__sine-tri-tone-down-negative-beep-amb-verb.wav',
    '263124__mossy4__sine-octaves-up-beep.wav',
    '263125__mossy4__sine-fifths-up-beep.wav',
    '263126__mossy4__tone-beep-lower-slower.wav',
    '263128__mossy4__tone-beep-amb-verb.wav',
    '263129__mossy4__sine-up-flutter-beep.wav',
    '263131__mossy4__tone-beep-slower-lower-amb-verb.wav',
    '263132__mossy4__tri-tone-up-beep.wav',
    '263655__mossy4__upward-beep-chromatic-fifths.wav',
    'npc_sound.wav'
)
foreach ($name in $approvedSounds) {
    Copy-ApprovedFile ("Companion/assets/npc_sounds_loud/" + $name)
}

# The project's own sounds/ directory. These are NOT optional extras: the
# six category files below are what npc_beacons.PASSIVE_BEACON_SOUND_FILES
# names, and a missing one raises LocalDataError out of npc_sound_factory,
# which kills the narrator on the first beacon that comes into range. Every
# release before 2026-08-10 shipped without them, because sounds/ then lived
# one level ABOVE the project -- outside anything staged here. It was moved
# in on 2026-08-11, so the checkout and the release now have the same shape
# and this is an ordinary in-project copy.
$approvedCategorySounds = @(
    'npcs.wav',
    'pokemarts.wav',
    'items.wav',
    'doors.wav',
    'warps.wav',
    'elevators.wav'
)
foreach ($name in $approvedCategorySounds) {
    Copy-ApprovedFile ("sounds/" + $name)
}

# Real recorded footsteps.
#
# ENUMERATED, not listed. This was a hardcoded list of seven filenames,
# which is the one shape that cannot survive someone adding an eighth
# recording: the new file simply would not ship, and nothing anywhere would
# say so. That matters more here than for any other asset because of how
# the runtime treats a shortfall -- a missing BEACON raises LocalDataError
# and kills the narrator on the first beacon in range, which is impossible
# to miss, whereas resolve_step_paths falls back to a synthesized click and
# says nothing at all. The reported symptom is exactly what that looks like
# from a chair: "the beacons activate but not the footsteps".
#
# Every .wav in the source directory is staged, and the count is checked
# again after staging.
$footstepSource = Join-Path $project 'sounds/footsteps'
if (-not (Test-Path -LiteralPath $footstepSource -PathType Container)) {
    throw "No sounds/footsteps directory at $footstepSource. Footsteps default ON; a release without them plays a synthesized click and reports nothing."
}
$footstepFiles = @(Get-ChildItem -LiteralPath $footstepSource -File -Filter '*.wav' | Sort-Object Name)
if ($footstepFiles.Count -eq 0) {
    throw "sounds/footsteps contains no .wav files. Refusing to build a release whose footsteps would silently fall back to a synthesized click."
}
foreach ($file in $footstepFiles) {
    Copy-ApprovedFile ("sounds/footsteps/" + $file.Name)
}
Write-Output "Staged $($footstepFiles.Count) footstep recordings."

# Required by CC-BY 4.0 for the Mossy4 pack under Companion/assets/.
Copy-ApprovedFile 'sounds/_readme_and_license.txt'

# Version stamp. Written into the archive rather than only into its file
# name so an installed copy can say which build it is -- which is what an
# updater has to compare against, and what a bug report needs to quote.
Set-Content -LiteralPath (Join-Path $stage 'VERSION') -Value $Version -Encoding ascii

# The bundled interpreter. Without this the recipient's first instruction is
# "go and install Python 3.12" -- not merely 3.12-or-newer, because
# dolphin-memory-engine publishes no wheel past it, so anyone already on
# 3.13 had to be talked into installing an older one alongside. That was the
# hardest step in the whole process and it came first. build_runtime.py
# stages CPython's official embeddable package with every required package
# already inside it, and verifies the result by running the staged
# interpreter itself; a release that reaches the next line needs no Python
# on the machine it lands on, and no internet connection to set itself up.
$pythonForBuild = Join-Path $project 'Companion/.venv/Scripts/python.exe'
if ($NoRuntime) {
    Write-Warning ('-NoRuntime: this archive has no bundled interpreter and ' +
        'is not fit to hand to anyone.')
} elseif (-not (Test-Path -LiteralPath $pythonForBuild -PathType Leaf)) {
    throw ("No .venv interpreter at $pythonForBuild. The bundled runtime is " +
        "built by installing wheels for the interpreter running pip, so a " +
        "matching 3.12 is required here. Run Setup.cmd in the checkout first, " +
        "or pass -NoRuntime for a code-only archive.")
} else {
    Write-Output 'Staging the bundled Python runtime ...'
    & $pythonForBuild (Join-Path $PSScriptRoot 'build_runtime.py') `
        --target (Join-Path $stage 'Runtime') `
        --requirements (Join-Path $project 'Companion/requirements.txt') `
        --companion (Join-Path $stage 'Companion') `
        --cache $runtimeCache
    if ($LASTEXITCODE -ne 0) {
        throw 'Staging the bundled Python runtime failed.'
    }
}

$forbiddenExtensions = @('.iso', '.rvz', '.wbfs', '.gcz', '.wia', '.ciso', '.nfs', '.tgc', '.gci', '.sav')
$forbiddenNames = @('_dialogue_extraction', 'logs', '.venv', 'research', 'personal music overrides', 'private music overrides')
$violations = Get-ChildItem -LiteralPath $stage -Recurse -Force | Where-Object {
    ($_.PSIsContainer -and $forbiddenNames -contains $_.Name.ToLowerInvariant()) -or
    (-not $_.PSIsContainer -and $forbiddenExtensions -contains $_.Extension.ToLowerInvariant())
}
if ($violations) {
    $names = ($violations.FullName -join [Environment]::NewLine)
    throw "Release safety check failed:`n$names"
}

# Completeness check: every beacon category the STAGED code declares must
# have its sound staged too. Read out of the staged npc_beacons.py rather
# than repeated as a literal list here, so adding a seventh category later
# fails the build instead of shipping another silent startup crash.
$beaconSource = Get-Content -LiteralPath (Join-Path $stage 'Companion/battle_narrator/npc_beacons.py') -Raw
$block = [regex]::Match(
    $beaconSource, 'PASSIVE_BEACON_SOUND_FILES\s*=\s*\{(?<body>[^}]*)\}')
if (-not $block.Success) {
    throw 'Could not read PASSIVE_BEACON_SOUND_FILES from the staged npc_beacons.py.'
}
$declared = [regex]::Matches($block.Groups['body'].Value, '"(?<file>[^"]+\.wav)"') |
    ForEach-Object { $_.Groups['file'].Value }
if (-not $declared) {
    throw 'PASSIVE_BEACON_SOUND_FILES parsed as empty; refusing to build.'
}
$missingBeaconSounds = $declared | Where-Object {
    -not (Test-Path -LiteralPath (Join-Path $stage (Join-Path 'sounds' $_)) -PathType Leaf)
}
if ($missingBeaconSounds) {
    throw ("Release is missing beacon sounds the code requires: " +
        ($missingBeaconSounds -join ', ') +
        ". The narrator would start and then die on the first beacon.")
}

# The footstep counterpart. Presence alone is not the question here: what
# the player hears depends on resolve_step_paths finding readable WAVs and
# being able to cache a 16-bit copy of each, and if any of that fails it
# returns one synthesized click and carries on silently. So the count is
# checked, rather than assumed from the copy loop above.
$stagedFootsteps = @(Get-ChildItem -LiteralPath (Join-Path $stage 'sounds/footsteps') -File -Filter '*.wav' -ErrorAction SilentlyContinue)
if ($stagedFootsteps.Count -ne $footstepFiles.Count) {
    throw ("Staged $($stagedFootsteps.Count) footstep recordings but the " +
        "project has $($footstepFiles.Count). A release short of them " +
        "plays a synthesized click and reports nothing.")
}

# Import check on the STAGED tree. The allowlist is a hand-maintained list
# of files, so the failure it invites is shipping a module whose import
# target was left off -- which surfaces as a traceback on the recipient's
# first launch and nowhere earlier. Compiling every staged module catches
# syntax problems, and importing the two setup-path entry points (the only
# ones that reach a recipient before any third-party package is installed)
# catches a missing local import.
#
# Run under the STAGED RUNTIME when there is one, not under the project's
# .venv. The two are not interchangeable, and assuming they were shipped a
# release that could not start: CPython's embeddable package omits `venv`,
# `ensurepip` and `tkinter`, so `setup_companion.py`'s module-level
# `import venv` -- perfectly fine in the .venv this check used to run in --
# raised ModuleNotFoundError on the recipient's machine before setup
# printed a single line. The check is only worth anything if it runs on the
# interpreter the recipient will actually use.
$stagedCompanion = Join-Path $stage 'Companion'
$stagedRuntime = Join-Path $stage 'Runtime/python.exe'
if (Test-Path -LiteralPath $stagedRuntime -PathType Leaf) {
    $pythonForCheck = $stagedRuntime
} else {
    $pythonForCheck = Join-Path $project 'Companion/.venv/Scripts/python.exe'
}
if (Test-Path -LiteralPath $pythonForCheck -PathType Leaf) {
    $check = & $pythonForCheck -c @"
import compileall, importlib.util, pathlib, sys
staged = pathlib.Path(sys.argv[1])
if not compileall.compile_dir(str(staged), quiet=2, force=True):
    print('a staged module failed to compile'); raise SystemExit(1)
sys.path.insert(0, str(staged))
for name in ('setup_companion', 'launch_accessible', 'bootstrap_game_data'):
    try:
        importlib.import_module(name)
    except Exception as exc:
        print(f'{name} does not import from the staged tree: {exc}')
        raise SystemExit(1)

# Footsteps, asked of the staged tree the way the runtime will ask.
#
# The count check earlier proves the files were copied. This proves they
# are usable: resolve_step_paths has to find them through resolve_sound_dir,
# open each as a WAV, and cache a 16-bit copy of the 24-bit recordings. If
# any step fails it returns a single synthesized click instead and logs
# nothing, so the player hears working beacons and no footsteps -- the exact
# symptom this check exists to make impossible to ship.
import tempfile
from battle_narrator.npc_beacons import resolve_sound_dir
from battle_narrator.terrain_footsteps import resolve_step_paths
sound_dir = resolve_sound_dir(staged)
source_steps = sorted((sound_dir / 'footsteps').glob('*.wav'))
if not source_steps:
    print(f'no footstep recordings under {sound_dir / "footsteps"}')
    raise SystemExit(1)
with tempfile.TemporaryDirectory() as scratch:
    resolved = resolve_step_paths(scratch, sound_dir / 'footsteps')
    fallback = [p for p in resolved if p.name == '_terrain_step_base.wav']
    if fallback:
        print('resolve_step_paths fell back to a synthesized click; the '
              'release would ship with no real footsteps')
        raise SystemExit(1)
    if len(resolved) != len(source_steps):
        print(f'resolved {len(resolved)} footsteps from '
              f'{len(source_steps)} recordings')
        raise SystemExit(1)
print(f'ok ({len(resolved)} footsteps)')
"@ $stagedCompanion
    if ($LASTEXITCODE -ne 0) {
        throw "Staged tree failed its import check: $check"
    }
    # compileall leaves __pycache__ behind; it must not ship.
    Get-ChildItem -LiteralPath $stage -Recurse -Force -Directory |
        Where-Object { $_.Name -eq '__pycache__' } |
        Remove-Item -Recurse -Force
} else {
    Write-Warning ("No interpreter at $pythonForCheck -- skipping the " +
        "staged import check.")
}

Compress-Archive -LiteralPath $stage -DestinationPath $archive -CompressionLevel Optimal
$hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
Set-Content -LiteralPath ($archive + '.sha256.txt') -Value "$hash  $([IO.Path]::GetFileName($archive))" -Encoding ascii
Write-Output "Created accessibility-only release: $archive"
Write-Output "SHA-256: $hash"
