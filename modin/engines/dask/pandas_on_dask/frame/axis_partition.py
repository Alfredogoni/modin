# Licensed to Modin Development Team under one or more contributor license agreements.
# See the NOTICE file distributed with this work for additional information regarding
# copyright ownership.  The Modin Development Team licenses this file to you under the
# Apache License, Version 2.0 (the "License"); you may not use this file except in
# compliance with the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed under
# the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF
# ANY KIND, either express or implied. See the License for the specific language
# governing permissions and limitations under the License.

from modin.engines.base.frame.axis_partition import PandasFrameAxisPartition
from .partition import PandasOnDaskFramePartition

from distributed.client import get_client
from distributed import Future
from distributed.utils import get_ip
import pandas


class PandasOnDaskFrameAxisPartition(PandasFrameAxisPartition):
    def __init__(self, list_of_blocks, bind_ip=False):
        # Unwrap from BaseFramePartition object for ease of use
        for obj in list_of_blocks:
            obj.drain_call_queue()
        self.list_of_blocks = [obj.future for obj in list_of_blocks]
        if bind_ip:
            self.list_of_ips = [obj.ip for obj in list_of_blocks]

    partition_type = PandasOnDaskFramePartition
    instance_type = Future

    @classmethod
    def deploy_axis_func(
        cls, axis, func, num_splits, kwargs, maintain_partitioning, *partitions
    ):
        client = get_client()
        axis_result = client.submit(
            deploy_dask_func,
            PandasFrameAxisPartition.deploy_axis_func,
            axis,
            func,
            num_splits,
            kwargs,
            maintain_partitioning,
            *partitions,
            pure=False,
        )

        lengths = kwargs.get("_lengths", None)
        result_num_splits = len(lengths) if lengths else num_splits

        # We have to do this to split it back up. It is already split, but we need to
        # get futures for each.
        return [
            client.submit(lambda l: l[i], axis_result, pure=False)
            for i in range(result_num_splits * 4)
        ]

    @classmethod
    def deploy_func_between_two_axis_partitions(
        cls, axis, func, num_splits, len_of_left, other_shape, kwargs, *partitions
    ):
        client = get_client()
        axis_result = client.submit(
            deploy_dask_func,
            PandasFrameAxisPartition.deploy_func_between_two_axis_partitions,
            axis,
            func,
            num_splits,
            len_of_left,
            other_shape,
            kwargs,
            *partitions,
            pure=False,
        )
        # We have to do this to split it back up. It is already split, but we need to
        # get futures for each.
        return [
            client.submit(lambda l: l[i], axis_result, pure=False)
            for i in range(num_splits * 4)
        ]

    def _wrap_partitions(self, partitions):
        return [
            self.partition_type(future, length, width, ip)
            for (future, length, width, ip) in zip(*[iter(partitions)] * 4)
        ]


class PandasOnDaskFrameColumnPartition(PandasOnDaskFrameAxisPartition):
    """The column partition implementation for Multiprocess. All of the implementation
    for this class is in the parent class, and this class defines the axis
    to perform the computation over.
    """

    axis = 0


class PandasOnDaskFrameRowPartition(PandasOnDaskFrameAxisPartition):
    """The row partition implementation for Multiprocess. All of the implementation
    for this class is in the parent class, and this class defines the axis
    to perform the computation over.
    """

    axis = 1


def deploy_dask_func(func, *args):
    """
    Run a function on a remote partition.

    Parameters
    ----------
    func : callable
        The function to run.

    Returns
    -------
        The result of the function `func`.
    """
    result = func(*args)
    ip = get_ip()
    if isinstance(result, pandas.DataFrame):
        return result, len(result), len(result.columns), ip
    elif all(isinstance(r, pandas.DataFrame) for r in result):
        return [i for r in result for i in [r, len(r), len(r.columns), ip]]
    else:
        return [i for r in result for i in [r, None, None, ip]]
