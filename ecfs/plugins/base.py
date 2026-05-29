from abc import ABC, abstractmethod
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Optional
import time


class TransportStatus(Enum):
    ONLINE = auto()
    DEGRADED = auto()   # working but slow/high error rate
    OFFLINE = auto()    # not available
    ERROR = auto()      # last operation failed


class ThreatLevel(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


class TransportType(Enum):
    INTERNET = "internet"
    RADIO = "radio"
    ACOUSTIC = "acoustic"
    PROXIMITY = "proximity"
    COVERT = "covert"


@dataclass
class TransportStats:
    packets_sent: int = 0
    packets_received: int = 0
    packets_failed: int = 0
    bytes_sent: int = 0
    bytes_received: int = 0
    avg_latency_ms: float = 0.0
    last_seen: float = field(default_factory=time.time)


class TransportPlugin(ABC):
    """Base class for all ECFS transport plugins.

    Each plugin implements send/receive for one physical medium.
    The core engine never touches the medium directly — it only
    calls these standardized methods.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this transport (e.g. 'lora', 'internet')."""
        ...

    @property
    @abstractmethod
    def transport_type(self) -> TransportType:
        """Category of this transport."""
        ...

    @property
    def priority(self) -> int:
        """Lower = preferred. Default 100."""
        return 100

    @property
    def max_packet_size(self) -> int:
        """Max bytes per single send. Default 65536."""
        return 65536

    @abstractmethod
    async def initialize(self) -> None:
        """Set up the transport (open sockets, connect hardware, etc)."""
        ...

    @abstractmethod
    async def teardown(self) -> None:
        """Clean shutdown."""
        ...

    @abstractmethod
    async def send_packet(self, data: bytes) -> bool:
        """Send raw packet bytes. Returns True on success."""
        ...

    @abstractmethod
    async def receive_packet(self) -> Optional[bytes]:
        """Receive one packet. Returns None if nothing available."""
        ...

    async def get_status(self) -> TransportStatus:
        """Current health. Override for active monitoring."""
        return TransportStatus.ONLINE

    async def health_check(self) -> TransportStatus:
        """Active probe. Override with real checks. Default just returns status."""
        return await self.get_status()

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r} type={self.transport_type.value}>"
