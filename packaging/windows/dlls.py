"""Copies into a package every DLL it needs from MSYS2, read from the binaries themselves.

python dlls.py SOURCE_BIN PACKAGE

Starts from each .exe, .pyd and .dll under PACKAGE, and from the libraries its
.typelib files name, which GObject Introspection opens by name at run time, so no
binary links them. Follows what each of those imports, delayed imports too. DLLs
SOURCE_BIN does not have belong to Windows, and stay out.
"""

import os
import re
import shutil
import struct
import sys

_IMPORTS, _DELAYED = 1, 13  # data directories of the PE header
_LIBRARY = re.compile(rb"lib[\w.+-]*?\.dll", re.IGNORECASE)


def imports(path):
    """The names of the DLLs the PE file at `path` imports, in lower case."""
    with open(path, "rb") as f:
        data = f.read()
    header = struct.unpack_from("<I", data, 0x3C)[0]
    sections, optional_size = struct.unpack_from("<xxHxxxxxxxxxxxxHxx", data, header + 4)
    optional = header + 24
    directories = optional + (112 if struct.unpack_from("<H", data, optional)[0] == 0x20B else 96)
    table = [struct.unpack_from("<II", data, optional + optional_size + 40 * index + 8)
             + struct.unpack_from("<II", data, optional + optional_size + 40 * index + 16)
             for index in range(sections)]

    def offset(address):
        """Where the address in memory is in the file."""
        for size, start, raw_size, raw in table:
            if start <= address < start + max(size, raw_size):
                return address - start + raw
        raise ValueError(f"{path}: address {address:#x} is in no section")

    def name_at(address):
        start = offset(address)
        return data[start:data.index(b"\0", start)].decode("ascii").lower()

    found = set()
    for directory, step, field in ((_IMPORTS, 20, 12), (_DELAYED, 32, 4)):
        address = struct.unpack_from("<I", data, directories + 8 * directory)[0]
        if not address:
            continue
        entry = offset(address)
        while True:
            name = struct.unpack_from("<I", data, entry + field)[0]
            if not name:
                break
            found.add(name_at(name))
            entry += step
    return found


def roots(package):
    """(binaries under `package`, the library names its typelibs ask for)."""
    binaries, libraries = [], set()
    for folder, _folders, names in os.walk(package):
        for name in names:
            path = os.path.join(folder, name)
            if name.lower().endswith((".exe", ".pyd", ".dll")):
                binaries.append(path)
            elif name.endswith(".typelib"):
                with open(path, "rb") as f:
                    libraries |= {found.decode("ascii").lower()
                                  for found in _LIBRARY.findall(f.read())}
    return binaries, libraries


def main():
    source, package = sys.argv[1:3]
    available = {name.lower(): os.path.join(source, name) for name in os.listdir(source)}
    binaries, wanted = roots(package)
    for binary in binaries:
        wanted |= imports(binary)
    copied, waiting = set(), list(wanted)
    while waiting:
        name = waiting.pop()
        if name in copied or name not in available:
            continue
        copied.add(name)
        waiting.extend(imports(available[name]))
    target = os.path.join(package, "bin")
    for name in sorted(copied):
        shutil.copy2(available[name], target)
    print(f"{len(copied)} DLLs from {len(binaries)} binaries")


if __name__ == "__main__":
    main()
