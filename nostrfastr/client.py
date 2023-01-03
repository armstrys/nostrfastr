# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/01_client.ipynb.

# %% auto 0
__all__ = ['Client']

# %% ../nbs/01_client.ipynb 6
import warnings
import json
import time
import os
import pprint
import sqlite3
import appdirs
import pandas as pd
from pathlib import Path
from nostr.message_type import ClientMessageType
from nostr.message_pool import EventMessage,\
    NoticeMessage, EndOfStoredEventsMessage
from nostr.filter import Filter, Filters
from nostr.event import Event, EventKind
from .nostr import PrivateKey, PublicKey,\
    RelayManager, MessagePool

from fastcore.utils import patch

# %% ../nbs/01_client.ipynb 8
class Client:
    def __init__(self, public_key_hex: str = None, private_key_hex: str = None,
                 db_name: str = 'nostr-data', relay_urls: list = None, ssl_options: dict = {},
                 first_response_only: bool = True):
        """A basic framework for common operations that a nostr client will
        need to execute.

        Args:
            public_key_hex (str, optional): public key to initiate client
            private_key_hex (str, optional): private key to log in with public key.
                Defaults to None, in which case client is effectively read only
            relay_urls (list, optional): provide a list of relay urls.
                Defaults to None, in which case a default list will be used.
            ssl_options (dict, optional): ssl options for websocket connection
                Defaults to empty dict
            allow_duplicates (bool, optional): whether or not to allow duplicate
                event ids into the queue from multiple relays. This isn't fully
                working yet. Defaults to False.
        """
        self.ssl_options = ssl_options
        self.first_response_only = first_response_only
        self.set_account(public_key_hex=public_key_hex,
                          private_key_hex=private_key_hex)
        if relay_urls is None:
            relay_urls = [
                'wss://nostr-2.zebedee.cloud',
                'wss://relay.damus.io',
                'wss://brb.io',
                'wss://nostr-2.zebedee.cloud',
                'wss://rsslay.fiatjaf.com',
                'wss://nostr-relay.wlvs.space',
                'wss://nostr.orangepill.dev',
                'wss://nostr.oxtr.dev'
            ]
        else:
            pass
        self.relay_manager = RelayManager(first_response_only=self.first_response_only)
        self.events_table_name = 'events'
        self.events_table_indexes = ['id', 'url']
        self.events_table_types = {
            'id': 'char',
            'pubkey': 'char',
            'created_at': 'int',
            'kind': 'int',
            'tags': 'char',
            'content': 'char',
            'sig': 'char',
            'subscription_id': 'char',
            'url': 'char'
        }
        self.db_location = Path(appdirs.user_data_dir('python-nostr'))
        self.db_name = db_name
        self.init_db()
        self.set_relays(relay_urls=relay_urls)
        self.load_existing_event_ids()

    def set_account(self, public_key_hex: str = None, private_key_hex: str = None) -> None:
        """logic to set public and private keys

        Args:
            public_key_hex (str, optional): if only public key is provided, operations
                that require a signature will fail. Defaults to None.
            private_key_hex (str, optional): _description_. Defaults to None.

        Raises:
            ValueException: if the private key and public key are both provided but
                don't match
        """
        self.private_key = None
        self.public_key = None
        if private_key_hex is None:
            self.private_key = self._request_private_key_hex()
        else:
            self.private_key = PrivateKey.from_hex(private_key_hex)

        if public_key_hex is None:
            self.public_key = self.private_key.public_key
        else:
            self.public_key = PublicKey.from_hex(public_key_hex)
        public_key_hex = self.public_key.hex()
        
        if public_key_hex != self.private_key.public_key.hex():
            self.public_key = PublicKey.from_hex(public_key_hex)
            self.private_key = None
        print(f'logged in as public key\n'
              f'\tbech32: {self.public_key.bech32()}\n'
              f'\thex: {self.public_key.hex()}')
    
    def _request_private_key_hex(self) -> str:
        """method to request private key. this method should be overwritten
        when building out a UI

        Returns:
            PrivateKey: the new private_key object for the client. will also
                be set in place at self.private_key
        """
        self.private_key = PrivateKey()
        return self.private_key
    
    @property
    def db_conn(self):
        self.db_location.mkdir(exist_ok=True)
        return sqlite3.Connection(self.db_location / f'{self.db_name}.sqlite')
    
    def init_db(self):
        table_columns = ', '.join([f'{col} {sql_type}' for col, sql_type
                                   in self.events_table_types.items()])
        with self.db_conn as con:
            con.execute(f'CREATE TABLE IF NOT EXISTS {self.events_table_name} '
                        f'({table_columns});')
            for idx in self.events_table_indexes:
                con.execute(f'CREATE INDEX IF NOT EXISTS {idx}_IDX ON {self.events_table_name}({idx});')
        
    def set_relays(self, relay_urls: list = None):
        relays_to_add = set(relay_urls) - set(self.relay_manager.relays.keys())
        relays_to_remove = set(self.relay_manager.relays.keys()) - set(relay_urls)
        for url in relays_to_remove:
            self.relay_manager.remove_relay(url)
        was_connected = self.relay_manager._is_connected
        for url in relays_to_add:
            self.relay_manager.add_relay(url=url)
        if was_connected:
            self.relay_manager.open_connections()

    def load_existing_event_ids(self):
        ids = pd.read_sql(sql='select id, url from events',
                          con=self.db_conn)
        if self.first_response_only:
            ids = ids['id']
        else:
            ids = ids['id'] + ':' + ids['url']
        self.relay_manager.message_pool._unique_objects = set(ids.to_list())

