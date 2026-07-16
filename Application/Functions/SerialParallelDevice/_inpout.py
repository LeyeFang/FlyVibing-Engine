"""
Pythonic wrapper for the **InpOut32** parallel-port I/O library on Windows.

Provides both an object-oriented (:class:`InpOut`, :class:`Port`) and a
module-level convenience API for reading/writing I/O ports at 8‑, 16‑ and
32‑bit widths.

Quick start
-----------
>>> import inpout
>>> inpout.out8(0x378, 0xFF)          # write byte to LPT1 data port
>>> val = inpout.in8(0x378)           # read it back

Or use the context-manager style::

>>> with inpout.InpOut() as io:
...     if not io.driver_open:
...         raise RuntimeError("InpOut driver not available")
...     lpt = io.port(io.LPT1)
...     lpt.byte8 = 0xAA
...     print(f"LPT1 data = 0x{lpt.byte8:02X}")

DLL auto-detection
------------------
On 64‑bit Python ``inpoutx64.dll`` is loaded; on 32‑bit Python
``inpout32.dll`` is used.  Pass an explicit *dll_name* to override.
"""

from __future__ import annotations

import ctypes
import struct
import sys
from pathlib import Path
from ctypes import (
    POINTER,
    byref,
    c_bool,
    c_short,
    c_ubyte,
    c_ulong,
    c_ushort,
    c_void_p,
)
from ctypes.wintypes import DWORD, HANDLE
from typing import Optional, Type

__all__ = [
    "InpOut",
    "Port",
    "_init",
    "driver_open",
    "is_64bit",
    "port",
    "in8",
    "out8",
    "in16",
    "out16",
    "in32",
    "out32",
]

# ======================================================================
# Internal helpers
# ======================================================================

# Directory containing this module — used to locate the DLLs.
_MODULE_DIR = Path(__file__).resolve().parent


def _default_dll_name() -> str:
    """Pick the right DLL for the current Python bitness.

    Returns the **absolute path** to the DLL located alongside this module.
    """
    name = "inpoutx64.dll" if struct.calcsize("P") == 8 else "inpout32.dll"
    local=_MODULE_DIR/name
    if local.is_file():
        return str(local)
    return name


def _check_u8(value: int) -> int:
    """Clamp *value* to 0‑255 and warn if out-of-range."""
    if not (0 <= value <= 0xFF):
        raise ValueError(f"Byte value {value} out of range (0–255)")
    return value


def _check_u16(value: int) -> int:
    """Clamp *value* to 0‑65535."""
    if not (0 <= value <= 0xFFFF):
        raise ValueError(f"Word value {value} out of range (0–65535)")
    return value


def _check_u32(value: int) -> int:
    """Clamp *value* to 0‑4294967295."""
    if not (0 <= value <= 0xFFFFFFFF):
        raise ValueError(f"Dword value {value} out of range (0–4294967295)")
    return value


# ======================================================================
# Descriptors for Port.byte8 / .word16 / .dword32
# ======================================================================

class _PortAccessor8:
    """Descriptor providing ``port.byte8`` read/write."""
    def __get__(self, instance: Port, owner: Type[Port]) -> int:
        return instance._io._in8(instance._addr)

    def __set__(self, instance: Port, value: int) -> None:
        instance._io._out8(instance._addr, _check_u8(value))


class _PortAccessor16:
    """Descriptor providing ``port.word16`` read/write."""
    def __get__(self, instance: Port, owner: Type[Port]) -> int:
        return instance._io._in16(instance._addr)

    def __set__(self, instance: Port, value: int) -> None:
        instance._io._out16(instance._addr, _check_u16(value))


class _PortAccessor32:
    """Descriptor providing ``port.dword32`` read/write."""
    def __get__(self, instance: Port, owner: Type[Port]) -> int:
        return instance._io._in32(instance._addr)

    def __set__(self, instance: Port, value: int) -> None:
        instance._io._out32(instance._addr, _check_u32(value))


# ======================================================================
# Port
# ======================================================================

