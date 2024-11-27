import logging

import pytest
from aiohttp import web
from aiohttp.web import HTTPAccepted, View

from some_aiohttp_service.base_service import BaseService


class TestService(BaseService):
    name = "test"

    @staticmethod
    async def work(job):
        print(job)

    async def startup(self, app):
        logging.info(f"Startup custom {self.name} service")

    async def cleanup(self, app):
        logging.info(f"Cleanup custom {self.name} service")

    async def prepare_job(self, job):
        logging.info("Preparing job")

    async def error_handler(self, job, error):
        return str(error)

    async def result_handler(self, job, result):
        return result


@pytest.mark.asyncio
async def test_service(caplog, aiohttp_client):
    class TestView1(View):
        async def get(self):
            await self.request.app["test"].commit_work({"operation": "operation"})
            raise HTTPAccepted(text="Job accepted")

    app = web.Application()

    app.cleanup_ctx.append(TestService(app, 3).init)

    app.router.add_view("/tw1", TestView1)
    with caplog.at_level(logging.INFO):
        async with await aiohttp_client(app) as client:
            resp = await client.get("/tw1")
            assert resp.status == 202
            text = await resp.text()
            assert "Job accepted" in text

        assert "Startup test service" in caplog.text
        assert "Startup custom test service" in caplog.text
        assert "Preparing job" in caplog.text
        assert "Cleanup test service" in caplog.text
        assert "Cleanup custom test service" in caplog.text
