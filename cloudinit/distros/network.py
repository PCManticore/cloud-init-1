"""Network base classes."""

import abc
import collections

import six

from cloudinit.distros import util


__all__ = (
    'BaseNetwork',
    'BaseRoute',
    'BaseRouteCollection',
    'BaseInterface',
)


@six.add_metaclass(abc.ABCMeta)
class BaseNetwork(object):
    """Base network class for network related utilities."""

    @abc.abstractmethod
    def routes(self):
        """Get an object representing the available routes."""

    @abc.abstractmethod
    def default_gateway(self):
        """Get the default gateway, as a route object."""

    @abc.abstractmethod
    def interfaces(self):
        """Get an object representing the available interfaces."""

    @abc.abstractmethod
    def hosts(self):
        """Get an object representing the available hosts."""

    @abc.abstractmethod
    def set_hostname(self, hostname):
        """Change the host name of the instance."""

    @abc.abstractmethod
    def set_timezone(self, timezone):
        """Change the current timezone with the given timezone."""


@six.add_metaclass(abc.ABCMeta)
class BaseRoute(object):
    """Base class for routes."""

    def __init__(self, destination, gateway, netmask,
                 interface, metric,
                 flags=None, refs=None, use=None, expire=None):
        self.destination = destination
        self.gateway = gateway
        self.netmask = netmask
        self.interface = interface
        self.metric = metric
        self.flags = flags
        self.refs = refs
        self.use = use
        self.expire = expire

    @abc.abstractproperty
    def static(self):
        """Check if this route is static."""


@six.add_metaclass(abc.ABCMeta)
class BaseRouteCollection(collections.Sequence):
    """A collection which encapsulates the routes available in the system.

    Each route item will be an instance of :meth:`BaseRoute` and a particular
    implementation depending on the underlying platform.
    To retrieve all the routes, it is sufficient to instantiate this class,
    it will, under the hood, retrieve the routes.
    The collection offers a couple of methods for adding or deleting a route.

    >>> RouteCollection.add(Route(..., ...))
    >>> RouteCollection.delete(Route(..., ...))
    >>> list(RouteCollection())
    >>> Route(..., ...) in RouteCollection()
    """

    def __init__(self):
        self._route_items = self._routes()

    @abc.abstractmethod
    def _routes(self):
        """Low level function to retrieve the available routes."""

    @util.abstractclassmethod
    def add(cls, route):
        """Add a new route in the underlying distro.

        The function should expect an instance of :class:`BaseRoute`.
        """

    @util.abstractclassmethod
    def delete(cls, route):
        """Delete a route from the underlying distro.

        This function should expect an instance of :class:`BaseRoute`.
        """

    def __getitem__(self, index):
        return self._route_items[index]

    def __delitem__(self, index):
        self.__class__.delete(self._route_items[index])
        del self._route_items[index]

    def __len__(self):
        return len(self._route_items)

    def __contains__(self, other):
        if isinstance(other, BaseRoute):
            return other in self._route_items

        return any(route.destination == other.destination
                   for route in self._route_items)


@six.add_metaclass(abc.ABCMeta)
class BaseInterface(object):
    """Base class reprensenting an interface.

    It provides both attributes for retrieving interface information,
    as well as methods for modifying the state of a route, such
    as activating or deactivating it.
    """

    def __init__(self, name, mac, index=None, mtu=None,
                 dhcp_server=None, dhcp_enabled=None):
        self._mtu = mtu

        self.name = name
        self.index = index
        self.mac = mac
        self.dhcp_server = dhcp_server
        self.dhcp_enabled = dhcp_enabled

    @abc.abstractmethod
    def _change_mtu(self, value):
        """Change the mtu for the underlying interface."""

    @util.abstractclassmethod
    def from_name(cls, name):
        """Get an instance of :class:`BaseInterface` from an interface name.

        E.g. this should retrieve the 'eth0' interface::

           >>> Interface.from_name('eth0')
        """

    @abc.abstractmethod
    def up(self):
        """Activate the current interface."""

    @abc.abstractmethod
    def down(self):
        """Deactivate the current interface."""

    @abc.abstractmethod
    def is_up(self):
        """Check if this interface is activated."""

    @property
    def mtu(self):
        return self._mtu

    @mtu.setter
    def mtu(self, value):
        self._change_mtu(value)
        self._mtu = value
