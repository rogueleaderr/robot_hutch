import json
import functools
import pika
import time
from config import GAME_CLOCK_OUTBOUND_EXCHANGE_NAME, GAME_CLOCK_INBOUND_QUEUE_NAME

__author__ = 'rogueleaderr'


class Mailbox:
    """
    Pika advises to make sure each thread has it's own connection and that the connection
    is created in the thread. We make sure each robot only has one mailbox
    and that mailbox is created inside of that robot's one personal thread
    """

    def __init__(self, mailbox_address, clock_tick_callback, board_height):
        self.unacked_message_tags = []
        self.connection = pika.BlockingConnection(pika.ConnectionParameters(host='localhost'))
        self.clock_channel = self.connection.channel()
        self.neighbor_channel = self.connection.channel()
        self.mailbox_name = mailbox_address
        self.board_height = board_height

        # Turn on delivery confirmations since neighbor channels can get overloaded
        self.neighbor_channel.confirm_delivery()

        # connect to neighbors
        queue_declare_result = self.neighbor_channel.queue_declare(queue=mailbox_address,
                                                                   exclusive=True)
        self.incoming_mailbox = queue_declare_result.method.queue

        # connect to game clock
        from_clock_queue_result = self.clock_channel.queue_declare(exclusive=True)
        self.clock_channel.queue_bind(exchange=GAME_CLOCK_OUTBOUND_EXCHANGE_NAME,
                                      queue=from_clock_queue_result.method.queue)

        self.clock_channel.queue_declare(queue=GAME_CLOCK_INBOUND_QUEUE_NAME, auto_delete=True)

        # the robot update_status function needs a reference to the mailbox so it
        # can send outgoing messages but basic_consume won't let us pass arguments
        # to the callback, so make the callback a partial function that
        # has the mailbox reference already available
        update_status = functools.partial(clock_tick_callback, self)
        self.clock_channel.basic_consume(update_status,
                                         queue=from_clock_queue_result.method.queue)

    def check_for_mail(self):
        messages = []
        all_messages_read = False
        empty_results = 0
        while not all_messages_read:
            method, properties, body = self.neighbor_channel.basic_get(self.incoming_mailbox)
            if body is None:
                # TODO figure out why we get empty messages when the queue is not empty
                # ended up with 30 through experimentation
                time.sleep(empty_results / 30)
                empty_results += 1
                # messages seem to be not showing up immediately sometimes
                # problem gets worse with larger boards
                if empty_results > self.board_height:
                    all_messages_read = True
            else:
                self.unacked_message_tags.append(method.delivery_tag)
                messages.append(body)
        # in case of duplicate messages, only allow one message per neighbor address
        return set(messages)

    def acknowledge_batch(self):
        for tag in self.unacked_message_tags:
            self.neighbor_channel.basic_ack(delivery_tag=tag)
        self.unacked_message_tags = []

    def send_message_to_neighbor(self, neighbor_mailbox, message_body):
        confirmed = False
        while not confirmed:
            confirmed = self.neighbor_channel.basic_publish(exchange='',
                                                            routing_key=neighbor_mailbox,
                                                            body=message_body)
            if not confirmed:
                # system is having trouble keeping up. give it a sec so messages are all
                # available by the time of the next update_status
                time.sleep(.1)

    def tell_clock_turn_is_completed(self, turn_number):
        message = {"address": self.mailbox_name,
                   "status": "turn_completed",
                   "turn_number": turn_number}
        body = json.dumps(message)
        self.clock_channel.basic_publish(exchange='',
                                         routing_key=GAME_CLOCK_INBOUND_QUEUE_NAME,
                                         body=body)

    def report_mailbox_ready(self):
        message = {"address": self.mailbox_name,
                   "status": "mailbox_ready"}
        body = json.dumps(message)
        self.clock_channel.basic_publish(exchange='',
                                         routing_key=GAME_CLOCK_INBOUND_QUEUE_NAME,
                                         body=body)
