# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/00_nostr_core.ipynb.

# %% auto 0
__all__ = ['PrivateKey', 'PublicKey', 'MessagePool', 'Connection', 'Relay', 'RelayManager']

# %% ../nbs/00_nostr_core.ipynb 7
from nostr import key
from nostr import bech32
import secp256k1
from fastcore.utils import patch

# %% ../nbs/00_nostr_core.ipynb 8
class PrivateKey(key.PrivateKey):
    """a class to manage private keys inherited from
    python-nostr.key.PrivateKey, with a from_hex() class method added
    """
    def __init__(self, *args, **kwargs):
        """create a private key from raw bytes
        """
        super().__init__(*args, **kwargs)
        sk = secp256k1.PrivateKey(self.raw_secret)
        self.public_key = PublicKey(sk.pubkey.serialize()[1:])

    def __repr__(self):
        pubkey = self.public_key.bech32()
        return f'PrivateKey({pubkey[:10]}...{pubkey[-10:]})'

    @classmethod
    def from_hex(cls, hex: str) -> 'PrivateKey':
        return cls(bytes.fromhex(hex))

class PublicKey(key.PublicKey):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def __repr__(self):
        pubkey = self.bech32()
        return f'PublicKey({pubkey[:10]}...{pubkey[-10:]})'
    
    @classmethod
    def from_npub(cls, npub: str):
        """ Load a PublicKey from its bech32/npub form """
        hrp, data, spec = bech32.bech32_decode(npub)
        raw_bytes = bech32.convertbits(data, 5, 8)[:-1]
        return cls(bytes(raw_bytes))

    @classmethod
    def from_hex(cls, hex: str) -> 'PrivateKey':
        return cls(bytes.fromhex(hex))

# %% ../nbs/00_nostr_core.ipynb 43
import json
import time
import warnings
import threading
from threading import Lock
from typing import Union
from queue import Queue
from nostr import message_pool
from nostr import relay, relay_manager
from nostr.relay import RelayPolicy
from nostr.message_pool import EventMessage, NoticeMessage, EndOfStoredEventsMessage
from nostr.message_type import RelayMessageType
from nostr.event import Event

# %% ../nbs/00_nostr_core.ipynb 45
class MessagePool(relay_manager.MessagePool):
    def __init__(self, first_response_only: bool = True):
        self.first_response_only = first_response_only
        self.events: Queue[EventMessage] = Queue()
        self.notices: Queue[NoticeMessage] = Queue()
        self.eose_notices: Queue[EndOfStoredEventsMessage] = Queue()
        self._unique_objects: set = set()
        self.lock: Lock = Lock()

    def _process_message(self, message: str, url: str):
        message_json = json.loads(message)
        message_type = message_json[0]
        if message_type == RelayMessageType.EVENT:
            subscription_id = message_json[1]
            e = message_json[2]
            event = Event(e['pubkey'], e['content'], e['created_at'], e['kind'], e['tags'], e['id'], e['sig'])
            with self.lock:
                if self.first_response_only:
                    object_id = event.id
                else:
                    object_id = f'{event.id}:{url}'
                if object_id not in self._unique_objects:
                    self.events.put(EventMessage(event, subscription_id, url))
                    self._unique_objects.add(event.id)


# %% ../nbs/00_nostr_core.ipynb 46
class Connection:
    def __init__(self, relay_or_manager: Union[relay.Relay, relay_manager.RelayManager],
                 *args, **kwargs):
        self.relay_manager = relay_or_manager
        self.conn = self.relay_manager.open_connections(*args, **kwargs)
    def __enter__(self):
        return self.conn
    def __exit__(self, ex_type, ex_value, traceback):
        self.relay_manager.close_connections()
        return False


class Relay(relay.Relay):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def __repr__(self):
        return json.dumps(self.to_json_object(), indent=2)

    @property
    def is_connected(self) -> bool:
        return False if self.ws.sock is None else self.ws.sock.connected
    
    def open_connections(self, ssl_options: dict={}):
        threading.Thread(
                target=self.connect,
                args=(ssl_options,),
                name=f"{self.url}-thread"
        ).start()
    
    def close(self):
        if self.ws.sock is not None:
            self.ws.close()
    
    def close_connections(self):
        self.close()
    
    def connection(self, *args, **kwargs):
        return Connection(self, *args, **kwargs)


# %% ../nbs/00_nostr_core.ipynb 47
class RelayManager(relay_manager.RelayManager):
    def __init__(self, first_response_only: bool = True,  *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.relays: dict[str, Relay] = {}
        self.message_pool = MessagePool(first_response_only=first_response_only)
        self._is_connected = False

    def __iter__(self):
        return iter(self.relays.values())
    
    def connection(self, *args, **kwargs):
        return Connection(self, *args, **kwargs)
    
    def open_connections(self, ssl_options: dict=None):
        for relay in self.relays.values():
            if not relay.is_connected:
                threading.Thread(
                    target=relay.connect,
                    args=(ssl_options,),
                    name=f"{relay.url}-thread"
                ).start()
        time.sleep(2)
        self.remove_closed_relays()
        assert all(self.connection_statuses.values())
        self._is_connected = True
    
    def close_connections(self):
        for relay in self.relays.values():
            relay.close()

        assert not any(self.connection_statuses.values())
        self._is_connected = False

    def remove_closed_relays(self):
        for url, connected in self.connection_statuses.items():
            if not connected:
                warnings.warn(
                    f'{url} is not connected... removing relay.'
                )
                self.remove_relay(url=url)

    def add_relay(self, url: str, read: bool=True, write: bool=True, subscriptions=None):
        subscriptions = subscriptions if subscriptions is not None else {}
        policy = RelayPolicy(read, write)
        relay = Relay(url, policy, self.message_pool, subscriptions)
        self.relays[url] = relay
    
    def remove_relay(self, url: str):
        self.relays[url].close()
        self.relays.pop(url)

    @property
    def connection_statuses(self) -> dict:
        """gets the url and connection statuses of relays

        Returns:
            dict: bool of connection statuses
        """
        statuses = [relay.is_connected for relay in self]
        return dict(zip(self.relays.keys(), statuses))
