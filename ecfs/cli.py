"""ECFS CLI — node management, relay server, and diagnostics.

Usage:
    ecfs relay start     Start a public relay server
    ecfs relay status    Check if a relay is running
    ecfs node start      Start a mesh node connected to a relay
    ecfs node send       Send a message through the mesh
    ecfs node receive    Listen for incoming messages
    ecfs detect          Show detected hardware
    ecfs status          Show node status and available transports
    ecfs send <msg>      Send a message (demo mode, no relay)
    ecfs version         Print version
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
import time

from ecfs import __version__


def cmd_version(_args: argparse.Namespace) -> None:
    print(f"ecfs {__version__}")


def cmd_detect(_args: argparse.Namespace) -> None:
    """Show detected hardware on this machine."""
    from ecfs.discovery.hardware import detect_hardware
    profile = detect_hardware()
    print(f"ECFS v{__version__} — Hardware Detection")
    print()
    print(f"  Network:    {'Yes' if profile.has_network else 'No'} ({len(profile.network_interfaces)} interfaces)")
    print(f"  Bluetooth:  {'Yes' if profile.has_bluetooth else 'No'}")
    print(f"  Serial:     {'Yes' if profile.has_serial else 'No'} ({', '.join(profile.serial_ports) if profile.serial_ports else 'none'})")
    print(f"  Speaker:    {'Yes' if profile.has_speaker else 'No'}")
    print(f"  Microphone: {'Yes' if profile.has_microphone else 'No'}")
    print(f"  NFC Reader: {'Yes' if profile.has_nfc_reader else 'No'}")
    print()
    print(f"Available transports: {profile.transport_count}")
    print(f"Summary: {profile.summary()}")


# ── Relay Server Commands ────────────────────────────────────────────

def cmd_relay_start(args: argparse.Namespace) -> None:
    """Start a public ECFS relay server."""
    from ecfs.relay.server import RelayServer

    async def _run():
        server = RelayServer(host=args.host, port=args.port)
        await server.start()
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping relay server...")
            await server.stop()
            print("Stopped.")

    asyncio.run(_run())


def cmd_relay_status(args: argparse.Namespace) -> None:
    """Check relay server status."""
    import urllib.request
    import json

    url = f"{args.url}/health"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            if data.get("ok"):
                print(f"Relay: ONLINE")
                print(f"  Nodes connected: {data.get('nodes', 0)}")
                stats = data.get("stats", {})
                print(f"  Fragments received: {stats.get('fragments_received', 0)}")
                print(f"  Fragments relayed:  {stats.get('fragments_relayed', 0)}")
                print(f"  Nodes registered:   {stats.get('nodes_registered', 0)}")
            else:
                print("Relay: UNHEALTHY")
    except Exception as e:
        print(f"Relay: OFFLINE ({e})")


# ── Node Commands ────────────────────────────────────────────────────

def cmd_node_start(args: argparse.Namespace) -> None:
    """Start an auto-discovering mesh node connected to a relay."""
    from ecfs.discovery.hardware import detect_hardware_async
    from ecfs.discovery.transport_factory import create_transports
    from ecfs.relay.client import RelayClient

    node_name = args.name
    node_id = hashlib.sha256(node_name.encode()).hexdigest()[:16]

    async def _run():
        # Detect local hardware
        profile = await detect_hardware_async()
        local_transports = create_transports(profile)
        transport_names = [t.name for t in local_transports]

        print(f"ECFS Node '{node_name}' starting...")
        print(f"  Node ID:    {node_id}")
        print(f"  Hardware:   {profile.summary()}")
        print(f"  Transports: {', '.join(transport_names) if transport_names else 'none'}")

        # Connect to relay
        relay = None
        if args.relay:
            relay = RelayClient(
                relay_url=args.relay,
                node_id=node_id,
                name=node_name,
                transports=transport_names or ["internet"],
            )
            ok = await relay.connect()
            if ok:
                print(f"  Relay:      Connected to {args.relay}")
                await relay.start_heartbeat()
            else:
                print(f"  Relay:      FAILED to connect to {args.relay}")
                print("  Running in local-only mode")

        print()
        print("Node is running. Use Ctrl+C to stop.")

        # Main loop: poll relay for fragments, forward to local transports
        try:
            while True:
                if relay and relay.is_connected:
                    frags = await relay.poll(timeout=2)
                    for frag in frags:
                        print(f"  Received fragment ({len(frag)} bytes) from relay")
                        # Forward to local transports
                        for t in local_transports:
                            try:
                                await t.send_packet(frag)
                            except Exception:
                                pass
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping node...")
            if relay:
                await relay.disconnect()
            print("Stopped.")

    asyncio.run(_run())


def cmd_node_send(args: argparse.Namespace) -> None:
    """Send a message through a relay."""
    import urllib.request
    import base64
    import json

    node_id = hashlib.sha256(args.name.encode()).hexdigest()[:16]
    relay_url = args.relay

    # Build fragment
    data = args.message.encode()
    fragment_b64 = base64.b64encode(data).decode()

    # Send via HTTP POST
    body = json.dumps({
        "type": "fragment",
        "node_id": node_id,
        "fragment": fragment_b64,
        "dest": args.dest or "*",
        "timestamp": time.time(),
    })

    url = f"{relay_url}/fragment"
    req = urllib.request.Request(
        url,
        data=body.encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())
            if result.get("ok"):
                print(f"Message sent ({len(data)} bytes) via {relay_url}")
            else:
                print(f"Failed: {result.get('error', 'unknown')}")
    except Exception as e:
        print(f"Failed to send: {e}")
        sys.exit(1)


def cmd_node_receive(args: argparse.Namespace) -> None:
    """Listen for incoming messages from a relay."""
    import urllib.request
    import base64
    import json

    node_id = hashlib.sha256(args.name.encode()).hexdigest()[:16]
    relay_url = args.relay

    print(f"Listening as '{args.name}' ({node_id[:8]}...) on {relay_url}")
    print("Waiting for messages (Ctrl+C to stop)...")

    try:
        while True:
            url = f"{relay_url}/poll?node_id={node_id}"
            req = urllib.request.Request(url)
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    result = json.loads(resp.read().decode())
                    if result.get("ok"):
                        frags = result.get("fragments", [])
                        for f in frags:
                            data = base64.b64decode(f["fragment"])
                            print(f"  Received: {data.decode(errors='replace')}")
            except Exception:
                pass
            time.sleep(2)
    except KeyboardInterrupt:
        print("\nStopped listening.")


# ── Legacy Commands ──────────────────────────────────────────────────

def cmd_status(_args: argparse.Namespace) -> None:
    """Show node status (standalone mode, no relay)."""
    print(f"ECFS v{__version__}")
    print("Mode: standalone (no relay)")
    print()
    print("Quick start:")
    print("  ecfs relay start          — start a relay server")
    print("  ecfs node start --relay <url>  — connect a node")
    print("  ecfs detect               — show detected hardware")


def cmd_send(args: argparse.Namespace) -> None:
    """Demo: create a packet, encrypt it (no relay needed)."""
    from ecfs.crypto.keys import ECFSKeyPair
    from ecfs.crypto.packet import ECFSPacket
    from ecfs.crypto.cipher import encrypt_packet_payload

    keypair = ECFSKeyPair.generate()
    print(f"Generated ephemeral keypair: {keypair.key_id.hex()[:16]}...")

    packet = ECFSPacket(
        destination_hash=keypair.public_destination_hash(),
        payload=encrypt_packet_payload(
            args.message.encode(), keypair.derive_shared_secret(keypair.public_exchange)
        ),
    )
    print(f"Packet ID: {packet.message_id}")
    print(f"Size: {len(packet.to_bytes())} bytes")
    print(f"Payload: {args.message}")
    print()
    print("Demo mode — packet created but not sent.")
    print("Use 'ecfs node start --relay <url>' for real transport.")


# ── Argument Parser ──────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ecfs",
        description="Autonomous Emergency Communication Failover System",
    )
    parser.add_argument("--version", action="version", version=f"ecfs {__version__}")

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("version", help="Print version")
    sub.add_parser("status", help="Show node status")
    sub.add_parser("detect", help="Detect hardware on this machine")

    send_p = sub.add_parser("send", help="Send a message (demo)")
    send_p.add_argument("message", help="Message to send")

    # Relay subcommands
    relay_parser = sub.add_parser("relay", help="Relay server commands")
    relay_sub = relay_parser.add_subparsers(dest="relay_command")

    relay_start = relay_sub.add_parser("start", help="Start relay server")
    relay_start.add_argument("--host", default="0.0.0.0", help="Bind host")
    relay_start.add_argument("--port", type=int, default=7700, help="Bind port")

    relay_status = relay_sub.add_parser("status", help="Check relay status")
    relay_status.add_argument("--url", default="http://localhost:7700", help="Relay URL")

    # Node subcommands
    node_parser = sub.add_parser("node", help="Mesh node commands")
    node_sub = node_parser.add_subparsers(dest="node_command")

    node_start = node_sub.add_parser("start", help="Start mesh node")
    node_start.add_argument("--name", default="ecfs-node", help="Node name")
    node_start.add_argument("--relay", help="Relay URL (e.g., http://relay:7700)")

    node_send = node_sub.add_parser("send", help="Send message via relay")
    node_send.add_argument("message", help="Message to send")
    node_send.add_argument("--name", default="ecfs-cli", help="Node name")
    node_send.add_argument("--relay", default="http://localhost:7700", help="Relay URL")
    node_send.add_argument("--dest", default="*", help="Destination node ID (or * for broadcast)")

    node_recv = node_sub.add_parser("receive", help="Listen for messages")
    node_recv.add_argument("--name", default="ecfs-listener", help="Node name")
    node_recv.add_argument("--relay", default="http://localhost:7700", help="Relay URL")

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "version" or getattr(args, "version", False):
        cmd_version(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "send":
        cmd_send(args)
    elif args.command == "detect":
        cmd_detect(args)
    elif args.command == "relay":
        if args.relay_command == "start":
            cmd_relay_start(args)
        elif args.relay_command == "status":
            cmd_relay_status(args)
        else:
            parser.parse_args([args.command, "--help"])
    elif args.command == "node":
        if args.node_command == "start":
            cmd_node_start(args)
        elif args.node_command == "send":
            cmd_node_send(args)
        elif args.node_command == "receive":
            cmd_node_receive(args)
        else:
            parser.parse_args([args.command, "--help"])
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
