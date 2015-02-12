import ctypes
import logging
import os

import win32process

from cloudinit.distros import general
from cloudinit.distros.windows.util import kernel32


LOG = logging.getLogger(__name__)


class General(general.BaseGeneral):

    @staticmethod
    def check_os_version(major, minor, build=0):
        vi = kernel32.Win32_OSVERSIONINFOEX_W()
        vi.dwOSVersionInfoSize = ctypes.sizeof(
            kernel32.Win32_OSVERSIONINFOEX_W)

        vi.dwMajorVersion = major
        vi.dwMinorVersion = minor
        vi.dwBuildNumber = build

        mask = 0
        for type_mask in [kernel32.VER_MAJORVERSION,
                          kernel32.VER_MINORVERSION,
                          kernel32.VER_BUILDNUMBER]:
            mask = kernel32.VerSetConditionMask(mask, type_mask,
                                                kernel32.VER_GREATER_EQUAL)

        type_mask = (kernel32.VER_MAJORVERSION |
                     kernel32.VER_MINORVERSION |
                     kernel32.VER_BUILDNUMBER)
        ret_val = kernel32.VerifyVersionInfoW(ctypes.byref(vi), type_mask,
                                              mask)
        if ret_val:
            return True
        else:
            err = kernel32.GetLastError()
            if err == kernel32.ERROR_OLD_WIN_VERSION:
                return False
            else:
                raise Exception(
                    "VerifyVersionInfo failed with error: %s" % err) # TODO

    @staticmethod
    def system32_dir():
        return os.path.expandvars('%windir%\\system32')

    @staticmethod
    def sysnative_dir():
        return os.path.expandvars('%windir%\\sysnative')

    @staticmethod
    def is_wow64():
        return win32process.IsWow64Process()

    def check_sysnative_dir_exists(self):
        sysnative_dir_exists = os.path.isdir(self.sysnative_dir())
        if not sysnative_dir_exists and self.is_wow64():
            LOG.warning('Unable to validate sysnative folder presence. '
                        'If Target OS is Server 2003 x64, please ensure '
                        'you have KB942589 installed')
        return sysnative_dir_exists

    def system_dir(self, sysnative=True):
        if sysnative and self.check_sysnative_dir_exists():
            return self.sysnative_dir()
        else:
            return self.system32_dir()
