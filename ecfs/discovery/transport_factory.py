import logging
from ecfs.discovery.hardware import HardwareProfile, detect_hardware
from ecfs.plugins.base import TransportPlugin

logger = logging.getLogger(__name__)


def create_transports(profile: 'HardwareProfile | None' = None) -> list:
    """Auto-create transport plugins based on available hardware.

    Returns a list of configured TransportPlugin instances ready to register.
    No configuration needed — just works.
    """
    if profile is None:
        profile = detect_hardware()

    transports = []

    # Network transports (always try if network available)
    if profile.has_network:
        try:
            from ecfs.plugins.internet_transport import InternetTransport
            transports.append(InternetTransport())
        except Exception as e:
            logger.debug('InternetTransport unavailable: %s', e)

        try:
            from ecfs.plugins.dns_transport import DNSTunnelTransport
            transports.append(DNSTunnelTransport(domain='ecfs.local'))
        except Exception as e:
            logger.debug('DNSTunnelTransport unavailable: %s', e)

        try:
            from ecfs.plugins.stego_transport import SteganographicHTTP
            transports.append(SteganographicHTTP())
        except Exception as e:
            logger.debug('SteganographicHTTP unavailable: %s', e)

    # BLE transport
    if profile.has_bluetooth:
        try:
            from ecfs.plugins.ble_transport import BLETransport
            transports.append(BLETransport())
        except Exception as e:
            logger.debug('BLETransport unavailable: %s', e)

    # LoRa transport (serial radio)
    if profile.has_serial:
        try:
            from ecfs.plugins.lora_transport import LoRaTransport
            transports.append(LoRaTransport(port=profile.serial_ports[0]))
        except Exception as e:
            logger.debug('LoRaTransport unavailable: %s', e)

    # Ultrasonic (speaker + mic)
    if profile.has_speaker and profile.has_microphone:
        try:
            from ecfs.plugins.ultrasonic_transport import UltrasonicAudioTransport
            transports.append(UltrasonicAudioTransport())
        except Exception as e:
            logger.debug('UltrasonicAudioTransport unavailable: %s', e)

    # RFID/NFC
    if profile.has_nfc_reader:
        try:
            from ecfs.plugins.rfid_transport import RFIDTransport
            transports.append(RFIDTransport())
        except Exception as e:
            logger.debug('RFIDTransport unavailable: %s', e)

    logger.info('Auto-created %d transports: %s', len(transports),
                [t.name for t in transports])
    return transports
