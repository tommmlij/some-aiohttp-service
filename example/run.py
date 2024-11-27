import asyncio
import logging

from aiohttp.web import Application, get, run_app
from aiohttp.web_exceptions import HTTPOk, HTTPAccepted

from some_aiohttp_service import BaseService

async def some_long_calculation(a, b):
    await asyncio.sleep(5)
    return f"Done with {a}/{b}"

class TestService(BaseService):
    name = "test"

    @staticmethod
    async def work(job):
        return await some_long_calculation(**job.data)

    async def error_handler(self, job, error):
        logging.error(error)

    async def result_handler(self, job, result):
        print(result)


async def health(_):
    raise HTTPOk

async def hello(request):
    a = request.match_info["a"]
    b = request.match_info["b"]
    await request.app["test"].commit_work({"a": a, "b": b})
    raise HTTPAccepted

app = Application()
app.add_routes([get("/work/{a}/{b}", hello), get("/health", health)])

app.cleanup_ctx.append(TestService(app).init)

run_app(app)
