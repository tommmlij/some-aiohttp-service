import asyncio
import logging
import colorlog
import sys

from aiohttp import web
from aiohttp.web_exceptions import HTTPOk

from some_aiohttp_service.base_service import BaseService
from some_aiohttp_service.exceptions import ServiceException

FORMAT = '%(asctime)s - %(process)-5d - %(log_color)s%(levelname)-8s%(reset)s | %(message)s'

handler = colorlog.StreamHandler(stream=sys.stdout)
handler.setFormatter(colorlog.ColoredFormatter(FORMAT))

log = logging.getLogger()
log.addHandler(handler)
log.setLevel(logging.DEBUG)


async def health(_):
    raise HTTPOk


async def hello(request):
    operation = request.match_info['operation']
    await request.app['transform'].commit_work({'operation': operation})
    return web.Response(text="Hello, world")


class TestError(ServiceException):
    pass


class TransformService(BaseService):
    name = 'transform'

    @staticmethod
    async def work(job):
        await asyncio.sleep(1)
        if job.data['operation'] == 'fail':
            raise TestError("Failing job")
        await asyncio.sleep(1)
        return f"Returning - {job.data}"

    async def error_handler(self, job, error):
        log.error(error)

    async def result_handler(self, job, result):
        log.info(result)


app = web.Application()
app.add_routes([
    web.get('/{operation}', hello),
    web.get('/health', health)
])

app.cleanup_ctx.append(TransformService(app, overall_timeout=30, throttle=10).init)

web.run_app(app, port=1500, host='0.0.0.0')
