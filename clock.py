import time

import pika

from board import Board
from config import GAME_CLOCK_OUTBOUND_EXCHANGE_NAME, GAME_CLOCK_INBOUND_QUEUE_NAME
from robot import Robot

__author__ = 'rogueleaderr'


class Clock:
    def __init__(self, board, tick_length=3, debug=False):
        self.connection = pika.BlockingConnection(pika.ConnectionParameters(host='localhost'))

        # outbound channel will broadcast clock ticks to the robots
        self.outbound_channel = self.connection.channel()
        self.outbound_channel.exchange_declare(exchange=GAME_CLOCK_OUTBOUND_EXCHANGE_NAME,
                                               type='fanout')
        self.outbound_channel.queue_declare(exclusive=True)
        self.exchange_name = GAME_CLOCK_OUTBOUND_EXCHANGE_NAME

        # inbound channel listens for acknowledgement from robots to make sure each has
        # finished updating before game moves on to next turn
        self.inbound_channel = self.connection.channel()
        self.inbound_channel.queue_declare(queue=GAME_CLOCK_INBOUND_QUEUE_NAME)
        self.inbound_channel.basic_consume(self.receive_robot_update,
                                           queue=GAME_CLOCK_INBOUND_QUEUE_NAME)
        self.updated_robots = set()

        self.tick_length = tick_length
        self.tick_count = 0
        self.board = board
        self.board_size = board.board_height ** 2
        self.debug = debug
        if debug:
            self._synchronous_board = [[robot.alive for robot in row] for row in board._board]

    def receive_robot_update(self, ch, method, properties, body):
        # body will be the address of the robot who's telling us it finished its turn
        self.updated_robots.add(body)
        ch.basic_ack(method.delivery_tag)

        # game can procedue to next turn once all robots are done updating
        if len(self.updated_robots) == self.board_size:
            self.updated_robots = set()
            self.tick()

    def start(self):
        self.board.start_robots()
        self.tick(skip_pause=True)
        self.inbound_channel.start_consuming()

    def tick(self, skip_pause=False):
        print("round #{}".format(self.tick_count))
        print(self.board)
        if self.debug:
            print(Board.print_boolean_board(self._synchronous_board))
            self._check_boards_agree()
            self._synchronous_tick()

        if self.board.extinct:
            raise ExtinctionEvent
        self.outbound_channel.basic_publish(exchange=self.exchange_name,
                                            routing_key='',
                                            body=str(self.tick_count))
        if not skip_pause:
            time.sleep(self.tick_length)
        self.tick_count += 1

    def _check_boards_agree(self):
        synchronous_board = self._synchronous_board
        board_height = len(synchronous_board)
        for i in range(board_height):
            for j in range(board_height):
                if self.board._board[i][j].alive != self._synchronous_board[i][j]:
                    import ipdb ; ipdb.set_trace()

    def _synchronous_tick(self):
        synchronous_board = self._synchronous_board
        board_height = len(synchronous_board)
        new_board = [[False for j in range(board_height)] for i in range(board_height)]
        for i in range(board_height):
            for j in range(board_height):
                living_neighbors = 0
                neighbors = Robot.calculate_neighbor_addresses(board_height, j, i)

                for n_i, n_j in neighbors:
                    if n_i == i and n_j == j:
                        continue
                    else:
                        living_neighbors += synchronous_board[n_i][n_j]
                # print(neighbors)
                # print(i, j, living_neighbors)
                alive = synchronous_board[i][j]
                if alive:
                    underpopulated = living_neighbors < 2
                    overpopulated = living_neighbors > 3
                    if underpopulated or overpopulated:
                        new_board[i][j] = False
                    else:
                        new_board[i][j] = True
                else:
                    if living_neighbors == 3:
                        new_board[i][j] = True
        self._synchronous_board = new_board

    def stop(self):
        self.inbound_channel.stop_consuming()


class ExtinctionEvent(Exception):
    pass
