import ctypes
from ctypes import wintypes
import logging
import os
import subprocess

import six
from six.moves import winreg
from win32com import client
import wmi

from cloudinit.distros import network
from cloudinit.distros.windows import general
from cloudinit.distros.windows.util import kernel32
from cloudinit.distros.windows.util import iphlpapi
from cloudinit.distros.windows.util import ws2_32


_MIB_IPPROTO_NETMGMT = 3
_FW_IP_PROTOCOL_TCP = 6
_FW_IP_PROTOCOL_UDP = 17
_FW_SCOPE_ALL = 0
_PROTOCOL_TCP = "TCP"
_PROTOCOL_UDP = "UDP"
_ComputerNamePhysicalDnsHostname = 5
LOG = logging.getLogger(__file__)


def _format_mac_address(phys_address, phys_address_len):
    mac_address = ""
    for i in range(0, phys_address_len):
        b = phys_address[i]
        if mac_address:
            mac_address += ":"
        mac_address += "%02X" % b
    return mac_address


def _socket_addr_to_str(socket_addr):
    addr_str_len = wintypes.DWORD(256)
    addr_str = ctypes.create_unicode_buffer(256)

    ret_val = ws2_32.WSAAddressToStringW(
        socket_addr.lpSockaddr,
        socket_addr.iSockaddrLength,
        None, addr_str, ctypes.byref(addr_str_len))
    if ret_val:
        raise Exception("WSAAddressToStringW failed: %s"
                        % ws2_32.WSAGetLastError())

    return addr_str.value


def _get_registry_dhcp_server(adapter_name):
    with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            "SYSTEM\\CurrentControlSet\\Services\\" +
            "Tcpip\\Parameters\\Interfaces\\%s" % adapter_name, 0,
            winreg.KEY_READ) as key:
        try:
            dhcp_server = winreg.QueryValueEx(key, "DhcpServer")[0]
            if dhcp_server == "255.255.255.255":
                dhcp_server = None
            return dhcp_server
        except Exception as ex:
            # Not found
            if ex.errno != 2:
                raise


