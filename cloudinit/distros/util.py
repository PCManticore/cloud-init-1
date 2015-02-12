"""Various utilities unrelated to a distro or another."""

__all__ = ('abstractclassmethod', )


class abstractclassmethod(classmethod):

    __isabstractmethod__ = True

    def __init__(self, func):
        func.__isabstractmethod__ = True
        super(abstractclassmethod, self).__init__(func)
