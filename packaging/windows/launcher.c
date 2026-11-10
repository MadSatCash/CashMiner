#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>
#include <wchar.h>

/* Start only the private runtime beside this executable. No PATH lookup. */
int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR args, int show) {
    wchar_t base[32768], python[32768], script[32768], command[32768];
    DWORD length = GetModuleFileNameW(NULL, base, 32768);
    if (!length || length >= 32768) return 1;
    wchar_t *slash = wcsrchr(base, L'\\');
    if (!slash) return 1;
    *slash = L'\0';
    if (swprintf(python, 32768, L"%ls\\_internal\\python\\pythonw.exe", base) < 0 ||
        swprintf(script, 32768, L"%ls\\_internal\\app\\CashMiner.pyw", base) < 0 ||
        swprintf(command, 32768, L"\"%ls\" -X utf8 -B \"%ls\"", python, script) < 0) return 1;
    if (GetFileAttributesW(python) == INVALID_FILE_ATTRIBUTES ||
        GetFileAttributesW(script) == INVALID_FILE_ATTRIBUTES) {
        MessageBoxW(NULL,
            L"Extraé el ZIP completo y abrí CashMiner.exe desde esa carpeta.\n"
            L"Extract the entire ZIP and open CashMiner.exe from that folder.",
            L"CashMiner - Paquete incompleto / Incomplete package", MB_OK | MB_ICONERROR);
        return 2;
    }
    STARTUPINFOW startup = {0};
    PROCESS_INFORMATION process = {0};
    startup.cb = sizeof(startup);
    if (!CreateProcessW(python, command, NULL, NULL, FALSE, CREATE_NO_WINDOW,
                        NULL, base, &startup, &process)) {
        wchar_t message[512];
        swprintf(message, 512,
            L"No se pudo iniciar CashMiner (Windows %lu).\n"
            L"Could not start CashMiner (Windows %lu).", GetLastError(), GetLastError());
        MessageBoxW(NULL, message, L"CashMiner", MB_OK | MB_ICONERROR);
        return 3;
    }
    CloseHandle(process.hThread);
    WaitForSingleObject(process.hProcess, INFINITE);
    DWORD result = 1;
    GetExitCodeProcess(process.hProcess, &result);
    CloseHandle(process.hProcess);
    return (int)result;
}