class Network(network.BaseNetwork):
    """Network namespace object tailored for the Windows platform."""

    def routes(self):
        """Get a collection of the available routes."""
        return RouteCollection()

    def default_gateway(self):
        """Get the default gateway.

        This will actually return a :class:`Route` instance. The gateway
        can be accessed with the :attr:`gateway` attribute.
        """
        return next((r for r in self.routes() if r.destination == '0.0.0.0'),
                    None)

    def interfaces(self):
        """Get a list of available interfaces."""

        interfaces = []
        size = wintypes.ULONG()
        ret_val = iphlpapi.GetAdaptersAddresses(
            ws2_32.AF_UNSPEC,
            iphlpapi.GAA_FLAG_SKIP_ANYCAST,
            None, None, ctypes.byref(size))

        if ret_val == kernel32.ERROR_NO_DATA:
            return interfaces

        if ret_val == kernel32.ERROR_BUFFER_OVERFLOW:
            proc_heap = kernel32.GetProcessHeap()
            p = kernel32.HeapAlloc(proc_heap, 0, size.value)
            if not p:
                raise Exception("Cannot allocate memory")

            ws2_32.init_wsa()

            try:
                p_addr = ctypes.cast(p, ctypes.POINTER(
                    iphlpapi.IP_ADAPTER_ADDRESSES))

                ret_val = iphlpapi.GetAdaptersAddresses(
                    ws2_32.AF_UNSPEC,
                    iphlpapi.GAA_FLAG_SKIP_ANYCAST,
                    None, p_addr, ctypes.byref(size))

                if ret_val == kernel32.ERROR_NO_DATA:
                    return interfaces

                if ret_val:
                    raise Exception("GetAdaptersAddresses failed")

                p_curr_addr = p_addr
                while p_curr_addr:
                    curr_addr = p_curr_addr.contents

                    xp_data_only = (curr_addr.Union1.Struct1.Length <=
                                    iphlpapi.IP_ADAPTER_ADDRESSES_SIZE_2003)

                    mac_address = _format_mac_address(
                        curr_addr.PhysicalAddress,
                        curr_addr.PhysicalAddressLength)

                    dhcp_enabled = (
                        curr_addr.Flags & iphlpapi.IP_ADAPTER_DHCP_ENABLED) != 0
                    dhcp_server = None

                    if dhcp_enabled:
                        if not xp_data_only:
                            if curr_addr.Flags & iphlpapi.IP_ADAPTER_IPV4_ENABLED:
                                dhcp_addr = curr_addr.Dhcpv4Server

                            ipv6_enabled = (
                                curr_addr.Flags &
                                iphlpapi.IP_ADAPTER_IPV6_ENABLED)
                            not_has_dhcp = (
                                 not dhcp_addr or
                                 not dhcp_addr.iSockaddrLength)

                            if ipv6_enabled and not_has_dhcp:
                                dhcp_addr = curr_addr.Dhcpv6Server

                            if dhcp_addr and dhcp_addr.iSockaddrLength:
                                dhcp_server = _socket_addr_to_str(dhcp_addr)
                        else:
                            dhcp_server = _get_registry_dhcp_server(
                                curr_addr.AdapterName)

                interface = Interface(
                    name=curr_addr.AdapterName,
                    mac=mac_address,
                    index=curr_addr.Union1.Struct1.IfIndex,
                    mtu=curr_addr.Mtu,
                    dhcp_server=dhcp_server,
                    dhcp_enabled=dhcp_enabled)
                interfaces.append(interface)

                p_curr_addr = ctypes.cast(
                    curr_addr.Next, ctypes.POINTER(
                        iphlpapi.IP_ADAPTER_ADDRESSES))

            finally:
                kernel32.HeapFree(proc_heap, 0, p)
                ws2_32.WSACleanup()

        return interfaces

    def set_static_network_config(self, mac_address, address, netmask,
                                  gateway, dnsnameservers):
        conn = wmi.WMI(moniker='//./root/cimv2')

        q = conn.query("SELECT * FROM Win32_NetworkAdapter WHERE "
                       "MACAddress = '{}'".format(mac_address))
        if not len(q):
            raise Exception("Network adapter not found")

        adapter_config = q[0].associators(
            wmi_result_class='Win32_NetworkAdapterConfiguration')[0]

        LOG.debug("Setting static IP address")
        (ret_val, ) = adapter_config.EnableStatic([address], [netmask])
        if ret_val > 1:
            raise Exception(
                "Cannot set static IP address on network adapter")
        reboot_required = (ret_val == 1)

        if gateway:
            LOG.debug("Setting static gateways")
            (ret_val, ) = adapter_config.SetGateways([gateway], [1])
            if ret_val > 1:
                raise Exception("Cannot set gateway on network adapter")
            reboot_required = reboot_required or ret_val == 1

        if dnsnameservers:
            LOG.debug("Setting static DNS servers")
            (ret_val,) = adapter_config.SetDNSServerSearchOrder(dnsnameservers)
            if ret_val > 1:
                raise Exception("Cannot set DNS on network adapter")
            reboot_required = reboot_required or ret_val == 1

        return reboot_required

    def set_hostname(self, hostname):
        ret_val = kernel32.SetComputerNameExW(
            _ComputerNamePhysicalDnsHostname,
            six.text_type(hostname))
        if not ret_val:
            raise Exception("Cannot set host name")

    @staticmethod
    def _get_fw_protocol(protocol):
        if protocol == _PROTOCOL_TCP:
            fw_protocol = _FW_IP_PROTOCOL_TCP
        elif protocol == _PROTOCOL_UDP:
            fw_protocol = _FW_IP_PROTOCOL_UDP
        else:
            raise NotImplementedError("Unsupported protocol")
        return fw_protocol

    def firewall_create_rule(self, name, port, protocol, allow=True):
        if not allow:
            raise NotImplementedError()

        fw_port = client.Dispatch("HNetCfg.FWOpenPort")
        fw_port.Name = name
        fw_port.Protocol = self._get_fw_protocol(protocol)
        fw_port.Port = port
        fw_port.Scope = _FW_SCOPE_ALL
        fw_port.Enabled = True

        fw_mgr = client.Dispatch("HNetCfg.FwMgr")
        fw_profile = fw_mgr.LocalPolicy.CurrentProfile
        fw_profile = fw_profile.GloballyOpenPorts.Add(fw_port)

    def firewall_remove_rule(self, _, port, protocol, allow=True):
        if not allow:
            raise NotImplementedError()

        fw_mgr = client.Dispatch("HNetCfg.FwMgr")
        fw_profile = fw_mgr.LocalPolicy.CurrentProfile

        fw_protocol = self._get_fw_protocol(protocol)
        fw_profile = fw_profile.GloballyOpenPorts.Remove(port, fw_protocol)

    # These are not required by the Windows version for now,
    # but we provide them as noop versions.
    def hosts(self):
        """Grab the content of the hosts file."""

    def set_timezone(self, timezone):
        """Change the timezone with the new timezone"""


class Route(network.BaseRoute):
    """Windows route class."""

    def static(self):
        return self.flags == _MIB_IPPROTO_NETMGMT


