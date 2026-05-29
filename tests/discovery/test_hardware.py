import pytest
from ecfs.discovery.hardware import HardwareProfile, detect_hardware, detect_hardware_async


class TestHardwareProfileDefaults:
    def test_hardware_profile_defaults(self):
        """All fields default to False/empty."""
        profile = HardwareProfile()
        assert profile.has_bluetooth is False
        assert profile.has_serial is False
        assert profile.has_speaker is False
        assert profile.has_microphone is False
        assert profile.has_nfc_reader is False
        assert profile.has_network is False
        assert profile.serial_ports == []
        assert profile.bluetooth_devices == []
        assert profile.network_interfaces == []


class TestHardwareProfileTransportCount:
    def test_hardware_profile_transport_count_empty(self):
        """No hardware means zero transports."""
        profile = HardwareProfile()
        assert profile.transport_count == 0

    def test_hardware_profile_transport_count_network(self):
        """Network alone counts as 1."""
        profile = HardwareProfile(has_network=True)
        assert profile.transport_count == 1

    def test_hardware_profile_transport_count_bluetooth(self):
        """Bluetooth counts as 1."""
        profile = HardwareProfile(has_bluetooth=True)
        assert profile.transport_count == 1

    def test_hardware_profile_transport_count_serial(self):
        """Serial counts as 1."""
        profile = HardwareProfile(has_serial=True)
        assert profile.transport_count == 1

    def test_hardware_profile_transport_count_audio(self):
        """Speaker + mic together count as 1."""
        profile = HardwareProfile(has_speaker=True, has_microphone=True)
        assert profile.transport_count == 1

    def test_hardware_profile_transport_count_speaker_only(self):
        """Speaker alone (no mic) counts as 0."""
        profile = HardwareProfile(has_speaker=True)
        assert profile.transport_count == 0

    def test_hardware_profile_transport_count_all(self):
        """All hardware counts correctly."""
        profile = HardwareProfile(
            has_network=True, has_bluetooth=True, has_serial=True,
            has_speaker=True, has_microphone=True, has_nfc_reader=True,
        )
        assert profile.transport_count == 5


class TestHardwareProfileSummary:
    def test_hardware_profile_summary(self):
        """Returns readable string with detected hardware."""
        profile = HardwareProfile(has_network=True, network_interfaces=['192.168.1.1'])
        result = profile.summary()
        assert 'Network' in result
        assert 'interfaces' in result

    def test_hardware_profile_summary_no_hardware(self):
        """Returns relay-only mode message when nothing detected."""
        profile = HardwareProfile()
        result = profile.summary()
        assert 'relay-only mode' in result

    def test_hardware_profile_summary_multiple(self):
        """Multiple hardware types listed."""
        profile = HardwareProfile(has_network=True, has_bluetooth=True)
        result = profile.summary()
        assert 'Network' in result
        assert 'Bluetooth' in result


class TestDetectHardware:
    def test_detect_hardware_returns_profile(self):
        """detect_hardware() returns a HardwareProfile."""
        profile = detect_hardware()
        assert isinstance(profile, HardwareProfile)

    def test_hardware_network_detection(self):
        """On a machine with network, has_network should be True."""
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            s.close()
            has_net = True
        except Exception:
            has_net = False

        profile = detect_hardware()
        if has_net:
            assert profile.has_network is True


@pytest.mark.asyncio
async def test_detect_hardware_async():
    """Async version returns HardwareProfile."""
    profile = await detect_hardware_async()
    assert isinstance(profile, HardwareProfile)
