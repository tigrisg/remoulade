# This file is a part of Remoulade.
#
# Copyright (C) 2017,2018 CLEARTYPE SRL <bogdan@cleartype.io>
#
# Remoulade is free software; you can redistribute it and/or modify it
# under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at
# your option) any later version.
#
# Remoulade is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU Lesser General Public
# License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
from typing import Callable, List

import redis

from ..backend import RateLimiterBackend


class RedisBackend(RateLimiterBackend):
    """A rate limiter backend for Redis_.

    Parameters:
      client(Redis): An optional client.  If this is passed,
        then all other parameters are ignored.
      url(str): An optional connection URL.  If both a URL and
        connection paramters are provided, the URL is used.
      **parameters(dict): Connection parameters are passed directly
        to :class:`redis.Redis`.

    .. _redis: https://redis.io
    """

    def __init__(self, *, client=None, url=None, **parameters):
        if url is not None:
            parameters["connection_pool"] = redis.ConnectionPool.from_url(url)

        self.client = client or redis.Redis(**parameters)

    def add(self, key: str, value: int, ttl: int) -> bool:
        return bool(self.client.set(key, value, px=ttl, nx=True))

    def incr(self, key: str, amount: int, maximum: int, ttl: int) -> bool:
        with self.client.pipeline() as pipe:
            while True:
                try:
                    pipe.watch(key)
                    value = int(pipe.get(key) or b"0")  # type: ignore
                    value += amount
                    if value > maximum:
                        return False

                    pipe.multi()
                    pipe.set(key, value, px=ttl)
                    pipe.execute()
                    return True
                except redis.WatchError:
                    continue

    def decr(self, key: str, amount: int, minimum: int, ttl: int) -> bool:
        with self.client.pipeline() as pipe:
            while True:
                try:
                    pipe.watch(key)
                    value = int(pipe.get(key) or b"0")  # type: ignore
                    value -= amount
                    if value < minimum:
                        return False

                    pipe.multi()
                    pipe.set(key, value, px=ttl)
                    pipe.execute()
                    return True
                except redis.WatchError:
                    continue

    def incr_and_sum(self, key: str, keys: Callable[[], List[str]], amount: int, maximum: int, ttl: int) -> bool:
        with self.client.pipeline() as pipe:
            while True:
                try:
                    # TODO: Drop non-callable keys in Remoulade v2.
                    key_list = keys() if callable(keys) else keys
                    pipe.watch(key, *key_list)
                    value = int(pipe.get(key) or b"0")  # type: ignore
                    value += amount
                    if value > maximum:
                        return False

                    # Fetch keys again to account for net/server latency.
                    values = pipe.mget(keys() if callable(keys) else keys)
                    total = amount + sum(int(n) for n in values if n)  # type: ignore
                    if total > maximum:
                        return False

                    pipe.multi()
                    pipe.set(key, value, px=ttl)
                    pipe.execute()
                    return True
                except redis.WatchError:
                    continue