# %% ../nbs/01_client.ipynb 16
@patch
def __enter__(self: Client):
    """context manager to allow processing a connected client
    within a `with` statement

    Returns:
        self: a `with` statement returns this object as it's assignment
        so that the client can be instantiated and used within
        the `with` statement.
    """
    self.connect()
    return self

@patch
def __exit__(self: Client, ex_type, ex_value, traceback):
    """closes the connections when exiting the `with` context

    arguments are currently unused, but could be use to control
    client behavior on error.

    Args:
        ex_type: exception type
        ex_value: exception value
        traceback: exception traceback
    """
    self.disconnect()
    return False

@patch
def connect(self: Client) -> None:
    self.relay_manager.open_connections(self.ssl_options)

@patch
def disconnect(self: Client) -> None:
    self.relay_manager.close_connections()


# %% ../nbs/01_client.ipynb 23
import uuid
from typing import Union

# %% ../nbs/01_client.ipynb 24
@patch
def publish_subscription(self: Client, filters: Union[Filter, Filters],
                         subscription_id: str = str(uuid.uuid4())) -> None:
    """publishes a request from a subscription id and a set of filters. Filters
    can be defined using the request_by_custom_filter method or from a list of
    preset filters (as of yet to be created):

    Args:
        request_filters (Filters): list of filters for a subscription
        subscription_id (str): subscription id to be sent to relay. defaults
            to a random guid
    """
    if isinstance(filters, Filter):
        filters = Filters([filters])
    request = [ClientMessageType.REQUEST, subscription_id]
    request.extend(filters.to_json_array())
    message = json.dumps(request)
    self.relay_manager.add_subscription(
        subscription_id, filters
        )
    self.relay_manager.publish_message(message)
    time.sleep(1)
    self.get_notices_from_relay()

@patch
def _notice_handler(self: Client, notice_msg: NoticeMessage):
    """a hidden method used to handle notice outputs
    from a relay. This method can be overwritten to display notices
    differently if needed

    Args:
        notice_msg (NoticeMessage): Notice message returned from relay
    """
    warnings.warn(f'{notice_msg.url}:\n\t{notice_msg.content}')

@patch
def get_notices_from_relay(self: Client):
    """calls the _notice_handler method on all notices from relays
    """
    while self.relay_manager.message_pool.has_notices():
        notice_msg = self.relay_manager.message_pool.get_notice()
        self._notice_handler(notice_msg=notice_msg)


# %% ../nbs/01_client.ipynb 28
@patch
def _event_handler(self: Client, event_msg: EventMessage) -> pd.DataFrame:
    """a hidden method used to handle event outputs
    from a relay. This can be overwritten to store events
    to a db for example.

    Args:
        event_msg (EventMessage): Event message returned from relay
    """
    self.insert_event_to_database(event_msg)

@patch
def get_events_pool(self: Client):
    """calls the _event_handler method on all events from relays
    """
    self.events = []
    while self.relay_manager.message_pool.has_events():
        event_msg = self.relay_manager.message_pool.get_event()
        self._event_handler(event_msg=event_msg)

@patch
def insert_event_to_database(self: Client, event_msg: EventMessage):
    table_column_names = ', '.join([col for col in self.events_table_types.keys()])
    event_json = event_msg.event.to_json_object()
    event_json['subscription_id'] = event_msg.subscription_id
    event_json['url'] = event_msg.url
    for col, sql_type in self.events_table_types.items():
        if sql_type == 'char':
            data = str(event_json[col]).replace('\'','\'\'') \
                                  .replace('\"','\"\"')
            event_json[col] = f'\"{data}\"'
        else:
            event_json[col] = str(event_json[col])

    table_values = ', '.join(
        [event_json[col] for col in self.events_table_types.keys()]
        )
    sql = f'''
        INSERT INTO {self.events_table_name} ({table_column_names})
        VALUES ({table_values});
        '''
    with self.db_conn as con:
        con.execute(sql)

# %% ../nbs/01_client.ipynb 34
@patch
def _eose_handler(self: Client, eose_msg: EndOfStoredEventsMessage):
    """a hidden method used to handle notice outputs
    from a relay. This can be overwritten to display notices
    differently - should be warnings or errors?

    Args:
        notice_msg (EndOfStoredEventsMessage): Message from relay
            to signify the last event in a subscription has been
            provided.
    """
    print(f'end of subscription: {eose_msg.subscription_id} received.')

