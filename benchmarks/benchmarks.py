import asyncio
from pathlib import Path

from .api import schema, schema_with_directives

basic_query = (Path(__file__).parent / "queries/simple.graphql").read_text()
many_fields_query = (Path(__file__).parent / "queries/many_fields.graphql").read_text()
many_fields_query_with_directives = (
    Path(__file__).parent / "queries/many_fields_with_directives.graphql"
).read_text()


class ExecuteSync:
    def time_execute(self):
        schema.execute_sync(basic_query)

    def time_execute_with_many_fields(self):
        schema.execute_sync(many_fields_query)

    def peakmem_execute_with_many_fields(self):
        schema.execute_sync(many_fields_query)

    def time_execute_with_many_fields_and_directives(self):
        schema_with_directives.execute_sync(many_fields_query_with_directives)


class Subscriptions:
    def time_subscription(self):
        s = """
        subscription {
            something
        }
        """

        async def _run():
            for _ in range(100):
                iterator = await schema.subscribe(s)

                value = await iterator.__anext__()

                assert value.data["something"] == "Hello World!"

        asyncio.run(_run())

    time_subscription.number = 1
