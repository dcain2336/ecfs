import asyncio
import logging
import os
import platform
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class HardwareProfile:
    """What hardware is available on this device."""
    has_bluetooth: bool = False
    has_serial: bool = False
    has_speaker: bool = False
    has_microphone: bool = False
    has_nfc_reader: bool = False
    has_network: bool = False
    serial_ports: list = field(default_factory=list)
    bluetooth_devices: list = field(default_factory=list)
    network_interfaces: list = field(default_factory=list)

    @property
    def transport_count(self) -> int:
        """Number of potentially available transport types."""
        count = 0
        if self.has_network:
            count += 1  # HTTPS/DNS/Stego all use network
        if self.has_bluetooth:
            count += 1
        if self.has_serial:
            count += 1  # LoRa via serial
        if self.has_speaker and self.has_microphone:
            count += 1  # Ultrasonic
        if self.has_nfc_reader:
            count += 1
        return count

    def summary(self) -> str:
        """Human-readable hardware summary."""
        parts = []
        if self.has_network:
            parts.append(f"Network ({len(self.network_interfaces)} interfaces)")
        if self.has_bluetooth:
            parts.append(f"Bluetooth ({len(self.bluetooth_devices)} devices)")
        if self.has_serial:
            parts.append(f"Serial ({', '.join(self.serial_ports)})")
        if self.has_speaker and self.has_microphone:
            parts.append("Audio (speaker+mic)")
        if self.has_nfc_reader:
            parts.append("NFC reader")
        if not parts:
            parts.append("No hardware detected — relay-only mode")
        return ', '.join(parts)


def detect_hardware() -> HardwareProfile:
    """Detect available hardware on this machine."""
    profile = HardwareProfile()

    # Detect serial ports (LoRa radios)
    try:
        if os.path.isdir('/dev'):
            for dev in os.listdir('/dev'):
                if dev.startswith('ttyUSB') or dev.startswith('ttyACM'):
                    profile.serial_ports.append(f'/dev/{dev}')
    except OSError:
        pass
    profile.has_serial = len(profile.serial_ports) > 0

    # Detect Bluetooth
    try:
        bt_path = '/sys/class/bluetooth'
        if os.path.isdir(bt_path):
            adapters = [d for d in os.listdir(bt_path) if d.startswith('hci')]
            profile.has_bluetooth = len(adapters) > 0
    except Exception:
        pass

    # Detect audio devices
    try:
        aplay_result = os.popen('aplay -l 2>/dev/null').read()
        profile.has_speaker = 'card' in aplay_result.lower()
        arecord_result = os.popen('arecord -l 2>/dev/null').read()
        profile.has_microphone = 'card' in arecord_result.lower()
    except Exception:
        pass

    # Detect NFC reader
    try:
        usb_devices = os.popen('lsusb 2>/dev/null').read()
        nfc_keywords = ['acr122', 'pn532', 'acr1252', 'scl3711', 'simply4all']
        profile.has_nfc_reader = any(kw in usb_devices.lower() for kw in nfc_keywords)
    except Exception:
        pass

    # Detect network interfaces
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('8.8.8.8', 80))
            profile.network_interfaces.append(s.getsockname()[0])
            profile.has_network = True
        except Exception:
            pass
        finally:
            s.close()
    except Exception:
        pass

    return profile


async def detect_hardware_async() -> HardwareProfile:
    """Async wrapper for hardware detection."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, detect_hardware)
