#!/usr/bin/env python
# -*- coding: utf-8 -*-

import collections
import datetime
import logging
logger = logging.getLogger(__name__)

from bson.code import Code
from bson.objectid import ObjectId
import pymongo

import twitchcancer.cron

'''
  Schema

  messages (in memory) {
    date: datetime of creation
    channel: "#channel",
    cancer: cancer points,
  }

  leaderboard {
    _id: "#channel",
    minute: {
      cancer: {
        'value': cancer points,
        'date': date achieved,
      },
      messages: {
        'value': message count,
        'date': date achieved,
      },
      cpm: {
        'value': cancer per message,
        'date': date achieved,
      },
    },
    total: {
      'date': date of the first record,
      'cancer': cancer points,
      'messages': message count,
      'cpm': cancer per message,
    },
    average: {
      'duration': amount of minutes recorded,
      'cancer': cancer points,
      'messages': message count,
      'cpm': cancer per message,
    }
  }
'''
# use MongoDB straight up
class Storage:

  def __init__(self, cron=False):
    super().__init__()

    client = pymongo.MongoClient()
    self.db = client.twitchcancer

    # store messages in memory only
    self.messages = collections.deque()

    # allow callers to signal they need maintenance to run
    self.cron = None

    if cron:
      # process and delete db.messages every minute
      self.cron = twitchcancer.cron.Cron()
      self.cron.add(call=self._archive)
      self.cron.start()

    logger.debug('created a Storage object with cron support set to %s', (self.cron != None))

  # update leaderboards from db.messages and ditch old messages
  def _archive(self):
    # debugging
    now_start = datetime.datetime.now(datetime.timezone.utc)
    message_delta = 0
    logger.debug('archive started at %s with %s messages total', now_start, len(self.messages))

    # run at 12:31:20
    # bp  at 12:30:00
    breakpoint = self._live_message_breakpoint()
    breakpoint = breakpoint.replace(second=0, microsecond=0)

    '''
      map/reduce self.messages into history = {
        '{minute}': {
          '{channel} {
            'cancer: cancer points,
            'messages': messages count
          }
      }
    '''
    history = collections.defaultdict(lambda: collections.defaultdict(lambda: {'cancer': 0, 'messages': 0}))

    # run until there's no old message left
    while True:
      try:
        message = self.messages.popleft()
      except IndexError:
        logger.info('archive ate all the messages, meaning we got no message in the last minute')
        break

      # stop if the message is too new
      if message['date'].replace(second=0, microsecond=0) >= breakpoint:
        self.messages.appendleft(message)
        logger.debug('archiving loop stopped at message %s', message['date'])
        break

      # group messages by minute
      message['date'] = message['date'].replace(second=0, microsecond=0)

      # defaultdict builds everything as needed
      history[message['date']][message['channel']]['cancer'] += message['cancer']
      history[message['date']][message['channel']]['messages'] += 1

      # debugging
      message_delta += 1

    # update leaderboards with this new data
    for minute, channels in history.items():
      for channel, record in channels.items():
        h = self._history_to_leaderboard(minute, channel, record['cancer'], record['messages'])

        self._update_leaderboard(h)

      logger.info('updated leaderboards with round %s with messages from %s channels', minute, len(channels))

    # debugging
    now_end = datetime.datetime.now(datetime.timezone.utc)
    logger.debug('archived %s messages in %s ms, %s messages left', message_delta, (now_end - now_start).total_seconds() * 1000, len(self.messages))

  # update db.leaderboard with this minute+channel record
  # @db.write
  def _update_leaderboard(self, new):
    find = {'_id': new['_id']}
    record = self.db.leaderboard.find_one(find)

    if not record:
      logger.debug('inserting new leaderboard record for %s', new['_id'])
      self.db.leaderboard.insert_one(new)
    else:
      update = {
        '$inc': {
          # increment totals
          'total.cancer': new['minute']['cancer']['value'],
          'total.messages': new['minute']['messages']['value'],

          # add 1 minute to the duration
          'average.duration': 1,

          # update averages with the new weighted value
          'average.cancer': (new['minute']['cancer']['value'] - record['average']['cancer']) / (record['average']['duration'] + 1),
          'average.messages': (new['minute']['messages']['value'] - record['average']['messages']) / (record['average']['duration'] + 1),
          'average.cpm': (new['minute']['cpm']['value'] - record['average']['cpm']) / (record['average']['duration'] + 1),
        },

        '$set': {
          'total.cpm': (record['total']['cancer'] + new['minute']['cancer']['value']) / (record['total']['messages'] + new['minute']['messages']['value']),
        }
      }

      # per minute records
      if new['minute']['cancer']['value'] > record['minute']['cancer']['value']:
        update['$set']['minute.cancer.value'] = new['minute']['cancer']['value']
        update['$set']['minute.cancer.date'] = new['minute']['cancer']['date']

        #logger.debug('new cancer pb for %s, %s, was %s', new['_id'], new['minute']['cancer'], record['minute']['cancer'])

      if new['minute']['messages']['value'] > record['minute']['messages']['value']:
        update['$set']['minute.messages.value'] = new['minute']['messages']['value']
        update['$set']['minute.messages.date'] = new['minute']['messages']['date']

        #logger.debug('new messages pb for %s, %s, was %s', new['_id'], new['minute']['messages'], record['minute']['messages'])

      if new['minute']['cpm']['value'] > record['minute']['cpm']['value']:
        update['$set']['minute.cpm.value'] = new['minute']['cpm']['value']
        update['$set']['minute.cpm.date'] = new['minute']['cpm']['date']

        #logger.debug('new cpm pb for %s, %s, was %s', new['_id'], new['minute']['cpm'], record['minute']['cpm'])

      self.db.leaderboard.update(find, update)

  # transforms an history record into a db.leaderboard record
  def _history_to_leaderboard(self, date, channel, cancer, messages):
    return {
      '_id': channel,
      'minute': {
        'cancer': {
          'value': cancer,
          'date': date,
        },
        'messages': {
          'value': messages,
          'date': date,
        },
        'cpm': {
          'value': cancer / messages,
          'date': date,
        },
      },
      'total': {
        'date': date,
        'cancer': cancer,
        'messages': messages,
        'cpm': cancer / messages,
      },
      'average': {
        'duration': 1,
        'cancer': cancer,
        'messages': messages,
        'cpm': cancer / messages,
      }
    }

  # returns the datetime where live and archived messages split
  def _live_message_breakpoint(self):
    # messages are old and ready to be archived after 1 minute
    return (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=1))

  # store a cancer level for a single message in a channel
  def store(self, channel, cancer):
    message = {
      'date': datetime.datetime.now(datetime.timezone.utc),
      'channel': channel,
      'cancer': int(cancer)
    }

    self.messages.append(message)

  # returns live cancer levels
  def cancer(self):
    breakpoint = self._live_message_breakpoint()
    minute = collections.defaultdict(lambda: {'cancer': 0, 'messages': 0})

    # sum cancer points and count recent messages for each channel
    for message in reversed(self.messages):
      if message['date'] < breakpoint:
        break

      minute[message['channel']]['cancer'] += message['cancer']
      minute[message['channel']]['messages'] += 1

    return [{
      'channel': channel,
      'cancer': records['cancer'],
      'messages': records['messages'],
    } for channel, records in minute.items()]

  # returns one of the leaderboards
  # @db.read
  def leaderboard(self, what, per):

    if per == 'minute':
      # sort the leaderboard by interval and field
      sort = [("{0}.{1}.{2}".format(per, what, 'value'), pymongo.DESCENDING)]
      result = self.db.leaderboard.find().sort(sort).limit(10)

      return [{
        'channel': r["_id"],
        'date': r["minute"][what]["date"].isoformat(),
        'value': str(r["minute"][what]["value"]),
      } for r in result]

    elif per == 'total':
      # sort the leaderboard by interval and field
      sort = [("{0}.{1}".format(per, what), pymongo.DESCENDING)]
      result = self.db.leaderboard.find().sort(sort).limit(10)

      return [{
        'channel': r["_id"],
        'date': r["total"]["date"].isoformat(),
        'value': str(r["total"][what]),
      } for r in result]

    elif per == 'average':
      # sort the leaderboard by interval and field
      sort = [("{0}.{1}".format(per, what), pymongo.DESCENDING)]
      result = self.db.leaderboard.find().sort(sort).limit(10)

      return [{
        'channel': r["_id"],
        'date': r["total"]["date"].isoformat(),
        'value': str(r["average"][what]),
      } for r in result]

import time

if __name__ == "__main__":
  logging.basicConfig(level=logging.DEBUG)

  store = Storage()