class Port:
    """Represents a single I/O port address.

    Provides attribute-style read/write access at three widths.
    All actual I/O is delegated to the parent :class:`InpOut` instance.

    Usage::

        port = inpout.port(0x378)
        port.byte8 = 0xFF        # write byte
        val = port.byte8         # read byte  → 255
        port.word16 = 0xABCD     # write word
        val = port.dword32       # read dword
    """

    byte8 = _PortAccessor8()
    """Read/write an 8‑bit unsigned value (0–255)."""

    word16 = _PortAccessor16()
    """Read/write a 16‑bit unsigned value (0–65535)."""

    dword32 = _PortAccessor32()
    """Read/write a 32‑bit unsigned value (0–4294967295)."""

    __slots__ = ("_io", "_addr")

    def __init__(self, address: int) -> None:
        self._io: InpOut = _default
        self._addr: int = address

    # -- helpers for InpOut to bind a specific io instance ---------------

    def _bind(self, io: InpOut) -> None:
        self._io = io

    # -- public properties -----------------------------------------------

    @property
    def address(self) -> int:
        """The I/O port address."""
        return self._addr

    # -- explicit read/write methods -------------------------------------

    def read_byte(self) -> int:
        """Read an 8‑bit value from the port."""
        return self.byte8

    def write_byte(self, value: int) -> None:
        """Write an 8‑bit value to the port."""
        self.byte8 = value

    def read_word(self) -> int:
        """Read a 16‑bit value from the port."""
        return self.word16

    def write_word(self, value: int) -> None:
        """Write a 16‑bit value to the port."""
        self.word16 = value

    def read_dword(self) -> int:
        """Read a 32‑bit value from the port."""
        return self.dword32

    def write_dword(self, value: int) -> None:
        """Write a 32‑bit value to the port."""
        self.dword32 = value

    def __repr__(self) -> str:
        return f"Port(0x{self._addr:04X})"


# ======================================================================
# InpOut
# ======================================================================

