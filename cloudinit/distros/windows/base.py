
from cloudinit.distros import base
from cloudinit.distros.windows import network as network_module
from cloudinit.distros.windows import general as general_module
from cloudinit.distros.windows import filesystem as filesystem_module
from cloudinit.distros.windows import users as users_module


__all__ = ('Distro', )


class Distro(base.BaseDistro):
    name = "windows"

    network = network_module.Network()
    filesystem = filesystem_module.Filesystem()
    users = users_module.Users()
    general = general_module.General()
    user_class = users_module.User
    route_class = network_module.Route
    interface_class = network_module.Interface
