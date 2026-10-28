import asyncio
import unittest
from netops.probe import run_tcp_probe

class TestProbe(unittest.IsolatedAsyncioTestCase):
    async def test_connected(self):
        async def handler(reader, writer):
            writer.close()
            await writer.wait_closed()
        server = await asyncio.start_server(handler,'127.0.0.1',0)
        try:
            port=server.sockets[0].getsockname()[1]
            out=await run_tcp_probe('127.0.0.1',port,count=3,interval_seconds=0)
            self.assertEqual(out['failures'],0)
            self.assertEqual(out['connect_ms']['count'],3)
            self.assertEqual(out['method'],'TCP_connect_duration_userspace')
        finally:server.close();await server.wait_closed()
    async def test_connection_refused(self):
        server=await asyncio.start_server(lambda r,w:None,'127.0.0.1',0)
        port=server.sockets[0].getsockname()[1]
        server.close();await server.wait_closed()
        out=await run_tcp_probe('127.0.0.1',port,count=2,interval_seconds=0)
        self.assertEqual(out['failures'],2)
        self.assertIsNone(out['connect_ms']['p99'])
    async def test_invalid_arguments(self):
        with self.assertRaises(ValueError):await run_tcp_probe('localhost',0)
        with self.assertRaises(ValueError):await run_tcp_probe('localhost',1234,count=10001)