@patch
def get_eose_from_relay(self: Client):
    """calls the _eose_handler end of subsribtion events from relays
    """
    while self.relay_manager.message_pool.has_eose_notices():
        eose_msg = self.relay_manager.message_pool.get_eose_notice()
        self._eose_handler(eose_msg=eose_msg)


# %% ../nbs/01_client.ipynb 36
@patch
def publish_event(self: Client, event: Event) -> None:
    """publish an event and immediately checks for a notice
    from the relay in case of an invalid event

    Args:
        event (Event): _description_
    """
    if self.private_key is None:
        self.private_key = self._request_private_key_hex()
    if not isinstance(event.created_at, int):
        event.created_at = int(event.created_at)
    self.check_event_pubkey(event)
    event.sign(self.private_key.hex())
    assert event.verify()
    message = json.dumps([ClientMessageType.EVENT, event.to_json_object()])
    self.relay_manager.publish_message(message)
    time.sleep(1)
    self.get_notices_from_relay()

@patch
def check_event_pubkey(self: Client, event: Event):
    if self.public_key.hex() != event.public_key:
        if self.private_key.public_key.hex() != self.public_key.hex():
            raise RuntimeError('cannot create event. '
                               'client private key and public key don\'t match')
        else:
            raise Exception('event is not valid')
    else:
        pass

# %% ../nbs/01_client.ipynb 40
@patch
def filter_events_by_id(self: Client, ids: Union[str,list]) -> Filter:
    """build a filter from event ids

    Args:
        ids (Union[str,list]): an event id or a list of event ids to request

    Returns:
        Filter: A filter object to use with a subscription
    """
    if isinstance(ids, str):
        ids = [ids]
    return Filter(
        ids=ids
        )

@patch
def filter_events_authors(self: Client, authors: Union[str,list]) -> Filter:
    """build a filter from authors

    Args:
        authors (Union[str,list]): an author or a list of authors to request

    Returns:
        Filter: A filter object to use with a subscription
    """
    # TODO: add support for npubs
    if isinstance(authors, str):
        authors = [authors]
    return Filter(
        authors=authors
        )

@patch
def event_metadata(self: Client,
                   name: str = None,
                   about: str = None,
                   picture: str = None,
    ) -> Event:
    """_summary_

    Args:
        self (Client): _description_
        name (str, optional): profile name. Defaults to None.
        about (str, optional): profile about me. Defaults to None.
        picture (str, optional): url to profile picture. Defaults to None.

    Returns:
        Event: Event to publish for a metadata update
    """
    # TODO: implement nip-05
    items = {
        'name': name,
        'about': about,
        'picture': picture
    }
    content = {}
    for item_name, item_value in items.items():
        if item_value is not None:
            content.update({f'{item_name}': f'{item_value}'})
    content = json.dumps(content)
    event = Event(public_key=self.public_key.hex(),
                  kind=EventKind.SET_METADATA,
                  content=content,
                  created_at=int(time.time()))
    return event

@patch
def event_text_note(self: Client, text: str) -> Event:
    """create a text not event

    Args:
        text (str): text for nostr note to be published
    """
    # TODO: need regex parsing to handle @ and note references
    event = Event(public_key=self.public_key.hex(),
                  content=text,
                  kind=EventKind.TEXT_NOTE,
                  created_at=int(time.time()))
    return event

@patch
def event_recommended_relay(self: Client, relay_list) -> Event:
    raise NotImplementedError()

@patch
def event_deletion(self: Client,
                     event_ids: Union[str,list],
                     reason: str) -> Event:
    """event to delete a single event by id

    Args:
        event_ids (str|list): event id as string or list of event ids
        reason (str): a reason for deletion provided by the user
    """
    if isinstance(event_ids, str):
        event_ids = [event_ids]
    event = Event(public_key=self.public_key.hex(),
                  kind=EventKind.DELETE,
                  content=reason,
                  tags=[['e'] + event_ids],
                  created_at=int(time.time()))
    return event

@patch
def event_reaction(self: Client) -> Event:
    raise NotImplementedError()

@patch
def event_channel(self: Client) -> Event:
    raise NotImplementedError()

@patch
def event_channel_metadata(self: Client) -> Event:
    raise NotImplementedError()

@patch
def event_channel_message(self: Client) -> Event:
    raise NotImplementedError()

@patch
def event_channel_hide_message(self: Client) -> Event:
    raise NotImplementedError()

@patch
def event_channel_mute_user(self: Client) -> Event:
    raise NotImplementedError()

@patch
def event_channel_metadata(self: Client) -> Event:
    raise NotImplementedError()

@patch
def event_encrypted_message(self: Client) -> Event:
    warnings.warn('''the current implementation of messages should be used with caution
                    see https://github.com/nostr-protocol/nips/issues/107''')
    raise NotImplementedError()

