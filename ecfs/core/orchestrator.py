"""MeshOrchestrator — the living brain of ECFS.

This is the layer that makes ECFS move like an organism:
- Continuously monitors transport health
- Fires packets through ALL available paths simultaneously (shotgun)
- When a transport dies, seamlessly shifts to others
- Stores packets and retries when new paths appear
- Fragments large messages so pieces can take different routes
- Reassembles at the destination regardless of order
- RELAYS fragments from other nodes — every node is also a router
- Fragments flow through the mesh like water, each node forwarding
  until they reach their destination. The chain never breaks.

The orchestrator is what turns independent transport plugins
into a single adaptive, self-healing mesh.
"""

import asyncio
import hashlib
import logging
import struct
import time
from typing import Callable, Dict, List, Optional, Set

from ecfs.core.fragmentation import Fragment, FragmentManager
from ecfs.core.queue import MessagePriority, MessageQueue, QueuedMessage
from ecfs.core.state_machine import State, StateMachine
from ecfs.plugins.base import TransportPlugin, TransportStatus

logger = logging.getLogger(__name__)


class MeshEvent:
    """Events emitted by the orchestrator for observability."""

    TRANSPORT_UP = "transport_up"
    TRANSPORT_DOWN = "transport_down"
    STATE_CHANGED = "state_changed"
    FRAGMENT_SENT = "fragment_sent"
    FRAGMENT_RECEIVED = "fragment_received"
    MESSAGE_REASSEMBLED = "message_reassembled"
    MESSAGE_QUEUED = "message_queued"
    RETRY_ATTEMPT = "retry_attempt"
    RETRY_SUCCESS = "retry_success"
    FRAGMENT_RELAYED = "fragment_relayed"
    FRAGMENT_DROPPED_TTL = "fragment_dropped_ttl"
    CHAIN_COMPLETE = "chain_complete"


