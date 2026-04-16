"""
Windows Memory Management — Privilege escalation & RAM cleanup.
Centralise le code ctypes Windows utilisé par model_manager.py et web/app.py.
"""
import sys
import ctypes


def _is_windows():
    return sys.platform == 'win32'


# ===== Constantes =====
SE_PRIVILEGE_ENABLED = 0x00000002
TOKEN_ADJUST_PRIVILEGES = 0x0020
TOKEN_QUERY = 0x0008

# SYSTEM_INFORMATION_CLASS
SystemFileCacheInformation = 0x15          # 21
SystemMemoryListInformation = 0x50         # 80
SystemCombinePhysicalMemoryInformation = 0x82  # 130

# SYSTEM_MEMORY_LIST_COMMAND
MemoryPurgeLowPriorityStandbyList = 1
MemoryPurgeStandbyList = 2
MemoryFlushModifiedList = 3
MemoryEmptyWorkingSets = 4

PROCESS_SET_QUOTA = 0x0100
PROCESS_QUERY_INFORMATION = 0x0400


# ===== Structures ctypes =====
class LUID(ctypes.Structure):
    _fields_ = [("LowPart", ctypes.c_ulong), ("HighPart", ctypes.c_long)]

class LUID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Luid", LUID), ("Attributes", ctypes.c_ulong)]

class TOKEN_PRIVILEGES(ctypes.Structure):
    _fields_ = [("PrivilegeCount", ctypes.c_ulong), ("Privileges", LUID_AND_ATTRIBUTES * 1)]

class SYSTEM_FILECACHE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("CurrentSize", ctypes.c_size_t),
        ("PeakSize", ctypes.c_size_t),
        ("PageFaultCount", ctypes.c_ulong),
        ("MinimumWorkingSet", ctypes.c_size_t),
        ("MaximumWorkingSet", ctypes.c_size_t),
        ("CurrentSizeIncludingTransitionInPages", ctypes.c_size_t),
        ("PeakSizeIncludingTransitionInPages", ctypes.c_size_t),
        ("TransitionRePurposeCount", ctypes.c_ulong),
        ("Flags", ctypes.c_ulong),
    ]

class MEMORY_COMBINE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("Handle", ctypes.c_void_p),
        ("PagesCombined", ctypes.c_size_t),
    ]


# ===== Fonctions =====

def enable_privilege(privilege_name):
    """Active un privilège Windows sur le processus courant. Retourne True si OK."""
    if not _is_windows():
        return False
    kernel32 = ctypes.windll.kernel32
    advapi32 = ctypes.windll.advapi32

    token = ctypes.c_void_p()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(),
        TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY,
        ctypes.byref(token)
    ):
        return False
    luid = LUID()
    if not advapi32.LookupPrivilegeValueW(None, privilege_name, ctypes.byref(luid)):
        kernel32.CloseHandle(token)
        return False
    tp = TOKEN_PRIVILEGES()
    tp.PrivilegeCount = 1
    tp.Privileges[0].Luid = luid
    tp.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED
    advapi32.AdjustTokenPrivileges(token, False, ctypes.byref(tp), 0, None, None)
    ok = kernel32.GetLastError() != 1300  # ERROR_NOT_ALL_ASSIGNED
    kernel32.CloseHandle(token)
    return ok


def clear_standby_list():
    """Purge la standby list Windows (NtSetSystemInformation). Requiert admin."""
    if not _is_windows():
        return
    try:
        ntdll = ctypes.windll.ntdll
        kernel32 = ctypes.windll.kernel32
        advapi32 = ctypes.windll.advapi32

        token = ctypes.c_void_p()
        if not advapi32.OpenProcessToken(
            kernel32.GetCurrentProcess(),
            TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY,
            ctypes.byref(token)
        ):
            return
        luid = LUID()
        if not advapi32.LookupPrivilegeValueW(None, "SeProfileSingleProcessPrivilege", ctypes.byref(luid)):
            kernel32.CloseHandle(token)
            return
        tp = TOKEN_PRIVILEGES()
        tp.PrivilegeCount = 1
        tp.Privileges[0].Luid = luid
        tp.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED
        advapi32.AdjustTokenPrivileges(token, False, ctypes.byref(tp), 0, None, None)
        if kernel32.GetLastError() == 1300:
            kernel32.CloseHandle(token)
            return
        command = ctypes.c_int(MemoryPurgeStandbyList)
        ntdll.NtSetSystemInformation(SystemMemoryListInformation, ctypes.byref(command), ctypes.sizeof(command))
        kernel32.CloseHandle(token)
    except Exception:
        pass


