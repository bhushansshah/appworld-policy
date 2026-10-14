"""Keep the scenario files encrypted in git.

Scenario files contain AppWorld data (names, emails, amounts), which may only be shared publicly in encrypted
form. So policy_scenarios/scenarios/ is git-ignored and committed as the encrypted bundle
policy_scenarios/.source/scenarios.bundle, the same way AppWorld ships its own task generators.

Usage (from the repo root):
    .venv/bin/python -m policy_scenarios.bundle unpack   # bundle -> policy_scenarios/scenarios/ (after cloning)
    .venv/bin/python -m policy_scenarios.bundle pack     # policy_scenarios/scenarios/ -> bundle (before committing)
    .venv/bin/python -m policy_scenarios.bundle check    # fails if the bundle and the folder differ
"""

import argparse
import sys
from pathlib import Path

from appworld.common.constants import PASSWORD, SALT
from appworld.common.crypto import bundle_file_path_to_content, pack_bundle, unpack_bundle

BASE_DIRECTORY = Path(__file__).resolve().parent
SCENARIOS = "scenarios"
BUNDLE_PATH = BASE_DIRECTORY / ".source" / "scenarios.bundle"


def folder_content() -> dict[str, str]:
    return {
        str(path.relative_to(BASE_DIRECTORY)): path.read_text()
        for path in sorted((BASE_DIRECTORY / SCENARIOS).rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and not path.name.startswith(".")
    }


def bundle_content() -> dict[str, str]:
    if not BUNDLE_PATH.exists():
        return {}
    return bundle_file_path_to_content(str(BUNDLE_PATH), PASSWORD, SALT)


def pack() -> None:
    # Encryption gives different bytes each time, so only rewrite the bundle when the files changed.
    pack_bundle(str(BUNDLE_PATH) + ".new", str(BASE_DIRECTORY), [SCENARIOS], PASSWORD, SALT)
    new_bundle = Path(str(BUNDLE_PATH) + ".new")
    if bundle_file_path_to_content(str(new_bundle), PASSWORD, SALT) == bundle_content():
        new_bundle.unlink()
        print(f"{BUNDLE_PATH.relative_to(BASE_DIRECTORY.parent)} is already up to date.")
        return
    new_bundle.replace(BUNDLE_PATH)
    print(f"Packed {len(folder_content())} files into {BUNDLE_PATH.relative_to(BASE_DIRECTORY.parent)}.")


def unpack() -> None:
    file_paths = unpack_bundle(str(BUNDLE_PATH), str(BASE_DIRECTORY), PASSWORD, SALT)
    print(f"Unpacked {len(file_paths)} files into {(BASE_DIRECTORY / SCENARIOS).relative_to(BASE_DIRECTORY.parent)}.")


def check() -> bool:
    in_bundle, in_folder = bundle_content(), folder_content()
    if in_bundle == in_folder:
        print("The bundle and the scenario files match.")
        return True
    for path in sorted(set(in_bundle) | set(in_folder)):
        if in_bundle.get(path) != in_folder.get(path):
            where = "only in the folder" if path not in in_bundle else "only in the bundle" if path not in in_folder else "differs"
            print(f"  {path}: {where}")
    print("The bundle and the scenario files differ. Run pack (to save the folder) or unpack (to restore it).")
    return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["pack", "unpack", "check"])
    command = parser.parse_args().command
    if command == "pack":
        pack()
    elif command == "unpack":
        unpack()
    elif not check():
        sys.exit(1)


if __name__ == "__main__":
    main()
