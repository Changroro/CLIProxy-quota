import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / ".local/codex-statusline"
REVISION = "a956835d020762cb2b570053af06f643a11c0ecc"


def main():
    SOURCE.parent.mkdir(parents=True, exist_ok=True)
    if not SOURCE.exists():
        subprocess.run(["git", "clone", "--depth", "1", "--branch", "rust-v0.160.0",
                        "https://github.com/openai/codex.git", str(SOURCE)], check=True)
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=SOURCE, text=True).strip()
    if actual != REVISION:
        raise RuntimeError(f"Expected Codex source {REVISION}, found {actual}")
    patch = ROOT / "codex-statusline/codex-0.160.0.patch"
    applied = subprocess.run(["git", "apply", "--reverse", "--check", str(patch)], cwd=SOURCE, capture_output=True)
    if applied.returncode:
        subprocess.run(["git", "apply", "--check", str(patch)], cwd=SOURCE, check=True)
        subprocess.run(["git", "apply", str(patch)], cwd=SOURCE, check=True)
    subprocess.run(["cargo", "build", "--locked", "--profile", "dev-small", "-p", "codex-cli", "--bin", "codex", "-j", "3"], cwd=SOURCE / "codex-rs", check=True)
    subprocess.run(["uvx", "--from", "rust-just", "just", "test", "--cargo-profile", "dev-small", "--locked", "-p", "codex-tui", "-E", "test(cxstatusline)", "-j", "1"], cwd=SOURCE / "codex-rs", check=True)
    subprocess.run([str(SOURCE / "codex-rs/target/dev-small/codex"), "--version"], check=True)


if __name__ == "__main__":
    main()
