#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(cd -- "$script_dir/.." && pwd)

# Codex loads user skills from $HOME/.agents/skills (official Codex docs).
skill_name=delegate-to-deepseek-harness
dest=${1:-"$HOME/.agents/skills/$skill_name"}

# Safety: refuse destinations where an accidental overwrite would be catastrophic.
case "$dest" in
  ""|"/"|/bin|/sbin|/etc|/etc/*|/usr|/usr/*|/var|/var/*|/home|/root|"$HOME"|"$HOME/")
    echo "error: refusing to install over '$dest'" >&2
    exit 1
    ;;
esac

if [[ "$dest" != /* ]]; then
  echo "error: destination must be an absolute path: $dest" >&2
  exit 1
fi

if [[ -e "$dest" && ! -d "$dest" ]]; then
  echo "error: destination exists and is not a directory: $dest" >&2
  exit 1
fi

# Merge into the destination. Existing extra files are preserved; this script
# never deletes or mirrors the destination tree.
mkdir -p "$dest"
cp -R "$repo_dir/SKILL.md" "$dest/SKILL.md"

for path in agents references scripts; do
  mkdir -p "$dest/$path"
  cp -R "$repo_dir/$path/." "$dest/$path/"
done

chmod +x "$dest"/scripts/*.sh

echo "Merged into: $dest"
echo 'Invoke with: $delegate-to-deepseek-harness'
