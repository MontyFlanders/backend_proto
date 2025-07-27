import strawberry
from app.resolvers.query_resolver import Query
from app.resolvers.mutation_resolver import Mutation

schema = strawberry.Schema(query=Query, mutation=Mutation)