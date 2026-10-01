import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / ".local/management-center"
REVISION = "a7ec312fbbb0a13f3a580ee0c7e29228a07c8867"
REPOSITORY = "https://github.com/router-for-me/Cli-Proxy-API-Management-Center.git"


def apply_theme(source, theme):
    patches = {
        "src/styles/global.scss": "minimal.scss",
        "src/features/dashboard/dashboard.module.scss": "dashboard.scss",
        "src/pages/LoginPage.module.scss": "login.scss",
    }
    for target, style in patches.items():
        path = source / target
        if not path.is_file():
            raise RuntimeError(f"Official theme target missing: {target}")
        original = subprocess.check_output(["git", "show", f"{REVISION}:{target}"], cwd=source).decode()
        path.write_text(original + "\n" + (theme / style).read_text())


def main():
    if not shutil.which("bun") or not shutil.which("git"):
        raise RuntimeError("Bun 1.3.14 and Git are required")
    if subprocess.check_output(["bun", "--version"], text=True).strip() != "1.3.14":
        raise RuntimeError("Official source requires Bun 1.3.14")
    SOURCE.parent.mkdir(parents=True, exist_ok=True)
    if not SOURCE.exists():
        subprocess.run(["git", "clone", REPOSITORY, str(SOURCE)], check=True)
        subprocess.run(["git", "checkout", "--detach", REVISION], cwd=SOURCE, check=True)
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=SOURCE, text=True).strip()
    if actual != REVISION:
        raise RuntimeError(f"Expected upstream {REVISION}, found {actual}")
    apply_theme(SOURCE, ROOT / "management-theme")
    patch = ROOT / "management-theme/usage.patch"
    if not patch.is_file():
        raise RuntimeError("Usage integration patch is missing")
    applied = subprocess.run(["git", "apply", "--reverse", "--check", str(patch)], cwd=SOURCE, capture_output=True)
    if applied.returncode:
        subprocess.run(["git", "apply", "--check", str(patch)], cwd=SOURCE, check=True)
        subprocess.run(["git", "apply", str(patch)], cwd=SOURCE, check=True)
    subprocess.run(["bun", "install", "--frozen-lockfile"], cwd=SOURCE, check=True)
    # Upstream tests leak i18n state between files; fresh globals keep every assertion enabled.
    subprocess.run(["bun", "test", "--isolate"], cwd=SOURCE, check=True)
    subprocess.run(["bun", "run", "lint"], cwd=SOURCE, check=True)
    subprocess.run(["bun", "run", "build"], cwd=SOURCE, check=True)
    output = ROOT / ".local/management.html"
    shutil.copyfile(SOURCE / "dist/index.html", output)
    print(output)


if __name__ == "__main__":
    main()
