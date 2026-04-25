from abc import ABC, abstractmethod


class Event(ABC):

    @classmethod
    @abstractmethod
    def Pack():
        ...

    @classmethod
    @abstractmethod
    def UnPack(cls):
        ...
