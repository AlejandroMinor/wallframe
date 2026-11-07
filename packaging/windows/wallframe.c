/* wallframe.exe: starts the Python beside it. Windows finds the DLLs beside that Python
   first, so the PATH stays the user's, for the programs post_command runs. */
#include <windows.h>
#include <wchar.h>

#define LONGEST 32768

static wchar_t folder[LONGEST], command[LONGEST];

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR arguments, int show)
{
    STARTUPINFOW startup = {sizeof startup};
    PROCESS_INFORMATION process;
    wchar_t *last;

    (void)instance, (void)previous, (void)arguments, (void)show;
    GetModuleFileNameW(NULL, folder, LONGEST);
    last = wcsrchr(folder, L'\\');
    if (last)
        *last = L'\0';
    swprintf(command, LONGEST, L"\"%ls\\bin\\pythonw.exe\" \"%ls\\wallframe.py\"", folder, folder);
    /* MSYS2's Python reads these: a package must not follow a shell's settings. */
    SetEnvironmentVariableW(L"MSYSTEM", NULL);
    SetEnvironmentVariableW(L"PYTHONHOME", NULL);
    SetEnvironmentVariableW(L"PYTHONPATH", NULL);
    if (!CreateProcessW(NULL, command, NULL, NULL, FALSE, 0, NULL, folder, &startup, &process)) {
        MessageBoxW(NULL, L"Could not start bin\\pythonw.exe. Reinstall wallframe.", L"wallframe",
                    MB_ICONERROR);
        return 1;
    }
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return 0;
}