class RouteCollection(network.BaseRouteCollection):
    """The windows version of the route collection."""

    def _routes(self):
        routing_table = []

        heap = kernel32.GetProcessHeap()

        forward_table_size = ctypes.sizeof(iphlpapi.Win32_MIB_IPFORWARDTABLE)
        size = wintypes.ULONG(forward_table_size)
        p = kernel32.HeapAlloc(heap, 0, ctypes.c_size_t(size.value))
        if not p:
            raise Exception(
                'Unable to allocate memory for the IP forward table')
        p_forward_table = ctypes.cast(
            p, ctypes.POINTER(iphlpapi.Win32_MIB_IPFORWARDTABLE))

        try:
            err = iphlpapi.GetIpForwardTable(p_forward_table,
                                             ctypes.byref(size), 0)
            if err == iphlpapi.ERROR_INSUFFICIENT_BUFFER:
                kernel32.HeapFree(heap, 0, p_forward_table)
                p = kernel32.HeapAlloc(heap, 0, ctypes.c_size_t(size.value))
                if not p:
                    raise Exception(
                        'Unable to allocate memory for the IP forward table')
                p_forward_table = ctypes.cast(
                    p, ctypes.POINTER(iphlpapi.Win32_MIB_IPFORWARDTABLE))

            err = iphlpapi.GetIpForwardTable(p_forward_table,
                                             ctypes.byref(size), 0)
            if err != kernel32.ERROR_NO_DATA:
                if err:
                    raise Exception(
                        'Unable to get IP forward table. Error: %s' % err)

                forward_table = p_forward_table.contents
                table = ctypes.cast(
                    ctypes.addressof(forward_table.table),
                    ctypes.POINTER(iphlpapi.Win32_MIB_IPFORWARDROW *
                                   forward_table.dwNumEntries)).contents

                i = 0
                while i < forward_table.dwNumEntries:
                    row = table[i]
                    destination = ws2_32.Ws2_32.inet_ntoa(
                        row.dwForwardDest).decode()
                    netmask = ws2_32.Ws2_32.inet_ntoa(
                        row.dwForwardMask).decode()
                    gateway = ws2_32.Ws2_32.inet_ntoa(
                        row.dwForwardNextHop).decode()
                    index = ws2_32.Ws2_32.dwForwardIfIndex
                    flags = ws2_32.Ws2_32.dwForwardProto
                    metric = row.dwForwardMetric1
                    route = Route(destination=destination,
                                  gateway=gateway,
                                  netmask=netmask,
                                  interface=index,
                                  metric=metric,
                                  flags=flags)
                    routing_table.append(route)
                    i += 1

            return routing_table
        finally:
            kernel32.HeapFree(heap, 0, p_forward_table)

    @classmethod
    def add(cls, route):
        """Add a new route in the underlying distro.

        The function should expect an instance of :class:`BaseRoute`.
        """
        args = ['ROUTE', 'ADD',
                route.destination,
                'MASK', route.netmask, route.gateway]
        popen = subprocess.Popen(args, shell=False,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE)
        _, stderr = popen.communicate()
        if popen.returncode or stderr:
            # Cannot use the return value to determine the outcome
            raise Exception('Unable to add route: %s' % stderr)

    @classmethod
    def delete(cls, _):
        """Delete a route from the underlying distro.

        This function should expect an instance of :class:`BaseRoute`.
        """


class Interface(network.BaseInterface):
    """Interface class tailored for Windows."""

    def _change_mtu(self, value):
        _general = general.General()

        if not _general.check_os_version(6, 0):
            raise Exception(
                'Setting the MTU is currently not supported on Windows XP '
                'and Windows Server 2003')


        base_dir = _general.system_dir()
        netsh_path = os.path.join(base_dir, 'netsh.exe')

        args = [netsh_path, "interface", "ipv4", "set", "subinterface",
                str(self.index),
                "mtu=%s" % value,
                "store=persistent"]
        ret_val = subprocess.call(args, shell=False)
        if ret_val:
            raise Exception(
                'Setting MTU for interface "%(mac_address)s" with '
                'value "%(mtu)s" failed' % {'mac_address': self.mac,
                                            'mtu': value})

    @classmethod
    def from_mac(cls, mac_address):
        interfaces = Network().interfaces()
        return next((interface for interface in interfaces
                     if interface.mac == mac_address), None)

    # These methods aren't required for Windows,
    # but we provide noop versions of them, in order
    # to be API-complete.

    @classmethod
    def from_name(cls, _):
        pass

    def up(self):
        pass

    def down(self):
        pass

    def is_up(self):
        pass
