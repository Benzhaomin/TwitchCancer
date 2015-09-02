#!/usr/bin/env python
# -*- coding: utf-8 -*-

import pickle
import threading
import logging
logger = logging.getLogger(__name__)

# ZeroMQ
import zmq

from twitchcancer.config import Config
from twitchcancer.utils.cron import Cron
from twitchcancer.storage.inmemorystore import InMemoryStore
from twitchcancer.storage.storageinterface import StorageInterface

#
# handle the message stream: store new messages in memory and publish summaries
#
# implements:
#  - storage.store()
#  - storage.cancer()
class MemoryStorage(StorageInterface):

  def __init__(self):
    super().__init__()

    self._store = InMemoryStore()

    # process and delete self.messages every minute
    self.cron = Cron()
    self.cron.add(call=self._archive)
    self.cron.start()

    # publish a summary of all cancer messages grouped by minute and channel
    self.zmq_context = zmq.Context()
    self.pubsub_socket = self.zmq_context.socket(zmq.PUB)
    self.pubsub_socket.bind(Config.get('monitor.socket.cancer_summary'))
    logger.info("bound publish socket to %s", Config.get('monitor.socket.cancer_summary'))

    # respond to live cancer requests
    self.cancer_socket = self.zmq_context.socket(zmq.REP)
    self.cancer_socket.bind(Config.get('monitor.socket.cancer_request'))
    logger.info("bound cancer socket to %s", Config.get('monitor.socket.cancer_request'))

    # TODO: use asyncio
    t = threading.Thread(target=self._handle_cancer_request)
    t.daemon = True
    t.start()
    logger.info("started handle cancer request thread")

  # adds a record in the in-memory store
  # @memory.write()
  def store(self, channel, cancer):
    self._store.store(channel, cancer)

  # computes cancer level from the in-memory store
  # @memory.read()
  def cancer(self):
    return self._store.cancer()

  # respond to cancer request on a socket
  # @socket.recv()
  # @memory.read()
  # @socket.send()
  def _handle_cancer_request(self):
    while True:
      self.cancer_socket.recv()
      cancer = self._store.cancer()
      self.cancer_socket.send_pyobj(cancer)

  # archive live messages from the in-memory store into the persistent store
  # @memory.read()
  # @socket.send()
  def _archive(self):
    history = self._store.archive()

    # publish the summaries on the pubsub socket
    for date, channels in history.items():
      for channel, record in channels.items():
        record = {
          'date': date,
          'channel': channel,
          'cancer': record['cancer'],
          'messages': record['messages']
        }

        self.pubsub_socket.send_multipart([b'summary', pickle.dumps(record)])

      logger.info('published leaderboards of round %s with messages from %s channels', date, len(channels))