class MeshOrchestrator:
    """The living brain that makes ECFS behave as one adaptive organism.

    Every node is simultaneously a sender, receiver, AND relay.
    Fragments flow through the mesh like water — each node forwards
    fragments it hasn't seen before through all available transports.
    The chain of custody is unbroken from source to destination.

    Usage:
        orch = MeshOrchestrator()
        orch.register_transport(internet_plugin)
        orch.register_transport(lora_plugin)
        await orch.start()

        # Send a message — it fragments + shotguns through all transports
        await orch.send(b"emergency broadcast")

        # Receive — reassembles fragments from any transport
        message = await orch.receive()

        # Relay is automatic — any fragment arriving that isn't from
        # this node gets forwarded through all other transports
    """

    HEALTH_CHECK_INTERVAL = 5.0  # seconds between transport health scans
    RETRY_INTERVAL = 10.0  # seconds between store-and-forward retries
    MAX_RETRY_AGE = 3600.0  # drop messages older than 1 hour
    MAX_HOP_COUNT = 16  # max hops before a fragment is dropped (prevents loops)
    RELAY_DEDUP_TTL = 300.0  # how long to remember relayed fragment hashes (5 min)

    def __init__(
        self,
        node_id: Optional[bytes] = None,
        max_fragment_size: int = 128,
        shotgun_redundancy: int = 2,
        enable_relay: bool = True,
    ) -> None:
        # Node identity (always 32 bytes — pad short IDs with \x00)
        if node_id is None:
            raw = f"ecfs-{time.time()}".encode()
            node_id = hashlib.sha256(raw).digest()[:32]
        self.node_id = node_id[:32].ljust(32, b"\x00")

        # Core components
        self._transports: Dict[str, TransportPlugin] = {}
        self._state_machine = StateMachine()
        self._fragmenter = FragmentManager(
            node_id=node_id, max_fragment_size=max_fragment_size
        )
        self._queue = MessageQueue()
        self._seen_fragments: Set[bytes] = set()  # dedup fragment hashes

        # Relay state
        self._relay_enabled = enable_relay
        self._relay_seen: Dict[bytes, float] = {}  # frag_hash → timestamp
        self._relay_forward_count = 0
        self._relay_drop_count = 0

        # Shotgun config: how many extra redundant copies to send per fragment
        self._shotgun_redundancy = shotgun_redundancy

        # Background tasks
        self._health_task: Optional[asyncio.Task] = None
        self._retry_task: Optional[asyncio.Task] = None
        self._relay_cleanup_task: Optional[asyncio.Task] = None
        self._running = False

        # Event listeners
        self._listeners: Dict[str, List[Callable]] = {}

        # Stats
        self._stats = {
            "messages_sent": 0,
            "messages_received": 0,
            "fragments_sent": 0,
            "fragments_received": 0,
            "deduped": 0,
            "queued": 0,
            "retry_sends": 0,
            "transport_failures": 0,
            "state_transitions": 0,
            "fragments_relayed": 0,
            "fragments_dropped_ttl": 0,
            "relay_deduped": 0,
        }

        # Wire up state machine callbacks
        self._state_machine.on_enter(State.EMERGENCY, self._on_enter_emergency)
        self._state_machine.on_enter(State.NORMAL, self._on_enter_normal)
        self._state_machine.on_enter(State.DEGRADED, self._on_enter_degraded)
        self._state_machine.on_enter(State.RECOVERY, self._on_enter_recovery)

    def register_transport(self, plugin: TransportPlugin) -> None:
        """Register a transport plugin with the orchestrator."""
        self._transports[plugin.name] = plugin
        logger.info("Registered transport: %s (type=%s, priority=%d)",
                     plugin.name, plugin.transport_type.value, plugin.priority)

    def on(self, event: str, callback: Callable) -> None:
        """Listen for orchestrator events."""
        if event not in self._listeners:
            self._listeners[event] = []
        self._listeners[event].append(callback)

    def _emit(self, event: str, **kwargs) -> None:
        """Emit an event to all listeners."""
        for callback in self._listeners.get(event, []):
            try:
                callback(event=event, **kwargs)
            except Exception:
                logger.exception("Event listener error for %s", event)

    async def start(self) -> None:
        """Start the orchestrator and all transports."""
        if self._running:
            return

        self._running = True
        logger.info("Starting MeshOrchestrator (node=%s)", self.node_id.hex()[:8])

        # Initialize all transports
        for name, plugin in self._transports.items():
            try:
                await plugin.initialize()
                logger.info("Transport initialized: %s", name)
            except Exception:
                logger.exception("Failed to initialize transport: %s", name)

        # Initial state evaluation
        self._evaluate_state()

        # Start background loops
        self._health_task = asyncio.create_task(self._health_monitor_loop())
        self._retry_task = asyncio.create_task(self._retry_loop())
        if self._relay_enabled:
            self._relay_cleanup_task = asyncio.create_task(self._relay_cleanup_loop())

        logger.info(
            "MeshOrchestrator running — state=%s, transports=%d, relay=%s",
            self._state_machine.current_state.name,
            len(self._transports),
            "on" if self._relay_enabled else "off",
        )

    async def stop(self) -> None:
        """Stop everything gracefully."""
        self._running = False

        if self._health_task:
            self._health_task.cancel()
        if self._retry_task:
            self._retry_task.cancel()
        if self._relay_cleanup_task:
            self._relay_cleanup_task.cancel()

        for plugin in self._transports.values():
            try:
                await plugin.teardown()
            except Exception:
                logger.exception("Error tearing down transport: %s", plugin.name)

        logger.info("MeshOrchestrator stopped")

    async def send(
        self,
        data: bytes,
        priority: MessagePriority = MessagePriority.NORMAL,
    ) -> bool:
        """Send a message through the mesh.

        1. Fragment the message into numbered pieces
        2. Get all available transports
        3. Shotgun fragments through multiple transports simultaneously
        4. If no transports available, queue for retry
        """
        # Fragment the message
        fragments = self._fragmenter.fragment(data)

        # Get available transports
        online = await self._get_online_transports()

        if not online:
            # No transports — queue the original data for retry
            logger.warning("No online transports, queuing message (%d bytes)", len(data))
            await self._queue.enqueue(
                data, message_id=data, priority=priority
            )
            self._stats["queued"] += 1
            self._emit(MeshEvent.MESSAGE_QUEUED, data_size=len(data))
            return False

        # Shotgun: fire fragments through multiple transports
        sent_count = 0
        for frag in fragments:
            frag_bytes = frag.encode()
            frag_hash = frag.fragment_hash

            # Dedup check
            if frag_hash in self._seen_fragments:
                self._stats["deduped"] += 1
                continue

            # Determine how many transports to send this fragment through
            num_paths = min(
                self._shotgun_redundancy if priority == MessagePriority.NORMAL else len(online),
                len(online),
            )

            # Sort transports: prefer faster/more reliable ones for each copy
            sorted_transports = sorted(online, key=lambda p: p.priority)

            sent_via = []
            for transport in sorted_transports[:num_paths]:
                try:
                    success = await transport.send_packet(frag_bytes)
                    if success:
                        sent_via.append(transport.name)
                        sent_count += 1
                except Exception as e:
                    self._stats["transport_failures"] += 1
                    logger.warning("Send failed on %s: %s", transport.name, e)

            if sent_via:
                self._seen_fragments.add(frag_hash)
                self._stats["fragments_sent"] += 1
                self._emit(
                    MeshEvent.FRAGMENT_SENT,
                    message_id=frag.message_id.hex()[:8],
                    fragment_index=frag.fragment_index,
                    sent_via=sent_via,
                )

        if sent_count > 0:
            self._stats["messages_sent"] += 1
            return True

        return False

    async def receive(self) -> Optional[bytes]:
        """Receive a complete reassembled message from any transport.

        This is the heart of the "water" behavior:
        1. Poll all transports for incoming fragments
        2. If a fragment originated from THIS node → try reassembly (it's for us)
        3. If a fragment originated from ANOTHER node → relay it forward
        4. Fragments flow through the mesh like water, each node forwarding
           until they reach their destination. The chain never breaks.
        """
        for name, plugin in self._transports.items():
            try:
                raw = await plugin.receive_packet()
                if raw is None:
                    continue

                # Try to decode as a fragment
                try:
                    frag = Fragment.decode(raw)
                except (ValueError, struct.error):
                    # Not a fragment — pass through raw (backward compat)
                    self._stats["messages_received"] += 1
                    return raw

                # Check version
                if frag.version != 1:
                    continue

                # Fragment dedup — same fragment from different transports
                frag_hash = frag.fragment_hash
                if frag_hash in self._seen_fragments:
                    self._stats["deduped"] += 1
                    continue
                self._seen_fragments.add(frag_hash)

                self._stats["fragments_received"] += 1
                self._emit(
                    MeshEvent.FRAGMENT_RECEIVED,
                    message_id=frag.message_id.hex()[:8],
                    fragment_index=frag.fragment_index,
                    from_transport=name,
                )

                # Is this fragment from another node? If so, relay it.
                # Every node is also a router — fragments flow through
                # the mesh like water, each hop bringing them closer
                # to their destination.
                is_from_another_node = frag.origin != self.node_id
                if is_from_another_node and self._relay_enabled:
                    await self._relay_fragment(frag, from_transport=name)

                # ALWAYS try reassembly regardless of origin.
                # The destination node (and any intermediate node) can
                # reassemble — the dedup cache prevents double-processing.
                complete_data = self._fragmenter.receive_fragment(frag)
                if complete_data is not None:
                    self._stats["messages_received"] += 1
                    self._emit(
                        MeshEvent.MESSAGE_REASSEMBLED,
                        message_id=frag.message_id.hex()[:8],
                        size=len(complete_data),
                        fragments=frag.fragment_total,
                    )
                    return complete_data

            except Exception:
                logger.exception("Receive error on transport: %s", name)

        return None

    # ── Relay System ─────────────────────────────────────────────────
    #
    # Every node acts as a router. When a fragment arrives that
    # originated from another node, this node forwards it through
    # all available transports (except the one it came from).
    # This creates the "water" flow — packets move through the mesh
    # organically, each hop bringing them closer to their destination.
    #
    # The relay dedup cache prevents infinite loops: if we've already
    # forwarded a fragment, we won't forward it again. The cache
    # entries expire after RELAY_DEDUP_TTL seconds.

    async def _relay_fragment(
        self, frag: Fragment, from_transport: str
    ) -> None:
        """Forward a fragment through all available transports except the source.

        This is the relay behavior that makes ECFS move like water.
        The fragment came in on `from_transport` — we forward it on
        every OTHER available transport so it continues flowing
        toward its destination.
        """
        if not self._relay_enabled:
            return

        frag_hash = frag.fragment_hash

        # TTL check: if fragment is too old, drop it (prevents stale packets
        # from circulating forever in case of dedup failures)
        age = time.time() - frag.timestamp
        if age > self.MAX_HOP_COUNT * 2.0:  # generous: 2 sec per hop × max hops
            self._stats["fragments_dropped_ttl"] += 1
            self._relay_drop_count += 1
            self._emit(
                MeshEvent.FRAGMENT_DROPPED_TTL,
                message_id=frag.message_id.hex()[:8],
                age_seconds=round(age, 1),
            )
            logger.warning(
                "Relay drop (TTL): fragment from %s aged %.1fs, max %.1fs",
                frag.origin.hex()[:8],
                age,
                self.MAX_HOP_COUNT * 2.0,
            )
            return

        # Relay dedup: don't forward the same fragment twice
        if frag_hash in self._relay_seen:
            self._stats["relay_deduped"] += 1
            return

        # Mark as relayed
        self._relay_seen[frag_hash] = time.time()

        # Get all online transports EXCEPT the one it came from
        online = await self._get_online_transports()
        relay_targets = [t for t in online if t.name != from_transport]

        if not relay_targets:
            logger.debug(
                "Relay: no other transports available for fragment from %s",
                frag.origin.hex()[:8],
            )
            return

        # Forward the fragment through all available paths
        frag_bytes = frag.encode()
        relayed_via = []
        for transport in relay_targets:
            try:
                success = await transport.send_packet(frag_bytes)
                if success:
                    relayed_via.append(transport.name)
                    self._relay_forward_count += 1
            except Exception as e:
                logger.debug(
                    "Relay send failed on %s: %s", transport.name, e
                )

        if relayed_via:
            self._stats["fragments_relayed"] += 1
            self._emit(
                MeshEvent.FRAGMENT_RELAYED,
                message_id=frag.message_id.hex()[:8],
                fragment_index=frag.fragment_index,
                origin=frag.origin.hex()[:8],
                from_transport=from_transport,
                relayed_via=relayed_via,
            )
            logger.info(
                "Relayed fragment #%d of msg %s via [%s] (from %s via %s)",
                frag.fragment_index,
                frag.message_id.hex()[:8],
                ",".join(relayed_via),
                frag.origin.hex()[:8],
                from_transport,
            )

    async def _relay_cleanup_loop(self) -> None:
        """Periodically clean up expired relay dedup entries."""
        while self._running:
            try:
                await asyncio.sleep(60.0)  # run every minute
                now = time.time()
                expired = [
                    h for h, ts in self._relay_seen.items()
                    if now - ts > self.RELAY_DEDUP_TTL
                ]
                for h in expired:
                    del self._relay_seen[h]
                if expired:
                    logger.debug(
                        "Relay dedup cache: cleaned %d entries, %d remaining",
                        len(expired),
                        len(self._relay_seen),
                    )
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Relay cleanup error")

    async def health_check(self) -> dict:
        """Check health of all transports and the orchestrator."""
        transport_health = {}
        for name, plugin in self._transports.items():
            try:
                status = await plugin.get_status()
                transport_health[name] = {
                    "status": status.name.lower(),
                    "type": plugin.transport_type.value,
                    "priority": plugin.priority,
                }
            except Exception:
                transport_health[name] = {"status": "error"}

        return {
            "running": self._running,
            "state": self._state_machine.current_state.name,
            "transports": transport_health,
            "online_count": sum(
                1 for h in transport_health.values()
                if h.get("status") in ("online", "degraded")
            ),
            "total_count": len(self._transports),
            "pending_reassembly": len(self._fragmenter.get_pending_info()),
            "queued_messages": self._queue.size,
            "relay_enabled": self._relay_enabled,
            "relay_cache_size": len(self._relay_seen),
            "relay_forward_count": self._relay_forward_count,
            "relay_drop_count": self._relay_drop_count,
            "stats": self._stats,
        }

    # ── Background Loops ──────────────────────────────────────────────

    async def _health_monitor_loop(self) -> None:
        """Continuously scan transport health and trigger failover."""
        while self._running:
            try:
                await asyncio.sleep(self.HEALTH_CHECK_INTERVAL)
                self._evaluate_state()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Health monitor error")
                await asyncio.sleep(1.0)

    async def _retry_loop(self) -> None:
        """Periodically retry sending queued packets when transports come back."""
        while self._running:
            try:
                await asyncio.sleep(self.RETRY_INTERVAL)
                await self._flush_queue()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Retry loop error")
                await asyncio.sleep(1.0)

    async def _flush_queue(self) -> None:
        """Try to send all queued messages through available transports."""
        if self._queue.size == 0:
            return

        online = await self._get_online_transports()
        if not online:
            return

        retry_count = 0
        while self._queue.size > 0:
            msg = await self._queue.dequeue()
            if msg is None:
                break

            success = await self.send(msg.data, priority=msg.priority)
            retry_count += 1
            self._stats["retry_sends"] += 1

            if success:
                self._emit(MeshEvent.RETRY_SUCCESS, size=len(msg.data))
            else:
                # Re-queue if still can't send (it'll be re-dequeued on next cycle)
                await self._queue.enqueue(msg.data, msg.message_id, priority=msg.priority)
                break

        if retry_count > 0:
            logger.info("Retried %d queued messages", retry_count)
            self._emit(MeshEvent.RETRY_ATTEMPT, count=retry_count)

    # ── State Machine Integration ─────────────────────────────────────

    def _evaluate_state(self) -> None:
        """Check transport health and transition state machine."""
        old_state = self._state_machine.current_state

        # Build list of plugins with their current status
        plugins = list(self._transports.values())
        self._state_machine.evaluate(plugins)

        new_state = self._state_machine.current_state
        if old_state != new_state:
            self._stats["state_transitions"] += 1
            self._emit(
                MeshEvent.STATE_CHANGED,
                old_state=old_state.name,
                new_state=new_state.name,
            )
            logger.warning(
                "State transition: %s → %s",
                old_state.name,
                new_state.name,
            )

    def _on_enter_emergency(self, old_state: State, new_state: State) -> None:
        """Entered emergency mode — all or most transports are down."""
        logger.critical(
            "EMERGENCY MODE: Transports failed. "
            "Packets will be queued and retried when paths reappear."
        )

    def _on_enter_normal(self, old_state: State, new_state: State) -> None:
        """Returned to normal — most transports are healthy."""
        logger.info("NORMAL MODE: Transports recovered. Flushing queue.")
        # Trigger a queue flush via the retry loop

    def _on_enter_degraded(self, old_state: State, new_state: State) -> None:
        """Degraded — some transports lost, but enough remain."""
        logger.warning("DEGRADED MODE: Some transports unavailable. Using remaining paths.")

    def _on_enter_recovery(self, old_state: State, new_state: State) -> None:
        """Recovery — transports coming back after emergency."""
        logger.info("RECOVERY MODE: Transports returning. Flushing queue.")

    # ── Helpers ───────────────────────────────────────────────────────

    async def _get_online_transports(self) -> List[TransportPlugin]:
        """Get all transports that are online or degraded."""
        result = []
        for plugin in self._transports.values():
            try:
                status = await plugin.get_status()
                if status in (TransportStatus.ONLINE, TransportStatus.DEGRADED):
                    result.append(plugin)
            except Exception:
                pass
        return sorted(result, key=lambda p: p.priority)

    @property
    def state(self) -> State:
        return self._state_machine.current_state

    @property
    def stats(self) -> dict:
        return dict(self._stats)

    @property
    def transport_names(self) -> List[str]:
        return list(self._transports.keys())
