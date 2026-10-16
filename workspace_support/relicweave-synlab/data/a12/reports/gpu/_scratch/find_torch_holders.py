"""Find processes that currently have torch DLLs mapped (they block pip's file writes).

A process that ran ``import torch`` on the broken tree loads ``c10.dll`` successfully and
only then fails on ``caffe2_nvrtc.dll``; it keeps ``c10.dll`` mapped for its whole lifetime.
That is what turns a broken torch into an un-reinstallable one.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

TH32CS_SNAPPROCESS = 0x00000002
MAX_PATH = 260
LIST_MODULES_ALL = 0x03

k32 = ctypes.WinDLL("kernel32", use_last_error=True)


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_char * MAX_PATH)]


class MODULEENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("th32ModuleID", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("GlblcntUsage", wintypes.DWORD),
                ("ProccntUsage", wintypes.DWORD),
                ("modBaseAddr", ctypes.POINTER(ctypes.c_byte)),
                ("modBaseSize", wintypes.DWORD), ("hModule", wintypes.HMODULE),
                ("szModule", ctypes.c_char * 256), ("szExePath", ctypes.c_char * MAX_PATH)]


def pids() -> list[tuple[int, str]]:
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    entry = PROCESSENTRY32()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
    out = []
    if k32.Process32First(snap, ctypes.byref(entry)):
        while True:
            out.append((int(entry.th32ProcessID), entry.szExeFile.decode(errors="replace")))
            if not k32.Process32Next(snap, ctypes.byref(entry)):
                break
    k32.CloseHandle(snap)
    return out


def modules(pid: int) -> list[str]:
    snap = k32.CreateToolhelp32Snapshot(0x00000008 | 0x00000010, pid)  # MODULE|PROCESS
    if snap == -1:
        return []
    entry = MODULEENTRY32()
    entry.dwSize = ctypes.sizeof(MODULEENTRY32)
    out = []
    if k32.Module32First(snap, ctypes.byref(entry)):
        while True:
            out.append(entry.szExePath.decode(errors="replace"))
            if not k32.Module32Next(snap, ctypes.byref(entry)):
                break
    k32.CloseHandle(snap)
    return out


needles = ("torch", "c10", "caffe2", "torch_cpu", "torch_cuda")
hits = []
for pid, name in pids():
    if pid == 0:
        continue
    mods = modules(pid)
    matched = [m for m in mods
               if any(n in m.lower() for n in needles) and "site-packages" in m.lower()]
    if matched:
        hits.append((pid, name, matched))
print(f"processes with torch DLLs mapped: {len(hits)}")
for pid, name, matched in hits:
    print(f"  pid={pid:<8} {name:<20} {len(matched)} module(s)")
    for m in matched[:4]:
        print(f"        {m}")
sys.exit(0)
