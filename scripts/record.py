#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import logging
logger = logging.getLogger('twitchcancer')

from twitchcancer.storage.storage import Storage

def run(args):
  storage = Storage()
  storage.record()

if __name__ == "__main__":
  parser = argparse.ArgumentParser()
  # persist data generated by monitor

  parser.add_argument('--log', dest='loglevel', default='WARNING',
    help="set the level of messages to display")

  #parser.add_argument("--db-host", dest="host", default="localhost", help="hostname or ip address (default: localhost)")
  #parser.add_argument("--db-port", dest="port", default=8080, help="port number (default: 8080)")

  args = parser.parse_args()

  # set logger level
  numeric_level = getattr(logging, args.loglevel.upper(), None)
  if not isinstance(numeric_level, int):
    raise ValueError('Invalid log level: %s' % loglevel)

  logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
  logger.setLevel(numeric_level)

  # start recording forever
  run(args)

