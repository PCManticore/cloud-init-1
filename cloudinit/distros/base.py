
import abc
import importlib
import platform

import six


__all__ = (
    'get_distro',
    'BaseDistro',
)


def get_distro():
    """Obtain the distro object for the underlying platform."""
    name, _, _ = platform.linux_distribution()
    if not name:
        name = platform.system()

    name = name.lower()
    distro_location = "cloudinit.distros.{0}.base".format(name)
    distro_module = importlib.import_module(distro_location)
    return distro_module.Distro


@six.add_metaclass(abc.ABCMeta)
class BaseDistro(object):
    """
    A base distro class, which provides a couple of hooks
    which needs to be implemented by subclasses, for each
    particular distro.
    """

    name = None

    @abc.abstractproperty
    def network(self):
        """Get the network object for the underlying platform."""

    @abc.abstractproperty
    def filesystem(self):
        """Get the filesystem object for the underlying platform."""

    @abc.abstractproperty
    def users(self):
        """Get the users object for the underlying platform."""

    @abc.abstractproperty
    def general(self):
        """Get the general object for the underlying platform."""

    @abc.abstractproperty
    def user_class(self):
        """Get the user class specific to this distro."""

    @abc.abstractproperty
    def route_class(self):
        """Get the route class specific to this distro."""

    @abc.abstractproperty
    def interface_class(self):
        """Get the interface class specific to this distro."""
