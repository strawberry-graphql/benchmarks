import strawberry


@strawberry.type
class Query:
    @strawberry.field
    def hello(self) -> str:
        return "Hello World!"


schema = strawberry.Schema(query=Query)


class ExecuteSync:
    def time_excute(self):
        for _ in range(100):
            schema.execute_sync("{ hello }")


class MemSuite:
    def mem_excute(self):
        for _ in range(100):
            schema.execute_sync("{ hello }")