class InpOut:
    """Main interface to the InpOut32 / inpoutx64 driver DLL.

    Handles DLL loading, driver-status queries, and provides factory
    methods for :class:`Port` objects.  Use as a context manager to
    guarantee cleanup.

    Well-known parallel-port base addresses
    ---------------------------------------
    ====== ============
    Name   Address
    ====== ============
    LPT1   0x378
    LPT2   0x278
    LPT3   0x3BC
    ====== ============

    Common LPT register offsets::

        base + 0  → Data register   (R/W)
        base + 1  → Status register (R)
        base + 2  → Control register (R/W)

    Usage::

        with InpOut() as io:
            print(f"Driver open: {io.driver_open}")
            print(f"64-bit OS:   {io.is_64bit}")

            # via Port object
            data_port = io.port(io.LPT1)
            data_port.byte8 = 0x55

            # via index notation
            io[io.LPT1 + 2].byte8 = 0x0C   # control register

            # via convenience shortcuts
            io.out8(io.LPT1, 0xAA)
            val = io.in16(io.LPT1)
    """

    # Well-known base addresses
    LPT1: int = 0x378
    LPT2: int = 0x278
    LPT3: int = 0x3BC

    def __init__(self, dll_name: Optional[str] = None) -> None:
        self._dll_name: str = dll_name or _default_dll_name()
        self._dll: Optional[ctypes.WinDLL] = None
        self._load()

    # -- DLL loading -----------------------------------------------------

    def _load(self) -> None:
        """Load the DLL and set up function signatures."""
        dll = ctypes.WinDLL(self._dll_name)

        # --- Original InpOut32 API ---
        self._Out32 = dll.Out32
        self._Out32.argtypes = [c_short, c_short]
        self._Out32.restype = None

        self._Inp32 = dll.Inp32
        self._Inp32.argtypes = [c_short]
        self._Inp32.restype = c_short

        # --- Driver status ---
        self._IsInpOutDriverOpen = dll.IsInpOutDriverOpen
        self._IsInpOutDriverOpen.argtypes = []
        self._IsInpOutDriverOpen.restype = c_bool

        self._IsXP64Bit = dll.IsXP64Bit
        self._IsXP64Bit.argtypes = []
        self._IsXP64Bit.restype = c_bool

        # --- DlPortIO API (8/16/32-bit) ---
        self._DlPortReadPortUchar = dll.DlPortReadPortUchar
        self._DlPortReadPortUchar.argtypes = [c_ushort]
        self._DlPortReadPortUchar.restype = c_ubyte

        self._DlPortWritePortUchar = dll.DlPortWritePortUchar
        self._DlPortWritePortUchar.argtypes = [c_ushort, c_ubyte]
        self._DlPortWritePortUchar.restype = None

        self._DlPortReadPortUshort = dll.DlPortReadPortUshort
        self._DlPortReadPortUshort.argtypes = [c_ushort]
        self._DlPortReadPortUshort.restype = c_ushort

        self._DlPortWritePortUshort = dll.DlPortWritePortUshort
        self._DlPortWritePortUshort.argtypes = [c_ushort, c_ushort]
        self._DlPortWritePortUshort.restype = None

        self._DlPortReadPortUlong = dll.DlPortReadPortUlong
        self._DlPortReadPortUlong.argtypes = [c_ulong]
        self._DlPortReadPortUlong.restype = c_ulong

        self._DlPortWritePortUlong = dll.DlPortWritePortUlong
        self._DlPortWritePortUlong.argtypes = [c_ulong, c_ulong]
        self._DlPortWritePortUlong.restype = None

        # --- WinIO physical-memory API (low-level) ---
        self._MapPhysToLin = dll.MapPhysToLin
        self._MapPhysToLin.argtypes = [c_void_p, DWORD, POINTER(HANDLE)]
        self._MapPhysToLin.restype = c_void_p

        self._UnmapPhysicalMemory = dll.UnmapPhysicalMemory
        self._UnmapPhysicalMemory.argtypes = [HANDLE, c_void_p]
        self._UnmapPhysicalMemory.restype = c_bool

        self._GetPhysLong = dll.GetPhysLong
        self._GetPhysLong.argtypes = [c_void_p, POINTER(DWORD)]
        self._GetPhysLong.restype = c_bool

        self._SetPhysLong = dll.SetPhysLong
        self._SetPhysLong.argtypes = [c_void_p, DWORD]
        self._SetPhysLong.restype = c_bool

        self._dll = dll

    # -- driver status ---------------------------------------------------

    @property
    def driver_open(self) -> bool:
        """*True* if the InpOut kernel driver was opened successfully."""
        return bool(self._IsInpOutDriverOpen())

    @property
    def is_64bit(self) -> bool:
        """*True* if the operating system is 64‑bit (x64) Windows."""
        return bool(self._IsXP64Bit())

    # -- port factory ----------------------------------------------------

    def port(self, address: int) -> Port:
        """Create a :class:`Port` instance bound to *address*.

        The returned object delegates all I/O to this :class:`InpOut`
        instance.
        """
        p = Port(address)
        p._bind(self)
        return p

    def __getitem__(self, address: int) -> Port:
        """``io[0x378]`` → :meth:`port`."""
        return self.port(address)

    # -- low-level I/O (used by Port descriptors) ------------------------

    def _in8(self, address: int) -> int:
        return self._DlPortReadPortUchar(address)

    def _out8(self, address: int, value: int) -> None:
        self._DlPortWritePortUchar(address, value)

    def _in16(self, address: int) -> int:
        return self._DlPortReadPortUshort(address)

    def _out16(self, address: int, value: int) -> None:
        self._DlPortWritePortUshort(address, value)

    def _in32(self, address: int) -> int:
        return self._DlPortReadPortUlong(address)

    def _out32(self, address: int, value: int) -> None:
        self._DlPortWritePortUlong(address, value)

    # -- public convenience shortcuts ------------------------------------

    def in8(self, address: int) -> int:
        """Read a byte from *address* (0–255)."""
        return self._in8(address)

    def out8(self, address: int, value: int) -> None:
        """Write a byte *value* (0–255) to *address*."""
        self._out8(address, _check_u8(value))

    def in16(self, address: int) -> int:
        """Read a word from *address* (0–65535)."""
        return self._in16(address)

    def out16(self, address: int, value: int) -> None:
        """Write a word *value* (0–65535) to *address*."""
        self._out16(address, _check_u16(value))

    def in32(self, address: int) -> int:
        """Read a dword from *address* (0–4294967295)."""
        return self._in32(address)

    def out32(self, address: int, value: int) -> None:
        """Write a dword *value* (0–4294967295) to *address*."""
        self._out32(address, _check_u32(value))

    # -- low-level physical memory (WinIO) -------------------------------

    def map_phys_to_lin(
        self, phys_addr: int, size: int
    ) -> tuple[int, int]:
        """Map a physical address range into linear (virtual) address space.

        .. warning::
           This is a low‑level operation.  Incorrect use may crash the
           system.  The WinIO backend is untested on x64.

        :param phys_addr: Physical base address.
        :param size:      Number of bytes to map.
        :returns:         ``(linear_address, handle)`` tuple.
        :raises OSError:  If the mapping fails.
        """
        handle = HANDLE()
        lin = self._MapPhysToLin(c_void_p(phys_addr), DWORD(size), byref(handle))
        if not lin:
            raise OSError("MapPhysToLin failed")
        return (lin or 0, handle.value or 0)

    def unmap_physical_memory(self, handle: int, linear_addr: int) -> bool:
        """Unmap a previously mapped physical memory region.

        :returns: *True* on success.
        """
        return bool(self._UnmapPhysicalMemory(HANDLE(handle), c_void_p(linear_addr)))

    def get_phys_long(self, phys_addr: int) -> int:
        """Read a 32‑bit value from a physical memory address.

        :returns: The 32‑bit value read.
        :raises OSError: If the read fails.
        """
        val = DWORD()
        if not self._GetPhysLong(c_void_p(phys_addr), byref(val)):
            raise OSError("GetPhysLong failed")
        return val.value

    def set_phys_long(self, phys_addr: int, value: int) -> None:
        """Write a 32‑bit value to a physical memory address.

        :raises OSError: If the write fails.
        """
        if not self._SetPhysLong(c_void_p(phys_addr), DWORD(value)):
            raise OSError("SetPhysLong failed")

    # -- context manager -------------------------------------------------

    def close(self) -> None:
        """Release the DLL handle.

        Called automatically when the context manager exits.  After
        calling this the instance is no longer usable.
        """
        if self._dll is not None:
            # ctypes.WinDLL does not have an explicit close, but we
            # drop the reference so the GC can release the handle.
            self._dll = None

    def __enter__(self) -> "InpOut":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def __repr__(self) -> str:
        dll = self._dll_name
        status = "open" if self._dll is not None else "closed"
        return f"InpOut(dll={dll!r}, {status})"


