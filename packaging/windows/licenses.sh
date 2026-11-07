#!/bin/bash
# Writes what the package at $1 bundles: THIRD-PARTY.txt, one line per MSYS2 package with
# its version and license, and each package's license files in licenses/.
set -euo pipefail

out=$1
prefix=${MINGW_PREFIX:-/ucrt64}
python=$(ls -d "$prefix"/lib/python3.* | head -1)

{
    for file in "$out"/bin/*; do
        name=$(basename "$file")
        if [ -f "$prefix/bin/$name" ]; then echo "$prefix/bin/$name"; fi
    done
    echo "$python/site-packages/PIL/__init__.py"
    echo "$python/site-packages/gi/__init__.py"
    echo "$python/site-packages/cairo/__init__.py"
    echo "$prefix/share/icons/Adwaita/index.theme"
} | while read -r path; do pacman -Qqo "$path" 2>/dev/null || true; done | sort -u > "$out/packages.tmp"

{
    echo "wallframe for Windows bundles these programs and libraries, unchanged, as MSYS2"
    echo "builds them. Each keeps its own license: see the licenses folder, and"
    echo "https://packages.msys2.org for each one's source code."
    echo
    while read -r package; do
        about=$(LC_ALL=C pacman -Qi "$package")
        version=$(sed -n 's/^Version *: *//p' <<< "$about")
        license=$(sed -n 's/^Licenses *: *//p' <<< "$about" | sed 's/spdx://g')
        printf '%-30s %-22s %s\n' "${package#mingw-w64-ucrt-x86_64-}" "$version" "$license"
    done < "$out/packages.tmp"
} > "$out/THIRD-PARTY.txt"

mkdir -p "$out/licenses"
while read -r package; do
    short=${package#mingw-w64-ucrt-x86_64-}
    if [ -d "$prefix/share/licenses/$short" ]; then
        cp -r "$prefix/share/licenses/$short" "$out/licenses/"
    fi
done < "$out/packages.tmp"
rm "$out/packages.tmp"
echo "$(($(wc -l < "$out/THIRD-PARTY.txt") - 4)) packages, $(ls "$out/licenses" | wc -l) with license files"
