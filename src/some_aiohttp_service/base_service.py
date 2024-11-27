import asyncio
import logging
import traceback
from abc import ABC, abstractmethod
from typing import Optional

from .exceptions import ServiceNotFoundError, ServiceException
from .job import JobType, Job

log = logging.getLogger()


class BaseService(ABC):
    name = 'base'

    overall_timeout: int

    throttle: Optional[int]
    DELAY_PERIODIC_JOB_RESCHEDULE = 3
    MAX_JOB_REPETITIONS = 10

    # Can be process or thread
    POOL_EXECUTOR = 'thread'

    # If CONCURRENT_WORK is true, multiple jobs can be run at the same time
    CONCURRENT_WORK = False

    # Creating a job id as a counter,
    # We don't need a lock here, because asyncio only uses one thread
    job_counter = 0

    @classmethod
    def get_job_id(cls):
        cls.job_counter += 1
        return cls.job_counter

    def __init__(self, _app,
                 worker_count=1,
                 overall_timeout=3000,
                 throttle=None
                 ):
        self.queue = asyncio.Queue()
        self.delayed_jobs = []
        self.app = None
        self.tasks = [None] * worker_count
        self.rescheduling_task = None
        self.running = False
        self.loop = None
        self.worker_count = worker_count
        self.overall_timeout = overall_timeout
        self.throttle = throttle

    async def init(self, app):
        app[self.name] = self
        self.app = app
        self.loop = asyncio.get_running_loop()
        self.running = True

        await self._startup(app)
        for i in range(self.worker_count):
            self.tasks[i] = asyncio.create_task(self.start(i))
        yield
        self.running = False
        await self._cleanup(app)
        log.info(f'Closing service {self.name}')

    async def commit_work(self, data):
        future = self.loop.create_future()
        job = Job(data=data, config={})
        log.debug(f'Service {self.name} - {job}')
        await self.queue.put((job, future))
        return future

    @staticmethod
    @abstractmethod
    async def work(job):
        pass

    async def start(self, worker_number):
        if self.loop.is_closed():
            return

        job, response_future = await self.queue.get()

        if job.type is JobType.TERMINATE:
            return

        if self.CONCURRENT_WORK and (self.running or not self.queue.empty()):
            self.tasks[worker_number] = asyncio.create_task(self.start(worker_number))

        await self.prepare_job(job)

        result = dict

        try:
            await self._on_job_started(job)
            result = await asyncio.wait_for(self.work(job), timeout=self.overall_timeout)
            if isinstance(result, dict) and 'delayed' in result:
                # We pull the job from a delayed job or create a new one if there was none
                if not result.get('repeat_forever', False):
                    job.repetitions += 1
                if job.repetitions < self.MAX_JOB_REPETITIONS:
                    log.info(f'Rescheduling job: {job}')
                    self.delayed_jobs.append((job, response_future))
                else:
                    log.info(f'Maximum number of repetitions reached, Failing job: {job}')
                    response_future.set_exception(
                        TimeoutError(f'Maximum number of repetitions reached, Failing job: {job}'))

            elif isinstance(result, dict) and 'queue' in result:
                try:
                    await self.app[result['queue']].commit_work(result.get('data', {}))
                except KeyError:
                    raise ServiceNotFoundError
            else:
                res = await self._result_handler(job, result)
                if res is not None:
                    await self._on_job_finished(job, res)
                response_future.set_result(result)
                if self.throttle:
                    await asyncio.sleep(self.throttle)


        except asyncio.TimeoutError as e:
            log.warning(f'Timeout during job {job}')
            await self._on_job_failed(job, f'Timeout during job {job}')
            result = e

        except ServiceNotFoundError as e:
            warning = f'Service {result["queue"]} does not exist'
            log.warning(warning)
            await self._on_job_failed(job, warning)
            result = e

        except ServiceException as e:
            log.warning(f'Service threw an exception')
            await self._on_job_failed(job, f'Service does not exist')
            result = e

        except Exception as e:
            result = await self.error_handler(job, e)
            if result is None:
                log.warning(f'{e.__class__.__name__} in {self.__class__.__name__} loop', exc_info=True)
                log.error(traceback.format_exc())
                result = f'{e.__class__.__name__}: {str(e)}'
            await self._on_job_failed(job, result)
            result = e

        finally:
            if self.running and not self.CONCURRENT_WORK:
                self.tasks[worker_number] = self.loop.create_task(self.start(worker_number))
            if isinstance(result, Exception):
                response_future.set_exception(result)
                # noinspection PyBroadException
                try:
                    # Get rid of the future exception never awaited error
                    await response_future
                except:
                    pass

    # If error is handled correctly, error handler should return a string passed to on_job_failed.
    # If it returns "none", it is considered that error is unpredicted and is printed to warning log and job failed function gets a dict
    # with field error with the string representation of exception
    @abstractmethod
    async def error_handler(self, job, error):
        pass

    async def _result_handler(self, job, result):
        return await self.result_handler(job, result) or True

    # Result handler is called after every successful job that wasn't delayed or queued another job, it should
    # return a value passed as a result to on_job_finished function, if None on_job_finished is not called
    @abstractmethod
    async def result_handler(self, job, result):
        pass

    async def on_job_started(self, job):
        pass

    async def _on_job_started(self, job):
        await self.on_job_started(job)

    async def on_job_finished(self, job, result):
        pass

    async def _on_job_finished(self, job, result):
        await self.on_job_finished(job, result)

    async def on_job_failed(self, job, reason):
        pass

    async def _on_job_failed(self, job, reason):
        await self.on_job_failed(job, reason)

    async def prepare_job(self, job):
        pass

    async def reschedule_job(self):
        while self.running:
            if self.delayed_jobs:
                await self.queue.put(self.delayed_jobs.pop(0))
            await asyncio.sleep(self.DELAY_PERIODIC_JOB_RESCHEDULE)

    async def _startup(self, app):
        # Put necessary startup stuff here
        log.info(f'Startup {self.name} service')
        self.rescheduling_task = asyncio.create_task(self.reschedule_job())
        await self.startup(app)

    async def startup(self, app):
        pass

    async def _cleanup(self, app):
        log.info(f'Cleanup {self.name} service')

        # We are terminating the queue with a terminate-job
        for _ in range(self.worker_count):
            await self.queue.put((Job(type=JobType.TERMINATE), None))
        try:
            await asyncio.gather(self.rescheduling_task)
        except asyncio.CancelledError:
            pass
        try:
            await asyncio.gather(*self.tasks)
        except asyncio.CancelledError:
            pass
        await self.cleanup(app)

    async def cleanup(self, app):
        # Put the necessary cleanups here
        pass
