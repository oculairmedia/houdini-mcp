"""Create an owner-only Windows file before any credential bytes are written."""

import ctypes
import os
from ctypes import wintypes as w


def windows_private_fd(path):
    """CREATE_NEW with a protected current-user/System DACL; never inherit a broad ACL."""
    import msvcrt

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.LocalFree.argtypes = [w.HLOCAL]
    advapi.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
    advapi.GetTokenInformation.argtypes = [
        w.HANDLE,
        w.DWORD,
        w.LPVOID,
        w.DWORD,
        ctypes.POINTER(w.DWORD),
    ]
    advapi.ConvertSidToStringSidW.argtypes = [w.LPVOID, ctypes.POINTER(w.LPWSTR)]
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        w.LPCWSTR,
        w.DWORD,
        ctypes.POINTER(w.LPVOID),
        ctypes.POINTER(w.DWORD),
    ]

    class Attributes(ctypes.Structure):
        _fields_ = [("length", w.DWORD), ("descriptor", w.LPVOID), ("inherit", w.BOOL)]

    kernel.CreateFileW.argtypes = [
        w.LPCWSTR,
        w.DWORD,
        w.DWORD,
        ctypes.POINTER(Attributes),
        w.DWORD,
        w.DWORD,
        w.HANDLE,
    ]
    kernel.CreateFileW.restype = w.HANDLE
    token, sid_text, descriptor = w.HANDLE(), w.LPWSTR(), w.LPVOID()
    handle = None
    try:
        if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
            raise ctypes.WinError(ctypes.get_last_error())
        size = w.DWORD()
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        sid = ctypes.cast(buffer, ctypes.POINTER(w.LPVOID))[0]
        if not advapi.ConvertSidToStringSidW(sid, ctypes.byref(sid_text)):
            raise ctypes.WinError(ctypes.get_last_error())
        sddl = f"D:P(A;;FA;;;SY)(A;;FA;;;{sid_text.value})"
        if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(descriptor), None
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        attributes = Attributes(ctypes.sizeof(Attributes), descriptor, False)
        handle = kernel.CreateFileW(
            str(path), 0x40000000, 0, ctypes.byref(attributes), 1, 0x80, None
        )
        if handle == w.HANDLE(-1).value:
            handle = None
            raise ctypes.WinError(ctypes.get_last_error())
        fd = msvcrt.open_osfhandle(handle, os.O_WRONLY | os.O_BINARY)
        handle = None  # Ownership transferred to the CRT fd.
        return fd
    finally:
        if handle is not None:
            kernel.CloseHandle(handle)
        if descriptor:
            kernel.LocalFree(descriptor)
        if sid_text:
            kernel.LocalFree(sid_text)
        if token:
            kernel.CloseHandle(token)
