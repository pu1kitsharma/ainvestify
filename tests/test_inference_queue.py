import threading
import time
from unittest.mock import Mock
import pytest
from pydantic import BaseModel
from agents.inference_queue import InferenceQueue
from agents.local_models import LocalModel, MODEL_JOB_SLOT


def test_fifo_prevents_long_workflow_from_reacquiring_ahead_of_waiting_company():
    queue = InferenceQueue()
    assert queue.acquire()
    order = []
    def company():
        assert queue.acquire(timeout=1)
        order.append('company')
        queue.release()
    thread = threading.Thread(target=company)
    thread.start()
    deadline = time.monotonic()+1
    while queue.waiting != 1 and time.monotonic()<deadline:
        time.sleep(.001)
    assert queue.waiting == 1
    queue.release()
    assert queue.acquire(timeout=1)
    order.append('discovery-next-page')
    queue.release()
    thread.join(1)
    assert order == ['company', 'discovery-next-page']


def test_timeout_does_not_poison_following_requests():
    queue = InferenceQueue()
    queue.acquire()
    assert not queue.acquire(timeout=.01)
    queue.release()
    assert queue.acquire(blocking=False)
    queue.release()


def test_network_failure_releases_inference_for_other_jobs():
    class Result(BaseModel):
        text: str
    model = LocalModel()
    model.client = Mock()
    model.client.chat.side_effect = RuntimeError('connection lost')
    with pytest.raises(RuntimeError):
        model.generate('Write', '{}', Result)
    assert MODEL_JOB_SLOT.acquire(blocking=False)
    MODEL_JOB_SLOT.release()
