#!/bin/bash
# Builds dist/wallframe, which runs with nothing else installed. In MSYS2's UCRT64 shell,
# from the repository, with the packages of .github/workflows/package-windows.yml.
# WALLFRAME_NO_LAUNCHER=1 leaves out wallframe.exe, on a machine without gcc.
set -euo pipefail

here=packaging/windows
out=dist/wallframe
prefix=${MINGW_PREFIX:-/ucrt64}
python=$(python -c 'import sys; print(f"python{sys.version_info[0]}.{sys.version_info[1]}")')

rm -rf "$out"
mkdir -p "$out/bin" "$out/lib/$python/site-packages" "$out/lib/girepository-1.0" \
         "$out/share/glib-2.0/schemas" "$out/share/icons" "$out/etc" "$out/app"

# Python and what wallframe imports; none of the rest of site-packages.
cp "$prefix/bin/python.exe" "$prefix/bin/pythonw.exe" "$out/bin/"
tar -C "$prefix/lib/$python" --exclude=site-packages --exclude=test --exclude=tests \
    --exclude=idlelib --exclude=tkinter --exclude=turtledemo --exclude=ensurepip \
    --exclude=lib2to3 --exclude=venv --exclude=__pycache__ --exclude=Tools \
    --exclude='config-*' --exclude=pydoc_data --exclude=sqlite3 --exclude=curses \
    --exclude='_tkinter*' --exclude='_curses*' --exclude='_sqlite3*' -cf - . \
    | tar -C "$out/lib/$python" -xmf -
for module in gi cairo PIL; do
    cp -r "$prefix/lib/$python/site-packages/$module" "$out/lib/$python/site-packages/"
done

# What GTK opens by name. The spawn helpers are programs GLib starts.
for typelib in GLib-2.0 GLibWin32-2.0 GObject-2.0 GModule-2.0 Gio-2.0 GioWin32-2.0 cairo-1.0 \
               freetype2-2.0 HarfBuzz-0.0 Pango-1.0 PangoCairo-1.0 GdkPixbuf-2.0 Graphene-1.0 \
               Gdk-4.0 GdkWin32-4.0 Gsk-4.0 Gtk-4.0; do
    if [ -f "$prefix/lib/girepository-1.0/$typelib.typelib" ]; then
        cp "$prefix/lib/girepository-1.0/$typelib.typelib" "$out/lib/girepository-1.0/"
    fi
done
cp -r "$prefix/lib/gdk-pixbuf-2.0" "$out/lib/"
if [ -d "$prefix/lib/gio" ]; then cp -r "$prefix/lib/gio" "$out/lib/"; fi
cp "$prefix/share/glib-2.0/schemas/gschemas.compiled" "$out/share/glib-2.0/schemas/"
cp -r "$prefix/share/icons/Adwaita" "$prefix/share/icons/hicolor" "$out/share/icons/"
find "$out/share/icons" -name '*.cache' -delete
if [ -d "$prefix/etc/fonts" ]; then cp -r "$prefix/etc/fonts" "$out/etc/"; fi
for program in gspawn-win64-helper gspawn-win64-helper-console; do
    if [ -f "$prefix/bin/$program.exe" ]; then cp "$prefix/bin/$program.exe" "$out/bin/"; fi
done

python "$here/dlls.py" "$(cygpath -m "$prefix/bin")" "$out"

cp -r src/wallframe "$out/app/"
find "$out/app" -name __pycache__ -type d -prune -exec rm -rf {} +
cp "$here/start.py" "$out/wallframe.py"
cp LICENSE "$out/"
bash "$here/licenses.sh" "$out"
python -m compileall -q "$out/lib/$python" "$out/app" || true  # a file it cannot read is run as it is

if [ -z "${WALLFRAME_NO_LAUNCHER:-}" ]; then
    windres "$here/wallframe.rc" -O coff -o "$here/wallframe.res"
    gcc -municode -mwindows -O2 -s -o "$out/wallframe.exe" "$here/wallframe.c" "$here/wallframe.res"
    rm "$here/wallframe.res"
fi

du -sm "$out"
