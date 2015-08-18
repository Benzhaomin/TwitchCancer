#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
logger = logging.getLogger(__name__)

# ZeroMQ
import zmq

from twitchcancer.storage.persistentstore import PersistentStore
from twitchcancer.storage.storageinterface import StorageInterface
from twitchcancer.storage.storage import Storage

#
# expose the entire model: read data, from the persistent and in-memory stores
#
# implements:
#  - storage.channel()
#  - storage.cancer()
#  - storage.leaderboard()
class ReadOnlyStorage(StorageInterface):

  def __init__(self):
    super().__init__()

    self._store = PersistentStore()

    # request cancer levels
    self.context = zmq.Context()
    self.poller = zmq.Poller()
    self._connect()

  # request cancer level from a live message store
  # @socket.read()
  def cancer(self):
    self.socket.send(b'')

    if self.poller.poll(2*1000): # 2s timeout in milliseconds
      return self.socket.recv_pyobj()
    else:
      logger.warn("no reply to a live cancer request, will reconnect")
      self._disconnect()
      self._connect()
      return []

  # read leaderboards from the database
  # @db.read()
  def leaderboards(self):
    return self._store.leaderboards()

  # read channel data from the database
  # @db.read()
  def channel(self, channel):
    return self._store.channel(channel)

  # create a socket and connect to the cancer server
  # @socket.connect()
  def _connect(self):
    self.socket = self.context.socket(zmq.REQ)
    self.socket.connect(Storage.CANCER_SOCKET_URI)
    self.poller.register(self.socket, zmq.POLLIN)

    logger.debug("connected cancer socket to %s", Storage.CANCER_SOCKET_URI)

  # disconnect from the cancer server
  # @socket.close()
  def _disconnect(self):
    self.socket.setsockopt(zmq.LINGER, 0)
    self.socket.close()
    self.poller.unregister(self.socket)

# TODO: add proper unit testing
if __name__ == "__main__":
  logging.basicConfig(level=logging.DEBUG)

  storage = ReadOnlyStorage()

  print(storage.cancer())
  print(storage.leaderboards())
  print(storage.channel('#forsenlol'))
