import asyncio
from pathlib import Path

from .api import schema, schema_with_directives

ROOT = Path(__file__).parent / "queries"

basic_query = (ROOT / "simple.graphql").read_text()
many_fields_query = (ROOT / "many_fields.graphql").read_text()
many_fields_query_directives = (ROOT / "many_fields_directives.graphql").read_text()
items_query = (ROOT / "items.graphql").read_text()


class ExecuteSync:
    def time_execute(self):
        schema.execute_sync(basic_query)

    def time_execute_with_many_fields(self):
        schema.execute_sync(many_fields_query)

    def peakmem_execute_with_many_fields(self):
        schema.execute_sync(many_fields_query)

    def time_execute_with_many_fields_and_directives(self):
        schema_with_directives.execute_sync(many_fields_query_directives)

    def time_execute_with_10_items(self):
        schema.execute_sync(items_query, variable_values={"count": 10})

    def time_execute_with_100_items(self):
        schema.execute_sync(items_query, variable_values={"count": 100})

    def time_execute_with_1000_items(self):
        schema.execute_sync(items_query, variable_values={"count": 1000})


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
