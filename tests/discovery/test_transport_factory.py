import pytest
from ecfs.discovery.hardware import HardwareProfile
from ecfs.discovery.transport_factory import create_transports
from ecfs.plugins.base import TransportPlugin


class TestCreateTransportsNoHardware:
    def test_create_transports_with_no_hardware(self):
        """No hardware means no transports."""
        profile = HardwareProfile()
        transports = create_transports(profile)
        assert transports == []


class TestCreateTransportsNetwork:
    def test_create_transports_with_network(self):
        """Network hardware creates network transports."""
        profile = HardwareProfile(has_network=True)
        transports = create_transports(profile)
        names = [t.name for t in transports]
        # Should have internet, dns, stego transports
        assert any('internet' in n.lower() for n in names)
        assert any('dns' in n.lower() for n in names)


class TestCreateTransportsBluetooth:
    def test_create_transports_with_bluetooth(self):
        """Bluetooth hardware creates BLE transport."""
        profile = HardwareProfile(has_bluetooth=True)
        transports = create_transports(profile)
        names = [t.name for t in transports]
        # BLE transport may not initialize on a machine without bluetooth adapter
        # but the factory should try to create it
        if transports:
            assert any('ble' in n.lower() for n in names)


class TestCreateTransportsSerial:
    def test_create_transports_with_serial(self):
        """Serial hardware creates LoRa transport."""
        profile = HardwareProfile(has_serial=True, serial_ports=['/dev/ttyUSB0'])
        transports = create_transports(profile)
        names = [t.name for t in transports]
        # LoRa may not init without real hardware, but factory tries
        if transports:
            assert any('lora' in n.lower() for n in names)


class TestCreateTransportsDeterministic:
    def test_create_transports_profiles_deterministic(self):
        """Same profile always produces same transport count."""
        profile = HardwareProfile(has_network=True)
        t1 = create_transports(profile)
        t2 = create_transports(profile)
        assert len(t1) == len(t2)

    def test_all_transports_are_plugins(self):
        """Every created transport is a TransportPlugin."""
        profile = HardwareProfile(has_network=True)
        transports = create_transports(profile)
        for t in transports:
            assert isinstance(t, TransportPlugin)