def free_windows_memory():
    """
    Libère la RAM système comme Wise Memory Optimizer / Mem Reduct.
    Séquence complète:
      0. Empty per-process working sets (psutil, no admin needed)
      1. Empty ALL process working sets (system-wide, admin)
      2. Clear system file cache
      3. Flush modified page list (Modified → Standby)
      4. Purge standby list (Standby → Free)
      5. Combine identical pages (Win10+ deduplication)
    Retourne dict avec résultats par étape.
    """
    if not _is_windows():
        return {'success': False, 'error': 'Windows only'}

    results = {'success': False, 'steps': {}}

    try:
        ntdll = ctypes.windll.ntdll
        kernel32 = ctypes.windll.kernel32

        # Enable both required privileges
        priv_profile = enable_privilege("SeProfileSingleProcessPrivilege")
        priv_quota = enable_privilege("SeIncreaseQuotaPrivilege")
        results['privileges'] = {'profile': priv_profile, 'quota': priv_quota}

        if not priv_profile:
            results['error'] = "Privilèges admin requis (lancer en admin)"

        # === Step 0: Per-process EmptyWorkingSet (NO ADMIN NEEDED) ===
        import psutil
        try:
            psapi = ctypes.windll.psapi
            trimmed = 0
            failed = 0
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    pid = proc.info['pid']
                    if pid == 0 or pid == 4:
                        continue
                    handle = kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_QUERY_INFORMATION, False, pid)
                    if handle:
                        if psapi.EmptyWorkingSet(handle):
                            trimmed += 1
                        else:
                            failed += 1
                        kernel32.CloseHandle(handle)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    failed += 1
            results['steps']['per_process_trim'] = trimmed > 0
            results['processes_trimmed'] = trimmed
            print(f"[RAM] Step 0: {trimmed} processes trimmed ({failed} skipped)")
        except Exception as e:
            results['steps']['per_process_trim'] = False
            print(f"[RAM] Step 0 failed: {e}")

        # === Step 1: Empty ALL process working sets (system-wide, needs admin) ===
        command = ctypes.c_int(MemoryEmptyWorkingSets)
        r = ntdll.NtSetSystemInformation(SystemMemoryListInformation, ctypes.byref(command), ctypes.sizeof(command))
        results['steps']['empty_working_sets'] = r == 0
        if r == 0:
            print("[RAM] Step 1/5: All working sets emptied (system-wide)")
        else:
            print(f"[RAM] Step 1/5: Failed (NTSTATUS=0x{r & 0xFFFFFFFF:08X}) — needs admin")

        # === Step 2: Clear system file cache ===
        info = SYSTEM_FILECACHE_INFORMATION()
        info.MinimumWorkingSet = ctypes.c_size_t(-1).value
        info.MaximumWorkingSet = ctypes.c_size_t(-1).value
        r = ntdll.NtSetSystemInformation(SystemFileCacheInformation, ctypes.byref(info), ctypes.sizeof(info))
        results['steps']['file_cache'] = r == 0
        if r == 0:
            print("[RAM] Step 2/5: System file cache cleared")
        else:
            print(f"[RAM] Step 2/5: File cache failed (NTSTATUS=0x{r & 0xFFFFFFFF:08X})")

        # === Step 3: Flush modified page list ===
        command = ctypes.c_int(MemoryFlushModifiedList)
        r = ntdll.NtSetSystemInformation(SystemMemoryListInformation, ctypes.byref(command), ctypes.sizeof(command))
        results['steps']['flush_modified'] = r == 0
        if r == 0:
            print("[RAM] Step 3/5: Modified pages flushed to disk")
        else:
            print(f"[RAM] Step 3/5: Flush modified failed (NTSTATUS=0x{r & 0xFFFFFFFF:08X})")

        # === Step 4: Purge standby list ===
        command = ctypes.c_int(MemoryPurgeStandbyList)
        r = ntdll.NtSetSystemInformation(SystemMemoryListInformation, ctypes.byref(command), ctypes.sizeof(command))
        results['steps']['purge_standby'] = r == 0
        if r == 0:
            print("[RAM] Step 4/5: Standby list purged")
        else:
            command_low = ctypes.c_int(MemoryPurgeLowPriorityStandbyList)
            r2 = ntdll.NtSetSystemInformation(SystemMemoryListInformation, ctypes.byref(command_low), ctypes.sizeof(command_low))
            if r2 == 0:
                results['steps']['purge_standby_low'] = True
                print("[RAM] Step 4/5: Low-priority standby purged (fallback)")
            else:
                print(f"[RAM] Step 4/5: Purge standby failed (NTSTATUS=0x{r & 0xFFFFFFFF:08X}) — needs admin")

        # === Step 5: Combine identical pages (Win10+ deduplication) ===
        try:
            combine_info = MEMORY_COMBINE_INFORMATION()
            combine_info.Handle = 0
            r = ntdll.NtSetSystemInformation(
                SystemCombinePhysicalMemoryInformation,
                ctypes.byref(combine_info),
                ctypes.sizeof(combine_info)
            )
            pages = combine_info.PagesCombined if r == 0 else 0
            results['steps']['combine_pages'] = r == 0
            results['pages_combined'] = pages
            if r == 0 and pages > 0:
                print(f"[RAM] Step 5/5: {pages} pages combined (deduplicated)")
            elif r == 0:
                print("[RAM] Step 5/5: Memory combine OK (0 duplicates found)")
        except Exception:
            results['steps']['combine_pages'] = False

        results['is_admin'] = priv_profile and priv_quota
        results['success'] = any(results['steps'].values())
        return results

    except Exception as e:
        results['error'] = str(e)
        return results