# ======================================================================
# Module-level default instance (lazy)
# ======================================================================

_default: Optional[InpOut] = None


def _init(dll_name: Optional[str] = None) -> InpOut:
    """Initialise (or re-initialise) the module-level default :class:`InpOut`.

    Called automatically on first use of any module-level convenience
    function.  Call explicitly only when you need a non-default DLL path.
    """
    global _default
    if _default is not None:
        _default.close()
    _default = InpOut(dll_name)
    return _default


def _get_default() -> InpOut:
    """Return the module-level default :class:`InpOut`, creating it if needed."""
    global _default
    if _default is None:
        _init()
    assert _default is not None
    return _default


# -- module-level convenience functions -----------------------------------

def driver_open() -> bool:
    """*True* if the InpOut kernel driver was opened successfully (default instance)."""
    return _get_default().driver_open


def is_64bit() -> bool:
    """*True* if the OS is 64‑bit Windows."""
    return _get_default().is_64bit


def port(address: int) -> Port:
    """Shorthand for ``_default.port(address)``."""
    return _get_default().port(address)


def in8(address: int) -> int:
    """Shorthand for ``_default.in8(address)``."""
    return _get_default().in8(address)


def out8(address: int, value: int) -> None:
    """Shorthand for ``_default.out8(address, value)``."""
    _get_default().out8(address, value)


def in16(address: int) -> int:
    """Shorthand for ``_default.in16(address)``."""
    return _get_default().in16(address)


def out16(address: int, value: int) -> None:
    """Shorthand for ``_default.out16(address, value)``."""
    _get_default().out16(address, value)


def in32(address: int) -> int:
    """Shorthand for ``_default.in32(address)``."""
    return _get_default().in32(address)


def out32(address: int, value: int) -> None:
    """Shorthand for ``_default.out32(address, value)``."""
    _get_default().out32(address, value)
