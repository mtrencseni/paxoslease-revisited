# Cross-Platform Tooling Guide for the PaxosLease Paper

This covers the verification toolchain: Java, the TLA+ tools, TLAPS, and Python. Building the paper additionally needs a LaTeX distribution providing `latexmk` and the `elsarticle` class; `make pdf` is the only target that requires it.

The workflow is supported on Windows, macOS, and Linux. The core TLA+ tools are Java programs, and official TLAPS installers are available for all three platforms.

## Shared requirements

All platforms need:

1. **A Java 17 JDK.** Current TLA+ tools require Java 11 or newer; Java 17 is a conservative cross-platform choice.
2. **Current `tla2tools.jar`.** Download it from the official [TLA+ releases](https://github.com/tlaplus/tlaplus/releases). It contains SANY, TLC, and the PlusCal translator.
3. **TLAPS.** Install it separately from the official [TLAPS downloads](https://proofs.tlapl.us/doc/web/content/Download/Binaries.html).
4. **Python 3 with virtual-environment support.** Install `pytest` and Hypothesis inside the project environment.
5. **Git.** Strongly recommended for preserving experiments and producing a publishable artifact.
6. **A command runner.** GNU Make is convenient on macOS/Linux. On Windows, a PowerShell script can provide the same reproducible commands.

The Eclipse-based TLA+ Toolbox is not required and is no longer actively maintained. The command-line tools are sufficient. VS Code with the TLA+ extension is optional.

## Windows 10/11

### Install Java and Git

Using `winget` in PowerShell:

```powershell
winget install EclipseAdoptium.Temurin.17.JDK
winget install Git.Git
```

Open a new terminal and verify:

```powershell
java -version
git --version
```

If Python is not already installed, install it from python.org or with `winget`, ensuring the launcher is available as `py`.

### Install TLA+ tools

Download `tla2tools.jar` from the official TLA+ releases and place it at:

```text
tools\tla2tools.jar
```

Verify in PowerShell:

```powershell
java -jar tools\tla2tools.jar -help
java -cp tools\tla2tools.jar tla2sany.SANY -help
java -cp tools\tla2tools.jar pcal.trans -help
Get-FileHash tools\tla2tools.jar -Algorithm SHA256
```

### Install TLAPS

Use the official Windows TLAPS installer. Open a new terminal afterward and verify:

```powershell
tlapm --version
```

If `tlapm` is not found, add the installer’s binary directory to the user `PATH` and reopen PowerShell.

### Create the Python environment

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install pytest hypothesis
pytest --version
python -c "import hypothesis; print(hypothesis.__version__)"
```

If PowerShell blocks the activation script, either adjust the current-user execution policy deliberately or run the environment’s Python directly as `.\.venv\Scripts\python.exe`.

Use `scripts\verify.ps1` instead of requiring GNU Make if desired.

## macOS

These instructions work on Intel and Apple Silicon Macs. The Java-based TLA+ tools run on either architecture. Check the architecture offered by the current TLAPS installer; an Intel-only TLAPS build may require Rosetta 2 on Apple Silicon.

### Install prerequisites

Install Apple command-line tools if they are absent:

```bash
xcode-select --install
```

Install Homebrew if desired, then install a Java 17 JDK and Python. One common setup is:

```bash
brew install --cask temurin@17
brew install python git
```

Verify:

```bash
java -version
python3 --version
git --version
```

An official Temurin/Adoptium `.pkg` is an equivalent alternative to Homebrew.

### Install TLA+ tools

Download the current `tla2tools.jar` into `tools/tla2tools.jar`, then verify:

```bash
java -jar tools/tla2tools.jar -help
java -cp tools/tla2tools.jar tla2sany.SANY -help
java -cp tools/tla2tools.jar pcal.trans -help
shasum -a 256 tools/tla2tools.jar
```

### Install TLAPS

Use the official macOS TLAPS installer and verify:

```bash
tlapm --version
```

If macOS quarantine blocks a legitimately downloaded official installer or binary, inspect the signing/source and resolve it through normal macOS security controls rather than disabling Gatekeeper globally.

### Create the Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install pytest hypothesis
pytest --version
python -c "import hypothesis; print(hypothesis.__version__)"
```

The system `make` supplied through Apple command-line tools is sufficient for a small project Makefile.

## Linux: Debian 12

### Install prerequisites

```bash
sudo apt update
sudo apt install openjdk-21-jdk python3-venv git make curl unzip
```

Verify:

```bash
java -version
python3 --version
git --version
make --version
```

### Install TLA+ tools

Download the current `tla2tools.jar` from the official TLA+ releases into `tools/tla2tools.jar`, then verify:

```bash
java -jar tools/tla2tools.jar -help
java -cp tools/tla2tools.jar tla2sany.SANY -help
java -cp tools/tla2tools.jar pcal.trans -help
sha256sum tools/tla2tools.jar
```

### Install TLAPS

Use the official Linux TLAPS installer appropriate for the machine architecture. Follow the installer’s bundled instructions, then verify:

```bash
tlapm --version
```

### Create the Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install pytest hypothesis
pytest --version
python -c "import hypothesis; print(hypothesis.__version__)"
```

## Optional tools on any platform

- **VS Code and the TLA+ extension:** convenient editing and model exploration.
- **Graphviz:** useful only if state-graph visualization adds value.
- **A Python linter such as Ruff:** useful for maintenance, but not part of the correctness argument.
- **GitHub Actions or another Linux CI runner:** useful after local verification is stable.

No database, container runtime, web framework, or HTTP server is required. The reference implementation should begin as a deterministic in-process simulator.

## Suggested project commands

On macOS/Linux, expose commands similar to:

```bash
make parse
make check
make prove
make test
make all
```

On Windows, expose equivalent PowerShell commands:

```powershell
.\scripts\verify.ps1 parse
.\scripts\verify.ps1 check
.\scripts\verify.ps1 prove
.\scripts\verify.ps1 test
.\scripts\verify.ps1 all
```

Underneath, the essential commands are:

```text
SANY:  java -cp tools/tla2tools.jar tla2sany.SANY <module>.tla
TLC:   java -jar tools/tla2tools.jar -config <model>.cfg <module>.tla
TLAPS: tlapm <proof-module>.tla
Tests: pytest
```

Run TLC from the specification directory or set module search paths consistently so imported modules resolve identically across platforms.

## Reproducibility record

Save the following with the final results.

Windows:

```powershell
java -version
tlapm --version
python --version
pytest --version
Get-FileHash tools\tla2tools.jar -Algorithm SHA256
git rev-parse HEAD
```

macOS:

```bash
java -version
tlapm --version
python --version
pytest --version
shasum -a 256 tools/tla2tools.jar
git rev-parse HEAD
```

Debian/Linux:

```bash
java -version
tlapm --version
python --version
pytest --version
sha256sum tools/tla2tools.jar
git rev-parse HEAD
```

Also record the operating-system version, CPU architecture, exact TLC configuration constants, enabled constraints, worker count, and complete verification commands.
